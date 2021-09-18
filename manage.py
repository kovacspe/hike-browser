import datetime
import os
from typing import NamedTuple

import fire
import yaml
import gpxpy
from gpxpy.gpx import GPXRoutePoint

from models import Hike, Group
from utils import is_group
from settings import DATA_DIR


def init_hike(date, name):
    """Initialize data folder"""
    date = datetime.datetime.strptime(date, '%d.%M.%Y')
    new_hike = Hike(name, date)
    hike_folder = new_hike.slug
    os.mkdir(os.path.join(DATA_DIR, hike_folder))
    os.mkdir(os.path.join(DATA_DIR, hike_folder, 'img'))

    new_hike.serialize(os.path.join(DATA_DIR, hike_folder))
    print(f'Sucessfully created hike with name: {hike_folder}')


def register(name):
    """Register hike"""

    pass


def load_all():
    groups = []
    hikes = []
    for folder in os.listdir(DATA_DIR):
        folder_path = os.path.join(DATA_DIR, folder)
        print(folder_path)
        if not os.path.isdir(folder_path):
            continue
        if is_group(folder_path):
            groups.append(Group.load_from_folder(folder_path))
            hikes += groups[-1].hikes
        else:
            hikes.append(Hike.load_from_folder(folder_path))
    return hikes, groups
    # for hike in hikes:
    #     print(hike)
    #     hike.serialize(os.path.join(DATA_DIR, hike.slug))


if __name__ == '__main__':
    fire.Fire({
        'init': init_hike,
        'add': register,
        'load': load_all
    })
