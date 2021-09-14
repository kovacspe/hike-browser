import datetime
import os
from typing import NamedTuple

import fire
import yaml
import gpxpy
from gpxpy.gpx import GPXRoutePoint

DATA_DIR = 'source'


class PointOfInterest(NamedTuple):
    gps: GPXRoutePoint
    name: str
    description: str


class HikeStats(NamedTuple):
    uphill: float
    downhill: float
    length: float


def yaml_equivalent_of_default(dumper, data):
    dict_representation = data._asdict()
    node = dumper.represent_dict(dict_representation)
    return node


yaml.add_representer(HikeStats, yaml_equivalent_of_default)
yaml.add_representer(PointOfInterest, yaml_equivalent_of_default)


class Hike:
    def __init__(self, tag, date):
        self.tag = tag
        self.image_paths = []
        self.date = date
        self.with_who = []
        self.hike_stats = None  # type: HikeStats
        self.places = []
        self.expected_time = 0
        self.real_time = 0
        self.md_description = ''

    @classmethod
    def load_from_folder(cls, path):
        #path = os.path.join(DATA_DIR, hike_folder)
        with open(os.path.join(path, 'route.gpx'), 'r', encoding='utf-8') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
        with open(os.path.join(path, 'info.yaml'), 'r', encoding='utf-8') as info_file:
            info = yaml.load(info_file)
        with open(os.path.join(path, 'description.md'), 'r', encoding='utf-8') as desc_file:
            desc = '\n'.join(desc_file.readlines())
        new_hike = cls(info['tag'], info['date'])
        new_hike.image_paths = os.listdir(os.path.join(path, 'img'))
        new_hike.hike_stats = cls._get_stats(gpx)
        new_hike.md_description = desc
        new_hike.hike_stats = HikeStats(**info['hike_stats'])
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


def init_hike(date, name):
    """Initialize data folder"""
    date = datetime.datetime.strptime(date, '%d.%M.%Y')
    year = date.year
    hike_folder = f'{year}-{name}'
    os.mkdir(os.path.join(DATA_DIR, hike_folder))
    os.mkdir(os.path.join(DATA_DIR, hike_folder, 'img'))
    new_hike = Hike(hike_folder, date)
    new_hike.serialize(os.path.join(DATA_DIR, hike_folder))
    print(f'Sucessfully created hike with name: {hike_folder}')


def register(name):
    """Register hike"""

    pass


def load_all():
    hikes_folders = os.listdir(DATA_DIR)
    print(hikes_folders)
    hikes = [Hike.load_from_folder(os.path.join(DATA_DIR, folder))
             for folder in hikes_folders if os.path.isdir(os.path.join(DATA_DIR, folder))]
    print(hikes)
    for hike in hikes:
        print(hike)
        hike.serialize(os.path.join(DATA_DIR, hike.tag))


if __name__ == '__main__':
    fire.Fire({
        'init': init_hike,
        'add': register,
        'load': load_all
    })
