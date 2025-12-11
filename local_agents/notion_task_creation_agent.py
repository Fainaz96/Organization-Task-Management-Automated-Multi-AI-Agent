from datetime import datetime
import os
import json
import uuid
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from datetime import date, timedelta
import notion_client
from agents import Agent, function_tool, handoff
import difflib

from model.response_agent_input import ResponseAgentInput
from openai import OpenAI # Assuming these are defined in your agents module
from db import get_db_connection
from utils.db_helper import execute_query
from utils.whatsapp_utils import send_whatsapp_message

from local_agents.notion_response_agent import notion_response_agent

# --- SETUP (Unchanged) ---
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")

if not all([NOTION_API_KEY, TASKS_DATABASE_ID]):
    raise ValueError("One or more required environment variables are missing from .env: NOTION_API_KEY, TASKS_DATABASE_ID")

notion = notion_client.Client(auth=NOTION_API_KEY)


# --- AGENT TOOLS (Unchanged) ---

def manage_response_agent_handoff(context, input: ResponseAgentInput):
    """
    Handles the response agent handoff by processing the specialist tool output
    and preparing the final response for the user.
    """
    print("response agent start") 

@function_tool
def search_database_by_title(task_name: str) -> str:
    """
    Searches the Notion database for tasks that exactly match the given title.

    Args:
        title: The title of the task to search for.

    Returns:
        A stringified JSON object from the Notion API's query database endpoint.
        The 'results' key will contain an array of page objects. If no task is found,
        the 'results' array will be empty.
    """
    if not task_name:
        return json.dumps({"error": "Missing task name for search."})

    try:    
        # 1. Search for the page (task) by its title
        search_params = {
            "query": task_name,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "ascending", "timestamp": "last_edited_time"}
        }
        search_response = notion.search(**search_params)
        results = search_response.get("results", [])

        # 2. Handle search results
        if not results:
            return json.dumps({"error": f"No task found with the name '{task_name}'."})
        
        if len(results) > 1:
            # To avoid ambiguity, you can check if there's an exact match for the title
            exact_matches = []
            for page in results:
                # The title property is structured, so we need to extract the plain text
                # print(page.get("properties", {}).get("Task", {}).get('title',{})[0].get('plain_text',{}))
                try:
                    page_title = page.get("properties", {}).get("Task", {}).get('title',{})[0].get('plain_text',{})
                    # print(page_title.lower())
                    # print(task_name.lower())
                    if page_title.lower() == task_name.lower():
                        # print(page_title)
                        exact_matches.append(page)
                except (IndexError, KeyError):
                    continue # Skip malformed pages
            # print(len(exact_matches))
            if len(exact_matches) == 0:
                found_page = exact_matches[0]
            else:
                 return json.dumps({"error": f"Ambiguous task name. Multiple tasks found matching '{task_name}'. Please be more specific."})
        else:
            found_page = results[0]

        task_id = found_page.get("id")
        if not task_id:
             return json.dumps({"error": "Found a matching task but could not retrieve its ID."})

        # 3. Use the found ID to retrieve comments with the original function
        # print(f"Found task '{task_name}' with ID: {task_id}. Retrieving comments...")
        # return retrieve_comments(block_id=task_id)
        if not task_id: 
            return json.dumps({"error": "Missing Block/Page ID"})
        try:
        # The API for retrieving comments requires a block_id
            response = notion.comments.list(block_id=task_id)
            return json.dumps(response, indent=2)
        except Exception as e:
            return f"Error retrieving comments: {e}"
    except Exception as e:
        return f"An error occurred: {e}"


