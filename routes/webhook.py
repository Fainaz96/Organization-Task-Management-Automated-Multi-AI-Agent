# routes/webhook.py

import asyncio
import codecs
import json
import os
import logging
import uuid
import io

from fastapi import (
    APIRouter, HTTPException, Request, Response, status, BackgroundTasks, 
    Query as FastapiQuery, Form, File, UploadFile
)
from db import get_db_connection
from services.chat_handler import handle_chat
from utils.db_helper import execute_query
from utils.phone_number_utils import get_current_datetime_in_timezone, get_timezones_for_phone
from utils.whatsapp_utils import send_whatsapp_message, get_whatsapp_media_bytes # Import the new function
import datetime
from local_agents.notion_whatsapp_supervisor_agent import whatsapp_supervisor_agent
from openai import OpenAI
from pydub import AudioSegment

router = APIRouter()
logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
client = OpenAI()

INACTIVITY_TIMEOUT_HOURS = 6

async def transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """A helper function to transcribe audio bytes using OpenAI."""
    try:
        audio_buffer = io.BytesIO(audio_bytes)
        
        # --- THIS IS THE FIX ---
        # Rewind the buffer to the beginning before passing it to pydub.
        audio_buffer.seek(0)
        # -----------------------
        
        # Determine format. WhatsApp is typically 'ogg'. Uploaded files can vary.
        # Pydub can often infer the format, but being explicit is safer.
        # We will let pydub infer for now, as it's more flexible for the test endpoint.
        audio = AudioSegment.from_file(audio_buffer)
        
        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        wav_buffer.name = "input.wav"

        transcription = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=wav_buffer,
            response_format="text"
        )
        logger.info(f"Transcription successful. Text: '{transcription}'")
        return transcription
    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        return ""

async def handlemessage(from_number: str, message_body: str):
    # This entire function for handling the agent logic remains unchanged.
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    async for conn in get_db_connection():  # get AsyncSession
        user_data = await execute_query(
            conn,
            "SELECT user_id, notion_user_id FROM Users WHERE phone_number = :phone_number",
            {"phone_number": from_number},
            fetch_one=True
        )
    # cursor = conn.cursor(dictionary=True)
    
    # query_notion_id = "SELECT user_id, notion_user_id FROM Users WHERE phone_number = %s;"
    # cursor.execute(query_notion_id, (from_number,))
    # user_data = cursor.fetchone()
    # cursor.close()
    if not user_data:
        logger.warning(f"WhatsApp number {from_number} not found in Users table.")
        return "Sorry, your number is not registered with our service."
        
    user_id = user_data['user_id']
    notion_id = user_data['notion_user_id']
    
    # query_last_thread = """
    #     SELECT t.thread_id, t.created_at
    #     FROM Threads t JOIN UserThread ut ON t.thread_id = ut.thread_id
    #     WHERE ut.user_id = %s AND t.type = 'whatsapp'
    #     ORDER BY t.created_at DESC LIMIT 1;
    # """
    # cursor = conn.cursor()
    # cursor.execute(query_last_thread, (user_id,))
    # last_thread = cursor.fetchone()
    # cursor.close()
    # print(last_thread)
    async for conn in get_db_connection():  # get AsyncSession
        last_thread = await execute_query(
            conn,
            """
            SELECT t.thread_id, t.created_at
            FROM Threads t JOIN UserThread ut ON t.thread_id = ut.thread_id
            WHERE ut.user_id = :user_id AND t.type = 'whatsapp'
            ORDER BY t.created_at DESC LIMIT 1;
            """,
            {"user_id": user_id},
            fetch_one=True
        )
    thread_id = None
    if last_thread:
        # cursor = conn.cursor()
        # query_last_message_time = "SELECT created_at FROM Messages WHERE thread_id = %s ORDER BY created_at DESC LIMIT 1;"
        # cursor.execute(query_last_message_time, (last_thread[0],))
        # last_message = cursor.fetchone()
        # print(last_message)
        # cursor.close()
        print(last_thread)
        async for conn in get_db_connection():  # get AsyncSession
            last_message = await execute_query(
                conn,
                """
                SELECT created_at FROM Messages WHERE thread_id = :thread_id ORDER BY created_at DESC LIMIT 1;
                """,
                {"thread_id": last_thread['thread_id']},
                fetch_one=True
            )
        
        time_limit = datetime.datetime.now() - datetime.timedelta(hours=INACTIVITY_TIMEOUT_HOURS)
        
        if last_message and last_message['created_at'] > time_limit:
            thread_id = last_thread['thread_id']
            logger.info(f"Continuing recent thread for {from_number}: {thread_id}")
    # cursor = conn.cursor()
    if thread_id is None:
        new_thread_obj = client.beta.threads.create()
        thread_id = new_thread_obj.id
        
        # cursor.execute("INSERT INTO Threads (thread_id, title, type) VALUES (%s, %s, %s)", (thread_id, f"Whatsapp+{from_number}", "whatsapp"))
        # cursor.execute("INSERT INTO UserThread (user_id, thread_id) VALUES (%s, %s)", (user_id, thread_id))
        # conn.commit()
        # logger.info(f"Created new thread for {from_number} due to inactivity: {thread_id}")
        async for conn in get_db_connection():  # get AsyncSession
            await execute_query(
                conn,
                """
                INSERT INTO Threads (thread_id, title, type) VALUES (:thread_id, :title, :type);
                """,
                {"thread_id": thread_id,"title":f"Whatsapp+{from_number}","type":"whatsapp"},
                fetch_one=False
            )
            await execute_query(
                conn,
                """
               INSERT INTO UserThread (user_id, thread_id) VALUES (:user_id, :thread_id)
                """,
                {"user_id":user_id,"thread_id": thread_id},
                fetch_one=False
            )

    # cursor.close()
    
    department_database_id = os.environ["NOTION_TASKS_DATABASE_ID"]
    target_user_timezone = get_timezones_for_phone(
            f"+{from_number}"
        )
    datetime_in_target_user_timezone = get_current_datetime_in_timezone(
            target_user_timezone[0]
    )
    print(datetime_in_target_user_timezone.date())
    chat = await handle_chat(thread_id, message_body, whatsapp_supervisor_agent, department_database_id, notion_id,datetime_in_target_user_timezone)
    
    processed_text = chat.messages[-1].text
    return processed_text

