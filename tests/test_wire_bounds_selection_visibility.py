import addon_utils
import bpy


MODULE = "wire_bounds_selection_visibility"


def make_object(name, display_type):
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.display_type = display_type
    return obj


addon_utils.enable(MODULE, default_set=False)
addon = __import__(MODULE)

scene = bpy.context.scene
view_layer = bpy.context.view_layer

assert not hasattr(addon, "_timer")
assert not hasattr(bpy.types, "WBSV_PT_panel")
assert not hasattr(bpy.types.Scene, "wbsv_enabled")
assert not hasattr(bpy.types.Scene, "wbsv_auto_capture")
assert not hasattr(addon, "_depsgraph_update_post")

wire = make_object("WBSV_Wire", "WIRE")
bounds = make_object("WBSV_Bounds", "BOUNDS")
solid = make_object("WBSV_Solid", "TEXTURED")

bpy.ops.object.select_all(action="DESELECT")
view_layer.objects.active = None
addon._active_name_by_view_layer.clear()
addon._shown_names_by_view_layer.clear()
addon._initialize_view_layer(scene, view_layer)

assert wire.hide_get(view_layer=view_layer)
assert bounds.hide_get(view_layer=view_layer)
assert not solid.hide_get(view_layer=view_layer)

view_layer.objects.active = wire
addon._on_active_object_changed()
assert not wire.hide_get(view_layer=view_layer)
assert wire.display_type == "WIRE"
assert wire.select_get(view_layer=view_layer)
assert not addon._show_object(wire, view_layer, select=True)

wire.select_set(False, view_layer=view_layer)
solid.select_set(True, view_layer=view_layer)
view_layer.objects.active = solid
addon._on_active_object_changed()
assert wire.hide_get(view_layer=view_layer)
assert not solid.hide_get(view_layer=view_layer)
assert not addon._hide_object(wire, view_layer)

solid.select_set(False, view_layer=view_layer)
view_layer.objects.active = bounds
addon._on_active_object_changed()
assert not bounds.hide_get(view_layer=view_layer)
assert bounds.display_type == "WIRE"
assert bounds.select_get(view_layer=view_layer)

bounds.select_set(False, view_layer=view_layer)
view_layer.objects.active = None
addon._on_active_object_changed()
assert bounds.hide_get(view_layer=view_layer)
assert bounds.display_type == "BOUNDS"

late = make_object("WBSV_Late", "TEXTURED")
assert not late.wbsv_managed
late.display_type = "WIRE"
addon._on_display_type_changed()
assert late.wbsv_managed
assert late.hide_get(view_layer=view_layer)

disabled = make_object("WBSV_Disabled", "WIRE")
disabled.hide_viewport = True
addon._capture_object(disabled, view_layer)
disabled.hide_set(True, view_layer=view_layer)
view_layer.objects.active = disabled
addon._on_active_object_changed()
assert not disabled.hide_viewport
assert not disabled.hide_get(view_layer=view_layer)
assert disabled.select_get(view_layer=view_layer)

disabled.select_set(False, view_layer=view_layer)
view_layer.objects.active = None
addon._on_active_object_changed()
assert disabled.hide_viewport
assert disabled.hide_get(view_layer=view_layer)

addon_utils.disable(MODULE, default_set=False)
assert wire.display_type == "WIRE"
assert bounds.display_type == "BOUNDS"
assert disabled.display_type == "WIRE"
assert late.display_type == "WIRE"
assert not wire.hide_get(view_layer=view_layer)
assert not bounds.hide_get(view_layer=view_layer)
assert not late.hide_get(view_layer=view_layer)
assert not disabled.hide_get(view_layer=view_layer)
assert disabled.hide_viewport
assert not solid.hide_get(view_layer=view_layer)
print("WBSV_SMOKE_OK")
