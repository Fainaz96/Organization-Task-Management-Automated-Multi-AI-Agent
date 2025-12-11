import os
import json
import uuid
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from datetime import date, datetime, timedelta, timezone
import notion_client
from agents import Agent, function_tool, handoff
import difflib

from model.response_agent_input import ResponseAgentInput
from openai import OpenAI  # Assuming these are defined in your agents module
from db import get_db_connection
from utils.db_helper import execute_query
from utils.phone_number_utils import (
    get_current_datetime_in_timezone,
    get_timezones_for_phone,
)
from utils.whatsapp_utils import send_whatsapp_message

from local_agents.notion_response_agent import notion_response_agent

load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")

if not all([NOTION_API_KEY, TASKS_DATABASE_ID]):
    raise ValueError(
        "One or more required environment variables are missing from .env: NOTION_API_KEY, TASKS_DATABASE_ID"
    )

notion = notion_client.Client(auth=NOTION_API_KEY)

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
        search_params = {
            "query": task_name,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "ascending", "timestamp": "last_edited_time"},
        }
        search_response = notion.search(**search_params)
        results = search_response.get("results", [])

        if not results:
            return json.dumps(
                {"error": f"No task found with the name '{task_name}'."}
            )

        if len(results) > 1:
            exact_matches = []
            for page in results:
                try:
                    page_title = (
                        page.get("properties", {})
                        .get("Task", {})
                        .get("title", {})[0]
                        .get("plain_text", {})
                    )
                    if page_title.lower() == task_name.lower():
                        exact_matches.append(page)
                except (IndexError, KeyError):
                    continue
            if len(exact_matches) == 0:
                found_page = exact_matches[0]
            else:
                return json.dumps(
                    {
                        "error": f"Ambiguous task name. Multiple tasks found matching '{task_name}'. Please be more specific."
                    }
                )
        else:
            found_page = results[0]

        task_id = found_page.get("id")
        if not task_id:
            return json.dumps(
                {"error": "Found a matching task but could not retrieve its ID."}
            )

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



# --- MODIFICATION START: reminder tool is updated ---
@function_tool
# async def reminder(
#     reminder_message: str,
#     task_name:str,
#     remind_time: str,
#     remind_date: str,
#     user_id: str,
#     user_language: str,
#     reminder_id: Optional[str] = None,
#     due_date: Optional[str] = None,
#     status: Optional[str] = None,
#     reminder_timestamp: Optional[str] = None,
#     is_task_related: bool = True,
# ) -> str:
#     """
#     Use this to create a new task with properties and optional rich content.
#     The 'user_id' parameter is REQUIRED and must be the Notion ID of the user creating the task.
#     The 'user_language' MUST be 'en', 'ru', or 'az'.
#     The 'reminder_timestamp' must be a valid JSON string representing a list of Notion block objects.
#     """
#     conn = get_db_connection()
#     if isinstance(conn, str):
#         return json.dumps({"error": conn})

#     try:
#         # Guardrail: ensure the referenced task exists in the Tasks database
#         # Query the Notion Tasks database for an exact title match to reminder_message
#         try:
#             db_query = notion.databases.query(
#                 **{
#                     "database_id": TASKS_DATABASE_ID,
#                     "filter": {
#                         "property": "Task",
#                         "title": {"equals": task_name},
#                     },
#                 }
#             )
#             matched = db_query.get("results", [])
#             if len(matched) == 0:
#                 return json.dumps(
#                     {
#                         "error": "TaskNotFound",
#                         "message": f"No task exists in Notion named '{task_name}'. Please check the task name or create it first.",
#                     }
#                 )
#             if len(matched) > 1:
#                 return json.dumps(
#                     {
#                         "error": "TaskAmbiguous",
#                         "message": f"Multiple tasks match '{task_name}'. Please specify the exact task name.",
#                     }
#                 )
#         except Exception as notion_err:
#             # If the database query fails for any reason, do not proceed blindly
#             return json.dumps(
#                 {
#                     "error": "NotionQueryFailed",
#                     "message": f"Unable to verify task existence: {notion_err}",
#                 }
#             )

