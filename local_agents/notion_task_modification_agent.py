#local_agents\notion_task_modification_agent.py
import os
import json
import uuid
from dotenv import load_dotenv
import notion_client
from agents import Agent, function_tool, handoff
from model.response_agent_input import ResponseAgentInput
import mysql.connector
from datetime import date, timedelta
from typing import List, Dict, Optional

from openai import OpenAI
from db import get_db_connection
from utils.db_helper import execute_query
from utils.whatsapp_utils import send_whatsapp_message
import difflib

from local_agents.notion_response_agent import notion_response_agent

# --- SETUP ---
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")

# Validate that the required environment variables are set
if not all([NOTION_API_KEY, TASKS_DATABASE_ID]):
    raise ValueError("One or more required environment variables are missing: NOTION_API_KEY, TASKS_DATABASE_ID")

# Initialize the Notion client
notion = notion_client.Client(auth=NOTION_API_KEY)

def manage_response_agent_handoff(context, input: ResponseAgentInput):
    """
    Handles the response agent handoff by processing the specialist tool output
    and preparing the final response for the user.
    """
    print("response agent start") 
    

@function_tool
def find_tasks(filter_json: Optional[str] = None) -> str:
    """
    Finds and retrieves a list of tasks from the Notion database based on a JSON filter.
    Use this to find a task's ID when the user provides its name.
    """
    try:
        query_params: Dict = {"database_id": TASKS_DATABASE_ID}
        if filter_json:
            query_params["filter"] = json.loads(filter_json)
            
        response = notion.databases.query(**query_params)
        return json.dumps(response, indent=2)
        
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON", "message": "The filter_json string was not valid JSON."})
    except notion_client.APIResponseError as e:
        return json.dumps({"error": "Notion API Error", "details": str(e)})

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
    
