"""Recording filter schemas"""

from pydantic import BaseModel, Field


class RecordingFilters(BaseModel):
    """
    Filters for bulk operations over recordings.

    Supports filtering by various criteria for automatic selection of records.
    """

    # Connections
    template_id: int | None = Field(None, description="Filter by template ID")
    source_id: int | None = Field(None, description="Filter by source ID")

    # Statuses (multiple selection)
    status: list[str] | None = Field(None, description="Filter by statuses (list)")

    # Flags
    is_mapped: bool | None = Field(None, description="Filter by presence of mapping to template")
    failed: bool | None = Field(None, description="Filter by presence of error")
    exclude_blank: bool = Field(True, description="Exclude blank records (too short/small)")

    # Dates (for backward compatibility)
    from_date: str | None = Field(None, description="Filter by start date (ISO 8601)")
    to_date: str | None = Field(None, description="Filter by end date (ISO 8601)")
    source_type: str | None = Field(None, description="Filter by source type")

    # Sorting
    order_by: str = Field("created_at", description="Field to sort by (created_at, updated_at, id)")
    order: str = Field("asc", description="Sorting direction (asc, desc)")

    class Config:
        json_schema_extra = {
            "example": {
                "template_id": 5,
                "status": ["INITIALIZED", "FAILED"],
                "is_mapped": True,
                "exclude_blank": True,
                "order_by": "created_at",
                "order": "asc"
            }
        }
