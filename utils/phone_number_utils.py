from datetime import datetime
import phonenumbers
from phonenumbers import geocoder, timezone
from phonenumbers.phonenumberutil import NumberParseException
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def get_timezones_for_phone(phone_number_str: str) -> tuple:
    """
    Infers possible timezones for a given phone number.

    Args:
        phone_number_str: The phone number as a string, preferably in
                          international E.164 format (e.g., "+14155552671").

    Returns:
        A tuple of possible timezone names (e.g., ('America/New_York',))
        or an empty tuple if the number is invalid or has no timezone info.
    
    IMPORTANT: For countries with multiple timezones like the US, this will
    return a list of ALL possible timezones for that country.
    """
    try:
        # Parse the phone number string.
        # This will raise a NumberParseException if the number is not valid.
        parsed_number = phonenumbers.parse(phone_number_str)

        # Check if the number is a valid phone number.
        if not phonenumbers.is_valid_number(parsed_number):
            print(f"Warning: '{phone_number_str}' is not a valid phone number.")
            return ()

        # Get the timezone(s) for the number.
        # This returns a tuple of strings.
        print(parsed_number)
        timezones = timezone.time_zones_for_number(parsed_number)
        return timezones

    except NumberParseException as e:
        print(f"Error parsing phone number '{phone_number_str}': {e}")
        return ()
    
def get_current_datetime_in_timezone(timezone_name: str) -> datetime | None:
    """
    Gets the current date and time for a specific IANA timezone name.

    Args:
        timezone_name: A valid IANA timezone string (e.g., "America/New_York").

    Returns:
        A timezone-aware datetime object for the current time in that zone,
        or None if the timezone name is invalid.
    """
    try:
        # Get the timezone object from the string name
        target_tz = ZoneInfo(timezone_name)
        
        # 1. Get the current time in UTC (this is the reliable starting point)
        utc_now = datetime.now(ZoneInfo("UTC"))
        
        # 2. Convert the UTC time to the target timezone
        local_time = utc_now.astimezone(target_tz)
        
        return local_time

    except ZoneInfoNotFoundError:
        print(f"Error: The timezone '{timezone_name}' is not a valid timezone.")
        return None