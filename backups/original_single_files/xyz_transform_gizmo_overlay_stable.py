
bl_info = {
    "name": "XYZ Transform Gizmo Overlay Stable",
    "author": "ChatGPT",
    "version": (1, 2, 1),
    "blender": (4, 0, 0),
    "description": "Draws stable X/Y/Z axis overlay with lines, arrowheads, and labels near the selected pivot.",
    "category": "3D View",
}

import bpy
import blf
import bmesh
import gpu
from mathutils import Vector
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

_draw_handler = None
_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _shader


def _addon_prefs(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    return getattr(scene, "xyz_transform_gizmo_overlay_stable_settings", None)


def _is_view3d_context(context):
    return (
        context.area is not None
        and context.area.type == "VIEW_3D"
        and context.region is not None
        and context.space_data is not None
        and context.space_data.type == "VIEW_3D"
        and context.space_data.region_3d is not None
    )


def _active_tool_id(context):
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
        return tool.idname if tool else ""
    except Exception:
        return ""


def _is_allowed_tool_active(context, settings):
    # 기본적으로는 항상 표시가 더 안정적입니다.
    # Blender에서는 transform gizmo가 보여도 active tool은 select_box인 경우가 흔합니다.
    if not settings.only_transform_tools:
        return True

    tool_id = _active_tool_id(context)

    allowed = set()
    if settings.show_on_move:
        allowed.add("builtin.move")
    if settings.show_on_rotate:
        allowed.add("builtin.rotate")
    if settings.show_on_scale:
        allowed.add("builtin.scale")
    if settings.show_on_transform:
        allowed.add("builtin.transform")

    return tool_id in allowed


def _selected_world_center(context):
    mode = context.mode

    if mode == "EDIT_MESH":
        points = []
        objects = getattr(context, "objects_in_mode_unique_data", None) or [context.edit_object]

        for obj in objects:
            if obj is None or obj.type != "MESH":
                continue

            try:
                bm = bmesh.from_edit_mesh(obj.data)
            except Exception:
                continue

            mw = obj.matrix_world

            # 선택 모드가 vertex/edge/face 무엇이든, 실제 선택된 vertex 기준으로 중심을 잡습니다.
            for v in bm.verts:
                if v.select:
                    points.append(mw @ v.co)

        if points:
            center = Vector((0.0, 0.0, 0.0))
            for p in points:
                center += p
            return center / len(points)

        # Edit Mode인데 아무 컴포넌트도 선택되지 않은 경우 fallback
        obj = context.edit_object
        if obj is not None:
            return obj.matrix_world.translation

    selected = [obj for obj in context.selected_objects if obj is not None]
    if selected:
        center = Vector((0.0, 0.0, 0.0))
        for obj in selected:
            center += obj.matrix_world.translation
        return center / len(selected)

    obj = context.object
    if obj:
        return obj.matrix_world.translation

    return None


def _axis_vectors(context, settings):
    if settings.orientation == "LOCAL" and context.active_object is not None:
        q = context.active_object.matrix_world.to_quaternion()
        return {
            "X": (q @ Vector((1.0, 0.0, 0.0))).normalized(),
            "Y": (q @ Vector((0.0, 1.0, 0.0))).normalized(),
            "Z": (q @ Vector((0.0, 0.0, 1.0))).normalized(),
        }

    return {
        "X": Vector((1.0, 0.0, 0.0)),
        "Y": Vector((0.0, 1.0, 0.0)),
        "Z": Vector((0.0, 0.0, 1.0)),
    }


def _project_axis(context, center, axis_vec):
    region = context.region
    rv3d = context.space_data.region_3d

    c2d = view3d_utils.location_3d_to_region_2d(region, rv3d, center)
    if c2d is None:
        return None, None

    # 축 방향이 화면 뒤쪽으로 가서 projection이 실패하는 경우를 줄이기 위해
    # +방향 실패 시 -방향도 시도합니다.
    unit2d = view3d_utils.location_3d_to_region_2d(region, rv3d, center + axis_vec)
    if unit2d is None:
        unit2d = view3d_utils.location_3d_to_region_2d(region, rv3d, center - axis_vec)
        if unit2d is None:
            return c2d, None
        # 반대 방향으로 얻은 projection이므로 화면상 방향을 다시 뒤집습니다.
        delta = c2d - unit2d
        return c2d, c2d + delta

    return c2d, unit2d


def _safe_normalized(vec2):
    l = vec2.length
    if l < 1e-8:
        return None
    return vec2 / l


def _draw_line_2d(p1, p2, color, width):
    try:
        shader = _get_shader()
        batch = batch_for_shader(shader, "LINES", {"pos": [p1, p2]})

        gpu.state.blend_set("ALPHA")
        try:
            gpu.state.line_width_set(width)
        except Exception:
            pass

        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

        try:
            gpu.state.line_width_set(1.0)
        except Exception:
            pass
        gpu.state.blend_set("NONE")
    except Exception:
        # draw callback에서 에러가 터지면 viewport가 불안정해질 수 있어서 조용히 스킵합니다.
        pass


def _draw_filled_triangle_2d(p1, p2, p3, color):
    try:
        shader = _get_shader()
        batch = batch_for_shader(shader, "TRIS", {"pos": [p1, p2, p3]})

        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.blend_set("NONE")
    except Exception:
        pass


def _draw_arrow_overlay(center_2d, unit_2d, color, shaft_length, arrow_size, width, filled_arrow):
    if center_2d is None or unit_2d is None:
        return None, None

    delta = unit_2d - center_2d
    direction = _safe_normalized(delta)
    if direction is None:
        return None, None

    start = Vector((center_2d.x, center_2d.y))
    tip = start + direction * shaft_length
    base = tip - direction * arrow_size

    perp = Vector((-direction.y, direction.x))
    wing = arrow_size * 0.48

    left = base + perp * wing
    right = base - perp * wing

    _draw_line_2d(start, base, color, width)

    if filled_arrow:
        _draw_filled_triangle_2d(tip, left, right, color)
    else:
        _draw_line_2d(left, tip, color, width)
        _draw_line_2d(right, tip, color, width)

    return tip, direction


def _draw_text(label, pos, color, size):
    try:
        font_id = 0
        x, y = pos

        blf.size(font_id, size)

        try:
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.70)
            blf.shadow_offset(font_id, 1, -1)
        except Exception:
            pass

        try:
            blf.color(font_id, color[0], color[1], color[2], color[3])
        except Exception:
            pass

        try:
            width, height = blf.dimensions(font_id, label)
        except Exception:
            width, height = (size * 0.6, size)

        blf.position(font_id, x - width * 0.5, y - height * 0.5, 0)
        blf.draw(font_id, label)

        try:
            blf.disable(font_id, blf.SHADOW)
        except Exception:
            pass
    except Exception:
        pass


