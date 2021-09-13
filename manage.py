import datetime
import os

import fire

DATA_DIR = 'source'


class PointOfInterest:
    def __init__(self):
        self.gps = None
        self.name = None
        self.description = None


class Hike:
    def __init__(self):
        pass

    @classmethod
    def load_from_folder(cls, path):
        pass

    def _fill_stats(gpx_file_path):
        pass

    def to_html(self):
        pass

    def validate(self):
        pass


def init_hike(date, name):
    """Initialize data folder"""
    year = datetime.date()
    os.mkdir(os.path.join(DATA_DIR, f'{year}-{name}'))


def register(name):
    """Register hike"""
    pass


if __name__ == '__main__':
    fire.Fire({
        'init': init_hike,
        'add': register
    })