@function_tool
async def get_notion_user_id_from_name(username: str) -> str:
    """
    Finds a user's Notion ID. Handles ambiguity by providing options and suggests corrections for misspellings.
    """
    # ... (connection logic remains the same)
    try:
        async for conn in get_db_connection():
            # First, try the original query
            users = await execute_query(
                conn,
                """
                SELECT notion_user_id, username FROM Users WHERE username LIKE :id
                """,
                {"id": f"%{username}%"},
                fetch_one=False
            )

            if users:
                # --- EXISTING LOGIC - NO CHANGES NEEDED ---
                if len(users) == 1:
                    user = users[0]
                    return json.dumps({"username": user["username"], "notion_user_id": user["notion_user_id"]})
                else:
                    found_names = [user['username'] for user in users]
                    return json.dumps({
                        "error": "Ambiguous Name",
                        "message": "Multiple users found. Ask for clarification.",
                        "options": found_names
                    })
            else:
                # --- NEW FALLBACK LOGIC FOR MISSPELLINGS ---
                # If no users were found, fetch all usernames to check for a close match.
                all_users_records = await execute_query(conn, "SELECT username FROM Users", {}, fetch_one=False)
                all_usernames = [record['username'] for record in all_users_records]
                
                # Find the best single match with a high similarity cutoff (e.g., 0.8)
                close_matches = difflib.get_close_matches(username, all_usernames, n=1, cutoff=0.8)
                
                if close_matches:
                    # A likely misspelling was found. Return a specific error with the suggestion.
                    return json.dumps({
                        "error": "User Not Found With Suggestion",
                        "message": f"No user found for '{username}', but a similar name was found.",
                        "suggestion": close_matches[0]
                    })
                else:
                    # No similar name found, return the original generic error.
                    return json.dumps({
                        "error": "User Not Found",
                        "message": f"Could not find any user with the name '{username}'."
                    })
    except Exception as e:
        return f"Error searching for user: {e}"