def _draw_center_cross(center_2d, color, size, width):
    x, y = center_2d.x, center_2d.y
    s = size * 0.5
    _draw_line_2d((x - s, y), (x + s, y), color, width)
    _draw_line_2d((x, y - s), (x, y + s), color, width)


def _draw_callback():
    context = bpy.context

    if not _is_view3d_context(context):
        return

    settings = _addon_prefs(context)
    if settings is None:
        return

    if not settings.enabled:
        return

    if not _is_allowed_tool_active(context, settings):
        return

    center = _selected_world_center(context)
    if center is None:
        return

    axes = _axis_vectors(context, settings)

    colors = {
        "X": settings.x_color,
        "Y": settings.y_color,
        "Z": settings.z_color,
    }

    center_2d_ref = None

    for label, axis_vec in axes.items():
        center_2d, unit_2d = _project_axis(context, center, axis_vec)
        if center_2d is None:
            continue

        if center_2d_ref is None:
            center_2d_ref = center_2d

        tip, direction = _draw_arrow_overlay(
            center_2d,
            unit_2d,
            colors[label],
            settings.axis_length,
            settings.arrow_size,
            settings.line_width,
            settings.filled_arrow,
        )

        if settings.show_labels and tip is not None and direction is not None:
            label_pos = tip + direction * settings.label_offset
            _draw_text(label, label_pos, colors[label], settings.font_size)

    if settings.show_center_cross and center_2d_ref is not None:
        _draw_center_cross(
            center_2d_ref,
            settings.center_color,
            settings.center_cross_size,
            settings.center_cross_width,
        )


def _tag_all_view3d_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return

    for window in wm.windows:
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
    if _draw_handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, "WINDOW")
        except Exception:
            pass
        _draw_handler = None


def _settings_update(self, context):
    if self.enabled:
        _ensure_draw_handler()
    else:
        _remove_draw_handler()

    _tag_all_view3d_redraw()


