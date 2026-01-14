"""Schedule conversion and validation helpers"""

from datetime import datetime

import pytz
from croniter import croniter

from api.schemas.automation.schedule import CronSchedule, HoursSchedule, TimeOfDaySchedule, WeekdaysSchedule


def validate_min_interval(cron_expression: str, min_hours: int = 1) -> bool:
    """
    Validate that cron runs at least every min_hours.

    Args:
        cron_expression: Cron expression to validate
        min_hours: Minimum interval in hours

    Returns:
        True if interval is valid (>= min_hours)
    """
    try:
        base = datetime.now()
        cron = croniter(cron_expression, base)
        next_run = cron.get_next(datetime)
        following_run = cron.get_next(datetime)
        interval_hours = (following_run - next_run).total_seconds() / 3600
        return interval_hours >= min_hours
    except Exception:
        return False


def get_next_run_time(cron_expression: str, timezone_str: str) -> datetime:
    """
    Calculate next run time for cron expression in given timezone.

    Args:
        cron_expression: Cron expression
        timezone_str: Timezone string (e.g., 'Europe/Moscow')

    Returns:
        Next run datetime in UTC
    """
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    cron = croniter(cron_expression, now)
    next_run = cron.get_next(datetime)
    return next_run.astimezone(pytz.UTC) if next_run.tzinfo else pytz.UTC.localize(next_run)


def schedule_to_cron(schedule: dict) -> tuple[str, str]:
    """
    Convert schedule dict to (cron_expression, human_readable).

    Args:
        schedule: Schedule configuration dict

    Returns:
        Tuple of (cron_expression, human_readable_description)

    Raises:
        ValueError: If schedule type is unknown
    """
    schedule_type = schedule.get("type")

    if schedule_type == "time_of_day":
        obj = TimeOfDaySchedule(**schedule)
    elif schedule_type == "hours":
        obj = HoursSchedule(**schedule)
    elif schedule_type == "weekdays":
        obj = WeekdaysSchedule(**schedule)
    elif schedule_type == "cron":
        obj = CronSchedule(**schedule)
    else:
        raise ValueError(f"Unknown schedule type: {schedule_type}")

    return obj.to_cron(), obj.human_readable()


def validate_cron_expression(expression: str) -> bool:
    """
    Validate cron expression syntax.

    Args:
        expression: Cron expression to validate

    Returns:
        True if valid
    """
    try:
        croniter(expression)
        return True
    except Exception:
        return False

