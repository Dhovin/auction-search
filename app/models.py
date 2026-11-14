"""Pydantic schemas for API requests and responses."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


VALID_DISTANCES = {-1, 10, 25, 50, 75, 100, 150, 250}
VALID_SORT_FIELDS = {"close", "relevancy", "bidlow", "bidhigh", "title"}
ChannelType = Literal[
    "email",
    "discord",
    "slack",
    "webhook",
    "ntfy",
    "gotify",
    "pushover",
    "pushbullet",
    "telegram",
]


class SavedSearchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    keywords: str = Field(..., min_length=1, max_length=200)
    must_include: str = ""
    exclude_words: str = ""
    min_bid: Optional[float] = Field(default=None, ge=0)
    max_bid: Optional[float] = Field(default=None, ge=0)
    zip_code: str = Field(default="", max_length=10)
    distance_radius: int = -1
    include_shippable_out_of_range: bool = True
    auction_id: str = Field(default="", max_length=32)
    sort_field: str = "close"
    max_pages: int = Field(default=2, ge=1, le=10)
    check_interval_minutes: int = Field(default=30, ge=1, le=1440)
    alert_on_new: bool = True
    closing_soon_hours: Optional[float] = Field(default=4.0, ge=0.1, le=168)
    enabled: bool = True
    run_immediately: bool = False

    @field_validator("distance_radius")
    @classmethod
    def validate_distance(cls, value: int) -> int:
        if value not in VALID_DISTANCES:
            raise ValueError(f"distance_radius must be one of {sorted(VALID_DISTANCES)}")
        return value

    @field_validator("sort_field")
    @classmethod
    def validate_sort_field(cls, value: str) -> str:
        if value not in VALID_SORT_FIELDS:
            raise ValueError(f"sort_field must be one of {sorted(VALID_SORT_FIELDS)}")
        return value


class SavedSearchUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    keywords: Optional[str] = Field(default=None, min_length=1, max_length=200)
    must_include: Optional[str] = None
    exclude_words: Optional[str] = None
    min_bid: Optional[float] = Field(default=None, ge=0)
    max_bid: Optional[float] = Field(default=None, ge=0)
    zip_code: Optional[str] = Field(default=None, max_length=10)
    distance_radius: Optional[int] = None
    include_shippable_out_of_range: Optional[bool] = None
    auction_id: Optional[str] = Field(default=None, max_length=32)
    sort_field: Optional[str] = None
    max_pages: Optional[int] = Field(default=None, ge=1, le=10)
    check_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    alert_on_new: Optional[bool] = None
    closing_soon_hours: Optional[float] = Field(default=None, ge=0.1, le=168)
    enabled: Optional[bool] = None

    @field_validator("distance_radius")
    @classmethod
    def validate_distance(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in VALID_DISTANCES:
            raise ValueError(f"distance_radius must be one of {sorted(VALID_DISTANCES)}")
        return value

    @field_validator("sort_field")
    @classmethod
    def validate_sort_field(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in VALID_SORT_FIELDS:
            raise ValueError(f"sort_field must be one of {sorted(VALID_SORT_FIELDS)}")
        return value


class ItemFlagUpdate(BaseModel):
    value: bool = True


class ManualItemAddRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2000)
    watch: bool = True


class NotificationChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    channel_type: ChannelType
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class NotificationChannelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    channel_type: Optional[ChannelType] = None
    config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class SiteSettingsUpdate(BaseModel):
    default_zip_code: Optional[str] = Field(default=None, max_length=10)
    default_distance_radius: Optional[int] = None
    global_exclude_words: Optional[str] = Field(default=None, max_length=500)
    default_check_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    default_closing_soon_hours: Optional[float] = Field(default=None, ge=0, le=168)
    include_shippable_out_of_range: Optional[bool] = None
    alert_batch_minutes: Optional[int] = Field(default=None, ge=0, le=120)

    @field_validator("default_zip_code")
    @classmethod
    def normalize_default_zip(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @field_validator("default_distance_radius")
    @classmethod
    def validate_default_distance(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in VALID_DISTANCES:
            raise ValueError(
                f"default_distance_radius must be one of {sorted(VALID_DISTANCES)}"
            )
        return value
