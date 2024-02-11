import datetime
import json
import os
from decimal import Decimal
from enum import Enum
from typing import List, NamedTuple, Optional

import gpxpy
import yaml
from gpxpy.gpx import GPX, GPXTrack, GPXTrackSegment, GPXWaypoint
from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import core_schema
from pydantic_yaml import parse_yaml_file_as, to_yaml_file
from unidecode import unidecode

from settings import DATA_DIR
from utils import format_timedelta, segment_by_waypoints, slugify


class Time(datetime.timedelta):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(),
            serialization=core_schema.wrap_serializer_function_ser_schema(
                lambda x, y: ":".join(str(x).split(":")[:2]))
        )

    @classmethod
    def validate(cls, v: str):
        hours, minutes = v.split(':')
        return datetime.timedelta(hours=int(hours), minutes=int(minutes))


class PlaceType(str, Enum):
    SIGN_POST = 'sign'
    POINT_OF_INTEREST = 'poi'
    MEMORY = 'memory'
    SLEEPING_PLACE = 'sleep'
    WELL = 'well'
    CITY = 'city'
    VIEW = 'view'
    TECH = 'tech'
    CASTLE = 'castle'
    CAVE = 'cave'
    PEAK = 'peak'

    @property
    def icon(self):
        return {
            PlaceType.SIGN_POST: 'signpost',
            PlaceType.SLEEPING_PLACE: 'night_shelter',
            PlaceType.POINT_OF_INTEREST: 'star',
            PlaceType.WELL: 'water_drop',
            PlaceType.CITY: 'location_city',
            PlaceType.VIEW: 'panorama',
            PlaceType.TECH: 'manufacturing',
            PlaceType.CASTLE: 'castle',
            PlaceType.CAVE: 'star',
            PlaceType.PEAK: 'landscape'
        }[self]

    @classmethod
    def guess_from_name(cls, name: str):
        normalized_name = unidecode(name).lower()

        def has_keyword(*keywords):
            return any(keyword in normalized_name for keyword in keywords)
        if has_keyword('pramen', 'studna', 'studnicka'):
            return PlaceType.WELL
        if has_keyword('kemp', 'camp', 'utulna', 'chata'):
            return PlaceType.SLEEPING_PLACE
        return PlaceType.SIGN_POST


class PointOfInterest(BaseModel):
    name: str
    type: PlaceType
    description: str | None = None
    lat: Decimal
    lon: Decimal
    elevation: Decimal

    @property
    def gpx(self) -> GPXWaypoint:
        return GPXWaypoint(
            latitude=float(self.lat),
            longitude=float(self.lon),
            elevation=float(self.elevation)
        )


class TravelBy(str, Enum):
    FOOT = 'foot'
    CAR = 'car'
    BIKE = 'bike'
    PUBLIC_TRANSPORT = 'pt'

    @property
    def icon(self):
        return {
            TravelBy.FOOT: 'hiking',
            TravelBy.CAR: 'car',
            TravelBy.BIKE: 'directions_bike',
            TravelBy.PUBLIC_TRANSPORT: 'directions_bus',
        }[self]


class Place(BaseModel):
    rest_time: Time
    name: str
    description: str | None = None
    ref: str | None = None


class Segment(BaseModel):
    name: str
    time: Time
    travel_by: TravelBy


class HikePlan(BaseModel):
    name: str
    date: datetime.date
    start_at: Time
    with_who: List[str]
    tags: List[str]
    segments: List[Segment]
    places: List[Place]


class HikeStats(NamedTuple):
    uphill: float
    downhill: float
    length: float
    time: Optional[datetime.timedelta] = None


class IterinaryPoint(NamedTuple):
    from_time: Time
    to: datetime.time
    time: Time
    name: str
    description: Optional[str] = None
    travel_by: Optional[TravelBy] = None
    stats: Optional[HikeStats] = None
    ref: Optional[str] = None
    icon: str | None = None


