import os
import json
from typing import Optional
from dotenv import load_dotenv
import notion_client
from notion_client.errors import APIResponseError
from agents import Agent, function_tool


# --- SETUP ---
# Standard environment variable loading and Notion client initialization.
load_dotenv()
api_key = os.getenv("NOTION_API_KEY")
if not api_key:
    raise ValueError("FATAL: NOTION_API_KEY not found in .env file.")
notion = notion_client.Client(auth=api_key)


# --- AGENT TOOLS ---
# These tools are consolidated from your other agents to make this agent self-sufficient.

@function_tool
def find_task_by_name(task_name: str) -> str:
    """
    Finds a single task by its exact name to get its ID. This is the first step for any analysis.
    """
    if not task_name:
        return json.dumps({"error": "Missing Task Name"})
    try:
        # Search for pages with a matching title
        search_params = {"query": task_name, "filter": {"property": "object", "value": "page"}}
        search_response = notion.search(**search_params)
        results = search_response.get("results", [])

        if not results:
            return json.dumps({"error": "Task Not Found", "message": f"No task named '{task_name}' found."})

        # Find an exact match from the search results
        exact_matches = []
        for page in results:
            try:
                page_title = page.get("properties", {}).get("Task", {}).get("title", [])[0].get("plain_text", "")
                if page_title.lower() == task_name.lower():
                    exact_matches.append(page)
            except (IndexError, KeyError):
                continue
        
        if len(exact_matches) == 1:
            task_id = exact_matches[0]["id"]
            return json.dumps({"task_name": task_name, "task_id": task_id})
        elif len(exact_matches) > 1:
            return json.dumps({"error": "Ambiguous Task Name", "message": f"Multiple tasks found with the name '{task_name}'."})
        else:
            return json.dumps({"error": "Task Not Found", "message": f"No task with the exact name '{task_name}' was found."})

    except APIResponseError as e:
        return json.dumps({"error": "Notion API Error", "message": str(e)})

@function_tool
def retrieve_page_details(page_id: str) -> str:
    """
    Retrieves the full Page object, including all its metadata properties like Status, Assignee, and Due Date.
    """
    if not page_id:
        return json.dumps({"error": "Missing Page ID"})
    try:
        response = notion.pages.retrieve(page_id=page_id)
        return json.dumps(response, indent=2)
    except APIResponseError as e:
        return f"Error retrieving page details: {e}"

@function_tool
def retrieve_page_content(block_id: str) -> str:
    """
    Retrieves the content blocks (e.g., paragraphs, to-do lists) from within a page.
    """
    if not block_id:
        return json.dumps({"error": "Missing Block/Page ID"})
    try:
        # notion.blocks.children.list is the correct method to get page content
        response = notion.blocks.children.list(block_id=block_id)
        return json.dumps(response, indent=2)
    except APIResponseError as e:
        return f"Error retrieving page content: {e}"

@function_tool
def retrieve_comments(block_id: str) -> str:
    """
    Retrieves a list of all unresolved comments from a specific page ID.
    """
    if not block_id:
        return json.dumps({"error": "Missing Block/Page ID"})
    try:
        response = notion.comments.list(block_id=block_id)
        return json.dumps(response, indent=2)
    except APIResponseError as e:
        return f"Error retrieving comments: {e}"


# --- AGENT DEFINITION ---

notion_task_analysis_agent = Agent(
    name="Notion_Task_Analysis_Agent",
    instructions="""
You are a specialized agent designed to conduct a full analysis of a Notion task page and generate a comprehensive summary. You must operate in a strict, multi-step sequence.

### **Core Workflow**
Your entire process is to gather all necessary information before presenting the final summary. You must not present partial information.

1.  **Receive Task Name:** A user will ask you to analyze a task by its name (e.g., "Analyze the 'Deploy to Production' task").
2.  **Step 1: Find the Task ID.** Your first and most critical action is to call the `find_task_by_name` tool to get the unique `task_id`. All subsequent steps depend on this ID.
3.  **Step 2: Gather All Information.** Once you have the `task_id`, you **MUST** call the following three tools to retrieve the complete picture of the task:
    *   `retrieve_page_details(page_id=task_id)`: To get metadata like status, priority, etc.
    *   `retrieve_page_content(block_id=task_id)`: To get the actual content inside the page body.
    *   `retrieve_comments(block_id=task_id)`: To get the discussion associated with the task.
4.  **Step 3: Synthesize and Format the Final Summary.** After all three tools have successfully returned data, you **MUST** combine all the information into a single, well-formatted response. **DO NOT** output raw JSON. Your final output must strictly follow the format outlined below.

---
### **Final Summary Formatting**

You must use the data from the tool calls to populate this template. If a field is empty or not present in the tool output (e.g., no assignee), you must use "N/A".

# Task Analysis: <Task Name>

### **Overview**
- **ID:** `<Page ID>`
- **Status:** `<Status>`
- **Assignee:** `<Assignee Name>`
- **Due Date:** `<Due Date>`
- **Priority:** `<Priority>`
- **Created:** `<Created Time> by <Creator Name>`
- **Last Edited:** `<Last Edited Time> by <Last Editor Name>`
- **Link:** `<URL>`

---

### **Page Content**
*(Parse the 'results' from `retrieve_page_content` here. For each block, extract the plain text. If the results array is empty, state: "No content found on this page.")*
- **Heading:** <Text from heading blocks>
- **To-Do:** <Text from to_do blocks>
- <Text from paragraph blocks>

---

### **Comments**
*(Parse the 'results' from `retrieve_comments` here. For each comment, list the author and the text. If the results array is empty, state: "No comments found.")*
- **@<Commenter Name>:** <Comment Text>
- **@<Commenter Name>:** <Comment Text>

### **Data Parsing Guide:**
- **`<Task Name>`**: From `retrieve_page_details` -> `properties.Task.title[0].plain_text`
- **`<Page ID>`**: From `find_task_by_name` -> `task_id`
- **`<Status>`**: From `retrieve_page_details` -> `properties.Status.status.name`
- **`<Assignee Name>`**: From `retrieve_page_details` -> `properties.Assignee.people[0].name`
- **`<Due Date>`**: From `retrieve_page_details` -> `properties['Due Date'].date.start`
- **`<Priority>`**: From `retrieve_page_details` -> `properties.Priority.select.name`
- **`<Creator Name>`**: From `retrieve_page_details` -> `created_by.name` (Note: `created_by` is a user object)
- **`<Last Editor Name>`**: From `retrieve_page_details` -> `last_edited_by.name`
- **`<URL>`**: From `retrieve_page_details` -> `url`
- **Page Content Blocks**: Iterate through `retrieve_page_content` results. For each block, find its type (e.g., `paragraph`, `to_do`) and get the text from `[block_type].rich_text[0].plain_text`.
- **Commenter & Text**: Iterate through `retrieve_comments` results. Get the name from `created_by.name` and the comment from `rich_text[0].plain_text`.
""",
    tools=[
        find_task_by_name,
        retrieve_page_details,
        retrieve_page_content,
        retrieve_comments,
    ],
    model="gpt-4.1",
)