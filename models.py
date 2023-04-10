import datetime
import os
from typing import NamedTuple, List, Optional
from pydantic_yaml import YamlModel, YamlStrEnum, YamlStr
from pydantic import validator


import gpxpy
from gpxpy.gpx import GPX, GPXTrack, GPXTrackSegment

from utils import format_timedelta
from settings import DATA_DIR


class Time(YamlStr):
    @property
    def time(self):
        hours, minutes = self.split(':')
        return datetime.timedelta(hours=int(hours), minutes=int(minutes))


class PlaceType(YamlStrEnum):
    SIGN_POST = 'Rázcestník'
    POINT_OF_INTEREST = 'Zaujímavosť'
    MEMORY = 'Spomienka'
    SLEEPING_PLACE = 'Prespávanie'


class TravelBy(YamlStrEnum):
    FOOT = 'foot'
    CAR = 'car'
    BIKE = 'bike'
    PUBLIC_TRANSPORT = 'pt'


class Place(YamlModel):
    name: str
    rest_time: Time
    type: PlaceType
    description: str = None

    @validator('rest_time')
    def _check_start_at(cls, v: str) -> Time:  # noqa
        """You can add your normal pydantic validators, like this one."""
        return Time(v)


class Segment(YamlModel):
    name: str
    time: Time
    travel_by: TravelBy

    @validator('time')
    def _check_time(cls, v: str) -> Time:  # noqa
        """You can add your normal pydantic validators, like this one."""
        return Time(v)


class HikePlan(YamlModel):
    name: str
    date: datetime.date
    start_at: Time
    with_who: List[str]
    tags: List[str]
    segments: List[Segment]
    places: List[Place]

    @validator('start_at')
    def _check_start_at(cls, v: str) -> Time:  # noqa
        """You can add your normal pydantic validators, like this one."""
        return Time(v)


class HikeStats(NamedTuple):
    uphill: float
    downhill: float
    length: float
    time: Optional[datetime.timedelta] = None


class IterinaryPoint(NamedTuple):
    from_time: datetime.time
    to: datetime.time
    time: datetime.timedelta
    name: str
    description: Optional[str] = None
    travel_by: Optional[TravelBy] = None
    stats: Optional[HikeStats] = None


class Hike:
    def __init__(self, slug: str, plan: HikePlan, gpx_track: GPX):
        self.plan = plan
        self.slug = slug
        self.gpx_track = gpx_track

    @staticmethod
    def get_folder(name: str) -> str:
        """Get hike folder path by name"""
        return os.path.join(DATA_DIR, name)

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
        plan = HikePlan.parse_file(os.path.join(hike_path, 'plan.yaml'))
        with open(os.path.join(hike_path, 'hike.gpx'), 'r', encoding='utf-8') as gpx_file:
            gpx_track = gpxpy.parse(gpx_file)
        return Hike(name, plan, gpx_track)

    def save(self):
        """Save hike to folder"""
        with open(os.path.join(self.folder, 'plan.yaml'), 'w', encoding='utf-8') as plan_file:
            plan_file.write(self.plan.yaml())
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

    def get_iterinary(self, start_time: Time) -> List[IterinaryPoint]:
        """Get iterinary"""
        schedule = []
        current_time = start_time.time
        for i, (place, segment) in enumerate(zip(self.plan.places[:-1], self.plan.segments)):
            delta = place.rest_time.time
            segment_stats = self.get_segment_stats(i)
            schedule.append(
                IterinaryPoint(
                    from_time=format_timedelta(
                        current_time) if current_time else None,
                    to=format_timedelta(current_time+delta),
                    name=place.name,
                    description=place.description,
                    time=delta

                ))
            current_time += delta
            delta = segment.time.time
            schedule.append(IterinaryPoint(
                from_time=format_timedelta(current_time),
                to=format_timedelta(current_time+delta),
                name=segment.name,
                travel_by=segment.travel_by,
                time=delta,
                stats=segment_stats

            ))

            current_time += delta
        last_place = self.plan.places[-1]
        schedule.append(IterinaryPoint(
            from_time=format_timedelta(current_time),
            to=None,
            name=last_place.name,
            description=last_place.description,
            time=delta
        ))
        return schedule

    def as_dict(self):
        """Serialize to dictionary"""
        serialized = {}
        serialized['schedule'] = self.get_iterinary(self.plan.start_at)
        serialized['stats'] = self.get_stats()
        return serialized


class HikeFactory:

    @staticmethod
    def generate_metadata_dict(hike: GPX):
        places = []
        segments = []
        for waypoint in hike.waypoints:
            places.append(
                Place(
                    name=waypoint.name,
                    rest_time='00:00',
                    type=PlaceType.SIGN_POST
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
            start_at='9:00'
        )

    @staticmethod
    def segment_by_waypoints(track: GPX, waypoints: GPX):
        """Divide track by waypoints"""
        segments = []
        last_point = 0
        for waypoint in waypoints.waypoints[1:-1]:
            point_on_track = track.get_nearest_location(waypoint)
            segments.append(
                GPXTrackSegment(
                    track.tracks[0].segments[0].points[last_point:point_on_track.point_no]
                )
            )
            last_point = point_on_track.point_no
        new_file = GPX()
        new_track = GPXTrack()
        new_track.segments = segments
        new_file.tracks = [new_track]
        new_file.waypoints = waypoints.waypoints
        return new_file

    @classmethod
    def create(cls, folder_name: str) -> Hike:
        """Create new Hike"""
        hike_folder = Hike.get_folder(folder_name)
        with open(os.path.join(hike_folder, 'route.gpx'), 'r', encoding='utf-8') as gpx_file:
            track = gpxpy.parse(gpx_file)
        with open(os.path.join(hike_folder, 'waypoints.gpx'), 'r', encoding='utf-8') as gpx_file:
            waypoints = gpxpy.parse(gpx_file)
        new_gpx = cls.segment_by_waypoints(track, waypoints)
        plan = cls.generate_metadata_dict(new_gpx)
        return Hike(folder_name, plan, new_gpx)