# --- MODIFICATION START: create_task tool is updated ---
@function_tool
async def create_task(
    task_name: str,
    creator_id: str,
    assignee_id: Optional[str] = None,
    due_date: Optional[str] = date.today(),
    priority: Optional[str] = "High",
    status: Optional[str] = None,
    children_blocks_json: Optional[str] = None,
    language:Optional[str] = None,
) -> str:
    """
    Use this to create a new task with properties and optional rich content.
    The 'creator_id' parameter is REQUIRED and must be the Notion ID of the user creating the task.
    The 'children_blocks_json' must be a valid JSON string representing a list of Notion block objects.
    """
    if not creator_id:
        return json.dumps({"error": "Missing Creator ID", "message": "The creator_id is required to create a task."})

    properties: Dict[str, Any] = {
        "Task": {"title": [{"text": {"content": task_name}}]},
        "Created by": {"people": [{"id": creator_id}]},
    }
    
    if assignee_id is None:
        assignee_id = creator_id
    properties["Assignee"] = {"people": [{"id": assignee_id}]}

    if due_date is None:
        due_date = str(datetime.now() + timedelta(hours=5, minutes=30))
    properties["Due Date"] = {"date": {"start": due_date}}
    
    if priority is None:
        priority = 'High'
    properties["Priority"] = {"select": {"name": priority}}
    
    if status is None:
        status = "Not started"
    properties["Status"] = {"status": {"name": status}}

    api_args: Dict[str, Any] = {"parent": {"database_id": TASKS_DATABASE_ID}, "properties": properties}
    
    conn = get_db_connection()
    if isinstance(conn, str):
        return json.dumps({"error": conn})
    try:
        # cursor = conn.cursor(dictionary=True)
        # query = "SELECT phone_number,username FROM Users WHERE notion_user_id LIKE %s"
        # cursor.execute(query, (f"{assignee_id}",))
        # user = cursor.fetchone()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                            user = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT phone_number,username FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{assignee_id}%"},
                                                        fetch_one=True
                            )
        # cursor = conn.cursor(dictionary=True)
        # creator_query = "SELECT phone_number,username FROM Users WHERE notion_user_id LIKE %s"
        # cursor.execute(creator_query, (f"{creator_id}",))
        # creator_user = cursor.fetchone()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                            creator_user = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT phone_number,username FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{creator_id}%"},
                                                        fetch_one=True
                            )
        print(user)
        print(user['username'])
        print(creator_user['username'])
        print(user['phone_number'])
        # ai_response = f"""Hi {user['username']}. *{"You" if creator_user['username'] == user['username'] else creator_user['username']}* just assigned this task *_{task_name}_* to you. This is a *{priority}* priority task. so  you will need to complete this by *{due_date}*.\n *1.{task_name}*\n> Due date: {due_date}\n> Priority: {priority}\n> Status: {status}\n> Assigned by: {creator_user['username']}
        # """
        ai_response = ""

        if language == 'Russian':
            if creator_user['username'] == user['username']:
                assigner_text = "Вы"
            else:
                assigner_text = creator_user['username']

            ai_response = f"""Здравствуйте, {user['username']}. *{assigner_text}* только что назначил(а) вам эту задачу: *_{task_name}_*. Это задача с приоритетом *{priority}*. Вам необходимо выполнить её до *{due_date}*.\n*1.{task_name}*\n> Срок выполнения: {due_date}\n> Приоритет: {priority}\n> Статус: {status}\n> Назначил(а): {creator_user['username']}"""

        elif language == 'Azerbaijani':
            if creator_user['username'] == user['username']:
                assigner_text = "Siz"
            else:
                assigner_text = creator_user['username']
                
            ai_response = f"""Salam, {user['username']}. *{assigner_text}* bu tapşırığı *_{task_name}_* sizə təyin etdi. Bu, *{priority}* prioritetli bir tapşırıqdır. Onu *{due_date}* tarixinədək tamamlamalısınız.\n*1.{task_name}*\n> Son tarix: {due_date}\n> Prioritet: {priority}\n> Status: {status}\n> Təyin etdi: {creator_user['username']}"""

        else:
            if creator_user['username'] == user['username']:
                assigner_text = "You"
            else:
                assigner_text = creator_user['username']

            ai_response = f"""Hi {user['username']}. *{assigner_text}* just assigned this task *_{task_name}_* to you. This is a *{priority}* priority task, so you will need to complete it by *{due_date}*.\n*1.{task_name}*\n> Due date: {due_date}\n> Priority: {priority}\n> Status: {status}\n> Assigned by: {creator_user['username']}"""
        print(ai_response)
        print(creator_id != assignee_id)
        if(creator_id != assignee_id):
            print(user['phone_number'], ai_response)
            await send_whatsapp_message(user['phone_number'], ai_response)
        # cursor = conn.cursor()
        notification_id = str(uuid.uuid4())
        # print(notion_id)
        # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
        # cursor.execute(query_for_changer, (f"%{creator_id}%",))
        # new_notion_id = cursor.fetchone()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                            new_notion_id = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{creator_id}%"},
                                                        fetch_one=True
                            )
        # cursor = conn.cursor()
        print(new_notion_id)
        # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
        # cursor.execute(query_for_changer, (f"%{assignee_id}%",))
        # new_message_assignee_id = cursor.fetchone()
        # cursor.close()
        # cursor = conn.cursor()
        async for conn in get_db_connection():  # get AsyncSession
                            new_message_assignee_id = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{assignee_id}%"},
                                                        fetch_one=True
                            )
        print(new_notion_id)
        print(assignee_id)
        client  = OpenAI()
        new_thread = client.beta.threads.create()
        new_thread_id = new_thread.id
        if(creator_id != assignee_id):
            print("INSERT INTO notifications(notification_id,receiver_id,sender_id,title) Values(%s,%s,%s,%s)",(f"{notification_id}",f"{creator_id}",f"{assignee_id}",f"{notification_id}",))
        #     cursor.execute("""INSERT INTO `threads`
        # (`thread_id`,
        # `title`,
        # `type`)
        # VALUES
        # (%s,
        # %s,
        # %s)
        # """,(new_thread_id,list(notification_id)[0],"web"))
        #     cursor.close()
        #     cursor = conn.cursor()
        #     cursor.execute("INSERT INTO notifications(notification_id,receiver_id,sender_id,title,thread_id) Values(%s,%s,%s,%s,%s)",(list(notification_id)[0],new_message_assignee_id[0],new_notion_id[0],ai_response,new_thread_id,))
            # cursor.close()
            async for conn in get_db_connection():  # get AsyncSession
                await execute_query(
                                                        conn,
                                                        """
                                                        INSERT INTO threads (thread_id, title, type) VALUES (:thread_id,:title,:type)
                                                        """,
                                                        {"thread_id":new_thread_id,"title":list(notification_id)[0],"type":"web"},
                                                        fetch_one=True
                )
            async for conn in get_db_connection():  # get AsyncSession
                await execute_query(
                                                        conn,
                                                        """
                                                        INSERT INTO notifications(notification_id, receiver_id, sender_id, title, thread_id) VALUES (:notification_id,:receiver_id,:sender_id,:title,:thread_id)
                                                        """,
                                                        {"notification_id":list(notification_id)[0], "receiver_id":new_message_assignee_id['user_id'], "sender_id":new_notion_id['user_id'], "title":ai_response, "thread_id":new_thread_id},
                                                        fetch_one=True
                )
    except Exception as e:
        print("Exception",e)     
    if children_blocks_json:
        try:
            api_args["children"] = json.loads(children_blocks_json)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON", "message": "The 'children_blocks_json' string was not valid."})
   
    try:
        response = notion.pages.create(**api_args)
        # --- THIS IS THE CRITICAL CHANGE ---
        # Extract only the essential data from the raw response
        props = response.get("properties", {})
        
        task_name_res = props.get("Task", {}).get("title", [{}])[0].get("plain_text", "N/A")
        status_res = props.get("Status", {}).get("status", {}).get("name", "N/A")
        due_date_res = props.get("Due Date", {}).get("date", {}).get("start", "N/A")
        priority_res = props.get("Priority", {}).get("select", {}).get("name", "N/A")

        # Create a clean, simple dictionary with only the data you need
        simplified_output = {
            "task_name": task_name_res,
            "status": status_res,
            "due_date": due_date_res,
            "priority": priority_res,
            "page_id": response.get("id") # It's good practice to include the ID
        }
        
        # Return the simplified dictionary as a JSON string
        return json.dumps(simplified_output, indent=2)
        # --- END OF CRITICAL CHANGE ---
    except notion_client.APIResponseError as e:
        return json.dumps({"error": "Notion API Error", "details": str(e)})
