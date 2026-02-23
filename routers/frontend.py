import math
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.get_db import get_db
from database.models import Day, Item, ItemTag, POIType, RouteMarker, RoutePoint, TagType, Trip, TripTag
from enums import ItemType, TransportType

frontend_router = APIRouter(tags=["frontend"])
templates = Jinja2Templates(directory="templates")


def _to_optional_float(value: str) -> Optional[float]:
    if not value:
        return None
    parsed = float(value)
    if parsed < 0:
        raise ValueError("Value must be >= 0")
    return parsed


def _to_optional_int(value: str) -> Optional[int]:
    if not value:
        return None
    return int(value)


def _to_optional_time(value: str) -> Optional[time]:
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def _to_optional_positive_int(value: str) -> Optional[int]:
    if not value:
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("Duration must be >= 0")
    return parsed


def _to_optional_non_negative_int(value: str) -> Optional[int]:
    if not value:
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("Value must be >= 0")
    return parsed


def _to_int_list(values: list[str]) -> list[int]:
    result: list[int] = []
    for value in values:
        if not value:
            continue
        result.append(int(value))
    return result


def _to_optional_date(value: str):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _validate_hex_color(value: str) -> str:
    color = value.strip()
    if not color.startswith("#") or len(color) != 7:
        raise ValueError("Color must be a HEX value like #A1B2C3")
    return color.upper()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))


def _parse_gpx_points(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    points: list[dict] = []

    for elem in root.iter():
        if elem.tag.endswith("trkpt"):
            lat = elem.attrib.get("lat")
            lon = elem.attrib.get("lon")
            if lat is None or lon is None:
                continue
            ele = None
            for child in elem:
                if child.tag.endswith("ele") and child.text:
                    try:
                        ele = float(child.text)
                    except ValueError:
                        ele = None
                    break
            points.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "ele": ele,
                }
            )
    return points


def _calc_elevation(points: list[RoutePoint]) -> tuple[float, float]:
    uphill = 0.0
    downhill = 0.0
    for i in range(1, len(points)):
        prev = points[i - 1].elevation_m
        cur = points[i].elevation_m
        if prev is None or cur is None:
            continue
        delta = cur - prev
        if delta > 0:
            uphill += delta
        elif delta < 0:
            downhill += -delta
    return uphill, downhill


def _route_profile_points(points: list[RoutePoint]) -> list[dict[str, float]]:
    profile: list[dict[str, float]] = []
    for point in points:
        if point.elevation_m is None:
            continue
        profile.append(
            {
                "distance_km": point.cumulative_distance_m / 1000.0,
                "elevation_m": point.elevation_m,
            }
        )
    return profile


def _snap_to_route(latitude: float, longitude: float, route_points: list[RoutePoint]) -> tuple[int, float]:
    best_seq = 0
    best_dist = float("inf")
    for point in route_points:
        dist = _haversine_m(latitude, longitude, point.latitude, point.longitude)
        if dist < best_dist:
            best_dist = dist
            best_seq = point.seq
    return best_seq, best_dist


def _minutes_to_hhmm(minutes: int) -> str:
    base = datetime.combine(datetime.today().date(), time(0, 0))
    return (base + timedelta(minutes=minutes)).strftime("%H:%M")


def _build_schedule(items: list[Item]) -> dict[int, dict[str, str]]:
    schedule: dict[int, dict[str, str]] = {}
    last_end_minutes: Optional[int] = None

    for item in items:
        start_minutes: Optional[int] = None
        end_minutes: Optional[int] = None
        duration = item.duration_minutes

        if item.start_time:
            start_minutes = item.start_time.hour * 60 + item.start_time.minute
        elif last_end_minutes is not None:
            start_minutes = last_end_minutes

        if start_minutes is not None and duration is not None:
            end_minutes = start_minutes + duration

        if end_minutes is not None:
            last_end_minutes = end_minutes
        elif start_minutes is not None and duration in (0, None):
            last_end_minutes = start_minutes

        schedule[item.id] = {
            "start": _minutes_to_hhmm(start_minutes) if start_minutes is not None else "",
            "end": _minutes_to_hhmm(end_minutes) if end_minutes is not None else "",
        }

    return schedule


def _ordered_items(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda item: (item.sort_order, item.id))


class MoveItemPayload(BaseModel):
    day_id: Optional[int] = None
    position: int = 0


@frontend_router.get("/")
async def home():
    return RedirectResponse(url="/frontend/trips", status_code=status.HTTP_302_FOUND)


