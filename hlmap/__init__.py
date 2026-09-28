"""hlmap - write Half-Life (GoldSrc) maps as Python code, compile and preview them.

Typical map script (maps/<name>.py) defines build() -> Map. See CLAUDE.md.
"""
from .geometry import Brush, Face, box, prism, wedge, cylinder, hull, make_face
from .mapfile import Map, Entity
from .level import Level, Material, Room, Opening, AABB
from . import props

__all__ = ["Brush", "Face", "box", "prism", "wedge", "cylinder", "hull", "make_face",
           "Map", "Entity", "Level", "Material", "Room", "Opening", "AABB", "props"]
