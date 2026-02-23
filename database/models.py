from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Float,
    Time,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase,relationship

from database.get_db import engine
from enums import POIType as POITypeEnum



class DatabaseModels(DeclarativeBase):
    pass


class ItemTag(DatabaseModels):
    __tablename__ = "item_tags"

    item_id = Column(Integer, ForeignKey("items.id"), primary_key=True)
    tag_type_id = Column(Integer, ForeignKey("tag_types.id"), primary_key=True)


class TripTag(DatabaseModels):
    __tablename__ = "trip_tags"

    trip_id = Column(Integer, ForeignKey("trips.id"), primary_key=True)
    tag_type_id = Column(Integer, ForeignKey("tag_types.id"), primary_key=True)


class Trip(DatabaseModels):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_plan = Column(Integer, nullable=False, default=0)

    days = relationship("Day", back_populates="trip", cascade="all, delete")
    items = relationship("Item", back_populates="trip", cascade="all, delete")
    route_points = relationship("RoutePoint", back_populates="trip", cascade="all, delete")
    route_markers = relationship("RouteMarker", back_populates="trip", cascade="all, delete")
    tags = relationship("TagType", secondary="trip_tags", back_populates="trips")


class Day(DatabaseModels):
    __tablename__ = "days"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)

    trip_id = Column(Integer, ForeignKey("trips.id"))
    trip = relationship("Trip", back_populates="days")

    items = relationship("Item", back_populates="day", cascade="all, delete")


class POIType(DatabaseModels):
    __tablename__ = "poi_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    material_icon_name = Column(String, nullable=False, default="place")

    items = relationship("Item", back_populates="poi_type")
    route_markers = relationship("RouteMarker", back_populates="poi_type")


class TagType(DatabaseModels):
    __tablename__ = "tag_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    color = Column(String, nullable=False, default="#94A3B8")

    items = relationship("Item", secondary="item_tags", back_populates="tags")
    trips = relationship("Trip", secondary="trip_tags", back_populates="tags")


class RoutePoint(DatabaseModels):
    __tablename__ = "route_points"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation_m = Column(Float, nullable=True)
    cumulative_distance_m = Column(Float, nullable=False, default=0.0)

    trip = relationship("Trip", back_populates="route_points")


class RouteMarker(DatabaseModels):
    __tablename__ = "route_markers"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    poi_type_id = Column(Integer, ForeignKey("poi_types.id"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    snapped_seq = Column(Integer, nullable=False)
    snapped_distance_m = Column(Float, nullable=False, default=0.0)

    trip = relationship("Trip", back_populates="route_markers")
    poi_type = relationship("POIType", back_populates="route_markers")


class Item(DatabaseModels):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)

    item_type = Column(String, nullable=False)

    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    transport_type = Column(String, nullable=True)
    distance_km = Column(Float, nullable=True)
    uphill_m = Column(Float, nullable=True)
    downhill_m = Column(Float, nullable=True)
    poi_icon_name = Column(String, nullable=True)

    poi_type_id = Column(Integer, ForeignKey("poi_types.id"), nullable=True)
    poi_type = relationship("POIType", back_populates="items")

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    url = Column(String, nullable=True)
    route_start_seq = Column(Integer, nullable=True)
    route_end_seq = Column(Integer, nullable=True)

    trip_id = Column(Integer, ForeignKey("trips.id"))
    day_id = Column(Integer, ForeignKey("days.id"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    trip = relationship("Trip", back_populates="items")
    day = relationship("Day", back_populates="items")
    tags = relationship("TagType", secondary="item_tags", back_populates="items")


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(DatabaseModels.metadata.create_all)

        # Lightweight migration for SQLite: add newly introduced columns if missing.
        result = await conn.exec_driver_sql("PRAGMA table_info(items)")
        existing_columns = {row[1] for row in result.fetchall()}

        if "uphill_m" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN uphill_m FLOAT")
        if "downhill_m" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN downhill_m FLOAT")
        if "distance_km" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN distance_km FLOAT")
        if "poi_icon_name" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN poi_icon_name VARCHAR")
        if "sort_order" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN sort_order INTEGER DEFAULT 0")
        if "route_start_seq" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN route_start_seq INTEGER")
        if "route_end_seq" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE items ADD COLUMN route_end_seq INTEGER")
        if "uphill_km" in existing_columns:
            await conn.exec_driver_sql(
                "UPDATE items SET uphill_m = uphill_km * 1000 WHERE uphill_m IS NULL AND uphill_km IS NOT NULL"
            )
        if "downhill_km" in existing_columns:
            await conn.exec_driver_sql(
                "UPDATE items SET downhill_m = downhill_km * 1000 WHERE downhill_m IS NULL AND downhill_km IS NOT NULL"
            )

        trip_result = await conn.exec_driver_sql("PRAGMA table_info(trips)")
        trip_columns = {row[1] for row in trip_result.fetchall()}
        if "is_plan" not in trip_columns:
            await conn.exec_driver_sql("ALTER TABLE trips ADD COLUMN is_plan INTEGER DEFAULT 0")

        poi_result = await conn.exec_driver_sql("PRAGMA table_info(poi_types)")
        poi_columns = {row[1] for row in poi_result.fetchall()}
        if "material_icon_name" not in poi_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE poi_types ADD COLUMN material_icon_name VARCHAR DEFAULT 'place'"
            )

        default_poi_types = {
            POITypeEnum.ACCOMMODATION.value: "hotel",
            POITypeEnum.RESTAURANT.value: "restaurant",
            POITypeEnum.VIEWPOINT.value: "landscape",
            POITypeEnum.CAVE.value: "terrain",
            POITypeEnum.SPRING.value: "water_drop",
        }
        for poi_name, icon_name in default_poi_types.items():
            await conn.exec_driver_sql(
                "INSERT OR IGNORE INTO poi_types (name, material_icon_name) VALUES (?, ?)",
                (poi_name, icon_name),
            )

        default_tag_types = [
            ("food", "#F97316"),
            ("water", "#0EA5E9"),
            ("view", "#84CC16"),
            ("sleep", "#8B5CF6"),
            ("danger", "#EF4444"),
            ("photo", "#06B6D4"),
            ("history", "#A16207"),
        ]

        tag_result = await conn.exec_driver_sql("PRAGMA table_info(tag_types)")
        tag_columns = {row[1] for row in tag_result.fetchall()}
        if "color" not in tag_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE tag_types ADD COLUMN color VARCHAR DEFAULT '#94A3B8'"
            )

        for tag_name, tag_color in default_tag_types:
            await conn.exec_driver_sql(
                "INSERT OR IGNORE INTO tag_types (name, color) VALUES (?, ?)",
                (tag_name, tag_color),
            )
            await conn.exec_driver_sql(
                "UPDATE tag_types SET color = ? WHERE name = ? AND (color IS NULL OR color = '')",
                (tag_color, tag_name),
            )
