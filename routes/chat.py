from fastapi import APIRouter, HTTPException,Depends, Form, UploadFile, File, WebSocket, WebSocketDisconnect, Query
from pydub import AudioSegment
from openai import OpenAI
import io
import os
from typing import List
from local_agents.notion_supervisor_agent import chatbot_supervisor_agent
from routes.auth import get_current_user_id, get_user_id_from_token
from schema.chat_schema import *
from db import get_db_connection
from agents import Runner
from schema.notification_schema import Notification, UpdateNotificationRequest
from services.chat_handler import handle_chat
import uuid
import datetime
from local_agents.notion_whatsapp_supervisor_agent import whatsapp_supervisor_agent
from utils.db_helper import execute_query

client = OpenAI()

router = APIRouter()

# --- MODIFICATION START ---
@router.post("/chat/new", response_model=NewChatResponse, tags=["Web Chat"])
async def start_new_chat(chat_title: str, type: str = "web",user_id: str = Depends(get_current_user_id)):
    try:
        thread_id = str(uuid.uuid4())
        conn = get_db_connection()
        if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
        # cursor = conn.cursor()
        # cursor.execute("INSERT INTO Threads (thread_id, title, type) VALUES (%s, %s, %s)", (thread_id, chat_title, "web"))
        # conn.commit()
        async for conn in get_db_connection():  # get AsyncSession
            await execute_query(
                                conn,
                                "INSERT INTO Threads (thread_id, title, type) VALUES (:thread_id, :title, :type)",
                                {"thread_id": thread_id, "title":chat_title, "type":"web"},
                                fetch_one=False
            )
        # cursor.execute("INSERT INTO UserThread(thread_id,user_id) VALUES (%s, %s)", (thread_id, user_id))
        # conn.commit()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            await execute_query(
                                conn,
                                "SELECT message_id, author_type, content FROM Messages WHERE thread_id = :thread_id ORDER BY created_at ASC",
                                {"thread_id": thread_id},
                                fetch_one=False
            )
        return NewChatResponse(thread_id=thread_id)
    except Exception as e:
        return e

@router.post("/text_chat", tags=["Web Chat"])
async def chat_with_agent(request: ChatRequest,user_id: str = Depends(get_current_user_id)):
    try:
        conn = get_db_connection()
        if not conn: raise HTTPException(status_code=500, detail="Database connection failed")

        # user_thread_cursor = conn.cursor()
        # user_thread_cursor.execute("SELECT * FROM UserThread WHERE user_id = %s AND thread_id = %s", (user_id, request.thread_id))
        # if not user_thread_cursor.fetchone():
        #     user_thread_cursor.execute("INSERT INTO UserThread (user_id, thread_id) VALUES (%s, %s)", (user_id, request.thread_id))
        #     conn.commit()
        # user_thread_cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            user_thread = await execute_query(
                                conn,
                                "SELECT * FROM UserThread WHERE user_id = :user_id AND thread_id = :thread_id",
                                {"user_id": user_id,"thread_id":request.thread_id},
                                fetch_one=True
            )

        if not user_thread:
            async for conn in get_db_connection():  # get AsyncSession
                user_thread = await execute_query(
                                    conn,
                                    "INSERT INTO UserThread (user_id, thread_id) VALUES (:user_id, :thread_id)",
                                    {"user_id": user_id,"thread_id":request.thread_id},
                                    fetch_one=True
                )
        
        # cursor = conn.cursor(dictionary=True)
        # query = """
        #     SELECT u.notion_user_id, d.database_id 
        #     FROM Users u
        #     LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
        #     LEFT JOIN Departments d ON du.department_id = d.department_id
        #     WHERE u.user_id = %s;
        # """
        # cursor.execute(query, (user_id,))
        # user_data = cursor.fetchone()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                user_data = await execute_query(
                                    conn,
                                    """
                                        SELECT u.notion_user_id, d.database_id 
                                        FROM Users u
                                        LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
                                        LEFT JOIN Departments d ON du.department_id = d.department_id
                                        WHERE u.user_id = :user_id;
                                    """,
                                    {"user_id": user_id},
                                    fetch_one=True
                )

        if not user_data:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

        notion_id = user_data.get('notion_user_id')
        department_database_id = user_data.get('database_id')
        
        if not department_database_id:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' is not assigned to a department with a Notion database ID.")

        return await handle_chat(
            thread_id=request.thread_id, 
            prompt=request.message, 
            agent_to_use=chatbot_supervisor_agent, 
            database_id=department_database_id, 
            current_user_id=notion_id
        )
    except Exception as e:
        print(e)
        return []

