import os
import unidecode


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
