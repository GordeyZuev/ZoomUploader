"""Declarative schedule schemas for automation jobs."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class ScheduleType(str, Enum):
    """Schedule type enumeration."""
    TIME_OF_DAY = "time_of_day"
    HOURS = "hours"
    WEEKDAYS = "weekdays"
    CRON = "cron"


class TimeOfDaySchedule(BaseModel):
    """Daily schedule at specific time."""
    type: Literal["time_of_day"]
    time: str = Field(pattern=r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$", description="Time in HH:MM format (e.g., 06:00)")
    timezone: str = Field(default="Europe/Moscow", description="Timezone (e.g., Europe/Moscow, UTC)")

    def to_cron(self) -> str:
        """Convert to cron expression."""
        hour, minute = self.time.split(":")
        return f"{minute} {hour} * * *"

    def human_readable(self) -> str:
        """Get human-readable description."""
        return f"Daily at {self.time}"


class HoursSchedule(BaseModel):
    """Periodic schedule every N hours."""
    type: Literal["hours"]
    hours: int = Field(ge=1, le=24, description="Run every N hours (1-24)")
    timezone: str = Field(default="Europe/Moscow", description="Timezone")

    def to_cron(self) -> str:
        """Convert to cron expression."""
        return f"0 */{self.hours} * * *"

    def human_readable(self) -> str:
        """Get human-readable description."""
        return f"Every {self.hours} hour(s)"


class WeekdaysSchedule(BaseModel):
    """Weekly schedule on specific days."""
    type: Literal["weekdays"]
    days: list[int] = Field(min_length=1, max_length=7, description="Days: 0=Monday, 1=Tuesday, ..., 6=Sunday")
    time: str = Field(pattern=r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$", description="Time in HH:MM format")
    timezone: str = Field(default="Europe/Moscow", description="Timezone")

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[int]) -> list[int]:
        """Validate and normalize days (0-6, Monday=0)."""
        if not all(0 <= day <= 6 for day in v):
            raise ValueError("Days must be 0-6 (0=Monday, 6=Sunday)")
        return sorted(set(v))

    def to_cron(self) -> str:
        """Convert to cron expression (cron uses 0=Sunday, so we adjust)."""
        hour, minute = self.time.split(":")
        days_cron = ",".join(str((d + 1) % 7) for d in self.days)
        return f"{minute} {hour} * * {days_cron}"

    def human_readable(self) -> str:
        """Get human-readable description."""
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days_str = ", ".join(day_names[d] for d in self.days)
        return f"Weekly on {days_str} at {self.time}"


class CronSchedule(BaseModel):
    """Custom cron expression schedule."""
    type: Literal["cron"]
    expression: str = Field(description="Cron expression (e.g., '0 6 * * *')")
    timezone: str = Field(default="Europe/Moscow", description="Timezone")

    def to_cron(self) -> str:
        """Return cron expression as-is."""
        return self.expression

    def human_readable(self) -> str:
        """Get human-readable description."""
        return f"Custom: {self.expression}"


Schedule = Annotated[
    TimeOfDaySchedule | HoursSchedule | WeekdaysSchedule | CronSchedule,
    Field(discriminator="type")
]