class XYZTransformGizmoOverlayStableSettings(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enable Overlay",
        description="Show X/Y/Z overlay near the selected pivot",
        default=True,
        update=_settings_update,
    )

    only_transform_tools: bpy.props.BoolProperty(
        name="Only While Transform Tools Are Active",
        description="Only draw while Move, Rotate, Scale, or Transform tool is active. Disable this for more stable behavior.",
        default=False,
        update=_settings_update,
    )

    show_on_move: bpy.props.BoolProperty(name="Move", default=True, update=_settings_update)
    show_on_rotate: bpy.props.BoolProperty(name="Rotate", default=True, update=_settings_update)
    show_on_scale: bpy.props.BoolProperty(name="Scale", default=True, update=_settings_update)
    show_on_transform: bpy.props.BoolProperty(name="Transform", default=True, update=_settings_update)

    orientation: bpy.props.EnumProperty(
        name="Orientation",
        description="Use global axes or the active object's local axes",
        items=[
            ("GLOBAL", "Global", "Use world X/Y/Z axes"),
            ("LOCAL", "Local", "Use active object's local X/Y/Z axes"),
        ],
        default="GLOBAL",
        update=_settings_update,
    )

    axis_length: bpy.props.IntProperty(
        name="Axis Length",
        description="Length of the on-screen axis lines in pixels",
        default=46,
        min=10,
        max=240,
        update=_settings_update,
    )

    arrow_size: bpy.props.IntProperty(
        name="Arrow Size",
        description="Arrow head size in pixels",
        default=12,
        min=4,
        max=60,
        update=_settings_update,
    )

    line_width: bpy.props.FloatProperty(
        name="Line Width",
        description="Overlay line width",
        default=2.0,
        min=1.0,
        max=10.0,
        update=_settings_update,
    )

    filled_arrow: bpy.props.BoolProperty(
        name="Filled Arrow Head",
        description="Draw filled triangular arrow heads",
        default=True,
        update=_settings_update,
    )

    show_labels: bpy.props.BoolProperty(
        name="Show Labels",
        description="Show X/Y/Z text next to arrow tips",
        default=True,
        update=_settings_update,
    )

    label_offset: bpy.props.IntProperty(
        name="Label Offset",
        description="Additional distance from arrow tip to label in pixels",
        default=13,
        min=0,
        max=100,
        update=_settings_update,
    )

    font_size: bpy.props.IntProperty(
        name="Font Size",
        description="Size of the X/Y/Z text",
        default=16,
        min=8,
        max=72,
        update=_settings_update,
    )

    show_center_cross: bpy.props.BoolProperty(
        name="Show Center Cross",
        description="Draw a small cross at the projected pivot center",
        default=False,
        update=_settings_update,
    )

    center_cross_size: bpy.props.IntProperty(
        name="Center Cross Size",
        default=10,
        min=4,
        max=50,
        update=_settings_update,
    )

    center_cross_width: bpy.props.FloatProperty(
        name="Center Cross Width",
        default=1.5,
        min=1.0,
        max=10.0,
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
    bl_label = "XYZ Transform Overlay"
    bl_idname = "VIEW3D_PT_xyz_transform_gizmo_overlay_stable"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "View"

    def draw(self, context):
        layout = self.layout
        settings = _addon_prefs(context)

        if settings is None:
            layout.label(text="Settings not found.")
            return

        layout.prop(settings, "enabled")

        col = layout.column()
        col.enabled = settings.enabled

        col.prop(settings, "only_transform_tools")

        tool_box = col.box()
        tool_box.enabled = settings.enabled and settings.only_transform_tools
        tool_box.label(text="Show On")
        row = tool_box.row(align=True)
        row.prop(settings, "show_on_move", toggle=True)
        row.prop(settings, "show_on_rotate", toggle=True)
        row.prop(settings, "show_on_scale", toggle=True)
        row.prop(settings, "show_on_transform", toggle=True)

        col.prop(settings, "orientation")

        shape_box = col.box()
        shape_box.label(text="Overlay Shape")
        shape_box.prop(settings, "axis_length")
        shape_box.prop(settings, "arrow_size")
        shape_box.prop(settings, "line_width")
        shape_box.prop(settings, "filled_arrow")

        label_box = col.box()
        label_box.label(text="Labels")
        label_box.prop(settings, "show_labels")
        sub = label_box.column()
        sub.enabled = settings.show_labels
        sub.prop(settings, "label_offset")
        sub.prop(settings, "font_size")

        center_box = col.box()
        center_box.label(text="Center")
        center_box.prop(settings, "show_center_cross")
        subc = center_box.column()
        subc.enabled = settings.show_center_cross
        subc.prop(settings, "center_cross_size")
        subc.prop(settings, "center_cross_width")
        subc.prop(settings, "center_color")

        color_box = col.box()
        color_box.label(text="Axis Colors")
        color_box.prop(settings, "x_color")
        color_box.prop(settings, "y_color")
        color_box.prop(settings, "z_color")


classes = (
    XYZTransformGizmoOverlayStableSettings,
    VIEW3D_PT_xyz_transform_gizmo_overlay_stable,
)


def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except ValueError:
        # 이미 등록된 경우. 재로드 상황에서 발생할 수 있습니다.
        pass
    except RuntimeError:
        pass


def _safe_unregister_class(cls):
    try:
        # 등록되지 않은 클래스는 bl_rna가 없을 수 있습니다.
        if hasattr(cls, "bl_rna"):
            bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass
    except Exception:
        pass


def register():
    for cls in classes:
        _safe_register_class(cls)

    if not hasattr(bpy.types.Scene, "xyz_transform_gizmo_overlay_stable_settings"):
        bpy.types.Scene.xyz_transform_gizmo_overlay_stable_settings = bpy.props.PointerProperty(
            type=XYZTransformGizmoOverlayStableSettings
        )

    _ensure_draw_handler()


def unregister():
    _remove_draw_handler()

    if hasattr(bpy.types.Scene, "xyz_transform_gizmo_overlay_stable_settings"):
        try:
            del bpy.types.Scene.xyz_transform_gizmo_overlay_stable_settings
        except Exception:
            pass

    for cls in reversed(classes):
        _safe_unregister_class(cls)


if __name__ == "__main__":
    register()
