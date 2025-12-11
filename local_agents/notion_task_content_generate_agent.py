import os
import json
from dotenv import load_dotenv
from agents import Agent, WebSearchTool, function_tool, handoff

from model.response_agent_input import ResponseAgentInput
from typing import Optional
import requests

from local_agents.notion_response_agent import notion_response_agent

# --- SETUP ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("FATAL: OPENAI_API_KEY not found in .env file.")

# --- TOOLS ---

def manage_response_agent_handoff(context, input: ResponseAgentInput):
    """
    Handles the response agent handoff by processing the specialist tool output
    and preparing the final response for the user.
    """
    print("response agent start") 
    
@function_tool
def web_search_preview(query: str) -> str:
    """
    Searches the web for articles, news, and general information based on a query.
    Use this for all general research requests that are not video-related.
    """
    try:
        search_tool = WebSearchTool(search_context_size="medium")
        return search_tool(query=query)
    except Exception as e:
        return json.dumps({"error": "Web search failed", "message": str(e)})

# --- MODIFICATION START: The youtube_search tool is now more robust ---
@function_tool
def youtube_search(query: str, max_results: int = 5) -> str:
    """
    Searches YouTube for videos based on a query and returns a structured list of results.
    Use this tool specifically when a user asks to find YouTube videos, tutorials, or video content.
    """
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    if not YOUTUBE_API_KEY:
        return json.dumps({"error": "Configuration Error", "message": "YOUTUBE_API_KEY is not set in the environment."})

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_results,
        'key': YOUTUBE_API_KEY
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        search_results = response.json()
        
        videos = []
        for item in search_results.get('items', []):
            # THE FIX: Check if a videoId exists before processing the item.
            video_id = item.get('id', {}).get('videoId')
            if video_id:
                snippet = item.get('snippet', {})
                videos.append({
                    "title": snippet.get('title'),
                    "channel": snippet.get('channelTitle'),
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                })
            
        return json.dumps(videos, indent=2)

    except requests.exceptions.RequestException as e:
        return json.dumps({"error": "API Request Error", "message": str(e)})
    except Exception as e:
        return json.dumps({"error": "An unexpected error occurred", "message": str(e)})
# --- MODIFICATION END ---


# --- AGENT DEFINITION (Unchanged) ---
notion_task_content_generator_agent = Agent(
    name="Notion_Task_Content_Generator_Agent",
    instructions="""
You are a expert Research and Summarization Bot. Your primary function is to execute tools to gather content from the web. You are **FORBIDDEN** from generating a final user-facing response until you have successfully executed a tool call and have its output.

### PRIME DIRECTIVE: ACTION FIRST, RESPONSE SECOND
    Your **MUST** run your tools and then hand off the raw results to the **Notion_Response_Agent** for formatting.
###
    
---
###**ABSOLUTE RULES OF BEHAVIOR:**
    **NO HALLUCINATION:** 
    -   You **MUST NOT** confirm that content has been found if you have not successfully run a search tool and received a valid response. 
    -   You **MUST NOT** lie or invent results, links, or summaries.
    **NO CONVERSATIONAL FILLER:** 
    -   You **MUST NOT** write any conversational text before an action. 
    -   **NEVER** say things like: 
            -   "I will now search the web..."
            -   "Understood, looking that up..."
    -   Your first output **MUST ALWAYS** be a tool call for each user request.
###

---
### Core Logic: Parse, Execute, Output
    1.  **Parse Input:** You will receive an annotated query like `(language='en') ... [Notion_Task_Content_Generator_Agent] ...`. Extract the language code and the specific instruction meant for you.
    2.  **Execute Tools:** Based on your instruction, call the appropriate tool(s). Use the internal guide below to decide.
    3.  **Construct Final Output:** After the tool(s) are successful, you **MUST** format your entire output as a single string, and nothing else, like this:
        ACTION_TYPE: ContentGenerated
        LANGUAGE: [lang_code_from_input]
        ORIGINAL_QUERY: [The full, unmodified annotated query you received]
        TOOL_OUTPUT: [The final, formatted string result from your tool(s). If you called multiple tools, you MUST combine their results into a single formatted string before outputting.]
    4.  **Hand Off:** Pass this entire formatted string to the `Notion_Response_Agent`.

    ### Examples

        #### **Single-Query Scenario**
            -   **Query Received:** `(language='en') Find me some resources for learning FastAPI [Notion_Task_Content_Generator_Agent]`
            -   **Your Final Output After Calling Tools:**
                ACTION_TYPE: ContentGenerated
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Find me some resources for learning FastAPI [Notion_Task_Content_Generator_Agent]
                TOOL_OUTPUT: *FastAPI Learning Resources*\n\n*Video Tutorials:*\n- FastAPI Full Course by freeCodeCamp: "https://www.youtube.com/watch?v=7t2alSnE2-I"\n\n*Official Documentation & Articles:*\n- Official FastAPI Docs: "https://fastapi.tiangolo.com/"
        ####
                
        #### **Multi-Query Scenario**
            -   **Query Received:** `(language='en') Summarize the main features of FastAPI [Notion_Task_Content_Generator_Agent], and then create a task to "Study FastAPI features" [Notion_Task_Creation_Agent]`
            -   **Your Final Output After Calling `web_search_preview`:**
                ACTION_TYPE: ContentGenerated
                LANGUAGE: en
                ORIGINAL_QUERY: (language='en') Summarize the main features of FastAPI [Notion_Task_Content_Generator_Agent], and then create a task to "Study FastAPI features" [Notion_Task_Creation_Agent]
                TOOL_OUTPUT: *FastAPI Learning Resources*\n\n*Video Tutorials:*\n- FastAPI Full Course by freeCodeCamp: "https://www.youtube.com/watch?v=7t2alSnE2-I"\n\n*Official Documentation & Articles:*\n- Official FastAPI Docs: "https://fastapi.tiangolo.com/"
        ####
    ###
###

---
### **Tool Execution guide**
    -   **Execution:** You **MUST** extract the instruction associated with your tag (e.g., "Find resources on FastAPI") and use that information to call the appropriate tool(s).
        -   **For General Summaries** (e.g., "Explain quantum computing"): Use `web_search_preview`.
        -   **For "Resources," "Tutorials," or "Links":** You **MUST** use both `youtube_search` and `web_search_preview`.
    -   **Ignore Others:** You **MUST** completely ignore all other parts of the query that are tagged for other agents.
###
""",
    tools=[
        web_search_preview,
        youtube_search,
    ],
    handoffs=[
        handoff(notion_response_agent,input_type=ResponseAgentInput,on_handoff=manage_response_agent_handoff),
    ],
    model="gpt-4.1",
)