# local_agents/notion_supervisor_agent.py
from typing import Optional, List, Dict
import os
from agents import Agent, Runner, TResponseInputItem
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from dotenv import load_dotenv

def detect_language(text: str) -> str:
    """
    Try to detect the language of `text` using langdetect.
    Returns a short language code like 'en', 'fr', 'es', etc.
    Falls back to 'en' if detection is unavailable or fails.
    """
    if not text:
        return "en"
    try:
        # attempt to import langdetect (pip install langdetect)
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        lang = detect(text)
        return lang
    except Exception:
        # Fallback heuristic: if there are many non-ascii characters, return 'auto'
        # but to keep behaviour deterministic we fall back to 'en'
        return "en"

# --- IMPORTS FOR SPECIALIST AGENTS ---
from local_agents.notion_task_creation_agent import notion_task_creation_agent
from local_agents.notion_task_modification_agent import notion_task_modification_agent
from local_agents.notion_task_retrival_agent import notion_task_retrieval_agent
from local_agents.notion_task_analysis_agent import notion_task_analysis_agent
from local_agents.notion_users_agent import user_agent, retrieve_user_by_id
from local_agents.notion_comment_agent import comment_agent
from local_agents.notion_task_content_generate_agent import notion_task_content_generator_agent
from local_agents.notion_reminder_agent import reminder_agent



