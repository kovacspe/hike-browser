import datetime
import os
from typing import NamedTuple

import fire
import yaml
import gpxpy
from gpxpy.gpx import GPXRoutePoint


from utils import yaml_equivalent_of_default, slugify, is_group
from settings import DATA_DIR


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


# class HikeEntity:
#     def __init__(self, name):
#         self.name = name

#     @classmethod
#     def load_by_slug(cls, slug):
#         path = os.path.join(DATA_DIR, slug)
#         return cls.load_from_folder(path)


class Group:
    def __init__(self, name, start_date, end_date, slug=None):
        self.slug = slug or f'{start_date.year}-{slugify(name)}'
        self.name = name
        self.start_date = start_date
        self.end_date = end_date
        self.md_description = ''
        self.hikes = []

    @classmethod
    def load_by_slug(cls, slug: str):
        path = os.path.join(DATA_DIR, slug)
        print(f'Loading group from {path}')
        return cls.load_from_folder(path)

    @classmethod
    def load_from_folder(cls, path):
        if not is_group(path):
            raise ValueError(f'{path} is not a group')
        with open(os.path.join(path, 'group_info.yaml'), 'r', encoding='utf-8') as info_file:
            info = yaml.load(info_file)
        start_date = datetime.datetime.strptime(info['start_date'], '%d.%M.%Y')
        end_date = datetime.datetime.strptime(info['end_date'], '%d.%M.%Y')
        group = cls(info['name'], start_date, end_date,
                    slug=info.get('slug', None))
        group.hikes = cls.retrieve_hikes()
        return group

    def serialize(self, path):
        with open(os.path.join(path, 'group_info.yaml'), 'w', encoding='utf-8') as info_file:
            info = self.__dict__
            yaml.dump(info, info_file)
        with open(os.path.join(path, 'description.md'), 'w', encoding='utf-8') as desc_file:
            desc_file.write(self.md_description)


class Hike:
    def __init__(self, name, date, slug):
        self.name = name
        self.slug = slug or f'{date.year}-{slugify(name)}'
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
    def load_by_slug(cls, slug):
        path = os.path.join(DATA_DIR, slug)
        print(f'Loading hike from {path}')
        return cls.load_from_folder(path)

    @classmethod
    def load_from_folder(cls, path):
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
        new_hike = cls(info.get('name', 'NAZOVS'),
                       info['date'], slug=info.get('slug', None))
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