class Hike(BaseModel):
    plan: HikePlan
    gpx_track: GPX
    slug: str

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    def get_folder(name: str) -> str:
        """Get hike folder path by name"""
        return os.path.join(DATA_DIR, 'hikes', name)

    @property
    def folder(self) -> str:
        """Get hike folder path"""
        return self.get_folder(self.slug)

    @property
    def track(self) -> GPXTrack:
        """Get track"""
        return self.gpx_track.tracks[0]

    @classmethod
    def from_folder(cls, name: str):
        """Load hike from folder"""
        hike_path = cls.get_folder(name)
        with open(os.path.join(hike_path, 'plan.yaml'), 'r', encoding='utf-8') as plan_file:
            plan = parse_yaml_file_as(HikePlan, plan_file)
        with open(os.path.join(hike_path, 'hike.gpx'), 'r', encoding='utf-8') as gpx_file:
            gpx_track = gpxpy.parse(gpx_file)

        return Hike(slug=name, plan=plan, gpx_track=gpx_track)

    def save(self):
        """Save hike to folder"""
        with open(os.path.join(self.folder, 'plan.yaml'), 'w', encoding='utf-8') as plan_file:
            to_yaml_file(plan_file, self.plan, indent=2, sequence_indent=4)
        with open(os.path.join(self.folder, 'hike.gpx'), 'w', encoding='utf-8') as gpx_file:
            gpx_file.write(self.gpx_track.to_xml())

    def get_stats(self) -> HikeStats:
        """Compute status"""
        length = self.track.length_3d()/1000
        uphill, downhill = self.track.get_uphill_downhill()
        return HikeStats(
            length=length,
            uphill=uphill,
            downhill=downhill
        )

    def get_segment_stats(self, segment_number: int) -> HikeStats:
        """Compute status"""
        length = self.track.segments[segment_number].length_3d()/1000
        uphill, downhill = self.track.segments[segment_number].get_uphill_downhill(
        )
        return HikeStats(
            length=length,
            uphill=uphill,
            downhill=downhill
        )

    def get_iterinary(self, start_time: datetime.timedelta, storage: 'DataStorage') -> List[IterinaryPoint]:
        """Get iterinary"""
        schedule = []
        current_time = start_time
        for i, (place, segment) in enumerate(zip(self.plan.places[:-1], self.plan.segments)):
            delta = place.rest_time
            segment_stats = self.get_segment_stats(i)
            point = storage.points[place.ref]
            schedule.append(
                IterinaryPoint(
                    from_time=format_timedelta(
                        current_time) if len(schedule) > 0 else None,
                    to=format_timedelta(current_time+delta),
                    name=place.name,
                    description=place.description,
                    time=delta,
                    icon=point.type.icon

                ))
            current_time += delta
            delta = segment.time
            schedule.append(IterinaryPoint(
                from_time=format_timedelta(current_time),
                to=format_timedelta(current_time+delta),
                name=segment.name,
                travel_by=segment.travel_by,
                time=delta,
                stats=segment_stats,
                icon=segment.travel_by.icon

            ))

            current_time += delta
        last_place = self.plan.places[-1]
        point = storage.points[last_place.ref]
        schedule.append(IterinaryPoint(
            from_time=format_timedelta(current_time),
            to=None,
            name=last_place.name,
            description=last_place.description,
            time=delta,
            icon=point.type.icon
        ))
        return schedule

    def get_waypoints(self, storage: 'DataStorage') -> list[tuple[Place, Optional[PointOfInterest]]]:
        return [
            (place, storage.points.get(place.ref, None))
            for place in self.plan.places
        ]

    @classmethod
    def create(cls, folder_name: str, waypoints: dict[str, PointOfInterest]) -> 'Hike':
        """Create new Hike"""
        hike_folder = Hike.get_folder(folder_name)
        with open(os.path.join(hike_folder, 'route.gpx'), 'r', encoding='utf-8') as gpx_file:
            track = gpxpy.parse(gpx_file)

        new_gpx = segment_by_waypoints(
            track, [waypoint.gpx for waypoint in waypoints.values()]
        )
        plan = cls.generate_plan(new_gpx, waypoints)
        return cls(slug=folder_name, plan=plan, gpx_track=new_gpx)

    @classmethod
    def generate_plan(cls, hike: GPX, waypoints: dict[str, PointOfInterest]) -> HikePlan:
        places = []
        segments = []
        for ref, waypoint in waypoints.items():
            places.append(
                Place(
                    name=waypoint.name,
                    rest_time='00:00',
                    ref=ref
                )
            )
        for i, _ in enumerate(hike.tracks[0].segments):
            segments.append(
                Segment(
                    name=f'{places[i].name} - {places[i+1].name}',
                    travel_by=TravelBy.FOOT,
                    time='00:00'
                )
            )
        return HikePlan(
            name='Name',
            segments=segments,
            places=places,
            tags=[],
            with_who=[],
            date=datetime.date.today(),
            start_at='09:00'
        )


