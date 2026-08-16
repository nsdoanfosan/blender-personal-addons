bl_info = {
    "name": "Debug Render Pass Cycle",
    "author": "PARK / OpenAI",
    "version": (1, 2, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport (Material Preview / Rendered) > B / M; Sidebar > View",
    "description": "Cycle Unreal-style debug render passes without changing materials",
    "category": "3D View",
}

import blf
import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, StringProperty


OPERATOR_CYCLE_ID = "view3d.cycle_debug_render_pass"
OPERATOR_SET_ID = "view3d.set_debug_render_pass"

# The order favors the passes most useful while authoring materials. Diffuse Color is
# Blender's closest equivalent to Unreal's Base Color buffer visualization.
PASS_SPECS = (
    ("COMBINED", "Combined"),
    ("DIFFUSE_COLOR", "Base Color (Diffuse Color)"),
    ("NORMAL", "Normal"),
    ("SPECULAR_COLOR", "Specular Color"),
    ("AO", "Ambient Occlusion"),
    ("TRANSPARENT", "Transparent"),
    ("MIST", "Scene Depth (Mist)"),
    ("POSITION", "World Position"),
)

CUSTOM_VIEW_SPECS = (
    ("ATTRIBUTE_FACTOR", "Factor"),
    ("ATTRIBUTE_RANDOM", "Random"),
    ("ATTRIBUTE_MESH_AO", "Mesh AO"),
)

VIEW_SPECS = (
    PASS_SPECS[0],
    PASS_SPECS[1],
    *CUSTOM_VIEW_SPECS,
    *PASS_SPECS[2:],
)

CUSTOM_VIEW_CHANNELS = {
    "ATTRIBUTE_FACTOR": ("Factor", "R"),
    "ATTRIBUTE_RANDOM": ("Random", "G"),
    "ATTRIBUTE_MESH_AO": ("AO", "B"),
}

DEBUG_MATERIAL_TAG = "debug_render_pass_cycle_runtime"
DEBUG_MATERIAL_PREFIX = ".DebugRenderPassCycle_"

SUPPORTED_RENDER_ENGINES = {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}

_listener_enabled = False
_listener_token = object()
_listener_window_ids = set()
_custom_view_by_space = {}
_material_override_states = {}
_debug_materials = {}
_draw_handler = None
LISTENER_BL_IDNAME = "WM_OT_debug_render_pass_input_listener"
LISTENER_WATCHDOG_INTERVAL = 2.0


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


def available_debug_view_ids(context=None):
    """Return built-in passes plus attribute views supported by this context."""
    render_pass_ids = available_render_pass_ids(context)
    if not render_pass_ids:
        return ()

    supports_material_override = (
        context is not None
        and getattr(context, "view_layer", None) is not None
        and hasattr(context.view_layer, "material_override")
        and getattr(context, "space_data", None) is not None
        and hasattr(context.space_data, "as_pointer")
    )
    if not supports_material_override:
        return render_pass_ids

    supported = set(render_pass_ids)
    supported.update(identifier for identifier, _label in CUSTOM_VIEW_SPECS)
    return tuple(identifier for identifier, _label in VIEW_SPECS if identifier in supported)


def render_pass_label(identifier):
    labels = dict(VIEW_SPECS)
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


def _is_debug_material(material):
    return bool(material and material.get(DEBUG_MATERIAL_TAG, False))


def _build_debug_material(view_id):
    attribute_name, packed_channel = CUSTOM_VIEW_CHANNELS[view_id]
    material = bpy.data.materials.new(f"{DEBUG_MATERIAL_PREFIX}{view_id}")
    material[DEBUG_MATERIAL_TAG] = True
    material.use_nodes = True

    node_tree = material.node_tree
    node_tree.nodes.clear()
    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    emission = node_tree.nodes.new("ShaderNodeEmission")
    named_attribute = node_tree.nodes.new("ShaderNodeAttribute")
    packed_attribute = node_tree.nodes.new("ShaderNodeAttribute")
    separate = node_tree.nodes.new("ShaderNodeSeparateColor")
    maximum = node_tree.nodes.new("ShaderNodeMath")

    named_attribute.attribute_name = attribute_name
    packed_attribute.attribute_name = "ChannelPacked_FRAO"
    separate.mode = "RGB"
    maximum.operation = "MAXIMUM"
    emission.inputs["Strength"].default_value = 1.0

    channel_socket = {
        "R": "Red",
        "G": "Green",
        "B": "Blue",
    }[packed_channel]
    node_tree.links.new(named_attribute.outputs["Fac"], maximum.inputs[0])
    node_tree.links.new(packed_attribute.outputs["Color"], separate.inputs["Color"])
    node_tree.links.new(separate.outputs[channel_socket], maximum.inputs[1])
    node_tree.links.new(maximum.outputs["Value"], emission.inputs["Color"])
    node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _debug_material(view_id):
    material = _debug_materials.get(view_id)
    if material is None or material.name not in bpy.data.materials:
        material = _build_debug_material(view_id)
        _debug_materials[view_id] = material
    return material


def _restore_material_overrides():
    for state in tuple(_material_override_states.values()):
        view_layer = state["view_layer"]
        try:
            if _is_debug_material(view_layer.material_override):
                view_layer.material_override = state["original"]
        except ReferenceError:
            pass
    _material_override_states.clear()
    _custom_view_by_space.clear()


def _remove_debug_materials():
    _restore_material_overrides()
    _debug_materials.clear()
    materials = getattr(bpy.data, "materials", None)
    if materials is None:
        return
    for material in tuple(materials):
        if _is_debug_material(material):
            materials.remove(material, do_unlink=True)


def current_debug_view_id(context):
    space = getattr(context, "space_data", None)
    view_layer = getattr(context, "view_layer", None)
    if space is not None and hasattr(space, "as_pointer") and view_layer is not None:
        space_pointer = space.as_pointer()
        custom_view = _custom_view_by_space.get(space_pointer)
        if custom_view is not None:
            material = _debug_materials.get(custom_view)
            if material is not None and view_layer.material_override == material:
                return custom_view
            _custom_view_by_space.pop(space_pointer, None)

    shading = _debug_shading(context)
    return shading.render_pass if shading is not None else None


def _draw_view_indicator():
    context = bpy.context
    if not viewport_supports_debug_passes(context):
        return

    view_id = current_debug_view_id(context)
    if view_id is None:
        return

    if view_id in CUSTOM_VIEW_CHANNELS:
        color = (1.0, 0.48, 0.12, 1.0)
    elif view_id == "COMBINED":
        color = (0.72, 0.72, 0.72, 1.0)
    else:
        color = (0.25, 0.7, 1.0, 1.0)

    font_id = 0
    blf.size(font_id, 16)
    blf.color(font_id, *color)
    blf.enable(font_id, blf.SHADOW)
    blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.85)
    blf.shadow_offset(font_id, 2, -2)
    blf.position(font_id, 22, 22, 0)
    blf.draw(font_id, f"DEBUG VIEW  |  {render_pass_label(view_id)}")
    blf.disable(font_id, blf.SHADOW)


