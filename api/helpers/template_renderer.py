"""Template renderer for upload metadata"""

import re
from datetime import datetime


class TemplateRenderer:
    """Renders templates with variable substitution and flexible topics formatting."""

    @staticmethod
    def render(template: str, context: dict, topics_display: dict | None = None) -> str:
        """
        Render template with context variables.

        Supports variable substitution with optional formatting:
        - Simple: {var_name}
        - With format: {var_name:format}

        Time format examples:
        - {publish_time:DD-MM-YY hh:mm}
        - {record_time:date}
        - {record_time:time}
        - {publish_time:YYYY-MM-DD}

        Args:
            template: Template string with {variable} or {variable:format} placeholders
            context: Dict with variable values
            topics_display: Optional topics display configuration

        Returns:
            Rendered string with substituted values

        Example:
            >>> render("{display_name} - {publish_time:DD.MM.YYYY}", {"display_name": "Test", "publish_time": datetime(2026,1,11)})
            "Test - 11.01.2026"
        """
        if not template:
            return ""

        # Pattern to match {variable} or {variable:format}
        pattern = r"\{([^{}:]+)(?::([^{}]+))?\}"

        def replace_placeholder(match):
            var_name = match.group(1)
            format_spec = match.group(2)  # Can be None

            if var_name not in context:
                return match.group(0)  # Keep original if variable not found

            value = context[var_name]

            # Apply format if specified
            if format_spec and isinstance(value, datetime):
                return TemplateRenderer._format_datetime(value, format_spec)
            return TemplateRenderer._format_value(value)

        return re.sub(pattern, replace_placeholder, template)

    @staticmethod
    def _format_value(value) -> str:
        """Format value for template substitution (default format)."""
        if value is None:
            return ""

        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")

        if isinstance(value, list):
            # Join list items with comma
            return ", ".join(str(item) for item in value if item)

        if isinstance(value, dict):
            # For dict, just return empty (not supported in simple templates)
            return ""

        return str(value)

    @staticmethod
    def _format_datetime(dt: datetime, format_spec: str) -> str:
        """
        Format datetime with custom format specification.

        Supports:
        - 'date' - only date (YYYY-MM-DD)
        - 'time' - only time (HH:MM)
        - Custom format string with replacements:
          - DD - day (01-31)
          - MM - month (01-12)
          - YY - year 2-digit (26)
          - YYYY - year 4-digit (2026)
          - hh - hour (00-23)
          - mm - minute (00-59)
          - ss - second (00-59)

        Args:
            dt: datetime object
            format_spec: format specification

        Returns:
            Formatted datetime string

        Examples:
            >>> _format_datetime(datetime(2026, 1, 11, 14, 30), "DD-MM-YY hh:mm")
            "11-01-26 14:30"
            >>> _format_datetime(datetime(2026, 1, 11, 14, 30), "date")
            "2026-01-11"
        """
        if format_spec == "date":
            return dt.strftime("%Y-%m-%d")
        if format_spec == "time":
            return dt.strftime("%H:%M")
        if format_spec == "datetime":
            return dt.strftime("%Y-%m-%d %H:%M")

        # Custom format with replacements
        result = format_spec
        replacements = {
            "YYYY": dt.strftime("%Y"),
            "YY": dt.strftime("%y"),
            "MM": dt.strftime("%m"),
            "DD": dt.strftime("%d"),
            "hh": dt.strftime("%H"),
            "mm": dt.strftime("%M"),
            "ss": dt.strftime("%S"),
        }

        # Replace in order (longest first to avoid conflicts)
        for key in sorted(replacements.keys(), key=len, reverse=True):
            result = result.replace(key, replacements[key])

        return result

    @staticmethod
    def _format_topics_list(topics: list[str] | list[dict], config: dict) -> str:
        """
        Format topics list according to configuration.

        Args:
            topics: List of topic strings or dicts with {topic, start, end}
            config: topics_display configuration dict

        Returns:
            Formatted topics string

        Example config:
            {
                "enabled": true,
                "max_count": 10,
                "min_length": 5,
                "max_length": 100,
                "format": "numbered_list",  # numbered_list, bullet_list, dash_list, comma_separated, inline
                "separator": "\n",
                "prefix": "Темы:",
                "show_timestamps": true  # Show timestamps if available
            }
        """
        if not config.get("enabled", True) or not topics:
            return ""

        show_timestamps = config.get("show_timestamps", True)

        # Normalize topics to list of dicts
        normalized_topics = []
        for item in topics:
            if isinstance(item, dict):
                normalized_topics.append(item)
            else:
                # String topic without timestamp
                normalized_topics.append({"topic": str(item), "start": None, "end": None})

        # Filter topics by length
        min_length = config.get("min_length", 0)
        max_length = config.get("max_length", 1000)
        filtered_topics = [t for t in normalized_topics if min_length <= len(t.get("topic", "")) <= max_length]

        # Limit count (None = unlimited)
        max_count = config.get("max_count", 10)
        if max_count is not None:
            filtered_topics = filtered_topics[:max_count]

        if not filtered_topics:
            return ""

        # Format topics
        format_type = config.get("format", "numbered_list")
        separator = config.get("separator", "\n")

        def format_topic_item(topic_dict: dict) -> str:
            """Format single topic with optional timestamp."""
            topic_text = topic_dict.get("topic", "")
            start = topic_dict.get("start")

            if show_timestamps and start is not None:
                # Format timestamp as HH:MM:SS
                timestamp = TemplateRenderer._format_seconds_to_timestamp(start)
                return f"{timestamp} — {topic_text}"
            return topic_text

        if format_type == "numbered_list":
            formatted = separator.join(
                f"{i + 1}. {format_topic_item(topic)}" for i, topic in enumerate(filtered_topics)
            )
        elif format_type == "bullet_list":
            formatted = separator.join(f"• {format_topic_item(topic)}" for topic in filtered_topics)
        elif format_type == "dash_list":
            formatted = separator.join(f"- {format_topic_item(topic)}" for topic in filtered_topics)
        elif format_type == "comma_separated":
            formatted = ", ".join(format_topic_item(topic) for topic in filtered_topics)
        elif format_type == "inline":
            formatted = " | ".join(format_topic_item(topic) for topic in filtered_topics)
        else:
            # Default: numbered list
            formatted = separator.join(
                f"{i + 1}. {format_topic_item(topic)}" for i, topic in enumerate(filtered_topics)
            )

        # Add prefix if specified
        prefix = config.get("prefix", "")
        if prefix:
            formatted = f"{prefix}{separator}{formatted}"

        return formatted

    @staticmethod
    def _format_seconds_to_timestamp(seconds: float) -> str:
        """
        Format seconds to HH:MM:SS timestamp.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted timestamp string (HH:MM:SS)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def prepare_recording_context(recording, topics_display: dict | None = None) -> dict:
        """
        Prepare context dict from recording object.

        Available variables:
        - {display_name} - recording name
        - {record_time} - recording start time (datetime)
        - {publish_time} - current time (datetime)
        - {duration} - recording duration
        - {themes} - short topics for title (from main_topics)
        - {topics} - detailed formatted topics for description (from topic_timestamps)

        Time formatting examples:
        - {record_time:DD.MM.YYYY}
        - {publish_time:date}
        - {record_time:time}

        Args:
            recording: Recording model instance
            topics_display: Optional topics display configuration for {topics}

        Returns:
            Dict with template variables
        """
        from logger import get_logger

        logger = get_logger()

        # Basic info
        context = {
            "display_name": recording.display_name or "Recording",
            "duration": getattr(recording, "duration", ""),
            "record_time": recording.start_time,  # datetime object for formatting
            "publish_time": datetime.utcnow(),  # current time
        }

        # Themes - short topics for title (from main_topics)
        if hasattr(recording, "main_topics") and recording.main_topics:
            # Join first 3 topics with comma for title
            context["themes"] = ", ".join(recording.main_topics[:3])
        else:
            context["themes"] = ""

        # Topics - detailed formatted topics for description (from topic_timestamps)
        topics_for_description = []
        if hasattr(recording, "topic_timestamps") and recording.topic_timestamps:
            # Use topic_timestamps directly (list of dicts with topic, start, end)
            topics_for_description = recording.topic_timestamps
            logger.info(f"[TemplateRenderer] Using {len(topics_for_description)} detailed topics from topic_timestamps")
        elif hasattr(recording, "main_topics") and recording.main_topics:
            # Fallback to main_topics if topic_timestamps not available (list of strings)
            topics_for_description = recording.main_topics
            logger.info(f"[TemplateRenderer] Using main_topics fallback: {len(topics_for_description)} topics")

        # Format topics for description
        if topics_for_description:
            if topics_display:
                logger.info(
                    f"[TemplateRenderer] Formatting {len(topics_for_description)} topics with config: {topics_display}"
                )
                context["topics"] = TemplateRenderer._format_topics_list(topics_for_description, topics_display)
                logger.info(f"[TemplateRenderer] Formatted topics length: {len(context['topics'])} chars")
            # Default formatting (handle both dict and string topics)
            elif topics_for_description and isinstance(topics_for_description[0], dict):
                context["topics"] = "\n".join(
                    f"{i + 1}. {item['topic']}" for i, item in enumerate(topics_for_description[:10])
                )
            else:
                context["topics"] = "\n".join(
                    f"{i + 1}. {topic}" for i, topic in enumerate(topics_for_description[:10])
                )
        else:
            context["topics"] = ""

        return context
