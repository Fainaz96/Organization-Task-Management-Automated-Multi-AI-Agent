import os
import json
from typing import Optional, List
import uuid
from dotenv import load_dotenv
import notion_client
from notion_client.errors import APIResponseError
from agents import Agent, function_tool, handoff

from model.response_agent_input import ResponseAgentInput
from openai import OpenAI
import difflib

from db import get_db_connection
from utils.db_helper import execute_query
from utils.whatsapp_utils import send_whatsapp_message

from local_agents.notion_response_agent import notion_response_agent

# --- SETUP ---
load_dotenv()
api_key = os.getenv("NOTION_API_KEY")
if not api_key:
    raise ValueError("FATAL: NOTION_API_KEY not found. Ensure it is set in your .env file.")
notion = notion_client.Client(auth=api_key)

def manage_response_agent_handoff(context, input: ResponseAgentInput):
    """
    Handles the response agent handoff by processing the specialist tool output
    and preparing the final response for the user.
    """
    print("response agent start") 

def _append_commented_by_signature(rich_text_list: list, commenter_notion_user_id: Optional[str]) -> list:
    """
    Internal Helper: Appends the mandatory '__________ Commented by @User' signature.
    This version uses the provided Notion User ID directly, without any database lookups.
    """
    if commenter_notion_user_id:
        separator = "\n\n__________\nCommented by "
        rich_text_list.append({"type": "text", "text": {"content": separator}})
        rich_text_list.append({"type": "mention", "mention": {"type": "user", "user": {"id": commenter_notion_user_id}}})
    else:
        fallback_signature = f"\n\n__________\nCommented by System (Attribution ID missing)"
        rich_text_list.append({"type": "text", "text": {"content": fallback_signature}})
        
    return rich_text_list


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
async def add_comment_to_page(page_id: str, rich_text_json: str, commenter_notion_user_id: str) -> str:
    """
    Adds a new top-level comment to a page. AUTOMATICALLY appends the mandatory 'Commented by @user' signature.
    The 'commenter_notion_user_id' parameter is REQUIRED and must be the Notion ID of the user creating the comment.
    """
    if not page_id:
        return json.dumps({"error": "Missing Page ID"})
    if not commenter_notion_user_id:
        return json.dumps({"error": "Missing commenter_notion_user_id", "message": "The commenter's Notion ID is required for attribution."})
        
    try:
        rich_text_list = json.loads(rich_text_json)
        final_rich_text = _append_commented_by_signature(rich_text_list, commenter_notion_user_id)
        response = notion.comments.create(parent={"page_id": page_id}, rich_text=final_rich_text)
        comment = ""
        for respond in final_rich_text:
            if(respond['type'] == "text"):
                if "Commented by" in respond['text']['content']:
                    break
                comment += respond['text']['content']
            if(respond['type'] == "mention"):
                comment += notion.users.retrieve(respond['mention']['user']['id'])['name']
        for respond in response['rich_text']:
            if(respond['type'] == "text"):
                respond['text']['content']
                if "Commented by" in respond['text']['content']:
                    continue
                comment_name  = respond['text']['content']


        count = 0
        for respond in response['rich_text']:
            if(respond['type'] == "mention"):
                try:
                    nid= respond['mention']['user']['id']
                    # conn = get_db_connection()
                    # cursor = conn.cursor()
                    # query_for_phone_number = "SELECT phone_number FROM Users WHERE notion_user_id LIKE %s"
                    # cursor.execute(query_for_phone_number, (f"%{nid}%",))
                    # phone_number = cursor.fetchone()
                    async for conn in get_db_connection():  # get AsyncSession
                            phone_number = await execute_query(
                                                        conn,
                                                        """
                                                        SELECT phone_number FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{nid}%"},
                                                        fetch_one=True
                            )
                    # query_for_commentor = "SELECT username FROM Users WHERE notion_user_id LIKE %s"
                    # cursor.execute(query_for_commentor, (f"%{commenter_notion_user_id}%",))
                    # commentor_name = cursor.fetchone()
                    # cursor.close()
                    async for conn in get_db_connection():  # get AsyncSession
                            commentor_name =await execute_query(
                                                        conn,
                                                        """
                                                        SELECT username FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{commenter_notion_user_id}%"},
                                                        fetch_one=True
                            )
                    #print(phone_number[0])
                    get_task_details = notion.pages.retrieve(page_id=page_id)
                    task_name = str(get_task_details['properties']['Task']['title'][0]['plain_text'])
                    #print(task_name)
                    ai_repsonse = f"*{commentor_name['username']}* commented in *{task_name}* \n"+f"> {comment}" 
                    if(commenter_notion_user_id != nid):
                        print(phone_number,ai_repsonse)
                        await send_whatsapp_message(phone_number['phone_number'],ai_repsonse )
                    # cursor = conn.cursor()
                    notification_id = str(uuid.uuid4())
                    # print(notion_id)
                    # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
                    # cursor.execute(query_for_changer, (f"%{commenter_notion_user_id}%",))
                    # new_notion_id = cursor.fetchone()
                    async for conn in get_db_connection():  # get AsyncSession
                            new_notion_id = commentor_name =await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{commenter_notion_user_id}%"},
                                                        fetch_one=True
                            )
                    #print(new_notion_id)
                    # query_for_changer = "SELECT user_id FROM Users WHERE notion_user_id LIKE %s"
                    # cursor.execute(query_for_changer, (f"%{nid}%",))
                    # new_message_assignee_id = cursor.fetchone()
                    async for conn in get_db_connection():  # get AsyncSession
                            new_message_assignee_id =await execute_query(
                                                        conn,
                                                        """
                                                        SELECT user_id FROM Users WHERE notion_user_id LIKE :id
                                                        """,
                                                        {"id":f"%{nid}%"},
                                                        fetch_one=True
                            )
                    print(new_notion_id)
                    print(nid)
                    client  = OpenAI()
                    new_thread = client.beta.threads.create()
                    new_thread_id = new_thread.id
                    print("INSERT INTO notifications(notification_id,sender_id,receiver_id,title) Values(%s,%s,%s,%s)",(f"{notification_id}",f"{commenter_notion_user_id}",f"{nid}",f"{notification_id}",))
                    if(commenter_notion_user_id != nid):
                    #     cursor.execute("""INSERT INTO `threads`
                    # (`thread_id`,
                    # `title`,
                    # `type`)
                    # VALUES
                    # (%s,
                    # %s,
                    # %s)
                    # """,(new_thread_id,list(notification_id)[0],"web"))
                        async for conn in get_db_connection():  # get AsyncSession
                            await execute_query(
                                                        conn,
                                                        """
                                                        INSERT INTO threads (thread_id, title, type) VALUES (:thread_id,:title,:type)
                                                        """,
                                                        {"thread_id":new_thread_id,"title":notification_id,"type":"web"},
                                                        fetch_one=True
                            )
                        async for conn in get_db_connection():  # get AsyncSession
                            await execute_query(
                                                        conn,
                                                        """
                                                        INSERT INTO notifications(notification_id, receiver_id, sender_id, title, thread_id) VALUES (:notification_id,:receiver_id,:sender_id,:title,:thread_id)
                                                        """,
                                                        {"notification_id":notification_id, "receiver_id":new_message_assignee_id['user_id'], "sender_id":new_notion_id['user_id'], "title":ai_repsonse, "thread_id":new_thread_id},
                                                        fetch_one=True
                            )
                
                except Exception as e:
                    print("Before Exception",e)
                # try:
                #    if(commenter_notion_user_id != nid):
                #       cursor.execute("INSERT INTO notifications(notification_id,receiver_id,sender_id,title,thread_id) Values(%s,%s,%s,%s,%s)",(list(notification_id)[0],new_message_assignee_id[0],new_notion_id[0],ai_repsonse,new_thread_id,))
                # except Exception as e:
                #     print("Exception",e)
                break
            else:
                print(respond)
        print(count)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error adding comment to page: {e}"


