import bpy


OPERATOR_IDNAME = "view3d.ta_toggle_wire_overlay"
KEYMAP_NAME = "3D View"
addon_keymaps = []


class VIEW3D_OT_ta_toggle_wire_overlay(bpy.types.Operator):
    bl_idname = OPERATOR_IDNAME
    bl_label = "Toggle Viewport Wire Overlay"
    bl_description = "Show or hide wire edges without changing the current viewport shading mode"

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
        overlay.show_wireframes = not overlay.show_wireframes
        context.area.tag_redraw()

        state = "shown" if overlay.show_wireframes else "hidden"
        self.report({"INFO"}, f"Viewport wire overlay {state}")
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

    keymap_item = keymap.keymap_items.new(
        OPERATOR_IDNAME,
        type="F4",
        value="PRESS",
    )
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
