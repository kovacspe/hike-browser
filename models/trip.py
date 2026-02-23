from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator

from enums import ItemType, TransportType


class TripCreate(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_plan: bool = False
    tag_ids: list[int] = Field(default_factory=list)


class DayCreate(BaseModel):
    date: date


class ItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    item_type: ItemType

    day_id: Optional[int] = None

    start_time: Optional[time] = None
    end_time: Optional[time] = None
    duration_minutes: Optional[int] = None

    transport_type: Optional[TransportType] = None
    distance_km: Optional[float] = None
    uphill_m: Optional[float] = None
    downhill_m: Optional[float] = None
    poi_type_id: Optional[int] = None
    tag_ids: list[int] = Field(default_factory=list)

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    url: Optional[HttpUrl] = None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not (-90 <= value <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not (-180 <= value <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def validate_time_logic(cls, value: Optional[int], values) -> Optional[int]:
        start = values.data.get("start_time")
        end = values.data.get("end_time")

        if start and end and value:
            raise ValueError("Use either end_time OR duration_minutes, not both")

        return value

    @field_validator("distance_km", "uphill_m", "downhill_m")
    @classmethod
    def validate_non_negative_km(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("Value must be >= 0")
        return value


class TagTypeCreate(BaseModel):
    name: str
    color: str = "#94A3B8"

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not value.startswith("#") or len(value) != 7:
            raise ValueError("Color must be a HEX value like #A1B2C3")
        return value


class TagTypeUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.startswith("#") or len(value) != 7:
            raise ValueError("Color must be a HEX value like #A1B2C3")
        return value


class POITypeCreate(BaseModel):
    name: str
    material_icon_name: str = "place"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("POI type name is required")
        return normalized

    @field_validator("material_icon_name")
    @classmethod
    def validate_icon_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Material icon name is required")
        return normalized


class POITypeUpdate(BaseModel):
    name: Optional[str] = None
    material_icon_name: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("POI type name is required")
        return normalized

    @field_validator("material_icon_name")
    @classmethod
    def validate_icon_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Material icon name is required")
        return normalized
