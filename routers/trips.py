from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.get_db import get_db
from database.models import Day, Item, ItemTag, POIType, RouteMarker, TagType, Trip, TripTag
from enums import ItemType
from models.trip import (
    DayCreate,
    ItemCreate,
    POITypeCreate,
    POITypeUpdate,
    TagTypeCreate,
    TagTypeUpdate,
    TripCreate,
)

trips_router = APIRouter(prefix="/trips", tags=["trips"])


@trips_router.post("/")
async def create_trip(trip: TripCreate, db: AsyncSession = Depends(get_db)):
    data = trip.model_dump()
    tag_ids = data.pop("tag_ids", [])
    if data.get("is_plan"):
        data["start_date"] = None
        data["end_date"] = None

    db_trip = Trip(**data)
    db.add(db_trip)
    await db.flush()

    if tag_ids:
        unique_tag_ids = sorted(set(tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(TripTag(trip_id=db_trip.id, tag_type_id=tag_id))

    await db.commit()
    await db.refresh(db_trip)
    return db_trip


@trips_router.put("/{trip_id}")
async def update_trip(trip_id: int, payload: TripCreate, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    data = payload.model_dump()
    tag_ids = data.pop("tag_ids", [])
    if data.get("is_plan"):
        data["start_date"] = None
        data["end_date"] = None

    trip.name = data["name"]
    trip.start_date = data["start_date"]
    trip.end_date = data["end_date"]
    trip.is_plan = 1 if data["is_plan"] else 0

    await db.execute(delete(TripTag).where(TripTag.trip_id == trip_id))
    if tag_ids:
        unique_tag_ids = sorted(set(tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(TripTag(trip_id=trip_id, tag_type_id=tag_id))

    await db.commit()
    await db.refresh(trip)
    return trip


@trips_router.post("/{trip_id}/days/")
async def create_day(trip_id: int, day: DayCreate, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    db_day = Day(**day.model_dump(), trip_id=trip_id)
    db.add(db_day)
    await db.commit()
    await db.refresh(db_day)
    return db_day


@trips_router.post("/{trip_id}/items/")
async def create_item(trip_id: int, item: ItemCreate, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    data = item.model_dump(mode="json")
    tag_ids = data.pop("tag_ids", [])
    data["trip_id"] = trip_id
    if data.get("item_type") == ItemType.POI.value:
        poi_type_id = data.get("poi_type_id")
        if not poi_type_id:
            raise HTTPException(status_code=400, detail="poi_type_id is required for POI items")
        poi_type = await db.get(POIType, poi_type_id)
        if not poi_type:
            raise HTTPException(status_code=400, detail="Invalid POI type")
        data["transport_type"] = None
        data["distance_km"] = None
        data["uphill_m"] = None
        data["downhill_m"] = None
    else:
        data["poi_type_id"] = None
        if data.get("item_type") != ItemType.TRANSPORT.value:
            data["transport_type"] = None
            data["distance_km"] = None
            data["uphill_m"] = None
            data["downhill_m"] = None

    db_item = Item(**data, sort_order=0)
    db.add(db_item)
    await db.flush()

    siblings_result = await db.execute(
        select(Item)
        .where(
            Item.trip_id == trip_id,
            Item.day_id.is_(None) if db_item.day_id is None else Item.day_id == db_item.day_id,
            Item.id != db_item.id,
        )
        .order_by(Item.sort_order.asc(), Item.id.asc())
    )
    siblings = siblings_result.scalars().all()
    db_item.sort_order = len(siblings)

    if tag_ids:
        unique_tag_ids = sorted(set(tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(ItemTag(item_id=db_item.id, tag_type_id=tag_id))

    await db.commit()
    await db.refresh(db_item)
    return db_item


@trips_router.get("/")
async def list_trips(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trip).order_by(Trip.start_date.desc(), Trip.id.desc()))
    return result.scalars().all()


@trips_router.delete("/{trip_id}/items/{item_id}")
async def delete_item(trip_id: int, item_id: int, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    item = await db.get(Item, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Item not found")

    day_id = item.day_id
    await db.delete(item)
    await db.flush()

    siblings_result = await db.execute(
        select(Item)
        .where(
            Item.trip_id == trip_id,
            Item.day_id.is_(None) if day_id is None else Item.day_id == day_id,
        )
        .order_by(Item.sort_order.asc(), Item.id.asc())
    )
    siblings = siblings_result.scalars().all()
    for index, row in enumerate(siblings):
        row.sort_order = index

    await db.commit()
    return {"ok": True}


@trips_router.get("/tags/")
async def list_tags(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TagType).order_by(TagType.name.asc()))
    return result.scalars().all()


@trips_router.post("/tags/")
async def create_tag(tag: TagTypeCreate, db: AsyncSession = Depends(get_db)):
    normalized_name = tag.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    existing_result = await db.execute(select(TagType).where(TagType.name == normalized_name))
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tag with this name already exists")

    db_tag = TagType(name=normalized_name, color=tag.color)
    db.add(db_tag)
    await db.commit()
    await db.refresh(db_tag)
    return db_tag


@trips_router.put("/tags/{tag_id}")
async def update_tag(tag_id: int, payload: TagTypeUpdate, db: AsyncSession = Depends(get_db)):
    tag = await db.get(TagType, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        normalized_name = data["name"].strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="Tag name is required")
        existing_result = await db.execute(
            select(TagType).where(TagType.name == normalized_name, TagType.id != tag_id)
        )
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Tag with this name already exists")
        tag.name = normalized_name
    if "color" in data:
        tag.color = data["color"]

    await db.commit()
    await db.refresh(tag)
    return tag


@trips_router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    tag = await db.get(TagType, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await db.execute(delete(ItemTag).where(ItemTag.tag_type_id == tag_id))
    await db.delete(tag)
    await db.commit()
    return {"ok": True}


@trips_router.get("/poi-types/")
async def list_poi_types(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(POIType).order_by(POIType.name.asc()))
    return result.scalars().all()


@trips_router.post("/poi-types/")
async def create_poi_type(payload: POITypeCreate, db: AsyncSession = Depends(get_db)):
    normalized_name = payload.name.strip()
    normalized_icon = payload.material_icon_name.strip()

    existing_result = await db.execute(select(POIType).where(POIType.name == normalized_name))
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="POI type with this name already exists")

    poi_type = POIType(name=normalized_name, material_icon_name=normalized_icon)
    db.add(poi_type)
    await db.commit()
    await db.refresh(poi_type)
    return poi_type


@trips_router.put("/poi-types/{poi_type_id}")
async def update_poi_type(poi_type_id: int, payload: POITypeUpdate, db: AsyncSession = Depends(get_db)):
    poi_type = await db.get(POIType, poi_type_id)
    if not poi_type:
        raise HTTPException(status_code=404, detail="POI type not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        normalized_name = data["name"].strip()
        existing_result = await db.execute(
            select(POIType).where(POIType.name == normalized_name, POIType.id != poi_type_id)
        )
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="POI type with this name already exists")
        poi_type.name = normalized_name

    if "material_icon_name" in data:
        poi_type.material_icon_name = data["material_icon_name"].strip()

    await db.commit()
    await db.refresh(poi_type)
    return poi_type


@trips_router.delete("/poi-types/{poi_type_id}")
async def delete_poi_type(poi_type_id: int, db: AsyncSession = Depends(get_db)):
    poi_type = await db.get(POIType, poi_type_id)
    if not poi_type:
        raise HTTPException(status_code=404, detail="POI type not found")

    item_usage_result = await db.execute(select(func.count()).select_from(Item).where(Item.poi_type_id == poi_type_id))
    marker_usage_result = await db.execute(
        select(func.count()).select_from(RouteMarker).where(RouteMarker.poi_type_id == poi_type_id)
    )
    used_by_items = item_usage_result.scalar_one()
    used_by_markers = marker_usage_result.scalar_one()
    if used_by_items or used_by_markers:
        raise HTTPException(
            status_code=400,
            detail="POI type is in use and cannot be deleted",
        )

    await db.delete(poi_type)
    await db.commit()
    return {"ok": True}


@trips_router.get("/{trip_id}")
async def get_trip(trip_id: int, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return trip