def _draw_header_indicator(self, context):
    if not viewport_supports_debug_passes(context):
        return

    view_id = current_debug_view_id(context)
    if view_id is None:
        return

    icon = "GROUP_VCOL" if view_id in CUSTOM_VIEW_CHANNELS else "SHADING_RENDERED"
    row = self.layout.row(align=True)
    row.label(text=f"Debug: {render_pass_label(view_id)}", icon=icon)


def _register_draw_handler():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_view_indicator,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
    if not getattr(_register_draw_handler, "header_registered", False):
        bpy.types.VIEW3D_HT_header.append(_draw_header_indicator)
        _register_draw_handler.header_registered = True


def _unregister_draw_handler():
    global _draw_handler
    if _draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, "WINDOW")
        _draw_handler = None
    if getattr(_register_draw_handler, "header_registered", False):
        bpy.types.VIEW3D_HT_header.remove(_draw_header_indicator)
        _register_draw_handler.header_registered = False


def apply_debug_view(context, view_id):
    shading = _debug_shading(context)
    if shading is None:
        return None

    if view_id in CUSTOM_VIEW_CHANNELS:
        view_layer = getattr(context, "view_layer", None)
        space = getattr(context, "space_data", None)
        if view_layer is None or space is None or not hasattr(space, "as_pointer"):
            return None

        view_layer_pointer = view_layer.as_pointer()
        if view_layer_pointer not in _material_override_states:
            original = view_layer.material_override
            if _is_debug_material(original):
                original = None
            _material_override_states[view_layer_pointer] = {
                "view_layer": view_layer,
                "original": original,
            }

        material = _debug_material(view_id)
        view_layer.material_override = material
        _custom_view_by_space.clear()
        _custom_view_by_space[space.as_pointer()] = view_id
        try:
            shading.render_pass = "COMBINED"
        except (TypeError, ValueError):
            return None
        context.area.tag_redraw()
        return view_id

    if view_id not in available_render_pass_ids(context):
        return None

    _restore_material_overrides()
    try:
        shading.render_pass = view_id
    except (TypeError, ValueError):
        return None
    context.area.tag_redraw()
    return view_id


