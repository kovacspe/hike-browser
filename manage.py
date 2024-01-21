import os

import shutil
import fire
from PIL import Image
from tqdm import tqdm

from models import Hike, HikeFactory
from settings import DATA_DIR, OUTPUT_DIR, BASE_DIR

from jinja2 import Environment, FileSystemLoader, select_autoescape


import datetime
env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape()
)


def init_hike(name: str):
    """Initialize data folder"""
    os.mkdir(os.path.join(DATA_DIR, 'hikes', name))
    print(f'Sucessfully created hike with name: {name}')


def generate(name: str):
    """Register hike"""
    hike = HikeFactory.create(name)
    hike.save()


def build_pages():
    shutil.rmtree(OUTPUT_DIR)
    os.mkdir(OUTPUT_DIR)
    os.mkdir(os.path.join(OUTPUT_DIR, 'hike'))
    for name in os.listdir(os.path.join(DATA_DIR, 'hikes')):
        try:
            build_hike_page(name)
        except:
            pass
    build_index()
    shutil.copytree(os.path.join(BASE_DIR, 'static'),
                    os.path.join(OUTPUT_DIR, 'static'))


def build_index():
    data = {'hikes': []}
    for name in os.listdir(os.path.join(DATA_DIR, 'hikes')):
        try:
            hike = Hike.from_folder(name)
            data['hikes'].append(
                {
                    'slug': hike.slug,
                    'name': hike.plan.name
                }
            )
        except:
            pass
    template = env.get_template('index.html')
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as html_file:
        html_file.write(template.render(**data))


def build_hike_page(name: str):
    template = env.get_template('hike.html')
    hike = Hike.from_folder(name)
    with open(os.path.join(OUTPUT_DIR, 'hike', f'{name}.html'), 'w', encoding='utf-8') as html_file:
        html_file.write(template.render(**hike.as_dict()))


def rotate_images(path: str):
    if path.endswith('*'):
        paths = [os.path.join(path[:-1], photo)
                 for photo in os.listdir(path[:-1])]
    else:
        paths = [path]
    for path in tqdm(paths):
        img = Image.open(path)
        img = img.transpose(Image.ROTATE_90)
        img.save(path)


if __name__ == '__main__':
    fire.Fire({
        'init': init_hike,
        'generate': generate,
        'rotateimg': rotate_images,
        'build': build_hike_page,
        'build-all': build_pages,
        'build-index': build_index
    })
