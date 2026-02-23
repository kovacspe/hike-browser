from enum import Enum


class ItemType(str, Enum):
    POI = "poi"
    TRANSPORT = "transport"


class TransportType(str, Enum):
    WALK = "walk"
    TRAIN = "train"
    CAR = "car"


class POIType(str, Enum):
    ACCOMMODATION = "accommodation"
    RESTAURANT = "restaurant"
    VIEWPOINT = "viewpoint"
    CAVE = "cave"
    SPRING = "spring"
