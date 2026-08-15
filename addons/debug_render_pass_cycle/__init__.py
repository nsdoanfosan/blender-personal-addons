bl_info = {
    "name": "Debug Render Pass Cycle",
    "author": "PARK / OpenAI",
    "version": (1, 0, 1),
    "blender": (4, 0, 0),
    "location": "3D Viewport (Material Preview / Rendered) > B / M; Sidebar > View",
    "description": "Cycle Unreal-style debug render passes without changing materials",
    "category": "3D View",
}

import bpy
from bpy.props import EnumProperty, StringProperty


OPERATOR_CYCLE_ID = "view3d.cycle_debug_render_pass"
OPERATOR_SET_ID = "view3d.set_debug_render_pass"

# The order favors the passes most useful while authoring materials. Diffuse Color is
# Blender's closest equivalent to Unreal's Base Color buffer visualization.
PASS_SPECS = (
    ("COMBINED", "Combined"),
    ("DIFFUSE_COLOR", "Base Color (Diffuse Color)"),
    ("NORMAL", "Normal"),
    ("POSITION", "Position"),
    ("DIFFUSE_LIGHT", "Diffuse Light"),
    ("SPECULAR_COLOR", "Specular Color"),
    ("SPECULAR_LIGHT", "Specular Light"),
    ("AO", "Ambient Occlusion"),
    ("SHADOW", "Shadow"),
    ("EMISSION", "Emission"),
    ("ENVIRONMENT", "Environment"),
    ("VOLUME_LIGHT", "Volume Light"),
    ("MIST", "Mist"),
    ("TRANSPARENT", "Transparent"),
)

addon_keymaps = []
SUPPORTED_RENDER_ENGINES = {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}


def engine_supports_viewport_passes(engine):
    return engine in SUPPORTED_RENDER_ENGINES


def available_render_pass_ids(context=None):
    """Return passes Blender can expose for the current viewport shading mode."""
    if context is not None:
        if not viewport_supports_debug_passes(context):
            return ()

    prop = bpy.types.View3DShading.bl_rna.properties.get("render_pass")
    if prop is None:
        return ()

    supported = {item.identifier for item in prop.enum_items}
    result = tuple(identifier for identifier, _label in PASS_SPECS if identifier in supported)
    return result


def render_pass_label(identifier):
    labels = dict(PASS_SPECS)
    return labels.get(identifier, identifier.replace("_", " ").title())


def adjacent_render_pass(current, step, pass_ids=None):
    """Get a wrapped neighboring render pass without mutating Blender state."""
    pass_ids = tuple(pass_ids or available_render_pass_ids())
    if not pass_ids:
        return current

    try:
        index = pass_ids.index(current)
    except ValueError:
        index = 0

    return pass_ids[(index + step) % len(pass_ids)]


def apply_adjacent_render_pass(shading, step, pass_ids):
    """Assign the next pass Blender accepts, skipping rejected pass types."""
    pass_ids = tuple(pass_ids)
    if not pass_ids:
        return None

    current = shading.render_pass
    if current in pass_ids:
        start = pass_ids.index(current)
        offsets = range(1, len(pass_ids))
        candidates = (pass_ids[(start + step * offset) % len(pass_ids)] for offset in offsets)
    else:
        candidates = pass_ids if step > 0 else reversed(pass_ids)

    for target in candidates:
        try:
            shading.render_pass = target
        except (TypeError, ValueError):
            continue

        if shading.render_pass == target:
            return target

    try:
        shading.render_pass = current
    except (TypeError, ValueError):
        pass
    return None


def _debug_shading(context):
    area = context.area
    space = context.space_data
    if area is None or area.type != "VIEW_3D":
        return None
    if space is None or space.type != "VIEW_3D":
        return None
    if space.shading.type not in {"MATERIAL", "RENDERED"}:
        return None
    return space.shading


def viewport_supports_debug_passes(context):
    shading = _debug_shading(context)
    if shading is None:
        return False

    # Blender's own Render Pass popover is available in Material Preview for
    # every scene engine, and in Rendered view for Eevee.
    if shading.type == "MATERIAL":
        return True
    return engine_supports_viewport_passes(context.scene.render.engine)