# --- FIXES APPLIED TO THIS FUNCTION ---
@router.post("/voice_chat", tags=["Web Chat"])
async def voice_chat_with_agent(
    thread_id: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id)
):
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an audio file.")
    
    try:
        file_bytes = await file.read()
        file_buffer = io.BytesIO(file_bytes)
        
        # FIX 1: Rewind the in-memory file to the start before reading.
        file_buffer.seek(0)
        
        file_extension = os.path.splitext(file.filename)[1].lower() or ".wav"
        
        # Pydub can often infer the format, which is more robust for uploads.
        audio = AudioSegment.from_file(file_buffer)
        
        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        wav_buffer.name = "input.wav"

        transcription = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=wav_buffer,
            response_format="json"
        )
        prompt = transcription.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio transcription failed: {str(e)}")

    try:
        conn = get_db_connection()
        if not conn: raise HTTPException(status_code=500, detail="Database connection failed")

        # user_thread_cursor = conn.cursor()
        # user_thread_cursor.execute("SELECT * FROM UserThread WHERE user_id = %s AND thread_id = %s", (user_id, thread_id))
        # if not user_thread_cursor.fetchone():
        #     user_thread_cursor.execute("INSERT INTO UserThread (user_id, thread_id) VALUES (%s, %s)", (user_id, thread_id))
        #     conn.commit()
        # user_thread_cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
            user_thread = await execute_query(
                                conn,
                                "SELECT * FROM UserThread WHERE user_id = :user_id AND thread_id = :thread_id",
                                {"user_id": user_id,"thread_id":thread_id},
                                fetch_one=True
            )

        if not user_thread:
            async for conn in get_db_connection():  # get AsyncSession
                user_thread = await execute_query(
                                    conn,
                                    "INSERT INTO UserThread (user_id, thread_id) VALUES (:user_id, :thread_id)",
                                    {"user_id": user_id,"thread_id":thread_id},
                                    fetch_one=True
                )
        
        
        # cursor = conn.cursor(dictionary=True)
        # query = """
        #     SELECT u.notion_user_id, d.database_id 
        #     FROM Users u
        #     LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
        #     LEFT JOIN Departments d ON du.department_id = d.department_id
        #     WHERE u.user_id = %s;
        # """
        # cursor.execute(query, (user_id,))
        # user_data = cursor.fetchone()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                user_data = await execute_query(
                                    conn,
                                    """
                                        SELECT u.notion_user_id, d.database_id 
                                        FROM Users u
                                        LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
                                        LEFT JOIN Departments d ON du.department_id = d.department_id
                                        WHERE u.user_id = :user_id;
                                    """,
                                    {"user_id": user_id},
                                    fetch_one=True
                )

        if not user_data:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

        notion_id = user_data.get('notion_user_id')
        department_database_id = user_data.get('database_id')
        
        if not department_database_id:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' is not assigned to a department with a Notion database ID.")

        return await handle_chat(
            thread_id=thread_id, 
            prompt=prompt, 
            agent_to_use=chatbot_supervisor_agent, 
            database_id=department_database_id, 
            current_user_id=notion_id
        )
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"An error occurred while handling the chat: {e}")

# FIX 2: The duplicate voice_chat_with_agent function has been removed.