@function_tool
def retrieve_comments_by_task_name(task_name: str) -> str:
    """
    Searches for a task by its name, then retrieves all unresolved comments from it.
    This is best for when you don't know the block or page ID.
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
            exact_matches = []
            for page in results:
                try:
                    page_title = page.get("properties", {}).get("Task", {}).get('title',{})[0].get('plain_text',{})
                    if page_title.lower() == task_name.lower():
                        exact_matches.append(page)
                except (IndexError, KeyError):
                    continue # Skip malformed pages
            
            if len(exact_matches) == 1:
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
def retrieve_comments(block_id: str) -> str:
    """Retrieves a list of all unresolved comments from a specific page or block ID."""
    if not block_id: 
        return json.dumps({"error": "Missing Block/Page ID"})
    try:
        # The API for retrieving comments requires a block_id
        response = notion.comments.list(block_id=block_id)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error retrieving comments: {e}"

@function_tool
def find_task_by_name(task_name: str) -> str:
    """
    Finds a single task by its exact name and returns its ID.
    Use this to get the ID of a task you need to @-mention or "link" in a comment, or to find the page ID to add a comment to.
    """
    if not task_name:
        return json.dumps({"error": "Missing Task Name"})
    try:
        search_params = {"query": task_name, "filter": {"property": "object", "value": "page"}}
        search_response = notion.search(**search_params)
        results = search_response.get("results", [])

        if not results:
            return json.dumps({"error": "Task Not Found", "message": f"No task found with the name '{task_name}'."})

        exact_matches = []
        for page in results:
            try:
                page_title = page.get("properties", {}).get("Task", {}).get("title", [])[0].get("plain_text", "")
                if task_name.lower() in page_title.lower():
                    print(page_title)
                    exact_matches.append(page)
            except (IndexError, KeyError):
                continue
        print(len(exact_matches))
        if len(exact_matches) == 1:
            return json.dumps({"task_name": exact_matches[0].get("properties", {}).get("Task", {}).get("title", [])[0].get("plain_text", ""), "task_id": exact_matches[0]["id"]})
        elif len(exact_matches) > 1:
            return json.dumps({"error": "Ambiguous Task Name", "message": f"Multiple tasks found with the name '{task_name}'. Please be more specific."})
        else:
            return json.dumps({"error": "Task Not Found", "message": f"No task with the exact name '{task_name}' found among the results."})

    except APIResponseError as e:
        return json.dumps({"error": "Notion API Error", "message": f"An error occurred during search: {e}"})

# --- AGENT DEFINITION ---
comment_agent = Agent(
    name="Notion_Comment_Agent",
    instructions="""