class DEBUGRENDERPASS_OT_cycle(bpy.types.Operator):
    bl_idname = OPERATOR_CYCLE_ID
    bl_label = "Cycle Debug Render Pass"
    bl_description = "Cycle the active viewport through supported debug render passes"
    bl_options = {"INTERNAL"}

    direction: EnumProperty(
        name="Direction",
        items=(
            ("PREVIOUS", "Previous", "Show the previous debug render pass"),
            ("NEXT", "Next", "Show the next debug render pass"),
        ),
        default="NEXT",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        # Passing through is what preserves Blender's normal B/M tools everywhere
        # except a supported Material Preview or Rendered 3D viewport.
        if _debug_shading(context) is None:
            return {"PASS_THROUGH"}
        if len(available_render_pass_ids(context)) < 2:
            return {"PASS_THROUGH"}
        return self.execute(context)

    def execute(self, context):
        shading = _debug_shading(context)
        if shading is None:
            self.report(
                {"WARNING"},
                "Debug passes require Material Preview or a supported Rendered view",
            )
            return {"CANCELLED"}

        pass_ids = available_render_pass_ids(context)
        step = -1 if self.direction == "PREVIOUS" else 1
        target = apply_adjacent_render_pass(shading, step, pass_ids)
        if target is None:
            self.report({"WARNING"}, "No compatible debug render pass is available")
            return {"CANCELLED"}

        context.area.tag_redraw()
        self.report({"INFO"}, f"Debug Render Pass: {render_pass_label(target)}")
        return {"FINISHED"}


class DEBUGRENDERPASS_OT_set(bpy.types.Operator):
    bl_idname = OPERATOR_SET_ID
    bl_label = "Set Debug Render Pass"
    bl_description = "Show a specific pass in the active viewport"
    bl_options = {"INTERNAL"}

    pass_id: StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        shading = _debug_shading(context)
        if shading is None:
            self.report(
                {"WARNING"},
                "Switch to Material Preview or a supported Rendered view first",
            )
            return {"CANCELLED"}

        if self.pass_id not in available_render_pass_ids(context):
            self.report({"ERROR"}, f"Unsupported render pass: {self.pass_id}")
            return {"CANCELLED"}

        try:
            shading.render_pass = self.pass_id
        except (TypeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        context.area.tag_redraw()
        self.report({"INFO"}, f"Debug Render Pass: {render_pass_label(self.pass_id)}")
        return {"FINISHED"}


class DEBUGRENDERPASS_PT_view3d(bpy.types.Panel):
    bl_label = "Debug Render Pass"
    bl_idname = "DEBUGRENDERPASS_PT_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "View"

    def draw(self, context):
        layout = self.layout
        shading = context.space_data.shading
        is_material = shading.type == "MATERIAL"
        is_rendered = shading.type == "RENDERED"
        engine_supported = engine_supports_viewport_passes(context.scene.render.engine)
        is_usable = is_material or (is_rendered and engine_supported)

        if not is_material and not is_rendered:
            layout.label(text="Use Material Preview or Rendered view", icon="INFO")
        elif is_rendered and not engine_supported:
            layout.label(text="This engine has no viewport debug passes", icon="INFO")

        column = layout.column(align=True)
        column.enabled = is_usable
        if is_usable:
            column.label(text=render_pass_label(shading.render_pass), icon="SHADING_RENDERED")

        row = column.row(align=True)
        previous = row.operator(OPERATOR_CYCLE_ID, text="B  Previous", icon="TRIA_LEFT")
        previous.direction = "PREVIOUS"
        next_pass = row.operator(OPERATOR_CYCLE_ID, text="M  Next", icon="TRIA_RIGHT")
        next_pass.direction = "NEXT"

        reset = column.operator(OPERATOR_SET_ID, text="Combined", icon="FILE_REFRESH")
        reset.pass_id = "COMBINED"

        layout.separator()
        layout.label(text="B/M override in Material Preview / Rendered")


classes = (
    DEBUGRENDERPASS_OT_cycle,
    DEBUGRENDERPASS_OT_set,
    DEBUGRENDERPASS_PT_view3d,
)


def register_keymaps():
    key_config = bpy.context.window_manager.keyconfigs.addon
    if key_config is None:
        return

    keymap = key_config.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
        region_type="WINDOW",
    )

    for key, direction in (("B", "PREVIOUS"), ("M", "NEXT")):
        keymap_item = keymap.keymap_items.new(
            OPERATOR_CYCLE_ID,
            type=key,
            value="PRESS",
            head=True,
        )
        keymap_item.properties.direction = direction
        addon_keymaps.append((keymap, keymap_item))


def unregister_keymaps():
    for keymap, keymap_item in addon_keymaps:
        try:
            keymap.keymap_items.remove(keymap_item)
        except (ReferenceError, RuntimeError):
            pass
    addon_keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
