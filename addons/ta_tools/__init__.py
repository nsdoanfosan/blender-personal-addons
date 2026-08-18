bl_info = {
    "name": "TA Tools",
    "author": "PARK",
    "version": (1, 2, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar; Ctrl+Shift+J",
    "description": "Personal collection, naming, linked object, mesh utilities, and quick menu",
    "category": "Object",
}

from . import export_collections
from . import alpha_image_to_mesh
from . import curve_fit_plane
from . import linked_object
from . import move_collection
from . import rename_objects
from . import scene_collection_object_renamer
from . import ta_tool
from . import face_sets_to_materials
from . import quick_menu


modules = (
    export_collections,
    alpha_image_to_mesh,
    curve_fit_plane,
    linked_object,
    move_collection,
    rename_objects,
    scene_collection_object_renamer,
    ta_tool,
    face_sets_to_materials,
    quick_menu,
)


def register():
    for module in modules:
        module.register()


def unregister():
    for module in reversed(modules):
        module.unregister()
