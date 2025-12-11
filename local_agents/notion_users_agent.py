#local_agents\notion_users_agent.py
import os
import json
from dotenv import load_dotenv
import notion_client
from agents import Agent, function_tool, handoff

from model.response_agent_input import ResponseAgentInput

# --- SETUP ---
load_dotenv()
notion = notion_client.Client(auth=os.getenv("NOTION_API_KEY"))

from local_agents.notion_response_agent import notion_response_agent

# --- TOOLS ---

def manage_response_agent_handoff(context, input: ResponseAgentInput):
    """
    Handles the response agent handoff by processing the specialist tool output
    and preparing the final response for the user.
    """
    print("response agent start") 

@function_tool
def list_all_users() -> str:
    """
    Retrieves a paginated list of all HUMAN users (people) in the Notion workspace. This tool automatically excludes all bots and integrations.
    """
    try:
        response = notion.users.list()
        all_users = response.get("results", [])
        
        # --- MODIFICATION START: Filter out bots ---
        person_users = [user for user in all_users if user.get("type") == "person"]
        
        # Create a new response object containing only the filtered users
        filtered_response = {
            "object": "list",
            "results": person_users,
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more")
        }
        # --- MODIFICATION END ---
        
        return json.dumps(filtered_response, indent=2)
    except Exception as e:
        return f"Error listing users: {e}"

@function_tool
def find_user_by_name(name: str) -> str:
    """
    Finds a single user by their exact display name (case-insensitive) and returns their full user object.
    This is a high-level tool that first lists all users and then searches the results.
    """
    # Added Block: Check for a missing name.
    if not name:
        return json.dumps({"error": "Missing Name", "message": "I need the name of the user you want to find. What is their name?"})
    try:
        all_users_response = notion.users.list()
        all_users = all_users_response.get("results", [])
        
        found_user = next((user for user in all_users if user.get("name", "").lower() == name.lower()), None)
        
        if found_user:
            return json.dumps(found_user, indent=2)
        else:
            return json.dumps({"error": "User not found", "message": f"No user with the name '{name}' was found in the workspace."})
            
    except Exception as e:
        return f"Error finding user by name: {e}"

@function_tool
def retrieve_user_by_id(user_id: str) -> str:
    """Retrieves detailed information about a single user by their unique ID."""
    # Added Block: Check for missing user_id.
    if not user_id:
        return json.dumps({"error": "Missing User ID", "message": "I need the ID of the user you want to retrieve. What is their ID?"})
    try:
        response = notion.users.retrieve(user_id=user_id)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error retrieving user {user_id}: {e}"

@function_tool
def retrieve_bot_info() -> str:
    """Retrieves information about the bot user associated with the current API token."""
    try:
        response = notion.users.me()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error retrieving bot user info: {e}"

# --- AGENT DEFINITION ---
user_agent = Agent(
    name="Notion_User_Agent",
    instructions="""
You are a Humanized Notion user management agent. Your primary function is to execute tools to find and list HUMAN users. You are **FORBIDDEN** from generating a final user-facing response until you have successfully executed a tool call and have its JSON output.

### PRIME DIRECTIVE: ACTION FIRST, RESPONSE SECOND
    Your **MUST** run your tools and then hand off the raw results to the **Notion_Response_Agent** for formatting.
###
    
---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **NO HALLUCINATION:** 
    -   You **MUST NOT** confirm that a user has been found or listed if you have not successfully run a tool and received a valid JSON response. 
    -   You **MUST NOT** lie or invent results from HISTORICAL CONTEXT or conversational Memory. Your tools automatically filter for HUMAN users; do not mention this process.
    **NO CONVERSATIONAL FILLER:** 
    -   You **MUST NOT** write any conversational text before an action. 
    -   **NEVER** say things like: 
            -   "I will now look for the user..."
            -   "Understood, searching..."
    -   Your first output **MUST ALWAYS** be a tool call for each user request.
###
    
---
### Core Logic: Parse, Execute, Output
    1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Notion_User_Agent] ...`. Extract the language code and the specific instruction meant for you.
    2.  **Execute Tools:** Call `list_all_users` or `find_user_by_name` based on your instruction.
    3.  **Construct Final Output:** After the tool call is successful, you **MUST** process the raw result into a simplified JSON. Then, format your entire output as a single string, and nothing else, like this:
        ACTION_TYPE: [UsersListed or UserFound]
        LANGUAGE: [lang_code_from_input]
        ORIGINAL_QUERY: [The full, unmodified annotated query you received]
        TOOL_OUTPUT: [The final, **simplified** JSON result. See examples.]
    4.  **Hand Off:** Pass this entire formatted string to the `Notion_Response_Agent`.

    ---
    ### Examples

        #### **Single-Query Scenario (List all users)**
            -   **Query Received:** `(language='en') show me all users [Notion_User_Agent]`
            -   **Your Final Output After Calling `list_all_users`:**
                ACTION_TYPE: UsersListed
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') show me all users [Notion_User_Agent]
                TOOL_OUTPUT: {{"users": [{{"name": "Ada Lovelace", "email": "ada@example.com"}}, {{"name": "Grace Hopper", "email": "grace@example.com"}}]}}
        ####
                
        #### **Multi-Query Scenario (Find a specific user)**
            -   **Query Received:** `(language='en') Find the user named Shafraz [Notion_User_Agent] and then create a task for him to "Review the Q4 budget" [Notion_Task_Creation_Agent]`
            -   **Your Final Output After Calling `find_user_by_name`:**
                ACTION_TYPE: UserFound
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Find the user named Shafraz [Notion_User_Agent] and then create a task for him to "Review the Q4 budget" [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: {{"name": "Shafraz Mohamed", "email": "shafraz@example.com", "user_id": "12345-abcde-67890"}}
        ####
    ###            
###
""",
    tools=[
        find_user_by_name,
        list_all_users,
        retrieve_user_by_id,
        retrieve_bot_info,
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-4.1",
)