class Plan(BaseModel):
    pass


class DataStorage(BaseModel):
    points: dict[str, PointOfInterest] = {}
    hikes: dict[str, Hike] = {}
    plans: dict[str, Plan] = {}

    def load(self):
        for name in os.listdir(os.path.join(DATA_DIR, 'hikes')):
            try:
                self.hikes[name] = Hike.from_folder(name)
            except:
                pass
        with open(os.path.join(DATA_DIR, 'points', 'points.yaml'), 'r', encoding='utf-8') as points_file:
            self.points = parse_yaml_file_as(
                dict[str, PointOfInterest], points_file)

    def save(self):
        for hike in self.hikes.values():
            hike.save()
        with open(os.path.join(DATA_DIR, 'points', 'points.yaml'), 'w', encoding='utf-8') as points_file:
            yaml.dump({name: json.loads(point.model_dump_json()) for name,
                      point in self.points.items()}, points_file, allow_unicode=True)

    def init_hike(self, name: str):
        os.mkdir(os.path.join(DATA_DIR, 'hikes', name))
        print(f'Sucessfully created hike with name: {name}')

    def create_from_gpx(self, name: str):
        """Create hikw from gpx files"""
        hike_folder = Hike.get_folder(name)
        new_points_refs = self.add_point_from_file(
            os.path.join(hike_folder, 'waypoints.gpx'), prefix=name)
        self.hikes[name] = Hike.create(name, new_points_refs)

    def find_possible_match(self, point: PointOfInterest, slug: str) -> Optional[str]:
        for slug2, point2 in self.points.items():
            if point2.gpx.distance_2d(point.gpx) < 200:
                return slug2
        for slug2, point2 in self.points.items():
            if slug2.split('-')[-1] == slug:
                return slug2
        return None

    def add_point(self, point: PointOfInterest, prefix: str):
        """Add point"""
        slug = slugify(point.name)
        possible_match = self.find_possible_match(point, slug)
        slug = '-'.join([prefix, slug])
        if possible_match:
            print(
                f'Looks like {slug} is similar to {possible_match}, to merge use:')
            print(f'python manage.py merge-points {possible_match} {slug}')
        self.points[slug] = point
        return slug

    def merge_points(self, slug1: str, slug2: str):
        for hike in self.hikes.values():
            for place in hike.plan.places:
                if place.ref == slug2:
                    place.ref = slug1

        del self.points[slug2]

    def add_point_from_file(self, file_name: str, prefix: str = '') -> dict[str, PointOfInterest]:
        """Add points from gpx file"""
        new_points = {}
        with open(file_name, 'r', encoding='utf-8') as gpx_file:
            waypoints = gpxpy.parse(gpx_file)
            for waypoint in waypoints.waypoints:
                new_point = PointOfInterest(
                    name=waypoint.name,
                    type=PlaceType.guess_from_name(waypoint.name),
                    description=None,
                    lat=waypoint.latitude,
                    lon=waypoint.longitude,
                    elevation=waypoint.elevation

                )
                new_points[self.add_point(new_point, prefix)] = new_point

        return new_points