@frontend_router.get("/frontend/trips")
async def trips_page(
    request: Request,
    tag_ids: list[int] = Query(default=[]),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    plan_filter: str = Query(default="all"),
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed_from = _to_optional_date(date_from)
        parsed_to = _to_optional_date(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date filter format") from exc

    query = select(Trip).options(selectinload(Trip.tags))
    if plan_filter == "plan":
        query = query.where(Trip.is_plan == 1)
    elif plan_filter == "dated":
        query = query.where(Trip.is_plan == 0)

    if parsed_from:
        query = query.where(Trip.start_date >= parsed_from)
    if parsed_to:
        query = query.where(Trip.start_date <= parsed_to)

    if tag_ids:
        query = query.join(TripTag, TripTag.trip_id == Trip.id).where(TripTag.tag_type_id.in_(tag_ids)).distinct()

    query = query.order_by(Trip.is_plan.asc(), Trip.start_date.desc(), Trip.id.desc())
    result = await db.execute(query)
    trips = result.scalars().all()

    tags_result = await db.execute(select(TagType).order_by(TagType.name.asc()))
    tags = tags_result.scalars().all()
    return templates.TemplateResponse(
        "trips/index.html",
        {
            "request": request,
            "trips": trips,
            "tags": tags,
            "selected_tag_ids": set(tag_ids),
            "date_from": date_from,
            "date_to": date_to,
            "plan_filter": plan_filter,
        },
    )


@frontend_router.get("/frontend/trips/new")
async def trip_create_page(request: Request, db: AsyncSession = Depends(get_db)):
    tags_result = await db.execute(select(TagType).order_by(TagType.name.asc()))
    tags = tags_result.scalars().all()
    return templates.TemplateResponse(
        "trips/new.html",
        {"request": request, "tags": tags},
    )


@frontend_router.get("/frontend/tags")
async def tags_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TagType).order_by(TagType.name.asc()))
    tags = result.scalars().all()
    return templates.TemplateResponse(
        "tags/index.html",
        {"request": request, "tags": tags},
    )


