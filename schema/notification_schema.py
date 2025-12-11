from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class Notification(BaseModel):
    # Change notification_id from int to str to match the UUID format from the database
    notification_id: str
    sender_id: str
    sender_name: Optional[str] = "System"
    receiver_id: str
    thread_id: Optional[str] = None
    title: str
    is_read: bool
    is_archived: bool
    created_at: datetime
    type: str

class UpdateNotificationRequest(BaseModel):
    is_read: bool

class UpdateArchiveNotificationRequest(BaseModel):
    is_archived: bool