@function_tool
async def update_task_properties(task_page_id: str, properties_to_update_json: str,notion_id:str,language:str) -> str:
    """
    Updates specific METADATA PROPERTIES of an existing task page (e.g., Status, Assignee, Due Date).
    This tool CANNOT change the text content inside the page body.
    The 'properties_to_update_json' must be a valid JSON string.
    Example for updating status: '{"Status": {"status": {"name": "In Progress"}}}'
    """
    if not task_page_id:
        return json.dumps({"error": "Missing Task Page ID", "message": "The ID of the task page to update is required."})
    try:
        properties = json.loads(properties_to_update_json)
        get_task_details = notion.pages.retrieve(page_id=task_page_id)
        response = notion.pages.update(page_id=task_page_id, properties=properties)
        # for details in get_task_details['properties']:
        #     print(f"{details} is {get_task_details['properties'][details]}")
        #     print(details)
        not_applicable =  "N\A"
        task_name = str(get_task_details['properties']['Task']['title'][0]['plain_text'] or not_applicable)
        print(task_name)
        try:
            # print(get_task_details['properties'])
            username = notion.users.retrieve(notion_id)['name']
            print(username)
            if language == 'Russian':
                message = f"*{username}* обновил(а) свойства в *{task_name}*.\n"
            elif language == 'Azerbaijani':
                message = f"*{username}* *{task_name}* tapşırığında xüsusiyyətləri yenilədi.\n"
            else:
                message = f"*{username}* updated property in *{task_name or not_applicable}*.  \n"
            
            for property in properties:
                if(property == "Assignee"):
                    if language == 'Russian':
                        message += f"""> Исполнитель\n> *{get_task_details['properties']['Assignee']['people'][0]['name'] or not_applicable}* -> *You*\n"""
                    elif language == 'Azerbaijani':
                        message += f"""> İcraçı\n> *{get_task_details['properties']['Assignee']['people'][0]['name'] or not_applicable}* -> *You*\n"""
                    else:
                        message += f"""> Assignee\n> *{get_task_details['properties']['Assignee']['people'][0]['name'] or not_applicable}* -> *You*\n"""
                    print(properties[property]['people'][0] or not_applicable)
                if(property == "Due Date"):
                    if language == 'Russian':
                        message += f"""> Срок выполнения\n> *{get_task_details['properties']['Due Date']['date']['start'] or not_applicable}* -> *{properties[property]['date']['start'] or not_applicable}*\n"""
                    elif language == 'Azerbaijani':
                        message += f"""> Son Tarix\n> *{get_task_details['properties']['Due Date']['date']['start'] or not_applicable}* -> *{properties[property]['date']['start'] or not_applicable}*\n"""
                    else:
                        message += f"""> Due Date\n> *{get_task_details['properties']['Due Date']['date']['start'] or not_applicable}* -> *{properties[property]['date']['start'] or not_applicable}*\n"""
                    print(properties[property]['date']['start'] or not_applicable)
                if(property == "Status"):
                    if language == 'Russian':
                        message += f"""> Статус\n> *{get_task_details['properties']['Status']['status']['name'] or not_applicable}* -> *{properties[property]['status']['name'] or not_applicable}*\n"""
                    elif language == 'Azerbaijani':
                        message += f"""> Status\n> *{get_task_details['properties']['Status']['status']['name'] or not_applicable}* -> *{properties[property]['status']['name'] or not_applicable}*\n"""
                    else:
                        message += f"> Status\n> *{get_task_details['properties']['Status']['status']['name'] or not_applicable}* -> *{properties[property]['status']['name'] or not_applicable}*\n"
                    print(properties[property]['status']['name'] or not_applicable)
                if(property == "Priority"):
                    if language == 'Russian':
                        message += f"""> Приоритет\n> *{get_task_details['properties']['Priority']['select']['name'] or not_applicable}* -> *{properties[property]['select']['name'] or not_applicable}* \n"""
                    elif language == 'Azerbaijani':
                        message += f"""> Prioritet\n> *{get_task_details['properties']['Priority']['select']['name'] or not_applicable}* -> *{properties[property]['select']['name'] or not_applicable}* \n"""
                    else:
                        message += f"> Priority\n> *{get_task_details['properties']['Priority']['select']['name'] or not_applicable}* -> *{properties[property]['select']['name'] or not_applicable}* \n"
                    print(properties[property]['select']['name'] or not_applicable)
                # if(property == "Created by"):
                #     message += f"> Which is created by {properties[property]} \n"
                #     print(properties[property])
            print(message)
            message_assignee = response['properties']['Assignee']['people'][0]['name']
            message_assignee_id = response['properties']['Assignee']['people'][0]['id']
            print(message_assignee)
            print(message_assignee_id)
            # conn = get_db_connection()
            # cursor = conn.cursor()
            # query_for_phone_number = "SELECT phone_number FROM Users WHERE notion_user_id LIKE %s"
            # cursor.execute(query_for_phone_number, (f"%{message_assignee_id}%",))
            # phone_number = cursor.fetchone()
            # cursor.close()
            async for conn in get_db_connection():  # get AsyncSession
                            phone_number = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT phone_number FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{message_assignee_id}%"},
                                                        fetch_one=True
                            )
            # cursor = conn.cursor()
            # query_for_changer = "SELECT username FROM Users WHERE notion_user_id LIKE %s"
            # cursor.execute(query_for_changer, (f"%{notion_id}%",))
            # changer = cursor.fetchone()
            async for conn in get_db_connection():  # get AsyncSession
                            changer = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT username FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{notion_id}%"},
                                                        fetch_one=True
                            )
            print(changer)
            # cursor.close()
            print(phone_number)
            ai_repsonse = f"{message}"
            if(notion_id != message_assignee_id):
                await send_whatsapp_message(phone_number['phone_number'],ai_repsonse)
            # cursor = conn.cursor()
            notification_id = {str(uuid.uuid4()),}
            print(notion_id)
            # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
            # cursor.execute(query_for_changer, (f"%{notion_id}%",))
            # new_notion_id = cursor.fetchone()
            async for conn in get_db_connection():  # get AsyncSession
                            new_notion_id = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{notion_id}%"},
                                                        fetch_one=True
                            )
            print(new_notion_id)
            # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
            # cursor.execute(query_for_changer, (f"%{message_assignee_id}%",))
            # new_message_assignee_id = cursor.fetchone()
            # cursor.close()
            async for conn in get_db_connection():  # get AsyncSession
                            new_message_assignee_id = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {f"%{message_assignee_id}%"},
                                                        fetch_one=True
                            )
            # cursor = conn.cursor()
            print(new_notion_id)
            # print(message_assignee_id)
            client  = OpenAI()
            new_thread = client.beta.threads.create()
            new_thread_id = new_thread.id
            print("INSERT INTO notifications(notification_id,sender_id,receiver_id,title) Values(%s,%s,%s,%s)",(f"{notification_id}",f"{notion_id}",f"{message_assignee_id}",f"{notification_id}",))
            if new_message_assignee_id[0]!=new_notion_id[0]:
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
                                                        {"notification_id":list(notification_id)[0], "receiver_id":new_message_assignee_id['user_id'], "sender_id":new_notion_id['user_id'], "title":ai_repsonse, "thread_id":new_thread_id},
                                                        fetch_one=True
                            )
    #             cursor.execute("""INSERT INTO `threads`
    # (`thread_id`,
    # `title`,
    # `type`)
    # VALUES
    # (%s,
    # %s,
    # %s)
    # """,(new_thread_id,list(notification_id)[0],"web"))
    #             cursor.close()
    #             cursor = conn.cursor()
    #             cursor.execute("INSERT INTO notifications(notification_id,receiver_id,sender_id,title,thread_id) Values(%s,%s,%s,%s,%s)",(list(notification_id)[0],new_message_assignee_id[0],new_notion_id[0],ai_repsonse,new_thread_id,))
    #             cursor.close()
        except Exception as e:
            print("Exception",e)
        # print(user['phone_number'])
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error updating task properties {task_page_id}: {e}"