@frontend_router.post("/frontend/tags")
async def create_tag(
    name: str = Form(...),
    color: str = Form("#94A3B8"),
    db: AsyncSession = Depends(get_db),
):
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    try:
        parsed_color = _validate_hex_color(color)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_result = await db.execute(select(TagType).where(TagType.name == normalized_name))
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tag with this name already exists")

    tag = TagType(name=normalized_name, color=parsed_color)
    db.add(tag)
    await db.commit()
    return RedirectResponse(url="/frontend/tags", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.post("/frontend/tags/{tag_id}/edit")
async def edit_tag(
    tag_id: int,
    name: str = Form(...),
    color: str = Form("#94A3B8"),
    db: AsyncSession = Depends(get_db),
):
    tag = await db.get(TagType, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    try:
        parsed_color = _validate_hex_color(color)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_result = await db.execute(
        select(TagType).where(TagType.name == normalized_name, TagType.id != tag_id)
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tag with this name already exists")

    tag.name = normalized_name
    tag.color = parsed_color
    await db.commit()
    return RedirectResponse(url="/frontend/tags", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.post("/frontend/tags/{tag_id}/delete")
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    tag = await db.get(TagType, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await db.execute(delete(ItemTag).where(ItemTag.tag_type_id == tag_id))
    await db.delete(tag)
    await db.commit()
    return RedirectResponse(url="/frontend/tags", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.get("/frontend/poi-types")
async def poi_types_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(POIType).order_by(POIType.name.asc()))
    poi_types = result.scalars().all()
    return templates.TemplateResponse(
        "poi_types/index.html",
        {"request": request, "poi_types": poi_types},
    )


@frontend_router.post("/frontend/poi-types")
async def create_poi_type(
    name: str = Form(...),
    material_icon_name: str = Form("place"),
    db: AsyncSession = Depends(get_db),
):
    normalized_name = name.strip()
    normalized_icon = material_icon_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="POI type name is required")
    if not normalized_icon:
        raise HTTPException(status_code=400, detail="Material icon name is required")

    existing_result = await db.execute(select(POIType).where(POIType.name == normalized_name))
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="POI type with this name already exists")

    poi_type = POIType(name=normalized_name, material_icon_name=normalized_icon)
    db.add(poi_type)
    await db.commit()
    return RedirectResponse(url="/frontend/poi-types", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.post("/frontend/poi-types/{poi_type_id}/edit")
async def edit_poi_type(
    poi_type_id: int,
    name: str = Form(...),
    material_icon_name: str = Form("place"),
    db: AsyncSession = Depends(get_db),
):
    poi_type = await db.get(POIType, poi_type_id)
    if not poi_type:
        raise HTTPException(status_code=404, detail="POI type not found")

    normalized_name = name.strip()
    normalized_icon = material_icon_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="POI type name is required")
    if not normalized_icon:
        raise HTTPException(status_code=400, detail="Material icon name is required")

    existing_result = await db.execute(
        select(POIType).where(POIType.name == normalized_name, POIType.id != poi_type_id)
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="POI type with this name already exists")

    poi_type.name = normalized_name
    poi_type.material_icon_name = normalized_icon
    await db.commit()
    return RedirectResponse(url="/frontend/poi-types", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.post("/frontend/poi-types/{poi_type_id}/delete")
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
        raise HTTPException(status_code=400, detail="POI type is in use and cannot be deleted")

    await db.delete(poi_type)
    await db.commit()
    return RedirectResponse(url="/frontend/poi-types", status_code=status.HTTP_303_SEE_OTHER)


@frontend_router.post("/frontend/trips/new")
async def create_trip(
    name: str = Form(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    is_plan: str = Form(""),
    tag_ids: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed_start = _to_optional_date(start_date)
        parsed_end = _to_optional_date(end_date)
        parsed_tag_ids = _to_int_list(tag_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid form values") from exc
    is_plan_value = is_plan == "on"

    if is_plan_value:
        parsed_start = None
        parsed_end = None

    trip = Trip(name=name, start_date=parsed_start, end_date=parsed_end, is_plan=1 if is_plan_value else 0)
    db.add(trip)
    await db.flush()

    if parsed_tag_ids:
        unique_tag_ids = sorted(set(parsed_tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(TripTag(trip_id=trip.id, tag_type_id=tag_id))

    await db.commit()
    await db.refresh(trip)
    return RedirectResponse(
        url=f"/frontend/trips/{trip.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/edit")
async def edit_trip(
    trip_id: int,
    name: str = Form(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    is_plan: str = Form(""),
    tag_ids: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    try:
        parsed_start = _to_optional_date(start_date)
        parsed_end = _to_optional_date(end_date)
        parsed_tag_ids = _to_int_list(tag_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid form values") from exc

    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Trip name is required")

    is_plan_value = is_plan == "on"
    if is_plan_value:
        parsed_start = None
        parsed_end = None

    trip.name = normalized_name
    trip.start_date = parsed_start
    trip.end_date = parsed_end
    trip.is_plan = 1 if is_plan_value else 0

    await db.execute(delete(TripTag).where(TripTag.trip_id == trip_id))
    if parsed_tag_ids:
        unique_tag_ids = sorted(set(parsed_tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(TripTag(trip_id=trip_id, tag_type_id=tag_id))

    await db.commit()
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.get("/frontend/trips/{trip_id}")
async def trip_detail_page(
    trip_id: int,
    request: Request,
    open_import_day: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    poi_result = await db.execute(select(POIType).order_by(POIType.name.asc()))
    poi_types = poi_result.scalars().all()
    tag_result = await db.execute(select(TagType).order_by(TagType.name.asc()))
    tag_types = tag_result.scalars().all()

    result = await db.execute(
        select(Trip)
        .options(
            selectinload(Trip.tags),
            selectinload(Trip.days).selectinload(Day.items).selectinload(Item.poi_type),
            selectinload(Trip.days).selectinload(Day.items).selectinload(Item.tags),
            selectinload(Trip.items).selectinload(Item.poi_type),
            selectinload(Trip.items).selectinload(Item.tags),
        )
        .where(Trip.id == trip_id)
    )
    trip = result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    route_points_result = await db.execute(
        select(RoutePoint).where(RoutePoint.trip_id == trip_id).order_by(RoutePoint.seq.asc())
    )
    route_points = route_points_result.scalars().all()
    route_markers_result = await db.execute(
        select(RouteMarker)
        .options(selectinload(RouteMarker.poi_type))
        .where(RouteMarker.trip_id == trip_id)
        .order_by(RouteMarker.snapped_distance_m.asc(), RouteMarker.id.asc())
    )
    route_markers = route_markers_result.scalars().all()
    route_total_km = (route_points[-1].cumulative_distance_m / 1000.0) if route_points else 0.0
    route_uphill_m, route_downhill_m = _calc_elevation(route_points)
    route_profile = _route_profile_points(route_points)

    day_items: dict[int, list[Item]] = {}
    day_schedules: dict[int, dict[int, dict[str, str]]] = {}
    for day in trip.days:
        ordered = _ordered_items(day.items)
        day_items[day.id] = ordered
        day_schedules[day.id] = _build_schedule(ordered)

    unassigned_items = _ordered_items([item for item in trip.items if item.day_id is None])
    unassigned_schedule = _build_schedule(unassigned_items)
    try:
        open_import_day_id = _to_optional_int(open_import_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid open_import_day value") from exc
    valid_day_ids = {day.id for day in trip.days}
    if open_import_day_id not in valid_day_ids:
        open_import_day_id = None

    return templates.TemplateResponse(
        "trips/detail.html",
        {
            "request": request,
            "trip": trip,
            "poi_types": poi_types,
            "tag_types": tag_types,
            "day_items": day_items,
            "day_schedules": day_schedules,
            "unassigned_items": unassigned_items,
            "unassigned_schedule": unassigned_schedule,
            "route_points_count": len(route_points),
            "route_total_km": route_total_km,
            "route_uphill_m": route_uphill_m,
            "route_downhill_m": route_downhill_m,
            "route_profile": route_profile,
            "route_markers": route_markers,
            "open_import_day_id": open_import_day_id,
        },
    )


@frontend_router.post("/frontend/trips/{trip_id}/route/import")
async def import_route_gpx(
    trip_id: int,
    target_day_id: str = Form(""),
    gpx_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    content = await gpx_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded GPX is empty")

    try:
        raw_points = _parse_gpx_points(content)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail="Invalid GPX XML") from exc

    if len(raw_points) < 2:
        raise HTTPException(status_code=400, detail="GPX must contain at least 2 track points")

    await db.execute(delete(RoutePoint).where(RoutePoint.trip_id == trip_id))
    await db.execute(delete(RouteMarker).where(RouteMarker.trip_id == trip_id))

    cumulative = 0.0
    previous = None
    for seq, point in enumerate(raw_points):
        if previous is not None:
            cumulative += _haversine_m(previous["lat"], previous["lon"], point["lat"], point["lon"])
        db.add(
            RoutePoint(
                trip_id=trip_id,
                seq=seq,
                latitude=point["lat"],
                longitude=point["lon"],
                elevation_m=point["ele"],
                cumulative_distance_m=cumulative,
            )
        )
        previous = point

    await db.commit()
    try:
        parsed_target_day_id = _to_optional_int(target_day_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid target day value") from exc
    redirect_url = f"/frontend/trips/{trip_id}"
    if parsed_target_day_id is not None:
        redirect_url = f"{redirect_url}?open_import_day={parsed_target_day_id}"
    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/route/markers")
async def add_route_marker(
    trip_id: int,
    title: str = Form(...),
    poi_type_id: int = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    description: str = Form(""),
    target_day_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    poi_type = await db.get(POIType, poi_type_id)
    if not poi_type:
        raise HTTPException(status_code=400, detail="Invalid POI type")

    route_points_result = await db.execute(
        select(RoutePoint).where(RoutePoint.trip_id == trip_id).order_by(RoutePoint.seq.asc())
    )
    route_points = route_points_result.scalars().all()
    if not route_points:
        raise HTTPException(status_code=400, detail="Import GPX route first")

    snapped_seq, _ = _snap_to_route(latitude, longitude, route_points)
    snapped_point = route_points[snapped_seq]

    marker = RouteMarker(
        trip_id=trip_id,
        title=title.strip() or "POI",
        description=description.strip() or None,
        poi_type_id=poi_type_id,
        latitude=latitude,
        longitude=longitude,
        snapped_seq=snapped_seq,
        snapped_distance_m=snapped_point.cumulative_distance_m,
    )
    db.add(marker)
    await db.commit()
    try:
        parsed_target_day_id = _to_optional_int(target_day_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid target day value") from exc
    redirect_url = f"/frontend/trips/{trip_id}"
    if parsed_target_day_id is not None:
        redirect_url = f"{redirect_url}?open_import_day={parsed_target_day_id}"
    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/route/markers/{marker_id}/delete")
async def delete_route_marker(
    trip_id: int,
    marker_id: int,
    target_day_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    marker = await db.get(RouteMarker, marker_id)
    if not marker or marker.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Marker not found")
    await db.delete(marker)
    await db.commit()
    try:
        parsed_target_day_id = _to_optional_int(target_day_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid target day value") from exc
    redirect_url = f"/frontend/trips/{trip_id}"
    if parsed_target_day_id is not None:
        redirect_url = f"{redirect_url}?open_import_day={parsed_target_day_id}"
    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/route/generate")
async def generate_itinerary_from_route(
    trip_id: int,
    day_id: str = Form(""),
    clear_existing: str = Form("on"),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    try:
        parsed_day_id = _to_optional_int(day_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid day value") from exc
    if parsed_day_id is None:
        raise HTTPException(status_code=400, detail="Select a day for GPX generation")
    day = await db.get(Day, parsed_day_id)
    if not day or day.trip_id != trip_id:
        raise HTTPException(status_code=400, detail="Day does not belong to this trip")

    route_points_result = await db.execute(
        select(RoutePoint).where(RoutePoint.trip_id == trip_id).order_by(RoutePoint.seq.asc())
    )
    route_points = route_points_result.scalars().all()
    if len(route_points) < 2:
        raise HTTPException(status_code=400, detail="Import GPX route first")

    markers_result = await db.execute(
        select(RouteMarker).where(RouteMarker.trip_id == trip_id).order_by(RouteMarker.snapped_distance_m.asc())
    )
    markers = markers_result.scalars().all()
    if not markers:
        raise HTTPException(status_code=400, detail="Add at least one marker before generation")

    if clear_existing == "on":
        ids_result = await db.execute(
            select(Item.id).where(Item.trip_id == trip_id, Item.day_id == parsed_day_id)
        )
        item_ids = [row[0] for row in ids_result.all()]
        if item_ids:
            await db.execute(delete(ItemTag).where(ItemTag.item_id.in_(item_ids)))
        await db.execute(delete(Item).where(Item.trip_id == trip_id, Item.day_id == parsed_day_id))
        await db.flush()

    anchors = [
        {
            "title": "Start",
            "seq": route_points[0].seq,
            "cum": route_points[0].cumulative_distance_m,
            "marker": None,
        }
    ]
    for marker in markers:
        anchors.append(
            {
                "title": marker.title,
                "seq": marker.snapped_seq,
                "cum": marker.snapped_distance_m,
                "marker": marker,
            }
        )
    anchors.append(
        {
            "title": "Finish",
            "seq": route_points[-1].seq,
            "cum": route_points[-1].cumulative_distance_m,
            "marker": None,
        }
    )
    anchors = sorted(anchors, key=lambda row: row["cum"])

    if clear_existing == "on":
        sort_order = 0
    else:
        max_result = await db.execute(
            select(func.max(Item.sort_order)).where(Item.trip_id == trip_id, Item.day_id == parsed_day_id)
        )
        max_sort = max_result.scalar_one_or_none()
        sort_order = (max_sort + 1) if max_sort is not None else 0
    for idx in range(len(anchors) - 1):
        start_anchor = anchors[idx]
        end_anchor = anchors[idx + 1]
        start_seq = int(start_anchor["seq"])
        end_seq = int(end_anchor["seq"])
        if end_seq <= start_seq:
            continue

        segment_points = route_points[start_seq : end_seq + 1]
        distance_m = max(0.0, end_anchor["cum"] - start_anchor["cum"])
        uphill_m, downhill_m = _calc_elevation(segment_points)

        transport_item = Item(
            title=f"{start_anchor['title']} -> {end_anchor['title']}",
            description="Generated from GPX route",
            item_type=ItemType.TRANSPORT.value,
            transport_type=TransportType.WALK.value,
            distance_km=distance_m / 1000.0,
            uphill_m=uphill_m,
            downhill_m=downhill_m,
            route_start_seq=start_seq,
            route_end_seq=end_seq,
            trip_id=trip_id,
            day_id=parsed_day_id,
            sort_order=sort_order,
        )
        db.add(transport_item)
        sort_order += 1

        marker = end_anchor["marker"]
        if marker is not None:
            snapped_point = route_points[int(marker.snapped_seq)]
            poi_item = Item(
                title=marker.title,
                description=marker.description,
                item_type=ItemType.POI.value,
                poi_type_id=marker.poi_type_id,
                latitude=snapped_point.latitude,
                longitude=snapped_point.longitude,
                route_start_seq=int(marker.snapped_seq),
                route_end_seq=int(marker.snapped_seq),
                trip_id=trip_id,
                day_id=parsed_day_id,
                sort_order=sort_order,
            )
            db.add(poi_item)
            sort_order += 1

    await db.commit()
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.get("/frontend/trips/{trip_id}/route/data")
async def route_data(
    trip_id: int,
    day_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    points_result = await db.execute(
        select(RoutePoint).where(RoutePoint.trip_id == trip_id).order_by(RoutePoint.seq.asc())
    )
    points = points_result.scalars().all()

    markers_result = await db.execute(
        select(RouteMarker)
        .options(selectinload(RouteMarker.poi_type))
        .where(RouteMarker.trip_id == trip_id)
        .order_by(RouteMarker.snapped_distance_m.asc())
    )
    markers = markers_result.scalars().all()

    selected_day_id: Optional[int] = None
    try:
        selected_day_id = _to_optional_int(day_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid day value") from exc

    display_points = points
    display_markers = markers
    display_title = "Full route"
    if selected_day_id is not None:
        day = await db.get(Day, selected_day_id)
        if not day or day.trip_id != trip_id:
            raise HTTPException(status_code=400, detail="Day does not belong to this trip")

        day_items_result = await db.execute(
            select(Item)
            .where(Item.trip_id == trip_id, Item.day_id == selected_day_id)
            .order_by(Item.sort_order.asc(), Item.id.asc())
        )
        day_items = day_items_result.scalars().all()

        seq_ranges: list[tuple[int, int]] = []
        for item in day_items:
            start_seq = item.route_start_seq
            end_seq = item.route_end_seq
            if start_seq is None or end_seq is None:
                continue
            if end_seq < start_seq:
                start_seq, end_seq = end_seq, start_seq
            if end_seq == start_seq:
                continue
            seq_ranges.append((start_seq, end_seq))

        route_point_by_seq = {point.seq: point for point in points}
        day_points: list[RoutePoint] = []
        for start_seq, end_seq in seq_ranges:
            segment = [route_point_by_seq[seq] for seq in range(start_seq, end_seq + 1) if seq in route_point_by_seq]
            if not segment:
                continue
            if day_points and day_points[-1].seq == segment[0].seq:
                day_points.extend(segment[1:])
            else:
                day_points.extend(segment)

        if day_points:
            display_points = day_points

        if seq_ranges:
            min_seq = min(start for start, _ in seq_ranges)
            max_seq = max(end for _, end in seq_ranges)
            display_markers = [marker for marker in markers if min_seq <= marker.snapped_seq <= max_seq]
        else:
            display_markers = []
        display_title = f"Day {day.date}"

    return JSONResponse(
        {
            "selected_day_id": selected_day_id,
            "display_title": display_title,
            "points": [
                {
                    "seq": p.seq,
                    "lat": p.latitude,
                    "lon": p.longitude,
                    "ele": p.elevation_m,
                    "cum_dist_m": p.cumulative_distance_m,
                }
                for p in display_points
            ],
            "markers": [
                {
                    "id": m.id,
                    "title": m.title,
                    "lat": m.latitude,
                    "lon": m.longitude,
                    "poi_type": m.poi_type.name if m.poi_type else "poi",
                }
                for m in display_markers
            ],
        }
    )


@frontend_router.post("/frontend/trips/{trip_id}/days")
async def create_day(
    trip_id: int,
    date: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
    day = Day(date=parsed_date, trip_id=trip_id)
    db.add(day)
    await db.commit()
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/items")
async def create_item(
    trip_id: int,
    title: str = Form(...),
    item_type: ItemType = Form(...),
    day_id: str = Form(""),
    description: str = Form(""),
    transport_type: str = Form(""),
    poi_type_id: str = Form(""),
    start_time: str = Form(""),
    duration_minutes: str = Form(""),
    distance_km: str = Form(""),
    uphill_m: str = Form(""),
    downhill_m: str = Form(""),
    insert_position: str = Form(""),
    tag_ids: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    try:
        parsed_day_id = _to_optional_int(day_id)
        parsed_poi_type_id = _to_optional_int(poi_type_id)
        parsed_start_time = _to_optional_time(start_time)
        parsed_duration = _to_optional_positive_int(duration_minutes)
        parsed_distance = _to_optional_float(distance_km)
        parsed_uphill = _to_optional_float(uphill_m)
        parsed_downhill = _to_optional_float(downhill_m)
        parsed_insert_position = _to_optional_non_negative_int(insert_position)
        parsed_tag_ids = _to_int_list(tag_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if parsed_day_id is not None:
        day = await db.get(Day, parsed_day_id)
        if not day or day.trip_id != trip_id:
            raise HTTPException(status_code=400, detail="Day does not belong to this trip")

    is_transport = item_type == ItemType.TRANSPORT
    parsed_transport_type = None
    if is_transport and transport_type:
        try:
            parsed_transport_type = TransportType(transport_type).value
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid transport type") from exc
    else:
        if parsed_poi_type_id is None:
            raise HTTPException(status_code=400, detail="POI type is required for POI items")
        poi_type = await db.get(POIType, parsed_poi_type_id)
        if not poi_type:
            raise HTTPException(status_code=400, detail="Invalid POI type")

    item = Item(
        title=title,
        description=description or None,
        item_type=item_type.value,
        start_time=parsed_start_time,
        duration_minutes=parsed_duration,
        transport_type=parsed_transport_type,
        poi_type_id=parsed_poi_type_id if not is_transport else None,
        distance_km=parsed_distance if is_transport else None,
        uphill_m=parsed_uphill if is_transport else None,
        downhill_m=parsed_downhill if is_transport else None,
        trip_id=trip_id,
        day_id=parsed_day_id,
        sort_order=0,
    )
    db.add(item)
    await db.flush()

    siblings_result = await db.execute(
        select(Item)
        .where(
            Item.trip_id == trip_id,
            Item.day_id.is_(None) if parsed_day_id is None else Item.day_id == parsed_day_id,
            Item.id != item.id,
        )
        .order_by(Item.sort_order.asc(), Item.id.asc())
    )
    siblings = siblings_result.scalars().all()
    if parsed_insert_position is None:
        item.sort_order = len(siblings)
    else:
        target_position = min(parsed_insert_position, len(siblings))
        for sibling in siblings:
            if sibling.sort_order >= target_position:
                sibling.sort_order += 1
        item.sort_order = target_position

    if parsed_tag_ids:
        unique_tag_ids = sorted(set(parsed_tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(ItemTag(item_id=item.id, tag_type_id=tag_id))

    await db.commit()
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/items/{item_id}/edit")
async def edit_item(
    trip_id: int,
    item_id: int,
    title: str = Form(...),
    item_type: ItemType = Form(...),
    day_id: str = Form(""),
    description: str = Form(""),
    transport_type: str = Form(""),
    poi_type_id: str = Form(""),
    start_time: str = Form(""),
    duration_minutes: str = Form(""),
    distance_km: str = Form(""),
    uphill_m: str = Form(""),
    downhill_m: str = Form(""),
    tag_ids: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    item = await db.get(Item, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        parsed_day_id = _to_optional_int(day_id)
        parsed_poi_type_id = _to_optional_int(poi_type_id)
        parsed_start_time = _to_optional_time(start_time)
        parsed_duration = _to_optional_positive_int(duration_minutes)
        parsed_distance = _to_optional_float(distance_km)
        parsed_uphill = _to_optional_float(uphill_m)
        parsed_downhill = _to_optional_float(downhill_m)
        parsed_tag_ids = _to_int_list(tag_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if parsed_day_id is not None:
        day = await db.get(Day, parsed_day_id)
        if not day or day.trip_id != trip_id:
            raise HTTPException(status_code=400, detail="Day does not belong to this trip")

    is_transport = item_type == ItemType.TRANSPORT
    parsed_transport_type = None
    if is_transport and transport_type:
        try:
            parsed_transport_type = TransportType(transport_type).value
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid transport type") from exc
    else:
        if parsed_poi_type_id is None:
            raise HTTPException(status_code=400, detail="POI type is required for POI items")
        poi_type = await db.get(POIType, parsed_poi_type_id)
        if not poi_type:
            raise HTTPException(status_code=400, detail="Invalid POI type")

    old_day_id = item.day_id
    item.title = title
    item.description = description or None
    item.item_type = item_type.value
    item.start_time = parsed_start_time
    item.duration_minutes = parsed_duration
    item.transport_type = parsed_transport_type if is_transport else None
    item.poi_type_id = parsed_poi_type_id if not is_transport else None
    item.distance_km = parsed_distance if is_transport else None
    item.uphill_m = parsed_uphill if is_transport else None
    item.downhill_m = parsed_downhill if is_transport else None
    item.day_id = parsed_day_id

    await db.execute(delete(ItemTag).where(ItemTag.item_id == item.id))
    if parsed_tag_ids:
        unique_tag_ids = sorted(set(parsed_tag_ids))
        tag_result = await db.execute(select(TagType.id).where(TagType.id.in_(unique_tag_ids)))
        valid_ids = {row[0] for row in tag_result.all()}
        if len(valid_ids) != len(unique_tag_ids):
            raise HTTPException(status_code=400, detail="One or more tags are invalid")
        for tag_id in unique_tag_ids:
            db.add(ItemTag(item_id=item.id, tag_type_id=tag_id))

    if old_day_id != parsed_day_id:
        all_items_result = await db.execute(
            select(Item).where(Item.trip_id == trip_id).order_by(Item.sort_order.asc(), Item.id.asc())
        )
        all_items = all_items_result.scalars().all()

        source_items = [row for row in all_items if row.day_id == old_day_id and row.id != item.id]
        target_items = [row for row in all_items if row.day_id == parsed_day_id and row.id != item.id]

        for index, row in enumerate(source_items):
            row.sort_order = index

        item.sort_order = len(target_items)

    await db.commit()
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.post("/frontend/trips/{trip_id}/items/{item_id}/move")
async def move_item(
    trip_id: int,
    item_id: int,
    payload: MoveItemPayload,
    db: AsyncSession = Depends(get_db),
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    item = await db.get(Item, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail="Item not found")

    target_day_id = payload.day_id
    if target_day_id is not None:
        day = await db.get(Day, target_day_id)
        if not day or day.trip_id != trip_id:
            raise HTTPException(status_code=400, detail="Day does not belong to this trip")

    all_items_result = await db.execute(
        select(Item).where(Item.trip_id == trip_id).order_by(Item.sort_order.asc(), Item.id.asc())
    )
    all_items = all_items_result.scalars().all()

    old_day_id = item.day_id
    source_items = [row for row in all_items if row.day_id == old_day_id and row.id != item.id]
    target_items = [row for row in all_items if row.day_id == target_day_id and row.id != item.id]

    if old_day_id == target_day_id:
        target_items = source_items

    bounded_position = max(0, min(payload.position, len(target_items)))
    target_items.insert(bounded_position, item)

    for index, row in enumerate(source_items):
        if old_day_id != target_day_id:
            row.sort_order = index

    for index, row in enumerate(target_items):
        row.day_id = target_day_id
        row.sort_order = index

    await db.commit()
    return {"ok": True}


@frontend_router.post("/frontend/trips/{trip_id}/items/{item_id}/delete")
async def delete_item(
    trip_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
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
    return RedirectResponse(
        url=f"/frontend/trips/{trip_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@frontend_router.get("/frontend/stats")
async def stats_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Item.distance_km, Item.uphill_m, Item.downhill_m, Trip.start_date, Item.transport_type)
        .join(Trip, Item.trip_id == Trip.id)
        .where(Item.item_type == ItemType.TRANSPORT.value)
    )

    total_distance = 0.0
    total_uphill = 0.0
    total_downhill = 0.0
    by_transport: dict[str, float] = {}
    per_year: dict[int, dict[str, float]] = {}

    for distance_km_value, uphill_m_value, downhill_m_value, start_date, transport_type in result.all():
        distance_value = distance_km_value or 0.0
        uphill_value = uphill_m_value or 0.0
        downhill_value = downhill_m_value or 0.0

        total_distance += distance_value
        total_uphill += uphill_value
        total_downhill += downhill_value
        transport_key = transport_type or "unknown"
        by_transport[transport_key] = by_transport.get(transport_key, 0.0) + distance_value

        if not start_date:
            continue

        year = start_date.year
        if year not in per_year:
            per_year[year] = {"distance": 0.0, "uphill_m": 0.0, "downhill_m": 0.0}
        per_year[year]["distance"] += distance_value
        per_year[year]["uphill_m"] += uphill_value
        per_year[year]["downhill_m"] += downhill_value

    ordered_years = sorted(per_year.items(), key=lambda item: item[0], reverse=True)
    transport_rows = sorted(by_transport.items(), key=lambda item: item[0])

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "total_distance": total_distance,
            "total_uphill": total_uphill,
            "total_downhill": total_downhill,
            "total_combined": total_uphill + total_downhill,
            "transport_rows": transport_rows,
            "years": ordered_years,
        },
    )