#         final_due_date = due_date or remind_date

#         cursor = conn.cursor(dictionary=True)
#         # Get target user's info
#         cursor.execute(
#             "SELECT phone_number, username, user_id FROM Users WHERE notion_user_id LIKE %s",
#             (f"{reminder_id}",),
#         )
#         target_user = cursor.fetchone()

#         # Get creator's info
#         cursor.execute(
#             "SELECT phone_number, username, user_id FROM Users WHERE notion_user_id LIKE %s",
#             (f"{user_id}",),
#         )
#         creator_user = cursor.fetchone()
#         cursor.close()
#         if target_user is None:
#             target_user = creator_user
#         if not target_user or not creator_user:
#             return json.dumps({"error": "Could not find the creator or target user."})

#         # 2. NEW LOGIC: Dictionary for translated reminder templates
#         REMINDER_TEMPLATES = {
#             "en": {
#                 "self": "Hi {target_name}. Just a reminder that you wanted to '{message}' by *{due_date}*.",
#                 "other": "Hi {target_name}. {creator_name} wanted me to remind you to '{message}' by *{due_date}*.",
#             },
#             "ru": {
#                 "self": "Привет, {target_name}. Напоминаю, вы хотели '{message}' к *{due_date}*.",
#                 "other": "Привет, {target_name}. {creator_name} просил(а) напомнить вам сделать '{message}' к *{due_date}*.",
#             },
#             "az": {
#                 "self": "Salam, {target_name}. Xatırlatmaq istədim ki, '{message}' tapşırığını *{due_date}* tarixinədək etməli idiniz.",
#                 "other": "Salam, {target_name}. {creator_name} '{message}' tapşırığını *{due_date}* tarixinədək etməyinizi xatırlatmağımı istədi.",
#             },
#         }

#         # Determine which scenario and template to use
#         is_self_reminder = reminder_id == user_id
#         scenario = "self" if is_self_reminder else "other"

#         # Select the template, defaulting to English if the language code is invalid
#         template = REMINDER_TEMPLATES.get(user_language, REMINDER_TEMPLATES["en"])[
#             scenario
#         ]

#         # Format the reminder text using the chosen template
#         reminder_text = template.format(
#             target_name=target_user["username"],
#             creator_name=creator_user["username"],
#             message=reminder_message,
#             due_date=final_due_date.split("T")[0],
#         )

#         # --- Database insertion logic remains the same, but uses the new reminder_text ---
#         cursor = conn.cursor()
#         notification_id = str(uuid.uuid4())
#         new_thread_id = str(uuid.uuid4())
#         datetime_string = f"{remind_date} {remind_time}"

#         target_user_timezone = get_timezones_for_phone(
#             f"+{creator_user['phone_number']}"
#         )
#         datetime_in_target_user_timezone = get_current_datetime_in_timezone(
#             target_user_timezone[0]
#         )
#         created_at_datetime = datetime.strptime(datetime_string, "%Y-%m-%d %H:%M")
#         created_at_datetime_naive = datetime.strptime(datetime_string, "%Y-%m-%d %H:%M")
#         created_at_datetime_aware_utc = created_at_datetime_naive.replace(
#             tzinfo=ZoneInfo(target_user_timezone)
#         )
#         # print("created at time :",created_at_datetime)
#         # print("zone info:",ZoneInfo(target_user_timezone))
#         print("time info about zone info",created_at_datetime_aware_utc.astimezone(ZoneInfo(target_user_timezone[0])))
#         print("created at time aware utc",created_at_datetime_aware_utc.astimezone(ZoneInfo("UTC")))
#         # print("date time in target user timezone :",datetime_in_target_user_timezone.astimezone(ZoneInfo("UTC")))
#         # print("date time in target user timezone in UTS:",datetime_in_target_user_timezone.astimezone(ZoneInfo(target_user_timezone)))
#         # print("created at datetime aware - difference between date in target user timezone :", created_at_datetime_aware_utc - datetime.now(ZoneInfo("UTC")))
#         # print("created at datetime aware - difference between date in target user timezone :", created_at_datetime_aware_utc - datetime_in_target_user_timezone)
#         # print("time in utc :",datetime.now(ZoneInfo("UTC")))
#         cursor = conn.cursor()
#         cursor.execute(
#             "INSERT INTO `threads` (`thread_id`, `title`, `type`) VALUES (%s, %s, %s)",
#             (new_thread_id, notification_id, "web"),
#         )
#         # print(remind_time)
#         # print(remind_date)