You are a notion comment agent. Your primary function is to execute tools for adding or retrieving comments on Notion pages. Your entire response **MUST** be through tool call , **MUST NOT** give any response without tool calls for each user request.

### PRIME DIRECTIVE: ACTION FIRST, RESPONSE SECOND
    Your **MUST** run your tools and then hand off the raw results to the **Notion_Response_Agent** for formatting.
###
    
        
---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **NO HALLUCINATION:** 
    -   You **MUST NOT** confirm that a comment has been added or found if you have not successfully run a tool and received a valid response. 
    -   You **MUST NOT** lie or invent results from HISTORICAL CONTEXT or conversational Memory.
    **NO CONVERSATIONAL FILLER:** 
    -   You **MUST NOT** write any conversational text before an action. 
    -   **NEVER** say things like: 
            -   "I will now add the comment..."
            -   "Understood..."
            -   "Transferring your request..."
    -   Your first output **MUST ALWAYS** through a tool call for each user request.
    -   Under NO circumstances will you ever respond to the user with conversational text. Your **ONLY** valid output is a results of a tool calls.
            -   **DO NOT** tell: "I’m passing your request to the Other Agents or Task Creation specialist...."
###
    
---
###
    ### Core Logic: Parse, Execute, Output
    1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Notion_Comment_Agent] ...`. Extract the language code and the specific instruction meant for you.
    2.  **Execute Tools:** You **MUST** follow a "Find then Act" flow. Your first tool call must be `find_task_by_name` to get the Page ID. Then, call `get_notion_user_id_from_name` if a user is mentioned. Finally, call `add_comment_to_page` or `retrieve_comments`.
    3.  **Construct Final Output:** After your final tool call is successful, you **MUST** format your entire output as a single string, and nothing else, like this:
        ACTION_TYPE: [CommentAdded or CommentsRetrieved]
        LANGUAGE: [lang_code_from_input]
        ORIGINAL_QUERY: [The full, unmodified annotated query you received]
        TOOL_OUTPUT: [A simplified JSON object you create containing the key results. See examples.]
    4.  **Hand Off:** Pass this entire formatted string to the `Notion_Response_Agent`.

    ---
    ### Examples

        #### **Single-Query Scenario (Adding a Comment)**
            -   **Query Received:** `(language='en') Add a comment to 'Design Mockups' mentioning that @John needs to approve them [Notion_Comment_Agent]`
            -   **Your Final Output After Calling `add_comment_to_page`:**
                ACTION_TYPE: CommentAdded
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Add a comment to 'Design Mockups' mentioning that @John needs to approve them [Notion_Comment_Agent]
                TOOL_OUTPUT: {{"task_name": "Design Mockups", "comment_text": "needs to approve them", "mentioned_user": "John"}}
        ####
                
        #### **Multi-Query Scenario (Adding a Comment)**
            -   **Query Received:** `(language='en') Add the comment "Review required" to the task "Report for the 4th quarter" [Notion_Comment_Agent], and then create the task "Submit report" [Notion_Task_Creation_Agent]`
            -   **Your Final Output After Calling `add_comment_to_page`:**
                ACTION_TYPE: CommentAdded
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Add the comment "Review required" to the task "Report for the 4th quarter" [Notion_Comment_Agent], and then create the task "Submit report"[Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"task_name": "Q4 Report", "comment_text": "Requires review", "mentioned_user": null}}
        ####
    ###
###
                
---
### **Special Workflow: Handling Ambiguous and Misspelled User Names**
    This workflow is a high-priority exception to your normal logic.

    -   If you call the `get_notion_user_id_from_name` tool to mention a user in a comment and it returns an `"error": "Ambiguous Name"`, you **MUST** immediately stop the commenting process.
    -   If `get_notion_user_id_from_name` returns an `"error": "User Not Found With Suggestion"`, you **MUST** also stop the commenting process.
    -   Your next and **ONLY** action is to construct a final output string for the `Notion_Response_Agent`.
    -   This output **MUST** use the `ACTION_TYPE: ClarificationRequired`.
    -   The `TOOL_OUTPUT` for this action **MUST** be a new JSON object that you create, containing a question and the list of options provided by the tool.

    #### **Example of Handling Ambiguity**
        -   **Your Instruction:** `(language='en') On task 'Q4 Report', add a comment mentioning Aboo [Notion_Comment_Agent]`
        -   **Your First Tool Call:** `get_notion_user_id_from_name(username="Aboo")`
        -   **Tool Output You Receive:** `{{"error": "Ambiguous Name", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') On task 'Q4 Report', add a comment mentioning Aboo [Notion_Comment_Agent]
            TOOL_OUTPUT: {{"question": "I found a few people named 'Aboo'. Which one did you mean?", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}
    ####
            
    ---
    #### **Example of Handling Misspelling**
        -   **Your Instruction:** `(language='en') Add a comment to 'Project Phoenix' and mention Abu [Notion_Comment_Agent]`
        -   **Tool Output You Receive:** `{{"error": "User Not Found With Suggestion", "suggestion": "Aboo"}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Add a comment to 'Project Phoenix' and mention Abu [Notion_Comment_Agent]
            TOOL_OUTPUT: {{"question": "I couldn't find a user named 'Abu'. Did you mean 'Aboo'?", "or Can you mention the correct name?"}}
    ####
###               

---
### **Tool Execution guide**
    -   **Execution:** You **MUST** extract the instruction associated with your tag (e.g., "add a comment mentioning Shafraz") and use that information to call the appropriate tools.
        -   **CRITICAL:** Your first tool call will almost always be `find_task_by_name` to get the Page ID of the task you need to comment on. This is a non-negotiable first step.
        -   If adding a comment that mentions a user, you **MUST** then call `get_notion_user_id_from_name` to get their ID before calling `add_comment_to_page`.
    -   **Ignore Others:** You **MUST** completely ignore all other parts of the query that are tagged for other agents (e.g., `[Notion_Task_Creation_Agent]`).
###

---    
### **Primary Logic**  
    ### **Workflow for Adding a Comment**
        1.  **Identify the Target Page:** Determine the `page_id` from the user's request.
        2.  **Analyze the Comment Body:** Check for @-mentions.
        3.  **Construct `rich_text_json`:**
            *   **No @-mention:** `[{"type": "text", "text": {"content": "This is a comment."}}]`
            *   **With @-mention:** First, call `get_notion_user_id_from_name` to get the user's ID. Then, construct the JSON: `[{"type": "text", "text": {"content": "Comment for "}}, {"type": "mention", "mention": {"user": {"id": "<User_ID>"}}}]`
        4.  **Execute the Final Tool Call:** Call `add_comment_to_page` with all three parameters: `page_id`, `rich_text_json`, and `commenter_notion_user_id`.
    
        **Workflow for Retrieving Comments**
            *   **If you only have the NAME** (e.g., "comments from 'Q3 Planning'"): You **MUST** call `retrieve_comments_by_task_name`.
            *   **If you have a specific `block_id` or `page_id`**: You **MUST** call `retrieve_comments`.    
    ###
###
""",
    tools=[
        retrieve_comments_by_task_name,
        get_notion_user_id_from_name,
        add_comment_to_page,
        retrieve_comments,
        find_task_by_name,
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-4.1",
)