@function_tool
def delete_task(task_page_id: str) -> str:
    """
    Deletes a task by archiving its page in Notion. This is a soft delete.
    Requires the ID of the task page to be deleted.
    """
    if not task_page_id:
        return json.dumps({"error": "Missing Task Page ID", "message": "The ID of the task page to delete is required."})
    try:
        response = notion.pages.update(page_id=task_page_id, archived=True)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error deleting task {task_page_id}: {e}"

# --- NEW TOOL FOR CONTENT MODIFICATION ---
@function_tool
def append_content_to_page(page_id: str, children_blocks_json: str) -> str:
    """
    Appends new content blocks (like paragraphs, to-do lists, or headings) to the BODY of a specific page.
    Use this tool when the user asks to add or list text, todos, or other content inside the task page itself.
    This tool does NOT modify properties like status or assignee.
    """
    if not page_id:
        return json.dumps({"error": "Missing page_id", "message": "The ID of the page to append content to is required."})
    try:
        # The input is a JSON string, which needs to be parsed into a Python list of block objects.
        children_blocks: List[Dict] = json.loads(children_blocks_json)
        response = notion.blocks.children.append(block_id=page_id, children=children_blocks)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error appending content to page {page_id}: {e}"


# --- AGENT DEFINITION (FIXED and UPDATED) ---
notion_task_modification_agent = Agent(
    name="Notion_Task_Modification_Agent",
    instructions=f"""
You are a notion task modification agent. Your primary function is to execute tools to update, change, or delete tasks. You are **FORBIDDEN** from generating a final user-facing response until you have successfully executed a tool call and have its output.

### PRIME DIRECTIVE: ACTION FIRST, RESPONSE SECOND
    Your **MUST** run your tools and then hand off the raw results to the **Notion_Response_Agent** for formatting.
###
    
---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **NO HALLUCINATION:** 
    -   You **MUST NOT** confirm that a task has been modified if you have not successfully run the `find_tasks`(if need), `get_notion_user_id_from_name`(if need), and a final modification tool like `update_task_properties` and received a valid tool's response. 
    -   You **MUST NOT** lie or invent results from HISTORICAL CONTEXT or conversational Memory.
    **NO CONVERSATIONAL FILLER:** 
    -   You **MUST NOT** write any conversational text before an action. 
    -   **NEVER** say things like: 
            -   "I will now update the task..."
            -   "Finding the task..."
            -   "Transferring your request..."
    -   Your first output **MUST ALWAYS** be a tool call for each user request.
    -   Under NO circumstances will you ever respond to the user with conversational text. Your **ONLY** valid output is a result of a tool call.
            -   **DO NOT** tell: "I’m passing your request to the Other Agents or Task Modification specialist...."
###
    
---
---
### Core Logic: Parse, Execute, Output
    ### Your Core Logic is a Strict Sequence:
        1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Notion_Task_Retrieval_Agent] ...`. Extract the language code and the specific instruction meant for you.
        2.  **Execute Tools:** Call `get_notion_user_id_from_name` if needed to get a user ID, then call the `find_tasks` tool with the correctly constructed filter JSON.
        3.  **Construct Final Output:** After the `find_tasks` tool call is successful (or fails), you **MUST** format your entire output as a single string, and nothing else, like this:

            ACTION_TYPE: TasksRetrieved
            LANGUAGE: [lang_code_from_input]
            ORIGINAL_QUERY: [The full, unmodified annotated query you received]
            TOOL_OUTPUT: [The final, raw JSON result from your `find_tasks` tool call. This MUST include the full 'results' array.]
        4.  **Hand Off:** Pass this entire formatted string to the `Notion_Response_Agent` for final user-friendly formatting and response.
    ###
        
    ---
    ### Internal Tool Usage Guide
        - To construct the `filter_json` for the `find_tasks` tool, analyze the user's request for keywords.
        - For "my tasks", use the `logged_in_user_id`.
        - For a specific person, use `get_notion_user_id_from_name` first.
        - **CRITICAL FILTERING RULE:** By default, you **MUST** always add conditions to your `filter_json` to exclude tasks with a status of "Done" or "Blocked", unless the user explicitly asks for them.
    ###
        
    ---
    ### Examples

        #### **Single-Query Scenario**
            -   **Query Received:** `(language='en') list my tasks for this week [Notion_Task_Retrieval_Agent]`
            -   **Your Final Output After Calling `find_tasks`:**
                ACTION_TYPE: TasksRetrieved
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') list my tasks for this week [Notion_Task_Retrieval_Agent]
                TOOL_OUTPUT: {{"results": [{{"id": "task-id-1", "properties": {{"Task": {{"title": [{{"plain_text": "Review overdue items"}}]}}, "Due Date": {{"date": {{"start": "2025-09-19"}}}}, "Priority": {{"select": {{"name": "High"}}}}, "Assignee": {{...}} }} }}, {{"id": "task-id-2", "properties": {{...}} }}]}}
        ####
                
        #### **Multi-Query Scenario**
            -   **Query Received:** `(language='en') Show me my tasks for today [Notion_Task_Retrieval_Agent] and then remind me to call Anna [Reminder_Agent]`
            -   **Your Final Output After Calling `find_tasks`:**
                ACTION_TYPE: TasksRetrieved
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Show me my tasks for today [Notion_Task_Retrieval_Agent] and then remind me to call Anna [Reminder_Agent]
                TOOL_OUTPUT: {{"results": [{{"id": "task-id-3", "properties": {{"Task": {{"title": [{{"plain_text": "Finalize report"}}]}}, "Due Date": {{"date": {{"start": "2025-09-21"}}}}, "Priority": {{"select": {{"name": "High"}}}}, "Assignee": {{...}} }} }}]}}
        ####
    ###
###
                
---
---
### **Special Workflow: Handling Ambiguous and Misspelled User Names**
    This workflow is a high-priority exception to your normal logic.

    -   If you call the `get_notion_user_id_from_name` tool and the JSON output it returns contains `"error": "Ambiguous Name"`, you **MUST** immediately stop the task modification process.
    -   If `get_notion_user_id_from_name` returns an `"error": "User Not Found With Suggestion"`, you **MUST** also stop the task modification process.
    -   Your next and **ONLY** action is to construct a final output string for the `Notion_Response_Agent`.
    -   This output **MUST** use the `ACTION_TYPE: ClarificationRequired`.
    -   The `TOOL_OUTPUT` for this action **MUST** be a new JSON object that you create, containing a question and the list of options provided by the tool.

    #### **Example of Handling Ambiguity**
        -   **Your Instruction:** `(language='en') Change the assignee of 'Project Alpha' to Aboo [Notion_Task_Modification_Agent]`
        -   **Your First Tool Call:** `get_notion_user_id_from_name(username="Aboo")`
        -   **Tool Output You Receive:** `{{"error": "Ambiguous Name", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Change the assignee of 'Project Alpha' to Aboo [Notion_Task_Modification_Agent]
            TOOL_OUTPUT: {{"question": "I found a few people named 'Aboo'. Which one did you mean?", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}
    ####
            
    ---
    #### **Example of Handling Misspelling**
        -   **Your Instruction:** `(language='en') Assign the task 'Deploy Updates' to Abu [Notion_Task_Modification_Agent]`
        -   **Tool Output You Receive:** `{{"error": "User Not Found With Suggestion", "suggestion": "Aboo"}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Assign the task 'Deploy Updates' to Abu [Notion_Task_Modification_Agent]
            TOOL_OUTPUT: {{"question": "I couldn't find a user named 'Abu'. Did you mean 'Aboo'?", "or Can you mention the correct name?"}}
    ####
###
---
                
---    
### **Primary Logic**  
    ### **Tool Execution guide**
        -   **Your Primary Task:** You **MUST** find the part of the query tagged with your name, `[Notion_Task_Modification_Agent]`.
        -   **Execution:** You **MUST** extract the instruction associated with your tag (e.g., "change the status of 'Task A' to Done") and use that information to call the appropriate tools.
            -   **CRITICAL "Find then Modify" FLOW:** Your first tool call **MUST** be `find_tasks` to get the Page ID of the task you need to modify. This is a non-negotiable first step.
            -   If changing an assignee, you **MUST** then call `get_notion_user_id_from_name` to get their ID before calling `update_task_properties`.
        -   **Ignore Others:** You **MUST** completely ignore all other parts of the query that are tagged for other agents (e.g., `[Notion_Reminder_Agent]`).
    ###
        
    ---
    ###**Example Scenarios:**
        **If the user provides a task NAME (e.g., "in 'task01'"):**
        1.  **First, you MUST call the `find_tasks` tool** to get the task's ID.
            - Build a filter for the exact title: `find_tasks(filter_json='{{"property": "Task", "title": {{"equals": "task01"}}}}')`
        2.  **Extract the `id`** from the JSON response of the `find_tasks` tool.
        3.  **Then, call the appropriate modification tool** (`update_task_properties` or `append_content_to_page` or `delete_task`) using the ID you just found.

        **If the user provides a valid page ID in his previous chats, you can skip the find step.**
    ###
        
    ---
    ### **Workflow 1: Updating Task PROPERTIES (Status, Assignee, Due Date, etc.)**
        Use this workflow when the user asks to change metadata about the task.

        1.  **Identify Target:** Get the `task_page_id` from the user's request.
        2.  **Identify Property Changes:** Determine which properties to change (Status, Priority, Due Date, Assignee).
        3.  **Resolve User ID (if changing assignee):** You **MUST** first use `get_notion_user_id_from_name` to get the new assignee's Notion ID.
        4.  **Construct JSON:** Build the `properties_to_update_json` string.
            *   For status: `{{"Status": {{"status": {{"name": "New Status"}}}}}}`
            *   For assignee: `{{"Assignee": {{"people": [{{"id": "user-id"}}]}}}}`
            *   For Due Date or Deadline:** `{{"Due Date": {{"date": {{"start": "YYYY-MM-DD"}}}}}}`
            *   For Priority or Priority Level:** `{{"Priority": {{"select": {{"name": "High"}}}}}}`
        5.  **Execute:** Call `update_task_properties` with the `task_page_id` ,the JSON string and logged_in_user_id, in USER LANGUAGE.
        6.  **Confirm:** Respond with "Done. The task properties have been updated."
    ###
        
    ---
    ### **Workflow 2: Adding CONTENT to the Task Page Body**
        Use this workflow ONLY when the user asks to add text, paragraphs, lists, or other rich content *inside* the task page.

        1.  **Identify Target:** Get the `task_page_id` from the user's request.
        2.  **Generate Content:** Based on the user's request, determine the content to be added.
        3.  **Construct JSON:** Build the `children_blocks_json` string. This must be a JSON array of Notion block objects.
            *   **CRITICAL JSON SYNTAX RULE:** The `children_blocks_json` string MUST be a valid JSON array. This means every block object `{{...}}` inside the main `[ ... ]` array **MUST** be separated by a comma. A missing comma will cause the entire operation to fail.
            *   **CRITICAL RULE FOR LINKS:** If a string of text contains a URL, you **MUST** split the string into a descriptive part and the URL part. Then, create a `rich_text` array with a separate object for the link.
            *   **Example of correct link handling:**
                *   **Input text:** "Check out the docs here: https://developers.notion.com"
                *   **Correct JSON construction:**
                    `[ {{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [ {{"type": "text", "text": {{"content": "Check out the docs here: "}}}}, {{"type": "text", "text": {{"content": "https://developers.notion.com", "link": {{"url": "https://developers.notion.com"}}}}}} ]}}}}, {{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [ ... ]}}}} ]`4.  **Execute:** Call `append_content_to_page` with the `task_page_id` and the `children_blocks_json` string.
        5.  **Confirm:** Respond with "Done. I have added the content to the task page."
    ###
        
    ---
    ### **Workflow 3: Deleting a Task**
        Use this workflow when the user asks to delete, remove, or archive a task.

        1.  **Identify Target:** Get the `task_page_id` from the user.
        2.  **Execute:** Call the `delete_task` tool with the `task_page_id`.
        3.  **Confirm:** Respond with "The task has been successfully deleted."
    ###
###
    
---
### **Context & Data Mapping:**
    - **Current Date:** `{date.today().isoformat()}`
    - **Logged-in User ID:** `{{logged_in_user_id}}`
    - **Database ID:** `{{database_id}}`
    - **[task name]:** Extract the task name from the successful tool call's JSON response (`properties.Name.title[0].plain_text`).
###
""",
    tools=[
        get_notion_user_id_from_name,
        find_tasks,
        update_task_properties,
        delete_task,
        append_content_to_page, 
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-4.1",
)
