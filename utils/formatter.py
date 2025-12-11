from typing import List, Dict, Any
from schema.chat_schema import Message

def format_db_rows_for_response(db_rows: List[Dict[str, Any]]) -> List[Message]:
    formatted_messages = []
    for row in db_rows:
        sender = "You" if row['author_type'] == "user" else "Bot"
        formatted_messages.append(Message(from_=sender, text=row['content'], id=row['message_id']))
    return formatted_messages