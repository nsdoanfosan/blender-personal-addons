import addon_utils
import bpy


MODULE = "ta_tools"
OPERATOR_IDNAME = "view3d.ta_toggle_wire_overlay"


addon_utils.enable(MODULE, default_set=False)

assert hasattr(bpy.types, "VIEW3D_OT_ta_toggle_wire_overlay")
for property_name in (
    "show_wireframes",
    "show_edge_sharp",
    "show_edge_seams",
    "show_edge_bevel_weight",
):
    assert property_name in bpy.types.View3DOverlay.bl_rna.properties

key_config = bpy.context.window_manager.keyconfigs.addon
keymap = key_config.keymaps.get("3D View")
assert keymap is not None

bindings = [
    item
    for item in keymap.keymap_items
    if item.idname == OPERATOR_IDNAME
]
assert len(bindings) == 4

expected_bindings = {
    "WIREFRAME": "F4",
    "SHARP": "F5",
    "SEAM": "F6",
    "BEVEL_WEIGHT": "F7",
}
actual_bindings = {
    item.properties.overlay_type: item.type
    for item in bindings
}
assert actual_bindings == expected_bindings

for binding in bindings:
    assert binding.value == "PRESS"
    assert not binding.ctrl
    assert not binding.shift
    assert not binding.alt

addon_utils.disable(MODULE, default_set=False)

remaining = [
    item
    for item in keymap.keymap_items
    if item.idname == OPERATOR_IDNAME
]
assert not remaining
assert not hasattr(bpy.types, "VIEW3D_OT_ta_toggle_wire_overlay")

print("TA_TOOLS_WIRE_OVERLAY_HOTKEY_OK")
