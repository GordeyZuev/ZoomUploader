"""Template renderer for upload metadata with flexible topics formatting."""

from datetime import datetime


class TemplateRenderer:
    """Renders templates with variable substitution and flexible topics formatting."""

    @staticmethod
    def render(template: str, context: dict, topics_display: dict | None = None) -> str:
        """
        Render template with context variables.

        Supports simple variable substitution: {var_name}

        Args:
            template: Template string with {variable} placeholders
            context: Dict with variable values
            topics_display: Optional topics display configuration

        Returns:
            Rendered string with substituted values

        Example:
            >>> render("{display_name} - {start_time}", {"display_name": "Test", "start_time": "2026-01-08"})
            "Test - 2026-01-08"
        """
        if not template:
            return ""

        # Note: topics_list is already prepared in prepare_recording_context()
        # with topic_timestamps (detailed topics) or main_topics (fallback)
        # No need to override it here

        result = template
        for key, value in context.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                # Convert value to string
                str_value = TemplateRenderer._format_value(value)
                result = result.replace(placeholder, str_value)

        return result

    @staticmethod
    def _format_value(value) -> str:
        """Format value for template substitution."""
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
    def _format_topics_list(topics: list[str], config: dict) -> str:
        """
        Format topics list according to configuration.

        Args:
            topics: List of topic strings
            config: topics_display configuration dict

        Returns:
            Formatted topics string

        Example config:
            {
                "enabled": true,
                "max_count": 10,
                "min_length": 5,
                "max_length": 100,
                "format": "numbered_list",
                "separator": "\n",
                "prefix": "Темы:",
                "include_timestamps": false
            }
        """
        if not config.get("enabled", True) or not topics:
            return ""

        # Filter topics by length
        min_length = config.get("min_length", 0)
        max_length = config.get("max_length", 1000)
        filtered_topics = [
            t for t in topics
            if min_length <= len(t) <= max_length
        ]

        # Limit count (None = unlimited)
        max_count = config.get("max_count", 10)
        if max_count is not None:
            filtered_topics = filtered_topics[:max_count]

        if not filtered_topics:
            return ""

        # Format topics
        format_type = config.get("format", "numbered_list")
        separator = config.get("separator", "\n")

        if format_type == "numbered_list":
            formatted = separator.join(
                f"{i+1}. {topic}" for i, topic in enumerate(filtered_topics)
            )
        elif format_type == "bullet_list":
            formatted = separator.join(
                f"• {topic}" for topic in filtered_topics
            )
        elif format_type == "dash_list":
            formatted = separator.join(
                f"- {topic}" for topic in filtered_topics
            )
        elif format_type == "comma_separated":
            formatted = ", ".join(filtered_topics)
        elif format_type == "inline":
            formatted = " | ".join(filtered_topics)
        else:
            # Default: numbered list
            formatted = separator.join(
                f"{i+1}. {topic}" for i, topic in enumerate(filtered_topics)
            )

        # Add prefix if specified
        prefix = config.get("prefix", "")
        if prefix:
            formatted = f"{prefix}{separator}{formatted}"

        return formatted

    @staticmethod
    def prepare_recording_context(recording, topics_display: dict | None = None) -> dict:
        """
        Prepare context dict from recording object.

        Args:
            recording: Recording model instance
            topics_display: Optional topics display configuration

        Returns:
            Dict with template variables
        """
        context = {
            "display_name": recording.display_name or "Recording",
            "start_time": recording.start_time,
            "title": recording.display_name or "",  # Alias for backward compatibility
            "duration": getattr(recording, "duration", ""),
        }

        # Add date variants
        if recording.start_time:
            context["date"] = recording.start_time.strftime("%Y-%m-%d")
            context["date_time"] = recording.start_time.strftime("%Y-%m-%d %H:%M")
        else:
            context["date"] = ""
            context["date_time"] = ""

        # Add main_topics if available
        if hasattr(recording, "main_topics") and recording.main_topics:
            context["main_topics"] = recording.main_topics

            # First topic as singular
            context["topic"] = recording.main_topics[0] if recording.main_topics else ""

            # Simple comma-separated (first 5)
            context["topics"] = ", ".join(recording.main_topics[:5])
        else:
            context["main_topics"] = []
            context["topic"] = ""
            context["topics"] = ""

        # Prefer topic_timestamps (detailed topics) over main_topics for topics_list
        topics_for_list = []
        if hasattr(recording, "topic_timestamps") and recording.topic_timestamps:
            # Extract topic strings from topic_timestamps
            topics_for_list = [item["topic"] for item in recording.topic_timestamps if isinstance(item, dict) and "topic" in item]
            # DEBUG
            from logger import get_logger
            logger = get_logger()
            logger.info(f"[TemplateRenderer] Extracted {len(topics_for_list)} topics from topic_timestamps")
            if topics_for_list:
                logger.info(f"[TemplateRenderer] First topic: {topics_for_list[0][:50]}...")
                logger.info(f"[TemplateRenderer] Last topic: {topics_for_list[-1][:50]}...")
        elif hasattr(recording, "main_topics") and recording.main_topics:
            # Fallback to main_topics if topic_timestamps not available
            topics_for_list = recording.main_topics
            from logger import get_logger
            logger = get_logger()
            logger.info(f"[TemplateRenderer] Using main_topics fallback: {len(topics_for_list)} topics")

        # Format topics_list
        if topics_for_list:
            if topics_display:
                from logger import get_logger
                logger = get_logger()
                logger.info(f"[TemplateRenderer] Formatting {len(topics_for_list)} topics with config: {topics_display}")
                context["topics_list"] = TemplateRenderer._format_topics_list(
                    topics_for_list,
                    topics_display
                )
                logger.info(f"[TemplateRenderer] Formatted topics_list length: {len(context['topics_list'])} chars")
                logger.info(f"[TemplateRenderer] Formatted topics_list preview: {context['topics_list'][:200]}...")
            else:
                # Default formatting
                context["topics_list"] = "\n".join(
                    f"{i+1}. {topic}" for i, topic in enumerate(topics_for_list[:10])
                )
        else:
            context["topics_list"] = ""

        # Add summary if available
        if hasattr(recording, "summary") and recording.summary:
            context["summary"] = recording.summary
        else:
            context["summary"] = ""

        return context

