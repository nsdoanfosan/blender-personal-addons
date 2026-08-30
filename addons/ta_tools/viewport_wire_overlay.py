import bpy
from bpy.props import EnumProperty


OPERATOR_IDNAME = "view3d.ta_toggle_wire_overlay"
KEYMAP_NAME = "3D View"
addon_keymaps = []

OVERLAY_SETTINGS = {
    "WIREFRAME": ("show_wireframes", "Wire"),
    "SHARP": ("show_edge_sharp", "Sharp edges"),
    "SEAM": ("show_edge_seams", "Seams"),
    "BEVEL_WEIGHT": ("show_edge_bevel_weight", "Bevel weights"),
}

HOTKEYS = (
    ("WIREFRAME", "F4"),
    ("SHARP", "F5"),
    ("SEAM", "F6"),
    ("BEVEL_WEIGHT", "F7"),
)


class VIEW3D_OT_ta_toggle_wire_overlay(bpy.types.Operator):
    bl_idname = OPERATOR_IDNAME
    bl_label = "Toggle Viewport Overlay"
    bl_description = "Show or hide a viewport overlay without changing the current shading mode"

    overlay_type: EnumProperty(
        name="Overlay",
        items=(
            ("WIREFRAME", "Wire", "Show or hide wire edges"),
            ("SHARP", "Sharp", "Show or hide sharp edge marks"),
            ("SEAM", "Seam", "Show or hide seam edge marks"),
            ("BEVEL_WEIGHT", "Bevel Weight", "Show or hide bevel weight edge marks"),
        ),
        default="WIREFRAME",
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.space_data is not None
            and context.space_data.type == "VIEW_3D"
        )

    def execute(self, context):
        overlay = context.space_data.overlay
        property_name, label = OVERLAY_SETTINGS[self.overlay_type]
        new_state = not getattr(overlay, property_name)
        setattr(overlay, property_name, new_state)
        context.area.tag_redraw()

        state = "shown" if new_state else "hidden"
        self.report({"INFO"}, f"Viewport {label} overlay {state}")
        return {"FINISHED"}


classes = (VIEW3D_OT_ta_toggle_wire_overlay,)


def _register_keymap():
    window_manager = bpy.context.window_manager
    key_config = window_manager.keyconfigs.addon if window_manager else None
    if key_config is None:
        return

    keymap = key_config.keymaps.new(name=KEYMAP_NAME, space_type="VIEW_3D")

    # Remove a stale copy left by a script reload before adding the current binding.
    for keymap_item in list(keymap.keymap_items):
        if keymap_item.idname == OPERATOR_IDNAME:
            keymap.keymap_items.remove(keymap_item)

    for overlay_type, key_type in HOTKEYS:
        keymap_item = keymap.keymap_items.new(
            OPERATOR_IDNAME,
            type=key_type,
            value="PRESS",
        )
        keymap_item.properties.overlay_type = overlay_type
        addon_keymaps.append((keymap, keymap_item))


def _unregister_keymap():
    for keymap, keymap_item in addon_keymaps:
        try:
            keymap.keymap_items.remove(keymap_item)
        except (ReferenceError, RuntimeError):
            pass
    addon_keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keymap()


def unregister():
    _unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