@router.websocket("/ws/voice_chat")
async def voice_chat_stream(websocket: WebSocket, thread_id: str, token: str):
    try:
        user_id = await get_user_id_from_token(token)
        if not user_id:
            await websocket.close(code=4001, reason="Invalid authentication token")
            return
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid authentication token")
        return

    await websocket.accept()
    audio_buffer = io.BytesIO()

    try:
        while True:
            data = await websocket.receive_bytes()
            audio_buffer.write(data)
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for thread {thread_id}. Processing audio.")
        audio_buffer.seek(0)

        if audio_buffer.getbuffer().nbytes == 0:
            print("No audio data received.")
            return

        try:
            audio_buffer.seek(0) # Rewind for reading
            audio = AudioSegment.from_file(audio_buffer, format="webm")
            
            wav_buffer = io.BytesIO()
            audio.export(wav_buffer, format="wav")
            wav_buffer.seek(0)
            wav_buffer.name = "streamed_audio.wav"

            transcription = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=wav_buffer,
                response_format="json"
            )
            prompt = transcription.text
            print(f"Transcription successful: {prompt}")

            # conn = get_db_connection()
            # cursor = conn.cursor(dictionary=True)
            # query = """
            #     SELECT u.notion_user_id, d.database_id 
            #     FROM Users u
            #     LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
            #     LEFT JOIN Departments d ON du.department_id = d.department_id
            #     WHERE u.user_id = %s;
            # """
            # cursor.execute(query, (user_id,))
            # user_data = cursor.fetchone()
            # cursor.close()
            async for conn in get_db_connection():  # get AsyncSession
                user_data = await execute_query(
                                    conn,
                                    """
                                        SELECT u.notion_user_id, d.database_id 
                                        FROM Users u
                                        LEFT JOIN DepartmentUser du ON u.user_id = du.user_id
                                        LEFT JOIN Departments d ON du.department_id = d.department_id
                                        WHERE u.user_id = :user_id;
                                    """,
                                    {"user_id": user_id},
                                    fetch_one=True
                )

            if user_data:
                notion_id = user_data.get('notion_user_id')
                department_database_id = user_data.get('database_id')
                if department_database_id:
                    await handle_chat(
                        thread_id=thread_id,
                        prompt=prompt,
                        agent_to_use=chatbot_supervisor_agent,
                        database_id=department_database_id,
                        current_user_id=notion_id
                    )
        except Exception as e:
            print(f"An error occurred during voice stream processing: {e}")

# ... (The rest of your file remains unchanged) ...
@router.get("/chat/{thread_id}", response_model=ChatHistoryResponse, tags=["Web Chat"])
async def get_chat_history(thread_id: str,user_id: str = Depends(get_current_user_id)):
    conn = get_db_connection()
    if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
    # cursor = conn.cursor(dictionary=True)
    # cursor.execute("SELECT message_id as id, author_type as role, content as text, IF(author_type='user', 'You', 'Bot') as 'from_' FROM Messages WHERE thread_id = %s ORDER BY created_at ASC", (thread_id,))
    # history = cursor.fetchall()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                history = await execute_query(
                                    conn,
                                    """
                                        SELECT message_id as id, author_type as role, content as text, IF(author_type='user', 'You', 'Bot') as 'from_' FROM Messages WHERE thread_id = :thread_id ORDER BY created_at ASC
                                    """,
                                    {"thread_id": thread_id},
                                    fetch_one=False
                )
    return ChatHistoryResponse(messages=history)

@router.get("/chats", response_model=List[ChatTitle], tags=["Web Chat"])
async def get_all_web_chat_titles(user_id: str = Depends(get_current_user_id)):
    try:
        conn = get_db_connection()
        if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
        # cursor = conn.cursor(dictionary=True)
        # cursor.execute("SELECT T.thread_id,T.title,T.created_at,T.type FROM Threads AS T JOIN UserThread AS UT ON T.thread_id = UT.thread_id WHERE T.type = %s && UT.user_id=%s;",('web',user_id,))
        # history = cursor.fetchall()
        # cursor.close()
        async for conn in get_db_connection():  # get AsyncSession
                history = await execute_query(
                                    conn,
                                    """
                                        SELECT T.thread_id,T.title,T.created_at,T.type FROM Threads AS T JOIN UserThread AS UT ON T.thread_id = UT.thread_id WHERE T.type = :type && UT.user_id=:user_id;
                                    """,
                                    {"type": 'web',"user_id":user_id},
                                    fetch_one=False
                )
        return history
    except Exception as e:
        print(e)
        return []

