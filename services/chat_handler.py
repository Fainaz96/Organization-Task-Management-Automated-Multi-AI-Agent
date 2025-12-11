from datetime import date
import logging
import re
from agents import Runner
from fastapi import HTTPException
import mysql
from db import get_db_connection
from schema.chat_schema import ChatHistoryResponse, Message
from utils.db_helper import execute_query
from utils.formatter import format_db_rows_for_response
import uuid
from typing import Optional
from agents import Agent, Runner
import os
import json
import re

async def handle_chat(
    thread_id: str,
    prompt: str,
    agent_to_use: Agent,
    database_id: Optional[str] = None,
    current_user_id: Optional[str] = None,
    date:Optional[str] = date.today().isoformat()
):
    original_db_id = os.getenv("NOTION_TASKS_DATABASE_ID")
    print(date)
    # conn = get_db_connection()
    # if not conn:
    #     raise HTTPException(status_code=500, detail="Database connection failed")

    # def get_safe_cursor():
    #     if not conn.is_connected():
    #         conn.ping(reconnect=True, attempts=3, delay=2)
    #     return conn.cursor(dictionary=True)

    try:
        # 1. Prepare conversation history with context
        # cursor = get_safe_cursor()
        # cursor.execute(
        #     "SELECT author_type, content FROM Messages WHERE thread_id = %s ORDER BY created_at ASC",
        #     (thread_id,)
        # )
        # db_history = cursor.fetchall()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            db_history = await execute_query(
                conn,
                "SELECT author_type, content FROM Messages WHERE thread_id = :thread_id ORDER BY created_at ASC",
                {"thread_id": thread_id},
                fetch_one=False
            )

        current_conversation = [
            {"role": row['author_type'], "content": row['content']}
            for row in db_history
        ]

        # cursor = get_safe_cursor()
        # cursor.execute(
        #     "SELECT task_id, task_name FROM ThreadTasks WHERE thread_id = %s ORDER BY created_at ASC",
        #     (thread_id,)
        # )
        # task_rows = cursor.fetchall()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            task_rows = await execute_query(
                conn,
                "SELECT author_type, content FROM Messages WHERE thread_id = :thread_id ORDER BY created_at ASC",
                {"thread_id": thread_id},
                fetch_one=False
            )
        
        tasks_in_thread = [
            {"id": row['task_id'], "name": row.get('task_name')}
            for row in task_rows if row.get('task_id')
        ]

        task_context_info = ""
        if tasks_in_thread:
            task_list_str = json.dumps(tasks_in_thread)
            task_context_info = (
                f"HISTORICAL CONTEXT:\n"
                f"- The following tasks have been created in this conversation: {task_list_str}\n"
                f"- If the user says 'the task' or 'that task,' they mean the last one in this list.\n"
                f"----\n\n"
            )

        # --- FIX: build the prompt safely ---
        agent_prompt = f"{task_context_info}{prompt}"

        if current_user_id:
            agent_prompt += f"\n(logged_in_user_id='{current_user_id}')"

        if database_id:
            agent_prompt += f"\n(database_id=`{database_id}`)"

        # Provide dynamic, user-local current date/time to agents
        if date is not None:
            try:
                # If a timezone-aware datetime was passed in from the webhook, use it
                current_date_str = None
                current_time_str = None
                # Avoid importing date type here since parameter name shadows it
                if hasattr(date, "date") and hasattr(date, "time"):
                    current_date_str = date.date().isoformat()
                    # ISO time without microseconds for readability
                    current_time_str = date.time().replace(microsecond=0).isoformat()
                elif hasattr(date, "isoformat"):
                    # If it's a date or string-like with isoformat
                    current_date_str = date.isoformat() if callable(date.isoformat) else str(date)
                else:
                    current_date_str = str(date)

                if current_date_str:
                    agent_prompt += f"\n(current_date='{current_date_str}')"
                if current_time_str:
                    agent_prompt += f"\n(current_time='{current_time_str}')"
            except Exception:
                # Non-fatal; proceed without adding date/time context
                pass

        # 2. Save user message and run the agent
        user_message_id = str(uuid.uuid4())
        # cursor = get_safe_cursor()
        # cursor.execute(
        #     "INSERT INTO Messages (message_id, thread_id, author_type, content) VALUES (%s, %s, %s, %s)",
        #     (user_message_id, thread_id, "user", prompt)
        # )
        # conn.commit()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            await execute_query(
                conn,
                "INSERT INTO Messages (message_id, thread_id, author_type, content) VALUES (:message_id, :thread_id, :author_type, :content)",
                {"message_id": user_message_id,"thread_id": thread_id,"author_type": "user","content": prompt},
                fetch_one=False
            )

        current_conversation.append({"role": "user", "content": agent_prompt})

        result = await Runner.run(agent_to_use, current_conversation)
        updated_conversation = result.to_input_list()

        # If the supervisor emitted only an annotated routing string and did not
        # actually perform a handoff, follow through by invoking the target agent
        # directly. Also, if a specialist returns a structured ACTION_TYPE block
        # without handing off, run the Notion_Response_Agent as a fallback.
        def _extract_handoff_agent(text: str) -> Optional[str]:
            if not isinstance(text, str):
                return None
            # Look for a bracketed agent name like [Notion_Task_Creation_Agent]
            m = re.search(r"\[([^\]]+?_Agent)\]", text)
            if m:
                return m.group(1).strip()
            return None

        # Identify last assistant text
        last_ai_text = ""
        for msg in reversed(updated_conversation):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                last_ai_text = "".join(
                    [part.get("text", "") for part in content if isinstance(part, dict)]
                ) if isinstance(content, list) else str(content)
                break

        def _looks_like_supervisor_route(text: str) -> bool:
            return isinstance(text, str) and text.strip().startswith("(language=") and "[Notion_" in text

        def _looks_like_structured_action_block(text: str) -> bool:
            return isinstance(text, str) and ("ACTION_TYPE:" in text and "TOOL_OUTPUT:" in text)

        try:
            from local_agents.notion_whatsapp_supervisor_agent import ALL_WHATSAPP_AGENTS  # lazy import
        except Exception:
            ALL_WHATSAPP_AGENTS = {}

        # Attempt up to two follow-through steps
        for _ in range(2):
            if _looks_like_supervisor_route(last_ai_text):
                try:
                    agent_name = _extract_handoff_agent(last_ai_text)
                    if agent_name and agent_name in ALL_WHATSAPP_AGENTS:
                        next_agent = ALL_WHATSAPP_AGENTS[agent_name]
                        result = await Runner.run(next_agent, updated_conversation)
                        updated_conversation = result.to_input_list()
                        # refresh last_ai_text for next decision
                        last_ai_text = ""
                        for msg in reversed(updated_conversation):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", "")
                                last_ai_text = "".join(
                                    [part.get("text", "") for part in content if isinstance(part, dict)]
                                ) if isinstance(content, list) else str(content)
                                break
                        continue
                except Exception:
                    break
            elif _looks_like_structured_action_block(last_ai_text):
                try:
                    # Run the response agent explicitly if needed
                    response_agent = ALL_WHATSAPP_AGENTS.get("Notion_Response_Agent")
                    if response_agent:
                        result = await Runner.run(response_agent, updated_conversation)
                        updated_conversation = result.to_input_list()
                        break
                except Exception:
                    break
            break

        # 3. Process agent's turn to generate the final response
        final_response_text = ""

        created_task_tool_message = next((
            msg for msg in updated_conversation
            if msg.get("role") == "tool" and msg.get("name") in ["create_task_with_content", "create_task"]
        ), None)

        if created_task_tool_message:
            try:
                tool_output = json.loads(created_task_tool_message.get("content", "{}"))
                if tool_output.get("object") == "page":
                    props = tool_output.get("properties", {})
                    task_name = props.get("Task", {}).get("title", [{}])[0].get("plain_text", "N/A")
                    task_id = tool_output.get("id", "N/A")
                    task_link = tool_output.get("url", "N/A")
                    created_by = props.get("Created by", {}).get("people", [{}])[0].get("name", "N/A")
                    assigned_to = props.get("Assigned to", {}).get("people", [{}])[0].get("name", "N/A")
                    created_date = tool_output.get("created_time", "N/A").split("T")[0]
                    due_date = props.get("Due Date", {}).get("date", {}).get("start", "N/A")

                    # Save task to ThreadTasks if new
                    if task_id != "N/A" and not any(t['id'] == task_id for t in tasks_in_thread):
                        # cursor = get_safe_cursor()
                        # cursor.execute(
                        #     "INSERT INTO ThreadTasks (thread_id, task_id, task_name) VALUES (%s, %s, %s)",
                        #     (thread_id, task_id, task_name)
                        # )
                        # conn.commit()
                        # cursor.close()
                        async for conn in get_db_connection():  # get AsyncSession
                            await execute_query(
                                conn,
                                "INSERT INTO ThreadTasks (thread_id, task_id, task_name) VALUES (:thread_id,:task_id,:task_name)",
                                {"thread_id": thread_id,"task_id": task_id,"task_name": task_name},
                                fetch_one=False
                            )

                    final_response_text = (
                        f"Task '{task_name}' has been created successfully. Here are the details:\n\n"
                        f"- **Task Name**: {task_name}\n"
                        f"- **Task Page ID**: {task_id}\n"
                        f"- **Task Link**: {task_link}\n"
                        f"- **Created By**: {created_by}\n"
                        f"- **Assigned to**: {assigned_to}\n"
                        f"- **Created Date**: {created_date}\n"
                        f"- **Due Date**: {due_date}"
                    )
            except (json.JSONDecodeError, KeyError, IndexError, mysql.connector.Error) as e:
                print(f"--- ERROR: Failed to parse/save task details. Error: {e} ---")
                final_response_text = ""

        # 4. Save the final assistant response
        final_assistant_message = next(
            (msg for msg in reversed(updated_conversation) if msg.get("role") == "assistant"),
            None
        )

        if final_assistant_message:
            message_id = final_assistant_message.get("id", str(uuid.uuid4()))

            if not final_response_text:
                content = final_assistant_message.get("content", "")
                final_response_text = "".join(
                    [part.get("text", "") for part in content if isinstance(part, dict)]
                ) if isinstance(content, list) else str(content)

            if final_response_text:
                # conn.ping(reconnect=True)
                # cursor = get_safe_cursor()
                # cursor.execute(
                #     "INSERT INTO Messages (message_id, thread_id, author_type, content) VALUES (%s, %s, %s, %s)",
                #     (message_id, thread_id, "assistant", final_response_text)
                # )
                # conn.commit()
                # cursor.close()
                async for conn in get_db_connection():  # get AsyncSession
                    await execute_query(
                                conn,
                                "INSERT INTO Messages (message_id, thread_id, author_type, content) VALUES (:message_id,:thread_id,:author_type,:content)",
                                {"message_id": message_id,"thread_id": thread_id,"author_type": "assistant","content":final_response_text},
                                fetch_one=False
                    )

        # 5. Return full updated chat history
        # conn.ping(reconnect=True)
        # cursor = get_safe_cursor()
        # cursor.execute(
        #     "SELECT message_id, author_type, content FROM Messages WHERE thread_id = %s ORDER BY created_at ASC",
        #     (thread_id,)
        # )
        # final_db_history = cursor.fetchall()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            final_db_history = await execute_query(
                                conn,
                                "SELECT message_id, author_type, content FROM Messages WHERE thread_id = :thread_id ORDER BY created_at ASC",
                                {"thread_id": thread_id},
                                fetch_one=False
            )

        formatted_messages = format_db_rows_for_response(final_db_history)
        return ChatHistoryResponse(messages=formatted_messages)

    except Exception as e:
        error_message = f"An error occurred: {e}"
        print(f"--- FATAL ERROR in handle_chat: {e} ---")
        return ChatHistoryResponse(
            messages=[Message(from_="Bot", text=error_message, id=str(uuid.uuid4()))]
        )

    finally:
        if database_id and original_db_id:
            os.environ["NOTION_TASKS_DATABASE_ID"] = original_db_id
        # if conn and conn.is_connected():
        #     conn.close()