def apply_adjacent_debug_view(context, step):
    view_ids = available_debug_view_ids(context)
    if not view_ids:
        return None

    current = current_debug_view_id(context)
    try:
        start = view_ids.index(current)
    except ValueError:
        start = 0

    for offset in range(1, len(view_ids)):
        target = view_ids[(start + step * offset) % len(view_ids)]
        applied = apply_debug_view(context, target)
        if applied is not None:
            return applied
    return None


def apply_debug_hotkey(context, key):
    """Apply one supported bare-key action, or return None to pass it through."""
    if not viewport_supports_debug_passes(context):
        return None

    if key == "B":
        target = apply_adjacent_debug_view(context, 1)
    elif key == "M":
        target = apply_debug_view(context, "COMBINED")
    else:
        return None

    if target is None:
        return None

    return target


def _view3d_window_region_under_mouse(context, event):
    """Return the View3D area/region below the event's window coordinates."""
    window = context.window
    if window is None or window.screen is None:
        return None

    mouse_x = event.mouse_x
    mouse_y = event.mouse_y
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue

        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if (
                region.x <= mouse_x < region.x + region.width
                and region.y <= mouse_y < region.y + region.height
            ):
                return area, region

    return None


def handle_debug_hotkey_event(context, event):
    """Handle one keyboard event exactly as the modal listener does."""
    if event.value != "PRESS" or event.type not in {"B", "M"}:
        return None
    if event.ctrl or event.shift or event.alt or event.oskey:
        return None

    viewport = _view3d_window_region_under_mouse(context, event)
    if viewport is None:
        return None

    area, region = viewport
    with bpy.context.temp_override(window=context.window, area=area, region=region):
        return apply_debug_hotkey(bpy.context, event.type)


class DEBUGRENDERPASS_OT_input_listener(bpy.types.Operator):
    bl_idname = "wm.debug_render_pass_input_listener"
    bl_label = "Debug Render Pass Input Listener"
    bl_description = "Handle B/M before Blender's mode-specific keymaps"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def invoke(self, context, event):
        window_pointer = context.window.as_pointer()
        if window_pointer in _listener_window_ids:
            return {"CANCELLED"}

        self._listener_token = _listener_token
        self._window_pointer = window_pointer
        _listener_window_ids.add(window_pointer)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not _listener_enabled or self._listener_token is not _listener_token:
            _listener_window_ids.discard(self._window_pointer)
            return {"CANCELLED"}

        target = handle_debug_hotkey_event(context, event)
        if target is None:
            return {"PASS_THROUGH"}

        self.report({"INFO"}, f"Debug Render Pass: {render_pass_label(target)}")
        return {"RUNNING_MODAL"}


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
        if len(available_debug_view_ids(context)) < 2:
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

        step = -1 if self.direction == "PREVIOUS" else 1
        target = apply_adjacent_debug_view(context, step)
        if target is None:
            self.report({"WARNING"}, "No compatible debug render pass is available")
            return {"CANCELLED"}

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

    def invoke(self, context, event):
        if not viewport_supports_debug_passes(context):
            return {"PASS_THROUGH"}
        return self.execute(context)

    def execute(self, context):
        shading = _debug_shading(context)
        if shading is None:
            self.report(
                {"WARNING"},
                "Switch to Material Preview or a supported Rendered view first",
            )
            return {"CANCELLED"}

        if self.pass_id not in available_debug_view_ids(context):
            self.report({"ERROR"}, f"Unsupported render pass: {self.pass_id}")
            return {"CANCELLED"}

        target = apply_debug_view(context, self.pass_id)
        if target is None:
            self.report({"ERROR"}, f"Could not show debug view: {self.pass_id}")
            return {"CANCELLED"}

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
            current_view = current_debug_view_id(context) or shading.render_pass
            column.label(text=render_pass_label(current_view), icon="SHADING_RENDERED")

        row = column.row(align=True)
        next_pass = row.operator(OPERATOR_CYCLE_ID, text="B  Next", icon="TRIA_RIGHT")
        next_pass.direction = "NEXT"
        reset = row.operator(OPERATOR_SET_ID, text="M  Combined", icon="FILE_REFRESH")
        reset.pass_id = "COMBINED"

        layout.separator()
        layout.label(text="B/M override in Material Preview / Rendered")