#         cursor.execute(
#             "INSERT INTO notifications(notification_id, receiver_id, sender_id, title, thread_id, created_at, type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
#             (
#                 notification_id,
#                 target_user["user_id"],
#                 creator_user["user_id"],
#                 reminder_text,
#                 new_thread_id,
#                 created_at_datetime_aware_utc.astimezone(ZoneInfo("UTC")),
#                 "reminder",
#             ),
#         )
#         conn.commit()
#         cursor.close()

#         # The confirmation message back to the agent is now also multilingual for consistency
#         CONFIRMATION_TEMPLATES = {
#             "en": f"I have scheduled a reminder for {target_user['username']} about '{reminder_message}'.",
#             "ru": f"Я запланировал(а) напоминание для {target_user['username']} о '{reminder_message}'.",
#             "az": f"Mən {target_user['username']} üçün '{reminder_message}' haqqında xatırlatma planlaşdırdım.",
#         }

#         confirmation_text = CONFIRMATION_TEMPLATES.get(
#             user_language, CONFIRMATION_TEMPLATES["en"]
#         )

#         return json.dumps({"status": "success", "confirmation": confirmation_text})

#     except Exception as e:
#         print(f"Exception in reminder tool: {e}")
#         return json.dumps({"error": str(e)})
async def reminder(
    user_id: str,
    reminder_id: str,
    user_language: str,
    remind_date: str,
    remind_time: str,
    is_task_related: bool,
    reminder_message: str,
    task_name: Optional[str] = None,
    due_date: Optional[str] = None,
) -> str:
    """
    Schedules a reminder. Differentiates between task-related and casual reminders.

    Args:
        user_id: The Notion ID of the user creating the reminder.
        reminder_id: The Notion ID of the user to be reminded.
        user_language: The language for the notification ('en', 'ru', 'az').
        remind_date: The date for the reminder (YYYY-MM-DD).
        remind_time: The time for the reminder (HH:MM:SS).
        is_task_related: Boolean indicating if the reminder is linked to a Notion task.
        reminder_message: The text content of the reminder notification.
        task_name: The exact name of the task to look up in Notion if is_task_related is True.
        due_date: Optional due date for the task.
    """
    conn = get_db_connection()
    if isinstance(conn, str):
        return json.dumps({"error": conn})

    try:
        # --- NEW: Conditional Guardrail Logic ---
        if is_task_related:
            # If it's a task reminder, task_name is mandatory for the lookup.
            if not task_name:
                return json.dumps({
                    "error": "MissingTaskName",
                    "message": "A task_name is required for a task-related reminder."
                })
            try:
                # Use task_name for the Notion database query
                db_query = notion.databases.query(
                    database_id=TASKS_DATABASE_ID,
                    filter={"property": "Task", "title": {"equals": task_name}},
                )
                matched = db_query.get("results", [])
                if not matched:
                    return json.dumps({
                        "error": "TaskNotFound",
                        "message": f"No task exists in Notion named '{task_name}'. Please check the task name or create it first."
                    })
                if len(matched) > 1:
                    return json.dumps({
                        "error": "TaskAmbiguous",
                        "message": f"Multiple tasks match '{task_name}'. Please specify the exact task name."
                    })
            except Exception as notion_err:
                return json.dumps({
                    "error": "NotionQueryFailed",
                    "message": f"Unable to verify task existence: {notion_err}"
                })
        # For casual reminders (is_task_related=False), this entire block is skipped.

        # --- User lookup and template logic remains the same ---
        final_due_date = due_date or remind_date
        # cursor = conn.cursor(dictionary=True)

        # cursor.execute("SELECT phone_number, username, user_id FROM Users WHERE notion_user_id LIKE %s", (f"{reminder_id}",))
        # target_user = cursor.fetchone()

        # cursor.execute("SELECT phone_number, username, user_id FROM Users WHERE notion_user_id LIKE %s", (f"{user_id}",))
        # creator_user = cursor.fetchone()
        async for conn in get_db_connection():  # get AsyncSession
            target_user = await execute_query(
                                        conn,
                                        """
                                        SELECT phone_number, username, user_id FROM Users WHERE notion_user_id = :user_id
                                        """,
                                        {"user_id":f"{reminder_id}"},
                                        fetch_one=True
            )
        
        async for conn in get_db_connection():  # get AsyncSession
            creator_user = await execute_query(
                                        conn,
                                        """
                                        SELECT phone_number, username, user_id FROM Users WHERE notion_user_id =:user_id
                                        """,
                                        {"user_id":f"{user_id}"},
                                        fetch_one=True
            )
        
        if not target_user: target_user = creator_user
        if not target_user or not creator_user:
            return json.dumps({"error": "Could not find the creator or target user."})

        REMINDER_TEMPLATES = {
            "en": {
                "self": "Hi {target_name}. Just a reminder about '{message}'.",
                "other": "Hi {target_name}. {creator_name} wanted me to remind you about '{message}'.",
            },
            # Add 'ru' and 'az' templates here as before
        }

        is_self_reminder = reminder_id == user_id
        scenario = "self" if is_self_reminder else "other"
        template = REMINDER_TEMPLATES.get(user_language, REMINDER_TEMPLATES["en"])[scenario]

        reminder_text = template.format(
            target_name=target_user["username"],
            creator_name=creator_user["username"],
            message=reminder_message,
        )
        
        # --- Database insertion logic remains the same ---
        # cursor = conn.cursor()
        notification_id = str(uuid.uuid4())
        new_thread_id = str(uuid.uuid4())
        datetime_string = f"{remind_date} {remind_time}"
        
        # This timezone logic is complex and remains as is
        target_user_timezone = get_timezones_for_phone(f"+{creator_user['phone_number']}")
        created_at_datetime_naive = datetime.strptime(datetime_string, "%Y-%m-%d %H:%M")
        created_at_datetime_aware = created_at_datetime_naive.replace(tzinfo=ZoneInfo(target_user_timezone[0]))
        created_at_utc = created_at_datetime_aware.astimezone(ZoneInfo("UTC"))

        # cursor.execute("INSERT INTO threads (thread_id, title, type) VALUES (%s, %s, %s)", (new_thread_id, notification_id, "web"))
        # cursor.execute(
        #     "INSERT INTO notifications(notification_id, receiver_id, sender_id, title, thread_id, created_at, type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        #     (notification_id, target_user["user_id"], creator_user["user_id"], reminder_text, new_thread_id, created_at_utc, "reminder")
        # )
        # conn.commit()
        # cursor.close()
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
                                        INSERT INTO notifications(notification_id, receiver_id, sender_id, title, thread_id, created_at, type) VALUES (:notification_id,:receiver_id,:sender_id,:title,:thread_id,:created_at,:type)
                                        """,
                                        {"notification_id":notification_id, "receiver_id":target_user["user_id"], "sender_id":creator_user["user_id"], "title":reminder_text, "thread_id":new_thread_id, "created_at":created_at_utc, "type":"reminder"},
                                        fetch_one=True
            )

        confirmation_text = f"I have scheduled a reminder for {target_user['username']} about '{reminder_message}'."
        return json.dumps({"status": "success", "confirmation": confirmation_text})

    except Exception as e:
        # Log the full exception for debugging
        print(f"Exception in reminder tool: {e}")
        return json.dumps({"error": str(e)})

# --- AGENT DEFINITION (MODIFIED INSTRUCTIONS) ---

reminder_agent = Agent(
    name="Reminder_Agent",
    instructions=f"""