# --- MODIFICATION END ---


# --- AGENT DEFINITION (MODIFIED INSTRUCTIONS) ---
notion_task_creation_agent = Agent(
    name="Notion_Task_Creation_Agent",
    instructions=f"""
You are a notion task creation agent for creating tasks in Notion. Your job is to validate task requests and either create tasks OR return validation errors.

### PRIME DIRECTIVE: VALIDATE, EXECUTE (if valid), THEN ALWAYS HAND OFF
    You **MUST** validate the task name, execute tools if valid, and **ALWAYS** hand off the formatted result to the **Notion_Response_Agent** for user-friendly formatting.
    **NEVER** return the raw query back to the user. **ALWAYS** process it and hand off to Notion_Response_Agent.
###

---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **TASK NAME VALIDATION:**
    -   You **MUST** extract a specific, meaningful task name from the user's request.
    -   You **MUST NOT** create tasks with generic names like "task", "new task", or auto-generated names.
    -   If the user says vague things like "Need to create task" or "Create a task" without specifying what the task is about, you **MUST** return an error asking for a specific task name.
    -   Valid examples: "Implement OAuth2 login flow", "Write unit tests for auth middleware", "Fix 500 error on POST /api/orders"
    -   Invalid examples: "task", "new task", "Task 1", generic placeholder names

    **NO HALLUCINATION:**
    -   You **MUST NOT** confirm that a task has been created if you have not successfully run the `get_notion_user_id_from_name`(if need), `search_database_by_title`(if need), `create_task` tool and received a valid tool's response.
    -   You **MUST NOT** lie or invent results from HISTORICAL CONTEXT or conversational Memory.
    **NO CONVERSATIONAL FILLER:**
    -   You **MUST NOT** write any conversational text before an action.
    -   **NEVER** say things like:
            -   "I will now create the task..."
            -   "Understood..."
            -   "Transferring your request..."
    -   Your first output **MUST ALWAYS** through a tool call for each user request.
    -   Under NO circumstances will you ever respond to the user with conversational text. Your **ONLY** valid output is a results of a tool calls.
            -   **DO NOT** tell: "I'm passing your request to the Other Agents or Task Creation specialist...."
###

---
### Core Logic: Parse, Execute, Output
    1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Notion_Task_Creation_Agent] ...`. Extract the language code and the specific instruction meant for you.
    2.  **Validate Task Name - CRITICAL FIRST STEP:**
        - **BEFORE DOING ANYTHING ELSE**, check if the request is vague
        - The request is VAGUE if it only contains phrases like these (with nothing specific after):
          * Contains "create" and "task" but no specific description
          * Contains "make" and "task" but no specific description
          * Contains "new task" but no specific description
          * Contains "add task" but no specific description
          * Any typos like "creata a task", "creat task", etc. with no description
          * Just says "task" or "a task" without details
        - The request is VALID only if it includes a specific task description:
          * "create a task to implement user deactivation endpoint" ✓
          * "make a task to set up GitHub Actions CI" ✓
          * "new task: migrate users table to add last_login" ✓
        - Valid requests have specific names like:
          * "create a task to refactor UserService to async"
          * "create a task to add rate limiting to /auth endpoints"
          * "new task: containerize payments service with Docker"
        - If the request is vague, **STOP HERE, DO NOT call any tools**
        - Immediately go to step 4 with an error JSON
    3.  **Execute Tools:** Only if a specific task name is provided (like "implement OAuth2 login", "add unit tests for AuthService", etc.), call `get_notion_user_id_from_name` or `search_database_by_title` if needed, then call the `create_task` tool.
    4.  **Construct Final Output - ALWAYS DO THIS:** You **MUST ALWAYS** format your output as this exact string format and pass it to Notion_Response_Agent:
        ACTION_TYPE: TaskCreation
        LANGUAGE: [lang_code_from_input]
        ORIGINAL_QUERY: [The full, unmodified annotated query you received]
        TOOL_OUTPUT: [For validation errors use: {{"error": "Invalid Task Name", "message": "Please provide a specific task name like 'Implement OAuth2 login flow' or 'Write unit tests for auth middleware'."}}]
    5.  **Hand Off:** Pass this ENTIRE formatted string to the `Notion_Response_Agent` for final user-friendly formatting and response. The Response Agent will format it properly for the user.

    ### **Examples:**
    **Valid Task Creation:**
        -   **Query Received:** `(language='en') Create a task to implement OAuth2 login flow [Notion_Task_Creation_Agent]`
        -   **Your Final Output After Calling `create_task`:**
                ACTION_TYPE: TaskCreation
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Create a task to implement OAuth2 login flow [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"task_name": "Implement OAuth2 login flow", "status": "Not started", "due_date": "2025-09-21", "priority": "High", "page_id": "f9a8b7-..."}}

    **Invalid/Vague Examples (NO tools called, BUT YOU MUST STILL OUTPUT):**

        Example 1:
        -   **Query Received:** `(language='en') create a task [Notion_Task_Creation_Agent]`
        -   **Your REQUIRED Output (NO tools called):**
                ACTION_TYPE: TaskCreation
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') create a task [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"error": "Invalid Task Name", "message": "Please provide a specific task name like 'Implement OAuth2 login flow' or 'Write unit tests for auth middleware'."}}

        Example 2 (with typo):
        -   **Query Received:** `(language='en') creata a task [Notion_Task_Creation_Agent]`
        -   **Your REQUIRED Output (NO tools called):**
                ACTION_TYPE: TaskCreation
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') creata a task [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"error": "Invalid Task Name", "message": "Please provide a specific task name like 'Implement OAuth2 login flow' or 'Write unit tests for auth middleware'."}}

        Example 3:
        -   **Query Received:** `(language='en') Need to create task [Notion_Task_Creation_Agent]`
        -   **Your REQUIRED Output (NO tools called):**
                ACTION_TYPE: TaskCreation
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Need to create task [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"error": "Invalid Task Name", "message": "Please provide a specific task name like 'Implement OAuth2 login flow' or 'Write unit tests for auth middleware'."}}

    **Multi-Query Scenario:**        
        -   **Query Received:** `(language='en') Create a task 'Add unit tests for AuthService' [Notion_Task_Creation_Agent] and then add a comment 'cc @Shafraz' [Notion_Comment_Agent]`
        -   **Your Final Output After Calling `create_task`:**
            ACTION_TYPE: TaskCreation
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Create a task 'Add unit tests for AuthService' [Notion_Task_Creation_Agent] and then add a comment 'cc @Shafraz' [Notion_Comment_Agent]
            TOOL_OUTPUT: {{"task_name": "Add unit tests for AuthService", "status": "Not started", "due_date": "2025-09-21", "priority": "High", "page_id": "c2a3b1-..."}}
###

---
### **Special Workflow: Handling Ambiguous and Misspellings User Names**
    This workflow is a high-priority exception to your normal logic.

    -   If you call the `get_notion_user_id_from_name` tool and the JSON output it returns contains `"error": "Ambiguous Name"`, you **MUST** immediately stop the task creation process.
    -   If `get_notion_user_id_from_name` returns an `"error": "User Not Found With Suggestion"`, you **MUST** also stop and format a `ClarificationRequired` output, but this time using the `"suggestion"`.
    -   Your next and **ONLY** action is to construct a final output string for the `Notion_Response_Agent`.
    -   This output **MUST** use the `ACTION_TYPE: ClarificationRequired`.
    -   The `TOOL_OUTPUT` for this action **MUST** be a new JSON object that you create, containing a question and the list of names provided by the tool.

    #### **Example of Handling Ambiguity**
        -   **Your Instruction:** `(language='en') Create a task for Aboo to review the document [Notion_Task_Creation_Agent]`
        -   **Your First Tool Call:** `get_notion_user_id_from_name(username="Aboo")`
        -   **Tool Output You Receive:** `{{"error": "Ambiguous Name", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Create a task for Aboo to review the document [Notion_Task_Creation_Agent]
            TOOL_OUTPUT: {{"question": "I found a few people named 'Aboo'. Which one did you mean?", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}
    #### 
   
    ---
    #### **Example of Handling Misspelling**
        -   **Your Instruction:** `(language='en') Create a task for Abu to review the document`
        -   **Tool Output You Receive:** `{{"error": "User Not Found With Suggestion", "suggestion": "Aboo"}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Create a task for Abu...
            TOOL_OUTPUT: {{"question": "I couldn't find a user named 'Abu'. Did you mean 'Aboo'?", "or Can you mention the correct name?"}}
    ####
###
                
---
### **How to Construct Rich Content**
    You must build a JSON array of block objects.

    *   **For a simple description:**
        `[ {{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [{{"type": "text", "text": {{"content": "This is the task description."}}}}]}}}} ]`

    *   **For a To-Do List:**
        `[ {{"object": "block", "type": "to_do", "to_do": {{"rich_text": [{{"type": "text", "text": {{"content": "First item."}}}}]}}}}, {{"object": "block", "type": "to_do", "to_do": {{"rich_text": [{{"type": "text", "text": {{"content": "Second item."}}}}]}}}} ]`

    *   **For Rich Text with a Hyperlink:**
        To create a hyperlink, the `link` object must be inside the `text` object.
        `[ {{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [
            {{"type": "text", "text": {{"content": "This is important: "}}}},
            {{"type": "text", "text": {{"content": "please review the documentation", "link": {{"url": "https://developers.notion.com"}}}}, "annotations": {{"bold": true}} }}
        ]}}}} ]`
###

---                   
### **Tool Execution guide**
    -   You **MUST** extract the `logged_in_user_id` from the context and pass it to the `creator_id` parameter.
    -   If the user assigns the task to themselves ("assign to me"), use the `logged_in_user_id` for the `assignee_id`.
###
    
---
### **Context & Data Mapping:**
    - **Current Date:** `{date.today().isoformat()}`
    - **Logged-in User ID:** `{{logged_in_user_id}}` (for `creator_id`)
    - **Database ID:** `{{database_id}}`
    - **Status:** from the successful tool call's `properties.Status.status.name`
    - **Due date:** from `properties['Due Date'].date.start`
    - **Priority:** from `properties.Priority.select.name`

### **CRITICAL FINAL REMINDER:**
    **YOU MUST ALWAYS OUTPUT** the formatted string (ACTION_TYPE, LANGUAGE, ORIGINAL_QUERY, TOOL_OUTPUT) and hand it off to Notion_Response_Agent, even when:
    - The task name is vague or missing (output with error JSON in TOOL_OUTPUT)
    - Validation fails (output with error JSON in TOOL_OUTPUT)
    - Any error occurs (output with error JSON in TOOL_OUTPUT)
    **NEVER** just return the original query. **ALWAYS** process it, format the output, and hand off to Notion_Response_Agent.
###
""",
    tools=[
        get_notion_user_id_from_name, 
        create_task,
        search_database_by_title,
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-4.1",
)
