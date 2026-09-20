"""When a scheduled thing next runs, in words."""


def format_next_run_time(iso_time_str: str) -> str:
    """
    Format ISO datetime string to human readable relative time.

    Generic utility that can be used by any component card/modal to display
    upcoming execution times in a user-friendly format.

    Args:
        iso_time_str: ISO 8601 formatted datetime string (with or without timezone)

    Returns:
        Human-readable relative time string ("in 2h", "in 3d", "Past due", etc.)
        Returns "Unknown" if parsing fails or input is empty
    """
    from datetime import UTC, datetime

    from app.core.log import logger

    if not iso_time_str:
        return "Unknown"

    try:
        # Handle both timezone-aware and naive datetimes
        if iso_time_str.endswith("Z"):
            next_run = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
        elif "+" in iso_time_str or iso_time_str.endswith("00:00"):
            next_run = datetime.fromisoformat(iso_time_str)
        else:
            # Assume UTC if no timezone info
            next_run = datetime.fromisoformat(iso_time_str).replace(tzinfo=UTC)

        now = datetime.now(UTC)

        # Make sure both datetimes are timezone-aware
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        delta = next_run - now
        total_seconds = delta.total_seconds()

        if total_seconds < 0:
            return "Past due"
        elif total_seconds < 60:
            return f"in {int(total_seconds)}s"
        elif total_seconds < 3600:
            minutes = int(total_seconds / 60)
            return f"in {minutes}m"
        elif total_seconds < 86400:
            hours = total_seconds / 3600
            if hours < 2:
                return f"in {hours:.1f}h"
            else:
                return f"in {int(hours)}h"
        else:
            days = int(total_seconds / 86400)
            return f"in {days}d"
    except Exception as e:
        logger.debug(f"Failed to format next run time '{iso_time_str}': {e}")
        return "Unknown"


def format_schedule_human_readable(schedule: str) -> str:
    """
    Convert schedule format to human readable description.

    Generic utility that can be used by any component card/modal to display
    scheduling patterns in a user-friendly format.

    Args:
        schedule: Schedule string (typically from APScheduler or similar)

    Returns:
        Human-readable schedule description ("Daily at 2:00 AM UTC", etc.)
        Returns original schedule string if no pattern matches
        Returns "Unknown schedule" for empty/invalid input
    """
    import re

    from app.core.log import logger

    if not schedule or "Unknown" in schedule:
        return "Unknown schedule"

    # Handle common cron patterns
    if "hour=2, minute=0, second=0" in schedule:
        return "Daily at 2:00 AM UTC"
    elif "hour=" in schedule and "minute=" in schedule:
        # Extract hour and minute from the schedule string
        try:
            hour_match = re.search(r"hour=([0-9]+)", schedule)
            minute_match = re.search(r"minute=([0-9]+)", schedule)
            if hour_match and minute_match:
                hour = int(hour_match.group(1))
                minute = int(minute_match.group(1))
                time_str = f"{hour:02d}:{minute:02d}"
                return f"Daily at {time_str} UTC"
        except Exception as e:
            logger.debug(f"Failed to parse schedule pattern '{schedule}': {e}")

    # Fallback to original schedule
    return schedule