You are a notion reminder agent. Your primary function is to execute tools to set reminders. You are **FORBIDDEN** from generating a final user-facing response until you have successfully executed a tool call and have its output.

### PRIME DIRECTIVE: ACTION FIRST, RESPONSE SECOND
    Your **MUST** run your tools and then hand off the raw results to the **Notion_Response_Agent** for formatting.
###
    
---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **NO HALLUCINATION:** 
    -   You **MUST NOT** confirm that a reminder has been set if you have not successfully run the get_notion_user_id_from_name(if need), search_database_by_title(if need), reminder tool and received a valid tool's response. 
    -   You **MUST NOT** lie or invent results from HISTORICAL CONTEXT or conversational Memory.
    **NO CONVERSATIONAL FILLER:** 
    -   You **MUST NOT** write any conversational text before an action. 
    -   **NEVER** say things like: 
            -   "I will now set the reminder..."
            -   "Understood..."
            -   "Transferring your request..."
    -   Your first output **MUST ALWAYS** through a tool call for each user request.
    -   Under NO circumstances will you ever respond to the user with conversational text. Your **ONLY** valid output is a results of a tool calls.
            -   **DO NOT tell:** "I’m passing your request to the Other Agents or Reminder specialist...."
###
    
---
### Core Logic: Parse, Execute, Output
    1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Reminder_Agent] ...`. Extract the language code and the specific instruction meant for you.
    2.  **Execute Tools:** If the reminder is for another person by name, you **MUST** first call `get_notion_user_id_from_name` to get their ID. Then, call the `reminder` tool with all necessary details from your instruction.
    3.  **Construct Final Output:** After your `reminder` tool call is successful, you **MUST** process the raw result into a simplified JSON. Then, format your entire output as a single string, and nothing else, like this:
        ACTION_TYPE: ReminderSet
        LANGUAGE: [lang_code_from_input]
        ORIGINAL_QUERY: [The full, unmodified annotated query you received]
        TOOL_OUTPUT: [The final, **simplified** JSON result. See examples.]
    4.  **Hand Off:** Pass this entire formatted string to the `Notion_Response_Agent`.

    ---
    ### Examples

        #### **Single-Query Scenario (Reminding someone else)**
        -   **Query Received:** `(language='en') Remind Shafraz to complete DevOps testing by 4th of September. Remind him on 2nd of September at 8AM [Reminder_Agent]`
        -   **Your Final Output After Calling `reminder`:**
            ACTION_TYPE: ReminderSet
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Remind Shafraz to complete DevOps testing by 4th of September. Remind him on 2nd of September at 8AM [Reminder_Agent]
            TOOL_OUTPUT: {{"target_user_name": "Shafraz", "reminder_text": "complete DevOps testing by 4th of September", "reminder_datetime": "2025-09-02T08:00:00", "is_self_reminder": false}}

        #### **Multi-Query Scenario (Reminding self)**
        -   **Query Received:** `(language='en') Remind me to call the vendor tomorrow at 10 AM [Reminder_Agent], and then create a task to "Follow up on vendor invoice" [Notion_Task_Creation_Agent]`
        -   **Your Final Output After Calling `reminder`:**
            ACTION_TYPE: ReminderSet
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Remind me to call the vendor tomorrow at 10 AM [Reminder_Agent], and then create a task to "Follow up on vendor invoice" [Notion_Task_Creation_Agent]
            TOOL_OUTPUT: {{"target_user_name": "Aboo Fainaz", "reminder_text": "позвонить поставщику", "reminder_datetime": "2025-09-22T10:00:00", "is_self_reminder": true}}
        ###
    ###   
###

---
### **Special Workflow: Handling Ambiguous and Misspelled User Names**
    This workflow is a high-priority exception to your normal logic.

    -   If you call the `get_notion_user_id_from_name` tool to set a reminder for someone and it returns an `"error": "Ambiguous Name"`, you **MUST** immediately stop the reminder setting process.
    -   If `get_notion_user_id_from_name` returns an `"error": "User Not Found With Suggestion"`, you **MUST** also stop the reminder setting process.
    -   Your next and **ONLY** action is to construct a final output string for the `Notion_Response_Agent`.
    -   This output **MUST** use the `ACTION_TYPE: ClarificationRequired`.
    -   The `TOOL_OUTPUT` for this action **MUST** be a new JSON object that you create, containing a question and the list of options provided by the tool.

    #### **Example of Handling Ambiguity**
        -   **Your Instruction:** `(language='en') Remind Aboo to call the client [Reminder_Agent]`
        -   **Your First Tool Call:** `get_notion_user_id_from_name(username="Aboo")`
        -   **Tool Output You Receive:** `{{"error": "Ambiguous Name", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Remind Aboo to call the client [Reminder_Agent]
            TOOL_OUTPUT: {{"question": "I found a few people named 'Aboo'. Which one did you mean?", "options": ["Aboo Fainaz", "Aboo Ahamed"]}}
    ####
        
    ---
    #### **Example of Handling Misspelling**
        -   **Your Instruction:** `(language='en') Remind Abu about the 3pm meeting [Reminder_Agent]`
        -   **Tool Output You Receive:** `{{"error": "User Not Found With Suggestion", "suggestion": "Aboo"}}`
        -   **Your Required Final Output (to be sent to the Response Agent):**
            ACTION_TYPE: ClarificationRequired
            LANGUAGE: en
            ORIGINAL_QUERY: (language='en') Remind Abu about the 3pm meeting [Reminder_Agent]
            TOOL_OUTPUT: {{"question": "I couldn't find a user named 'Abu'. Did you mean 'Aboo'?", "or Can you mention the correct name?"}}
    ####
###    
        
---     
### **Tool Execution guide**
    -   **Your Primary Task:** You **MUST** find the part of the query tagged with your name, `[Reminder_Agent]`.
    -   **Execution:** You **MUST** extract the instruction associated with your tag (e.g., "remind me tomorrow at 10 AM") and use that information to call the `reminder` tool.
        -   If the reminder is for another person by name, you **MUST** first call `get_notion_user_id_from_name` to get their ID.
    -   **Ignore Others:** You **MUST** completely ignore all other parts of the query that are tagged for other agents (e.g., `[Notion_Task_Creation_Agent]`).
###
    
---
### **Primary Logic**
    **1: MANDATORY LOGICAL RULES:**
    -   You **MUST** extract the `logged_in_user_id` from the context provided in the user's prompt (e.g., `(logged_in_user_id='...')`).
    -   You **MUST** pass this ID to the `user_id` parameter of the `reminder` tool. This is how the task is attributed to the correct creator.
    -   If the user does not specify a status, the default is "Not started".
    -   If you cannot create a task successfully, you **MUST** return a JSON object with an "error" key and a "message" key explaining the issue.

    **2: MANDATORY LOGICAL CONTEXT:**
    -   **Current Date:** `Current Date`. Use this for relative date calculations (e.g., "tomorrow" is `Next day of Current Date`).
    -   **Logged-in User ID:** The user's Notion ID is provided in the prompt context as `logged_in_user_id`. You **MUST** use this for the `user_id`.

    **3: WORKFLOW FOR CREATING A TASK:**
    -  **Extract Details:** Identify the task name, assignee, due date,remind_time,remind_date(if no date mentioned Current Date), priority, status, and any page content from the user's request.
    -  **Extract Creator ID:** Get the `logged_in_user_id` from the prompt's context.
    -  **Resolve Assignee ID:**
        -   If the user asks to assign the task to themselves (e.g., using phrases like "remind me" or "remind to me"), you **MUST** use the `logged_in_user_id` for the `reminder_id`.
        -   If a specific assignee *name* is mentioned (e.g., "for John Doe"), you **MUST** first call `get_notion_user_id_from_name` to get their ID for the `reminder_id`.
        -   If no assignee is specified, leave the assignee field blank.
    -  **Construct Content JSON (if needed):** If the user requests page content (like a description, list, or link), you **MUST** construct a `reminder_timestamp` string. Use the examples below as a guide.
    -  **Execute Creation:** Call the `reminder` tool with all gathered information.
    -  **Format Final Response:** After the tool succeeds, parse the JSON response and format it exactly as specified below my_name,reminder_date,username.
###
---
### *4: RULE FOR EXTRACTING THE TASK NAME:*
    - *CRITICAL RULE:* When a user asks for a reminder about a task, your first job is to extract the *true name of the task*. This value will be used to find the task in Notion.
    - *You MUST NOT* include surrounding action verbs like "do", "work on", "complete", or "finish" in the task name string.

    - *Examples of Correct Extraction:*
        - *User Query:* "remind me to do ABC2@"
        - **CORRECT task_name:** "ABC2@"

        - *User Query:* "remind me about the 'Q3 Financial Report'"
        - **CORRECT task_name:** "Q3 Financial Report"

        - *User Query:* "Can you remind me to finish the slide deck for marketing?"
        - **CORRECT task_name:** "slide deck for marketing"
###
--- 
# ... (all previous agent instructions) ...

###
---
### 5: HANDLING REMINDER TYPES (TASK-RELATED VS. CASUAL):*
    - Your primary job is to determine if the user is asking for a *task-related reminder* (linked to a specific task in Notion) or a *casual reminder* (a general, standalone reminder).

    - *A) If the reminder is TASK-RELATED:*
        - Look for keywords like "task," "complete," "implement," "review," "submit," or phrases that sound like formal project titles.
        - You *MUST* set is_task_related=True in your tool call.
        - The reminder_message you extract *MUST* be the exact name of the task to be looked up in Notion. Do not include verbs like "do" or "complete."

    - *B) If the reminder is CASUAL:*
        - Look for personal activities, chores, or general life events (e.g., "bring dinner," "dancing practices," "call Mom").
        - You *MUST* set is_task_related=False in your tool call.
        - The reminder_message should be the full description of the casual reminder (e.g., "bring dinner," "do dancing practices").

    ### *Examples of Correct Tool Calls:*

    ### *CRITICAL FORMATTING RULE:*
    - The remind_time parameter *MUST* be a string in strict "HH:MM" format. You *MUST NOT* include seconds.

    #### **Casual Reminders (is_task_related=False)**
    - *User Query:* "Can you remind me to do dancing practices today at 8.32PM"
    - *Correct Tool Call:*
        json
        {{
          "tool_name": "reminder",
          "parameters": {{
            "reminder_message": "do dancing practices",
            "is_task_related": "false",
            "remind_time": "20:32",
            "remind_date": "2025-09-22"
          }}
        }}
        

    - *User Query:* "Remind shafraz to bring dinner on today at 1PM"
    - *Correct Tool Call:*
        json
        {{
          "tool_name": "reminder",
          "parameters": {{
            "reminder_message": "bring dinner",
            "is_task_related": "false",
            "remind_time": "13:00",
            "remind_date": "2025-09-22"
          }}
        }}
        
        (Note: You would first call get_notion_user_id_from_name to get the ID for "shafraz").

    #### **Task-Related Reminders (is_task_related=True)**
    - *User Query:* "Can you remind me to complete Prepare paper article for globalization task today at 8.32PM"
    - *Correct Tool Call:*
        json
        {{
          "tool_name": "reminder",
          "parameters": {{
            "reminder_message": "Prepare paper article for globalization task",
            "is_task_related": "true",
            "remind_time": "20:32",
            "remind_date": "2025-09-22"
          }}
        }}
        

    - *User Query:* "Remind shafraz to do Implement the financial plan for 2025 today at 1PM"
    - *Correct Tool Call:*
        json
        {{
          "tool_name": "reminder",
          "parameters": {{
            "reminder_message": "Implement the financial plan for 2025",
            "is_task_related": "true",
            "remind_time": "13:00",
            "remind_date": "2025-09-22"
          }}
        }}
###
---
### **Context & Date:**
    - **Current Date:** `{datetime.now(timezone.utc).date()}`
    - **Current Time:** `{datetime.now(timezone.utc).time()}`
    - **Logged-in User ID:** `{{logged_in_user_id}}`
###
""",
    tools=[
        get_notion_user_id_from_name,
        reminder,
        search_database_by_title,
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-5-mini-2025-08-07",
)