@router.get("/notifications/", response_model=List[Notification], tags=["Notifications"])
async def get_user_notifications(user_id:str = Depends(get_current_user_id)):
    """
    Retrieves all notifications for a given user based on their Notion ID (receiver_id).
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    # cursor = conn.cursor(dictionary=True)
    
    date = datetime.datetime.now()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_utc = now_utc + datetime.timedelta(hours=5,minutes=30)
    date = now_utc
    # query = """
    #     SELECT
    #         n.notification_id, n.sender_id, u.username AS sender_name,
    #         n.receiver_id, n.thread_id, n.title, n.is_read, n.is_archived,
    #         n.created_at, n.type
    #     FROM Notifications n LEFT JOIN Users u ON n.sender_id = u.notion_user_id
    #     WHERE n.receiver_id = %s AND n.created_at < %s
    #     ORDER BY n.created_at DESC;
    # """
    
    # cursor.execute(query, (user_id,date,))
    # notifications = cursor.fetchall()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                notifications  = await execute_query(
                                    conn,
                                    """
                                        SELECT
                                            n.notification_id, n.sender_id, u.username AS sender_name,
                                            n.receiver_id, n.thread_id, n.title, n.is_read, n.is_archived,
                                            n.created_at, n.type
                                        FROM Notifications n LEFT JOIN Users u ON n.sender_id = u.notion_user_id
                                        WHERE n.receiver_id = :receiver_id AND n.created_at < :created_at
                                        ORDER BY n.created_at DESC;
                                    """,
                                    {"receiver_id":user_id,"created_at":date},
                                    fetch_one=False
                )
    
    if not notifications:
        return []
        
    return notifications

@router.post("/whatsapp/chat/new", response_model=NewChatResponse, tags=["WhatsApp"])
async def start_new_whatsapp_chat(chat_title: str, type: str = "whatsapp",user_id: str = Depends(get_current_user_id)):
    thread_id = str(uuid.uuid4())
    # conn = get_db_connection()
    # if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
    # cursor = conn.cursor()
    # cursor.execute("INSERT INTO Threads (thread_id, title, type) VALUES (%s, %s, %s)", (thread_id, chat_title, type))
    # conn.commit()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                await execute_query(
                                    conn,
                                    """
                                        INSERT INTO Threads (thread_id, title, type) VALUES (:thread_id, :title, :type)
                                    """,
                                    {"thread_id":thread_id,"title":chat_title,"type":type},
                                    fetch_one=False
                )
    return NewChatResponse(thread_id=thread_id)

@router.post("/whatsapp/chat", response_model=ChatHistoryResponse, tags=["WhatsApp"])
async def chat_with_whatsapp_agent(request: WhatsAppChatRequest,user_id: str = Depends(get_current_user_id)):
    conn = get_db_connection()
    if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
    
    # user_thread_cursor = conn.cursor()
    # user_thread_cursor.execute("SELECT * FROM UserThread WHERE user_id = %s AND thread_id = %s", (request.user_id, request.thread_id))
    # if not user_thread_cursor.fetchone():
    #     user_thread_cursor.execute("INSERT INTO UserThread (user_id, thread_id) VALUES (%s, %s)", (request.user_id, request.thread_id))
    #     conn.commit()
    # user_thread_cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                await execute_query(
                                    conn,
                                    """
                                        INSERT INTO UserThread (user_id, thread_id) VALUES (:user_id,:thread_id)
                                    """,
                                    {"user_id":request.user_id,"thread_id":request.thread_id},
                                    fetch_one=False
                )

    # cursor = conn.cursor(dictionary=True)
    # query = "SELECT d.database_id FROM Departments d JOIN DepartmentUser du ON d.department_id = du.department_id WHERE du.user_id = %s;"
    # cursor.execute(query, (request.user_id,))
    # department_info = cursor.fetchone()
    async for conn in get_db_connection():  # get AsyncSession
                department_info = await execute_query(
                                    conn,
                                    """
                                        SELECT d.database_id FROM Departments d JOIN DepartmentUser du ON d.department_id = du.department_id WHERE du.user_id = :user_id;
                                    """,
                                    {"user_id":request.user_id},
                                    fetch_one=True
                )
    
    # query_notion_id = "SELECT notion_user_id FROM Users WHERE user_id= %s;"
    # cursor.execute(query_notion_id, (request.user_id,))
    # notion_id = cursor.fetchone()
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                notion_id = await execute_query(
                                    conn,
                                    """
                                        SELECT notion_user_id FROM Users WHERE user_id= %s;
                                    """,
                                    {"user_id":request.user_id},
                                    fetch_one=True
                )

    if not department_info or not department_info["database_id"]:
        raise HTTPException(status_code=404, detail=f"User '{request.user_id}' is not Assigned to a department with a Notion database ID.")
    
    department_database_id = department_info["database_id"]
    return await handle_chat(request.thread_id, request.message, whatsapp_supervisor_agent, department_database_id, notion_id)

