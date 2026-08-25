import addon_utils
import bpy


MODULE = "ta_tools"
OPERATOR_IDNAME = "view3d.ta_toggle_wire_overlay"


addon_utils.enable(MODULE, default_set=False)

assert hasattr(bpy.types, "VIEW3D_OT_ta_toggle_wire_overlay")
assert "show_wireframes" in bpy.types.View3DOverlay.bl_rna.properties

key_config = bpy.context.window_manager.keyconfigs.addon
keymap = key_config.keymaps.get("3D View")
assert keymap is not None

bindings = [
    item
    for item in keymap.keymap_items
    if item.idname == OPERATOR_IDNAME
]
assert len(bindings) == 1

binding = bindings[0]
assert binding.type == "F4"
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
