bl_info = {
    "name": "TA UV Tools",
    "author": "PARK",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "UV Editor",
    "description": "Personal UV fitting and 90 degree rotation utilities",
    "category": "UV",
}

from . import fit_uv_uniform
from . import rotate_90_hotkeys


modules = (
    fit_uv_uniform,
    rotate_90_hotkeys,
)


def register():
    for module in modules:
        module.register()


def unregister():
    for module in reversed(modules):
        module.unregister()
