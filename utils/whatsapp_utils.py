# utils/whatsapp_utils.py

import os
import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# --- ADD THIS NEW FUNCTION ---
async def get_whatsapp_media_bytes(media_id: str) -> bytes | None:
    """
    Downloads media (like an audio file) from WhatsApp's servers.
    
    Args:
        media_id: The ID of the media to download.

    Returns:
        The raw bytes of the media file, or None if an error occurs.
    """
    # Step 1: Get the media URL from the media ID
    url_step1 = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    media_url = ""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url_step1, headers=headers)
            response.raise_for_status()
            media_url = response.json().get("url")
            if not media_url:
                logger.error(f"Could not retrieve media URL for media_id: {media_id}")
                return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error getting media URL: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting media URL: {e}")
        return None

    # Step 2: Download the actual media file from the URL
    try:
        async with httpx.AsyncClient() as client:
            download_response = await client.get(media_url, headers=headers)
            download_response.raise_for_status()
            return download_response.content
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error downloading media file: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading media file: {e}")
        return None

# --- YOUR EXISTING send_whatsapp_message FUNCTION REMAINS UNCHANGED ---
async def send_whatsapp_message(to_number: str, message: str):
    """
    Sends a message to a WhatsApp number. If the message exceeds the
    4096 character limit, it is automatically split into multiple,
    numbered messages.
    """
    # (Your existing code for this function is perfect, no changes needed)
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    if len(message) <= 4070:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message},
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info(f"WhatsApp API response (single message): {response.json()}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending single message: {e.response.text}")
        except Exception as e:
            logger.error(f"Unexpected error sending single message: {e}")
        return

    logger.info(f"Message is too long ({len(message)} chars). Splitting into multiple parts.")
    
    chunk_size = 4070 - 15
    parts = [message[i:i + chunk_size] for i in range(0, len(message), chunk_size)]
    total_parts = len(parts)

    async with httpx.AsyncClient() as client:
        for i, part in enumerate(parts):
            part_number = i + 1
            part_message = f"({part_number}/{total_parts}) {part}"
            
            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "text",
                "text": {"body": part_message},
            }
            
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info(f"Sent part {part_number}/{total_parts} to {to_number}")
                
                if part_number < total_parts:
                    await asyncio.sleep(0.75)
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error sending part {part_number}/{total_parts}: {e.response.text}")
                break 
            except Exception as e:
                logger.error(f"Unexpected error sending part {part_number}/{total_parts}: {e}")
                break