classes = (
    DEBUGRENDERPASS_OT_input_listener,
    DEBUGRENDERPASS_OT_cycle,
    DEBUGRENDERPASS_OT_set,
    DEBUGRENDERPASS_PT_view3d,
)


def remove_legacy_user_keymaps():
    """Remove stale shortcuts written by older versions of this add-on."""
    key_config = bpy.context.window_manager.keyconfigs.user
    if key_config is None:
        return

    def is_plain_legacy_item(keymap_item):
        return (
            keymap_item.idname in {OPERATOR_CYCLE_ID, OPERATOR_SET_ID}
            and keymap_item.type in {"B", "M"}
            and keymap_item.value == "PRESS"
            and not keymap_item.ctrl
            and not keymap_item.shift
            and not keymap_item.alt
        )

    has_legacy_items = any(
        is_plain_legacy_item(keymap_item)
        for keymap in key_config.keymaps
        for keymap_item in keymap.keymap_items
    )
    if not has_legacy_items:
        return

    for keymap in key_config.keymaps:
        stale_items = [
            keymap_item
            for keymap_item in keymap.keymap_items
            if is_plain_legacy_item(keymap_item)
        ]
        for keymap_item in stale_items:
            keymap.keymap_items.remove(keymap_item)


def _start_input_listeners():
    if not _listener_enabled:
        return None

    window_manager = bpy.context.window_manager
    live_window_ids = {window.as_pointer() for window in window_manager.windows}
    _listener_window_ids.intersection_update(live_window_ids)

    for window in window_manager.windows:
        window_pointer = window.as_pointer()
        try:
            has_listener = any(
                operator is not None
                and getattr(operator, "bl_idname", None) == LISTENER_BL_IDNAME
                for operator in window.modal_operators
            )
        except (AttributeError, ReferenceError):
            has_listener = window_pointer in _listener_window_ids

        if has_listener:
            _listener_window_ids.add(window_pointer)
            continue

        _listener_window_ids.discard(window_pointer)

        try:
            with bpy.context.temp_override(window=window):
                bpy.ops.wm.debug_render_pass_input_listener("INVOKE_DEFAULT")
        except (RuntimeError, TypeError):
            continue

    # This low-frequency watchdog also covers windows created after registration
    # and replaces a listener if Blender ever cancels it during a file transition.
    return LISTENER_WATCHDOG_INTERVAL if _listener_enabled else None


def _schedule_input_listeners():
    if bpy.app.background or not _listener_enabled:
        return
    if not bpy.app.timers.is_registered(_start_input_listeners):
        bpy.app.timers.register(_start_input_listeners, first_interval=0.1)


@persistent
def _load_post_start_input_listeners(_unused):
    _listener_window_ids.clear()
    _remove_debug_materials()
    _schedule_input_listeners()


@persistent
def _save_pre_remove_debug_materials(_unused):
    # Runtime override materials must never be written into the user's blend file.
    _remove_debug_materials()


def register():
    global _listener_enabled, _listener_token

    for cls in classes:
        bpy.utils.register_class(cls)

    _listener_token = object()
    _listener_enabled = True
    _remove_debug_materials()
    remove_legacy_user_keymaps()
    if _load_post_start_input_listeners not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_start_input_listeners)
    if _save_pre_remove_debug_materials not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_pre_remove_debug_materials)
    _register_draw_handler()
    _schedule_input_listeners()


def unregister():
    global _listener_enabled, _listener_token

    _listener_enabled = False
    _listener_token = object()
    _listener_window_ids.clear()
    _unregister_draw_handler()
    _remove_debug_materials()

    if bpy.app.timers.is_registered(_start_input_listeners):
        bpy.app.timers.unregister(_start_input_listeners)
    if _load_post_start_input_listeners in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_start_input_listeners)
    if _save_pre_remove_debug_materials in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_pre_remove_debug_materials)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
