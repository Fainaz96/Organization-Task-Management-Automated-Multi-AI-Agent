from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class NewChatRequest(BaseModel):
    chat_title: str
    user_id: str
    type: str = "web"

class NewChatResponse(BaseModel):
    thread_id: str

class ChatRequest(BaseModel):
    thread_id: str
    message: str
    # user_id: str

class Message(BaseModel):
    from_: str
    text: str
    id: Optional[str] = None

class ChatHistoryResponse(BaseModel):
    messages: List[Message]

class ChatTitle(BaseModel):
    thread_id: str
    title: str
    type:str
    created_at: datetime

class WhatsAppChatRequest(BaseModel):
    thread_id: str
    message: str
    user_id: str

class Notification(BaseModel):
    # Change notification_id from int to str to match the UUID format from the database
    notification_id: str
    sender_id: str
    sender_name: Optional[str] = "System"
    receiver_id: str
    thread_id: Optional[str] = None
    title: str
    is_read: bool
    created_at: datetime