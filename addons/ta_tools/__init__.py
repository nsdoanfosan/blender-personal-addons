bl_info = {
    "name": "TA Tools",
    "author": "PARK",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar",
    "description": "Personal collection, naming, linked object, and mesh utilities",
    "category": "Object",
}

from . import export_collections
from . import linked_object
from . import move_collection
from . import rename_objects
from . import scene_collection_object_renamer
from . import ta_tool


modules = (
    export_collections,
    linked_object,
    move_collection,
    rename_objects,
    scene_collection_object_renamer,
    ta_tool,
)


def register():
    for module in modules:
        module.register()


def unregister():
    for module in reversed(modules):
        module.unregister()