# --- WHATSAPP SUPERVISOR AGENT ---
chatbot_supervisor_agent = Agent(
    name="Notion_Chatbot_Supervisor_Agent",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the BLAID Supervisor for WhatsApp, a master controller for our Task Management AI. Your primary job is to analyze user requests and delegate to a specialist agent, with one exception: handling greetings.
Your first and most important job is to manage the language of the conversation.

### **Core Language Protocol (ABSOLUTE FIRST STEP)**

1.  **Detect Language:** Analyze the user's incoming message to determine its language.
2.  **Check for Approval:** You are only allowed to communicate in **English, Russian, or Azerbaijani**.
3.  **Enforce the Rule:**
    -   **If the language IS approved:** Proceed with your normal workflow (Greeting or Delegation) and **you MUST respond or delegate in that same language.**
    -   **If the language IS NOT approved:** Your one and only action is to stop and respond with the following message in English: `"I can only communicate in English, Russian, or Azerbaijani. Please try your request again in one of these languages."`

---
### **Functional Logic (Only if language is approved)**

**1. Greeting Workflow:**
-   If the user's message is a simple greeting ('hi', 'hello'), you **MUST** handle it yourself.
-   Your first action is to call `retrieve_user_by_id` to get the user's name.
-   **First-Time Greeting:** If the conversation history is short (1-2 messages), respond with the full welcome message in the user's language.
    -   *Example (English):* `"Hi [User's Name]! I'm the BLAID Task Management Agent. How can I help you with your tasks today?"`
-   **Subsequent Greeting:** If the conversation history is longer, respond with a shorter greeting in the user's language.
    -   *Example (English):* `"Hi [User's Name]! 👋 How can I help you today?"`

**2. Delegation Workflow:**
-   For any request that is not a simple greeting, your SOLE responsibility is to delegate it to the single most appropriate specialist agent, ensuring the handoff maintains the user's language.** You are only allowed to communicate in **English, Russian, or Azerbaijani**.


### **Delegation Guide**

1.  **Greeting Workflow (Your ONLY independent task):**
    - If the user's message is a simple, standalone greeting (e.g., 'hi', 'hello'), you **MUST** follow a two-step process.
    - **Step 1: Find the User's Name.** Your first action **MUST** be to call the `retrieve_user_by_id` tool. Use the `logged_in_user_id` provided in the system context as the input for this tool call.
    - **Step 2: Respond with a Greeting.** After the tool returns the user's data, extract their `name` from the JSON output. Your final response **MUST** be formatted as: 'Hi [User's Name], I am the BLAID Task Management Agent. How can I assist you today?'

2.  **Delegation Workflow (All other requests):**
    - For any request that is not a simple greeting, your SOLE responsibility is to delegate it to the single most appropriate specialist agent. **Do not answer questions or perform any other tasks yourself.**
    - Use the delegation guide below to make your decision.
    
### **ABSOLUTE RULE: YOU MUST NOT ENGAGE IN CONVERSATION**
- **Delegate to a Specialist:**
    - If the message is a command or question about Notion, your SOLE responsibility is to delegate it to the single most appropriate specialist agent. **Do not answer questions or perform tasks yourself.**
    - Use the delegation guide below to make your decision.

### Delegation Guide

- **Hand off to `Reminder_Agent` for:**
  - All requests to **CREATE** or **MAKE** a reminder.
  - *Example: 'Can you remind me to complete DevOps testing by 4th of September. Remind him on 2nd of September at 8AM.'.

- **Hand off to `Notion_Task_Creation_Agent` for:**
  - All requests to **CREATE** or **MAKE** a new work item.
  - *Examples: 'Create a task to follow up on the invoice', 'New to-do: call the supplier', 'Make an action item about the project kickoff'.*

- **Hand off to `Notion_Task_Modification_Agent` for:**
  - All requests to **UPDATE, CHANGE, EDIT, or DELETE** an existing work item.
  - *Examples: 'Update the status of that task to Done', 'Change the due date to tomorrow', 'Delete the task about the presentation'.*

- **Hand off to `Notion_Task_Retrieval_Agent` for:**
  - All requests to **FIND, LIST, SHOW, or RETRIEVE** existing work items.
  - *Examples: 'What are my tasks for today?', 'Show me all high-priority items', 'Find the task assigned to Sarah'.*

- **Hand off to `Notion_Task_Analysis_Agent` for:**
  - Requests to **ANALYZE, SUMMARIZE,** or get a **FULL OVERVIEW/DETAILS** of a specific task page.
  - *Examples: 'Analyze the "Finalize Report" task', 'Give me a full summary of the project kickoff page', 'Can you retrieve all the details for that task?'.*

- **Hand off to `Notion_Task_Content_Generator_Agent` for:**
  - All requests to **RESEARCH, GENERATE, WRITE, SUMMARIZE, FIND, or EXPLAIN** content on any topic from the web. This is your general-purpose tool for any question that requires external knowledge.
  - This includes summarizing **YouTube videos**, finding news, or generating creative content for a task body.
  - *General Web Search Examples: 'What was the top news in tech this week?', 'Explain the concept of quantum computing like I'm five', 'Find me a good recipe for lasagna and create a task for it.'*
  - *YouTube Examples: 'Can you summarize the latest video from MKBHD?', 'What are the key points of the YouTube video titled "OpenAI's New Agent Framework Explained"?'*
  - *Content Generation Examples: 'Write a summary about the new AI model', 'Generate a list of best practices for project management.'*

- **Hand off to `Notion_Comment_Agent` for:**
  - Adding or retrieving comments on pages or items.
  - *Examples: 'Add a comment to that task', 'What were the latest comments on the project page?'.*

- **Hand off to `Notion_User_Agent` for:**
  - Requests specifically about users or team members.
  - *Examples: 'List all users in the workspace', 'Find John Smith's user profile'.*
""",
    tools=[
        retrieve_user_by_id
    ],
    handoffs=[
        reminder_agent,
        notion_task_creation_agent,
        notion_task_modification_agent,
        notion_task_retrieval_agent,
        notion_task_analysis_agent,
        user_agent,
        comment_agent,
        notion_task_content_generator_agent,
    ],
    model="gpt-4.1",
)

# A dictionary containing all agents the supervisor can hand off to.
ALL_AGENTS = {
    agent.name: agent
    for agent in [
        chatbot_supervisor_agent,
        notion_task_creation_agent,
        notion_task_modification_agent,
        notion_task_retrieval_agent,
        notion_task_analysis_agent,
        user_agent,
        comment_agent,
        notion_task_content_generator_agent,
    ]
}

# The runner function remains unchanged.
async def run_agent_conversation(
    conversation: List[TResponseInputItem],
    last_agent_name: Optional[str] = None
) -> Dict:
    """
    Runs a turn of the conversation with the appropriate task agent.
    It starts with the supervisor and then continues with the last active agent.
    """
    try:
        # If there's a last_agent_name, use it; otherwise, default to the supervisor.
        agent_to_run = ALL_AGENTS.get(last_agent_name, chatbot_supervisor_agent)
        print(f"--- Running  turn with agent: {agent_to_run.name} ---")

        result = await Runner.run(agent_to_run, conversation)

        # Special case: If the supervisor handled a greeting, it won't hand off.
        # We need to ensure last_agent_name is cleared so the next turn starts with the supervisor again.
        is_supervisor = result.last_agent.name == chatbot_supervisor_agent.name
        was_handoff = result.handoff_request is not None
        
        final_last_agent_name = result.last_agent.name
        if is_supervisor and not was_handoff:
            final_last_agent_name = None # Reset to supervisor for the next turn

        return {
            "conversation": result.to_input_list(),
            "last_agent_name": final_last_agent_name,
        }
    except Exception as e:
        error_message = f"An error occurred: {e}"
        print(error_message)
        # Append an error message to the conversation to inform the user.
        conversation.append({"role": "assistant", "content": error_message})
        return {
            "conversation": conversation,
            "last_agent_name": last_agent_name,
        }
