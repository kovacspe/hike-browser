import datetime
import os
from typing import NamedTuple

import fire
import yaml
import gpxpy
from gpxpy.gpx import GPXRoutePoint


from utils import yaml_equivalent_of_default, slugify


class PointOfInterest(NamedTuple):
    gps: GPXRoutePoint
    name: str
    description: str


class HikeStats(NamedTuple):
    uphill: float
    downhill: float
    length: float


yaml.add_representer(HikeStats, yaml_equivalent_of_default)
yaml.add_representer(PointOfInterest, yaml_equivalent_of_default)


class Group:
    def __init__(self):
        self.slug = None
        self.description = ''
        self.hikes = []

    @classmethod
    def load_from_folder(cls, path):
        pass


class Hike:
    def __init__(self, name, date):
        self.name = name
        self.slug = f'{date.year}-{slugify(name)}'
        self.image_paths = []
        self.date = date
        self.start_name = None
        self.end_name = None
        self.with_who = []
        self.hike_stats = None  # type: HikeStats
        self.places = []
        self.expected_time = 0
        self.real_time = 0
        self.md_description = ''

    @classmethod
    def load_from_folder(cls, path):
        #path = os.path.join(DATA_DIR, hike_folder)
        if os.path.exists(os.path.join(path, 'route.gpx')):
            with open(os.path.join(path, 'route.gpx'), 'r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                hike_stats = cls._get_stats(gpx)
        else:
            gpx = None
            hike_stats = {}

        with open(os.path.join(path, 'info.yaml'), 'r', encoding='utf-8') as info_file:
            info = yaml.load(info_file)
        with open(os.path.join(path, 'description.md'), 'r', encoding='utf-8') as desc_file:
            desc = '\n'.join(desc_file.readlines())
        new_hike = cls(info['tag'], info['date'])
        new_hike.image_paths = os.listdir(os.path.join(path, 'img'))
        new_hike.hike_stats = hike_stats
        new_hike.md_description = desc
        if info['hike_stats'] is not None:
            new_hike.hike_stats = HikeStats(**info['hike_stats'])
        else:
            new_hike.hike_stats = None
        return new_hike

    @staticmethod
    def _get_stats(gpx):
        route = gpx.tracks[0].segments[0]
        length = route.length_3d()/1000
        uphill, downhill = route.get_uphill_downhill()
        return HikeStats(
            length=length,
            uphill=uphill,
            downhill=downhill
        )

    def to_html(self):
        pass

    def validate(self):
        pass

    def serialize(self, path):
        with open(os.path.join(path, 'info.yaml'), 'w', encoding='utf-8') as info_file:
            info = self.__dict__
            yaml.dump(info, info_file)
        with open(os.path.join(path, 'description.md'), 'w', encoding='utf-8') as desc_file:
            desc_file.write(self.md_description)

    def __str__(self):
        return str(self.__dict__)
