
import os
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic_yaml import parse_yaml_file_as

from models import DataStorage, Hike
from settings import BASE_DIR, DATA_DIR, OUTPUT_DIR

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)


class PageBuilder:
    def __init__(self, storage: DataStorage, output_dir: str):
        self.storage = storage
        self.output_dir = output_dir

    def build_places_map(self):
        data = {
            'points': list(self.storage.points.values())
        }
        template = env.get_template('places_map.html')
        with open(os.path.join(self.output_dir, 'places_map.html'), 'w', encoding='utf-8') as html_file:
            html_file.write(template.render(**data))

    def build_index(self):
        data = {'hikes': [
            {
                'slug': hike.slug,
                'name': hike.plan.name
            } for hike in self.storage.hikes.values()
        ]}
        template = env.get_template('index.html')
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf-8') as html_file:
            html_file.write(template.render(**data))

    def build_hike_page(self, name: str):
        template = env.get_template('hike.html')
        hike = Hike.from_folder(name)
        with open(os.path.join(self.output_dir, 'hike', f'{name}.html'), 'w', encoding='utf-8') as html_file:
            html_file.write(template.render(**hike.as_dict()))

    def build_pages(self):
        """Build all pages"""
        shutil.rmtree(self.output_dir)
        os.mkdir(self.output_dir)
        os.mkdir(os.path.join(self.output_dir, 'hike'))
        for name in os.listdir(os.path.join(DATA_DIR, 'hikes')):
            self.build_hike_page(name)

        self.build_index()
        self.build_places_map()
        shutil.copytree(os.path.join(BASE_DIR, 'static'),
                        os.path.join(self.output_dir, 'static'))