@router.get("/webhook")
def verify_webhook(mode: str = FastapiQuery(None, alias="hub.mode"), token: str = FastapiQuery(None, alias="hub.verify_token"), challenge: str = FastapiQuery(None, alias="hub.challenge")):
    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("WEBHOOK_VERIFIED")
            return Response(content=challenge, status_code=200)
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return Response(status_code=status.HTTP_400_BAD_REQUEST)

@router.post("/test")
async def test_text(from_number:str, msg_body:str):
    """Test endpoint for sending TEXT messages."""
    ai_response = await handlemessage(from_number, msg_body)
    return ai_response

# --- ADD THIS NEW ENDPOINT FOR VOICE TESTING ---
@router.post("/test/voice")
async def test_voice(from_number: str = Form(...), file: UploadFile = File(...)):
    """Test endpoint for sending VOICE messages by uploading a file."""
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Please upload an audio file.")
    
    audio_bytes = await file.read()
    transcribed_text = await transcribe_audio_bytes(audio_bytes)
    
    if not transcribed_text:
        return "Could not understand the audio. Please try again."
        
    ai_response = await handlemessage(from_number, transcribed_text)
    return codecs.decode(ai_response, 'unicode_escape')

# --- MODIFY THIS MAIN WEBHOOK HANDLER ---
@router.post("/webhook")
async def handle_webhook(request: Request,background_tasks: BackgroundTasks):
    body = await request.json()
    logger.info(f"Incoming webhook message: {json.dumps(body, indent=2)}")

    if body.get("object") != "whatsapp_business_account":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        return Response(status_code=200)

    if "statuses" in value:
        status_data = value["statuses"][0]
        logger.info(f"Status update for {status_data['id']}: {status_data['status']}")
        return Response(status_code=200)

    if "messages" in value:
        message_entry = value["messages"][0]
        from_number = message_entry["from"]
        
        message_body = ""
        
        # Handle TEXT messages (existing logic)
        if message_entry.get("type") == "text":
            message_body = message_entry["text"]["body"]
        
        # Handle AUDIO messages (new logic)
        elif message_entry.get("type") == "audio":
            logger.info(f"Received audio message from {from_number}")
            audio_id = message_entry["audio"]["id"]
            audio_bytes = await get_whatsapp_media_bytes(audio_id)
            if audio_bytes:
                message_body = await transcribe_audio_bytes(audio_bytes)
            else:
                message_body = "Failed to process the received audio."
        
        # If we have a message body from either text or audio, process it.
        if message_body:
            # ai_response = await handlemessage(from_number, message_body)
            # await send_whatsapp_message(from_number, ai_response)
            background_tasks.add_task(process_message, from_number, message_body) 
    return Response(status_code=200)


async def process_message(from_number: str, msg_body: str):   
    ai_response = await handlemessage(from_number, msg_body)
    await send_whatsapp_message(from_number, ai_response)