bl_info = {
    "name": "XYZ Transform Gizmo Overlay Stable",
    "author": "ChatGPT",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "description": "Shows a lightweight axis compass only while a transform is running.",
    "category": "3D View",
}

import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector


_draw_handler = None
_shader = None


# Reading Window.modal_operators is deliberate.  It lets the add-on observe Blender's
# existing transform without replacing G/R/S keymaps or wrapping transform operators.
_TRANSFORM_OPERATORS = {
    "TRANSFORM_OT_translate": ("MOVE", "show_on_move"),
    "TRANSFORM_OT_rotate": ("ROTATE", "show_on_rotate"),
    "TRANSFORM_OT_trackball": ("ROTATE", "show_on_rotate"),
    "TRANSFORM_OT_resize": ("SCALE", "show_on_scale"),
    "TRANSFORM_OT_transform": ("TRANSFORM", "show_on_transform"),
}

_LEGACY_ORIENTATION_MAP = {
    0: "GLOBAL",
    1: "LOCAL",
    "GLOBAL": "GLOBAL",
    "LOCAL": "LOCAL",
}


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _shader


def _addon_settings(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    settings = getattr(scene, "xyz_transform_gizmo_overlay_stable_settings", None)
    if settings is not None:
        _migrate_legacy_orientation_setting(settings)
    return settings


def _is_view3d_context(context):
    return (
        context.area is not None
        and context.area.type == "VIEW_3D"
        and context.region is not None
        and context.space_data is not None
        and context.space_data.type == "VIEW_3D"
        and context.space_data.region_3d is not None
    )


def _active_transform(context, settings):
    """Return (operator, display name) for the current G/R/S transform, if any."""
    window = getattr(context, "window", None)
    if window is None:
        return None

    try:
        operators = tuple(window.modal_operators)
    except (AttributeError, ReferenceError, TypeError):
        return None

    for operator in reversed(operators):
        info = _TRANSFORM_OPERATORS.get(getattr(operator, "bl_idname", ""))
        if info is None:
            continue

        display_name, setting_name = info
        if getattr(settings, setting_name, True):
            return operator, display_name

    return None


def _operator_property_is_set(properties, name):
    try:
        return properties.is_property_set(name)
    except (AttributeError, ReferenceError, TypeError):
        return False


def _operator_orientation_matrix(operator):
    """Use Blender's resolved modal orientation matrix when it is available."""
    try:
        properties = operator.properties
        raw_matrix = properties.orient_matrix
        matrix = Matrix(raw_matrix).to_3x3()
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return None

    if abs(matrix.determinant()) < 1.0e-8:
        return None

    return matrix


def _scene_orientation(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return "GLOBAL", None

    try:
        slot = scene.transform_orientation_slots[0]
        orientation_type = slot.type
        custom_orientation = slot.custom_orientation
    except (AttributeError, IndexError, ReferenceError, TypeError):
        return "GLOBAL", None

    if not orientation_type or orientation_type == "DEFAULT":
        orientation_type = "GLOBAL"
    return orientation_type, custom_orientation


def _operator_orientation_type(context, operator):
    scene_type, custom_orientation = _scene_orientation(context)

    try:
        properties = operator.properties
        if _operator_property_is_set(properties, "orient_type"):
            operator_type = properties.orient_type
            if operator_type and operator_type != "DEFAULT":
                return operator_type, custom_orientation
    except (AttributeError, ReferenceError, TypeError):
        pass

    return scene_type, custom_orientation


def _object_rotation_matrix(obj):
    if obj is None:
        return Matrix.Identity(3)
    try:
        return obj.matrix_world.to_quaternion().to_matrix()
    except (AttributeError, ReferenceError, ValueError):
        return Matrix.Identity(3)


def _fallback_orientation_matrix(context, orientation_type, custom_orientation):
    active_object = getattr(context, "active_object", None)

    if orientation_type == "GLOBAL":
        return Matrix.Identity(3)

    if orientation_type in {"LOCAL", "NORMAL", "GIMBAL"}:
        return _object_rotation_matrix(active_object)

    if orientation_type == "PARENT":
        parent = getattr(active_object, "parent", None)
        return _object_rotation_matrix(parent)

    if orientation_type == "VIEW":
        try:
            return context.space_data.region_3d.view_matrix.inverted_safe().to_3x3()
        except (AttributeError, ReferenceError, ValueError):
            return Matrix.Identity(3)

    if orientation_type == "CURSOR":
        try:
            return context.scene.cursor.matrix.to_3x3()
        except (AttributeError, ReferenceError, ValueError):
            return Matrix.Identity(3)

    if custom_orientation is not None:
        try:
            return custom_orientation.matrix.to_3x3()
        except (AttributeError, ReferenceError, ValueError):
            pass

    return Matrix.Identity(3)


def _orientation_axes(context, settings, operator):
    if settings.orientation_mode == "GLOBAL":
        orientation_type = "GLOBAL"
        matrix = Matrix.Identity(3)
    elif settings.orientation_mode == "LOCAL":
        orientation_type = "LOCAL"
        matrix = _object_rotation_matrix(getattr(context, "active_object", None))
    else:
        orientation_type, custom_orientation = _operator_orientation_type(context, operator)
        matrix = _operator_orientation_matrix(operator)
        if matrix is None:
            matrix = _fallback_orientation_matrix(
                context,
                orientation_type,
                custom_orientation,
            )

    axes = {}
    for index, label in enumerate(("X", "Y", "Z")):
        try:
            axis = Vector(matrix.col[index]).to_3d()
        except (AttributeError, IndexError, TypeError, ValueError):
            axis = Vector((1.0 if index == 0 else 0.0, 1.0 if index == 1 else 0.0, 1.0 if index == 2 else 0.0))
        if axis.length_squared < 1.0e-12:
            axis = Vector((1.0 if index == 0 else 0.0, 1.0 if index == 1 else 0.0, 1.0 if index == 2 else 0.0))
        axes[label] = axis.normalized()

    return axes, orientation_type


def _screen_axis_direction(context, axis):
    try:
        view_axis = context.space_data.region_3d.view_matrix.to_3x3() @ axis
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return None, 0.0

    direction = Vector((view_axis.x, view_axis.y))
    if direction.length_squared < 2.5e-3:
        return None, view_axis.z
    return direction.normalized(), view_axis.z


def _rgba(color, alpha_scale=1.0):
    return (
        float(color[0]),
        float(color[1]),
        float(color[2]),
        max(0.0, min(1.0, float(color[3]) * alpha_scale)),
    )


def _draw_primitive(primitive, positions, color, line_width=None):
    if not positions:
        return

    shader = _get_shader()
    batch = batch_for_shader(shader, primitive, {"pos": positions})
    gpu.state.blend_set("ALPHA")
    try:
        if line_width is not None:
            try:
                gpu.state.line_width_set(line_width)
            except (AttributeError, ValueError):
                pass
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
    finally:
        if line_width is not None:
            try:
                gpu.state.line_width_set(1.0)
            except (AttributeError, ValueError):
                pass
        gpu.state.blend_set("NONE")


def _draw_line_2d(start, end, color, width):
    _draw_primitive("LINES", (start, end), color, line_width=width)


def _draw_filled_triangle_2d(point_a, point_b, point_c, color):
    _draw_primitive("TRIS", (point_a, point_b, point_c), color)


def _draw_rect_2d(left, bottom, right, top, color):
    _draw_primitive(
        "TRIS",
        (
            (left, bottom),
            (right, bottom),
            (right, top),
            (left, bottom),
            (right, top),
            (left, top),
        ),
        color,
    )


def _draw_text(label, position, color, size):
    font_id = 0
    x, y = position
    blf.size(font_id, size)

    shadow_enabled = False
    try:
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.75)
        blf.shadow_offset(font_id, 1, -1)
        shadow_enabled = True
    except (AttributeError, ValueError):
        pass

    try:
        blf.color(font_id, color[0], color[1], color[2], color[3])
        width, height = blf.dimensions(font_id, label)
        blf.position(font_id, x - width * 0.5, y - height * 0.5, 0)
        blf.draw(font_id, label)
    finally:
        if shadow_enabled:
            try:
                blf.disable(font_id, blf.SHADOW)
            except (AttributeError, ValueError):
                pass


def _draw_center_cross(center, color, size, width):
    half_size = size * 0.5
    _draw_line_2d(
        (center.x - half_size, center.y),
        (center.x + half_size, center.y),
        color,
        width,
    )
    _draw_line_2d(
        (center.x, center.y - half_size),
        (center.x, center.y + half_size),
        color,
        width,
    )


def _draw_arrow(center, direction, color, settings):
    length = float(settings.axis_length)
    arrow_size = float(settings.arrow_size)
    width = float(settings.line_width)
    tip = center + direction * length
    base = tip - direction * arrow_size
    perpendicular = Vector((-direction.y, direction.x))
    wing = arrow_size * 0.48
    left = base + perpendicular * wing
    right = base - perpendicular * wing

    _draw_line_2d(center, base, color, width)
    if settings.filled_arrow:
        _draw_filled_triangle_2d(tip, left, right, color)
    else:
        _draw_line_2d(left, tip, color, width)
        _draw_line_2d(right, tip, color, width)
    return tip


def _draw_depth_marker(center, depth, color, settings):
    radius = max(4.0, float(settings.arrow_size) * 0.45)
    points = []
    segments = 12
    for index in range(segments):
        angle = math.tau * index / segments
        next_angle = math.tau * (index + 1) / segments
        points.extend(
            (
                center,
                center + Vector((math.cos(angle), math.sin(angle))) * radius,
                center + Vector((math.cos(next_angle), math.sin(next_angle))) * radius,
            )
        )
    _draw_primitive("TRIS", points, color)

    # A small inner mark differentiates an axis pointing into/out of the screen.
    if depth < 0.0:
        inner = radius * 0.45
        _draw_line_2d(
            (center.x - inner, center.y - inner),
            (center.x + inner, center.y + inner),
            (1.0, 1.0, 1.0, color[3]),
            1.0,
        )
        _draw_line_2d(
            (center.x - inner, center.y + inner),
            (center.x + inner, center.y - inner),
            (1.0, 1.0, 1.0, color[3]),
            1.0,
        )
    return center


def _compass_layout(context, settings):
    region = context.region
    radius = (
        float(settings.axis_length)
        + float(settings.label_offset)
        + float(settings.font_size)
        + 18.0
    )
    center = Vector((region.width - radius - 18.0, radius + 46.0))
    if region.width < radius * 2.0 + 36.0:
        center.x = region.width * 0.5
    return center, radius


def _draw_callback():
    context = bpy.context
    if not _is_view3d_context(context):
        return

    settings = _addon_settings(context)
    if settings is None or not settings.enabled:
        return

    # This is the idle hot path: no selection queries, mesh iteration, or GPU work.
    transform = _active_transform(context, settings)
    if transform is None:
        return

    operator, operation_name = transform

    try:
        axes, orientation_name = _orientation_axes(context, settings, operator)
        center, radius = _compass_layout(context, settings)

        operation_y = center.y - radius + 19.0
        hint_y = operation_y - 18.0
        bottom = hint_y - 11.0 if settings.show_shortcut_hint else operation_y - 12.0
        _draw_rect_2d(
            center.x - radius,
            bottom,
            center.x + radius,
            center.y + radius,
            settings.background_color,
        )

        colors = {
            "X": settings.x_color,
            "Y": settings.y_color,
            "Z": settings.z_color,
        }
        collapsed_labels = []

        for label, axis in axes.items():
            color = _rgba(colors[label])
            direction, depth = _screen_axis_direction(context, axis)

            if direction is None:
                tip = _draw_depth_marker(center, depth, color, settings)
                collapsed_labels.append((label, color))
            else:
                tip = _draw_arrow(center, direction, color, settings)
                if settings.show_labels:
                    label_position = tip + direction * settings.label_offset
                    _draw_text(label, label_position, color, settings.font_size)

        if settings.show_labels:
            for index, (label, color) in enumerate(collapsed_labels):
                label_position = center + Vector((0.0, 16.0 + index * (settings.font_size + 2.0)))
                _draw_text(label, label_position, color, settings.font_size)

        if settings.show_center_cross:
            _draw_center_cross(
                center,
                settings.center_color,
                settings.center_cross_size,
                settings.center_cross_width,
            )

        title = f"{operation_name}  |  {orientation_name}"
        _draw_text(title, (center.x, operation_y), settings.text_color, settings.status_font_size)
        if settings.show_shortcut_hint:
            if operation_name == "ROTATE":
                shortcut_hint = "X / Y / Z: rotation axis"
            else:
                shortcut_hint = "X / Y / Z: axis    Shift + axis: plane"
            _draw_text(
                shortcut_hint,
                (center.x, hint_y),
                settings.hint_color,
                settings.hint_font_size,
            )
    except Exception:
        # A draw callback must never break Blender's transform if a context disappears
        # while a window/area is being closed.
        return


def _tag_all_view3d_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return

    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _ensure_draw_handler():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback,
            (),
            "WINDOW",
            "POST_PIXEL",
        )


