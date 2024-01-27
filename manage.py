
import fire

from build import PageBuilder
from models import DataStorage
from settings import OUTPUT_DIR

if __name__ == '__main__':
    storage = DataStorage()
    storage.load()
    builder = PageBuilder(storage=storage, output_dir=OUTPUT_DIR)
    fire.Fire({
        'init': storage.init_hike,
        'generate': storage.create_from_gpx,
        'build': builder.build_hike_page,
        'build-all': builder.build_pages,
        'build-index': builder.build_index
    })
    storage.save()
