import datetime
import os

import unidecode
from gpxpy.gpx import GPX, GPXTrack, GPXTrackSegment, GPXWaypoint


def is_group(folder_path: str) -> bool:
    return 'group_info.yaml' in os.listdir(folder_path)


def to_camel_case(name: str):
    words = name.split()
    words = [word[0].upper()+word[1:].lower() for word in words]
    return ''.join(words)


def slugify(name: str) -> str:
    name = unidecode.unidecode(name)
    name = to_camel_case(name)
    return name


def yaml_equivalent_of_default(dumper, data):
    dict_representation = data._asdict()
    node = dumper.represent_dict(dict_representation)
    return node


def parse_timedelta(time):
    hours, minutes = time.split(':')
    return datetime.timedelta(hours=int(hours), minutes=int(minutes))


def format_timedelta(time: datetime.timedelta):
    return ':'.join(str(time).split(':')[:2])


def segment_by_waypoints(track: GPX, waypoints: list[GPXWaypoint]):
    """Divide track by waypoints"""
    segments = []
    last_point = 0
    for waypoint in waypoints[1:]:
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
    new_file.waypoints = waypoints
    return new_file