def _remove_draw_handler():
    global _draw_handler
    if _draw_handler is None:
        return

    try:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, "WINDOW")
    except (ReferenceError, RuntimeError, ValueError):
        pass
    _draw_handler = None


def _settings_update(self, _context):
    # Settings live on Scene, while the draw handler is global.  Removing it for a
    # disabled Scene would also disable enabled Scenes until another property update.
    _ensure_draw_handler()
    _tag_all_view3d_redraw()


def _migrate_legacy_orientation_setting(settings):
    """Preserve explicit v1 Global/Local choices without overriding new settings."""
    try:
        raw_keys = set(settings.keys())
    except (AttributeError, ReferenceError, TypeError):
        return

    # A raw orientation_mode key means the user has already used v2 settings.
    if "orientation_mode" in raw_keys or "orientation" not in raw_keys:
        return

    legacy_value = settings.get("orientation")
    try:
        orientation_mode = _LEGACY_ORIENTATION_MAP.get(legacy_value)
    except TypeError:
        return
    if orientation_mode is None:
        return

    try:
        settings.orientation_mode = orientation_mode
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return


class XYZTransformGizmoOverlayStableSettings(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enable Transform Compass",
        description="Show the axis compass while a transform is running",
        default=True,
        update=_settings_update,
    )

    show_on_move: bpy.props.BoolProperty(name="Move", default=True, update=_settings_update)
    show_on_rotate: bpy.props.BoolProperty(name="Rotate", default=True, update=_settings_update)
    show_on_scale: bpy.props.BoolProperty(name="Scale", default=True, update=_settings_update)
    show_on_transform: bpy.props.BoolProperty(
        name="Transform",
        default=True,
        update=_settings_update,
    )

    orientation_mode: bpy.props.EnumProperty(
        name="Orientation",
        description="Follow Blender's current transform orientation or force an override",
        items=(
            ("AUTO", "Follow Blender", "Use the current transform orientation"),
            ("GLOBAL", "Global", "Always show world X/Y/Z axes"),
            ("LOCAL", "Local", "Always show the active object's local axes"),
        ),
        default="AUTO",
        update=_settings_update,
    )

    axis_length: bpy.props.IntProperty(
        name="Axis Length",
        description="Length of the on-screen axis lines in pixels",
        default=46,
        min=20,
        max=160,
        update=_settings_update,
    )
    arrow_size: bpy.props.IntProperty(
        name="Arrow Size",
        description="Arrow head size in pixels",
        default=12,
        min=4,
        max=40,
        update=_settings_update,
    )
    line_width: bpy.props.FloatProperty(
        name="Line Width",
        default=2.0,
        min=1.0,
        max=6.0,
        update=_settings_update,
    )
    filled_arrow: bpy.props.BoolProperty(
        name="Filled Arrow Head",
        default=True,
        update=_settings_update,
    )
    show_labels: bpy.props.BoolProperty(
        name="Show Axis Labels",
        default=True,
        update=_settings_update,
    )
    label_offset: bpy.props.IntProperty(
        name="Label Offset",
        default=12,
        min=0,
        max=48,
        update=_settings_update,
    )
    font_size: bpy.props.IntProperty(
        name="Axis Font Size",
        default=16,
        min=9,
        max=36,
        update=_settings_update,
    )
    status_font_size: bpy.props.IntProperty(
        name="Status Font Size",
        default=13,
        min=9,
        max=28,
        update=_settings_update,
    )
    show_shortcut_hint: bpy.props.BoolProperty(
        name="Show Axis Shortcut Hint",
        default=True,
        update=_settings_update,
    )
    hint_font_size: bpy.props.IntProperty(
        name="Hint Font Size",
        default=10,
        min=8,
        max=20,
        update=_settings_update,
    )

    show_center_cross: bpy.props.BoolProperty(
        name="Show Center Cross",
        default=False,
        update=_settings_update,
    )
    center_cross_size: bpy.props.IntProperty(
        name="Center Cross Size",
        default=10,
        min=4,
        max=30,
        update=_settings_update,
    )
    center_cross_width: bpy.props.FloatProperty(
        name="Center Cross Width",
        default=1.5,
        min=1.0,
        max=5.0,
        update=_settings_update,
    )

    background_color: bpy.props.FloatVectorProperty(
        name="Background",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.02, 0.025, 0.035, 0.68),
        update=_settings_update,
    )
    text_color: bpy.props.FloatVectorProperty(
        name="Status Text",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.92, 0.92, 0.92, 1.0),
        update=_settings_update,
    )
    hint_color: bpy.props.FloatVectorProperty(
        name="Hint Text",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.70, 0.70, 0.70, 0.9),
        update=_settings_update,
    )
    center_color: bpy.props.FloatVectorProperty(
        name="Center Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 0.85),
        update=_settings_update,
    )
    x_color: bpy.props.FloatVectorProperty(
        name="X Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.18, 0.18, 1.0),
        update=_settings_update,
    )
    y_color: bpy.props.FloatVectorProperty(
        name="Y Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.25, 0.95, 0.25, 1.0),
        update=_settings_update,
    )
    z_color: bpy.props.FloatVectorProperty(
        name="Z Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.35, 0.55, 1.0, 1.0),
        update=_settings_update,
    )