@router.get("/whatsapp/chat/{thread_id}", response_model=ChatHistoryResponse, tags=["WhatsApp"])
async def get_whatsapp_chat_history(thread_id: str):
    return await get_chat_history(thread_id)

@router.get("/whatsapp/chats", response_model=List[ChatTitle], tags=["WhatsApp"],)
async def get_all_whatsapp_chat_titles():
    # conn = get_db_connection()
    try:
        # if not conn: raise HTTPException(status_code=500, detail="Database connection failed")
        # cursor = conn.cursor(dictionary=True)
        # cursor.execute("SELECT thread_id, title,title,created_at FROM Threads WHERE type = 'whatsapp'")
        # history = cursor.fetchall()
        # cursor.close()
        # return history
        async for conn in get_db_connection():  # get AsyncSession
                history = await execute_query(
                                    conn,
                                    """
                                        SELECT thread_id, title,title,created_at FROM Threads WHERE type = 'whatsapp';
                                    """,
                                    None,
                                    fetch_one=False
                )
        return history
    except Exception as e:
        return []

@router.post("/chat/archive/{thread_id}",tags=["Web Chat"])
async def archive_chat(thread_id:str):
    conn = None 
    try:
        conn = get_db_connection()
        if not conn:
           raise HTTPException(status_code=500, detail="Database connection failed")
        
        # cursor = conn.cursor()
        
        # update_query = "UPDATE `threads` SET `type` = 'archived' WHERE `thread_id` = %s;"
        # cursor.execute(update_query, (thread_id,))
        
        # if cursor.rowcount == 0:
        #     raise HTTPException(
        #         status_code=404,
        #         detail=f"Thread with ID '{thread_id}' not found."
        #     )
            
        # conn.commit()
        async for conn in get_db_connection():  # get AsyncSession
                history = await execute_query(
                                    conn,
                                    """
                                        UPDATE `threads` SET `type` = 'archived' WHERE `thread_id` = :thread_id;
                                    """,
                                    {"thread_id":thread_id},
                                    fetch_one=False
                )
        
        return {"status": "success", "message": "Thread archived successfully."}

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"An error occurred: {e}"
        )
    # finally:
    #     cursor.close()

@router.patch("/notifications/{notification_id}", tags=["Notifications"])
async def update_notification_status(
    notification_id: str,
    request: UpdateNotificationRequest,
    user_id: str = Depends(get_current_user_id),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    # cursor = conn.cursor()

    # query = """
    #     UPDATE Notifications
    #     SET is_read = %s
    #     WHERE notification_id = %s AND receiver_id = %s
    # """
    # cursor.execute(query, (request.is_read, notification_id, user_id))
    # conn.commit()

    # updated = cursor.rowcount
    # cursor.close()
    async for conn in get_db_connection():  # get AsyncSession
                updated = await execute_query(
                                    conn,
                                    """
                                        UPDATE Notifications
                                        SET is_read = :is_read
                                        WHERE notification_id = :notification_id AND receiver_id = :user_id
                                    """,
                                    {"is_read":request.is_read, "notification_id":notification_id, "user_id":user_id},
                                    fetch_one=False
                )

    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found or not owned by user")

    return {"notification_id": notification_id, "is_read": request.is_read}