class VIEW3D_PT_xyz_transform_gizmo_overlay_stable(bpy.types.Panel):
    bl_label = "XYZ Transform Compass"
    bl_idname = "VIEW3D_PT_xyz_transform_gizmo_overlay_stable"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "View"

    def draw(self, context):
        layout = self.layout
        settings = _addon_settings(context)
        if settings is None:
            layout.label(text="Settings not found.", icon="ERROR")
            return

        layout.prop(settings, "enabled")
        layout.label(text="Appears only during an active transform.", icon="INFO")

        column = layout.column()
        column.enabled = settings.enabled

        show_box = column.box()
        show_box.label(text="Show During")
        row = show_box.row(align=True)
        row.prop(settings, "show_on_move", toggle=True)
        row.prop(settings, "show_on_rotate", toggle=True)
        row.prop(settings, "show_on_scale", toggle=True)
        row.prop(settings, "show_on_transform", toggle=True)

        column.prop(settings, "orientation_mode")

        shape_box = column.box()
        shape_box.label(text="Compass")
        shape_box.prop(settings, "axis_length")
        shape_box.prop(settings, "arrow_size")
        shape_box.prop(settings, "line_width")
        shape_box.prop(settings, "filled_arrow")

        text_box = column.box()
        text_box.label(text="Labels")
        text_box.prop(settings, "show_labels")
        label_column = text_box.column()
        label_column.enabled = settings.show_labels
        label_column.prop(settings, "label_offset")
        label_column.prop(settings, "font_size")
        text_box.prop(settings, "status_font_size")
        text_box.prop(settings, "show_shortcut_hint")
        hint_column = text_box.column()
        hint_column.enabled = settings.show_shortcut_hint
        hint_column.prop(settings, "hint_font_size")

        center_box = column.box()
        center_box.label(text="Center")
        center_box.prop(settings, "show_center_cross")
        center_column = center_box.column()
        center_column.enabled = settings.show_center_cross
        center_column.prop(settings, "center_cross_size")
        center_column.prop(settings, "center_cross_width")
        center_column.prop(settings, "center_color")

        color_box = column.box()
        color_box.label(text="Colors")
        color_box.prop(settings, "background_color")
        color_box.prop(settings, "text_color")
        color_box.prop(settings, "hint_color")
        color_box.prop(settings, "x_color")
        color_box.prop(settings, "y_color")
        color_box.prop(settings, "z_color")


classes = (
    XYZTransformGizmoOverlayStableSettings,
    VIEW3D_PT_xyz_transform_gizmo_overlay_stable,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.xyz_transform_gizmo_overlay_stable_settings = bpy.props.PointerProperty(
        type=XYZTransformGizmoOverlayStableSettings
    )
    # Preferences enable can call register() before bpy.context has an active scene.
    # Install one handler unconditionally; the callback returns immediately when the
    # current scene has no settings or the overlay is disabled.
    _ensure_draw_handler()


def unregister():
    global _shader

    _remove_draw_handler()
    if hasattr(bpy.types.Scene, "xyz_transform_gizmo_overlay_stable_settings"):
        del bpy.types.Scene.xyz_transform_gizmo_overlay_stable_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    _shader = None


if __name__ == "__main__":
    register()
