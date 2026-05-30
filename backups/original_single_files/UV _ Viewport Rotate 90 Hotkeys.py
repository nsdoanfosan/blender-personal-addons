bl_info = {
    "name": "UV / Viewport Rotate 90 Hotkeys",
    "author": "ChatGPT",
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "description": "Rotate selected UVs or 3D selection by 90 degrees with Ctrl + Arrow keys",
    "category": "UV",
}

import bpy
import bmesh
import math
from mathutils import Vector, Matrix


addon_keymaps = []


# ------------------------------------------------------------
# Utility
# ------------------------------------------------------------

def bbox_center_from_vectors(coords):
    min_x = min(v.x for v in coords)
    max_x = max(v.x for v in coords)
    min_y = min(v.y for v in coords)
    max_y = max(v.y for v in coords)

    if len(coords[0]) == 2:
        return Vector(((min_x + max_x) * 0.5, (min_y + max_y) * 0.5))

    min_z = min(v.z for v in coords)
    max_z = max(v.z for v in coords)

    return Vector((
        (min_x + max_x) * 0.5,
        (min_y + max_y) * 0.5,
        (min_z + max_z) * 0.5,
    ))


def get_view_snapped_axis(context):
    """
    현재 3D View 방향을 읽고,
    가장 가까운 월드 X/Y/Z 축으로 보정한다.

    반환:
    axis_world: Vector
    axis_label: str
    """

    rv3d = context.region_data

    if rv3d is None:
        return Vector((0, 0, 1)), "Z"

    # View가 바라보는 방향.
    # Blender view space 기준 -Z가 화면 안쪽 방향이다.
    view_dir = rv3d.view_rotation @ Vector((0, 0, -1))
    view_dir.normalize()

    candidates = [
        ("X", Vector((1, 0, 0))),
        ("-X", Vector((-1, 0, 0))),
        ("Y", Vector((0, 1, 0))),
        ("-Y", Vector((0, -1, 0))),
        ("Z", Vector((0, 0, 1))),
        ("-Z", Vector((0, 0, -1))),
    ]

    axis_label, axis_world = max(
        candidates,
        key=lambda item: view_dir.dot(item[1])
    )

    return axis_world.normalized(), axis_label


# ------------------------------------------------------------
# UV Editor Operator
# ------------------------------------------------------------

class UV_OT_rotate_selected_90_hotkey(bpy.types.Operator):
    bl_idname = "uv.rotate_selected_90_hotkey"
    bl_label = "Rotate Selected UV 90 Degrees"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(
        name="Direction",
        items=[
            ('PLUS', "+90 Degrees", "Rotate selected UVs +90 degrees"),
            ('MINUS', "-90 Degrees", "Rotate selected UVs -90 degrees"),
        ],
        default='PLUS',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        tool_settings = context.tool_settings
        use_uv_sync = tool_settings.use_uv_select_sync
        mesh_select_mode = tool_settings.mesh_select_mode

        objects = getattr(context, "objects_in_mode_unique_data", None)
        if not objects:
            objects = [context.edit_object] if context.edit_object else []

        total_rotated = 0

        for obj in objects:
            if not obj or obj.type != 'MESH':
                continue

            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue

            selected_loops = []
            seen = set()

            def add_loop(loop):
                if loop.face.hide:
                    return

                key = id(loop)
                if key not in seen:
                    seen.add(key)
                    selected_loops.append(loop)

            for face in bm.faces:
                if face.hide:
                    continue

                # UV Sync Selection OFF:
                # UV Editor 자체의 UV 선택 상태 기준
                if not use_uv_sync:
                    for loop in face.loops:
                        luv = loop[uv_layer]

                        if luv.select:
                            add_loop(loop)

                        if getattr(luv, "select_edge", False):
                            add_loop(loop)
                            add_loop(loop.link_loop_next)

                # UV Sync Selection ON:
                # Mesh Edit Mode 선택 상태 기준
                else:
                    if mesh_select_mode[2] and face.select:
                        for loop in face.loops:
                            add_loop(loop)

                    elif mesh_select_mode[1]:
                        for loop in face.loops:
                            if loop.edge.select:
                                add_loop(loop)
                                add_loop(loop.link_loop_next)

                    elif mesh_select_mode[0]:
                        for loop in face.loops:
                            if loop.vert.select:
                                add_loop(loop)

            if not selected_loops:
                continue

            coords = [loop[uv_layer].uv.copy() for loop in selected_loops]
            center = bbox_center_from_vectors(coords)

            for loop in selected_loops:
                uv = loop[uv_layer].uv

                dx = uv.x - center.x
                dy = uv.y - center.y

                if self.direction == 'PLUS':
                    uv.x = center.x - dy
                    uv.y = center.y + dx
                else:
                    uv.x = center.x + dy
                    uv.y = center.y - dx

            bmesh.update_edit_mesh(mesh)
            total_rotated += len(selected_loops)

        if total_rotated == 0:
            self.report({'WARNING'}, "No selected UVs found.")
            return {'CANCELLED'}

        return {'FINISHED'}


# ------------------------------------------------------------
# 3D Viewport Operator
# ------------------------------------------------------------

class VIEW3D_OT_rotate_selected_90_snap_axis(bpy.types.Operator):
    bl_idname = "view3d.rotate_selected_90_snap_axis"
    bl_label = "Rotate Selected 90 Degrees by Snapped View Axis"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(
        name="Direction",
        items=[
            ('PLUS', "+90 Degrees", "Rotate +90 degrees"),
            ('MINUS', "-90 Degrees", "Rotate -90 degrees"),
        ],
        default='PLUS',
    )

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D'

    def execute(self, context):
        axis_world, axis_label = get_view_snapped_axis(context)

        angle = math.radians(90.0)
        if self.direction == 'MINUS':
            angle *= -1.0

        if context.mode == 'EDIT_MESH':
            result = self.rotate_edit_mesh_selection(context, axis_world, angle)
        elif context.mode == 'OBJECT':
            result = self.rotate_object_selection(context, axis_world, angle)
        else:
            self.report({'WARNING'}, "Only Object Mode and Edit Mesh Mode are supported.")
            return {'CANCELLED'}

        if result:
            sign = "+90" if self.direction == 'PLUS' else "-90"
            self.report({'INFO'}, f"Rotated {sign} around snapped view axis: {axis_label}")
            return {'FINISHED'}

        self.report({'WARNING'}, "No valid selection found.")
        return {'CANCELLED'}

    def rotate_object_selection(self, context, axis_world, angle):
        objects = [
            obj for obj in context.selected_objects
            if obj and obj.type in {'MESH', 'CURVE', 'EMPTY', 'ARMATURE', 'LIGHT', 'CAMERA'}
        ]

        if not objects:
            return False

        rot = Matrix.Rotation(angle, 4, axis_world)

        for obj in objects:
            origin = obj.matrix_world.translation.copy()

            # 오브젝트의 위치는 유지하고,
            # 오브젝트 원점 기준으로 방향만 90도 회전
            obj.matrix_world = (
                Matrix.Translation(origin)
                @ rot
                @ Matrix.Translation(-origin)
                @ obj.matrix_world
            )

        return True

    def rotate_edit_mesh_selection(self, context, axis_world, angle):
        objects = getattr(context, "objects_in_mode_unique_data", None)
        if not objects:
            objects = [context.edit_object] if context.edit_object else []

        edit_data = []
        world_coords = []

        for obj in objects:
            if not obj or obj.type != 'MESH':
                continue

            bm = bmesh.from_edit_mesh(obj.data)

            selected_verts = set()

            for v in bm.verts:
                if v.select and not v.hide:
                    selected_verts.add(v)

            for e in bm.edges:
                if e.select and not e.hide:
                    for v in e.verts:
                        if not v.hide:
                            selected_verts.add(v)

            for f in bm.faces:
                if f.select and not f.hide:
                    for v in f.verts:
                        if not v.hide:
                            selected_verts.add(v)

            if not selected_verts:
                continue

            edit_data.append((obj, bm, list(selected_verts)))

            for v in selected_verts:
                world_coords.append(obj.matrix_world @ v.co)

        if not world_coords:
            return False

        center_world = bbox_center_from_vectors(world_coords)
        rot3 = Matrix.Rotation(angle, 3, axis_world)

        for obj, bm, verts in edit_data:
            inv_world = obj.matrix_world.inverted()

            for v in verts:
                wp = obj.matrix_world @ v.co
                new_wp = center_world + (rot3 @ (wp - center_world))
                v.co = inv_world @ new_wp

            bmesh.update_edit_mesh(obj.data)

        return True


# ------------------------------------------------------------
# Register
# ------------------------------------------------------------

classes = (
    UV_OT_rotate_selected_90_hotkey,
    VIEW3D_OT_rotate_selected_90_snap_axis,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc:
        # UV Editor hotkeys
        km = kc.keymaps.new(
            name='UV Editor',
            space_type='IMAGE_EDITOR',
            region_type='WINDOW'
        )

        kmi = km.keymap_items.new(
            UV_OT_rotate_selected_90_hotkey.bl_idname,
            type='RIGHT_ARROW',
            value='PRESS',
            ctrl=True
        )
        kmi.properties.direction = 'PLUS'
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            UV_OT_rotate_selected_90_hotkey.bl_idname,
            type='LEFT_ARROW',
            value='PRESS',
            ctrl=True
        )
        kmi.properties.direction = 'MINUS'
        addon_keymaps.append((km, kmi))

        # 3D View hotkeys
        km = kc.keymaps.new(
            name='3D View',
            space_type='VIEW_3D',
            region_type='WINDOW'
        )

        kmi = km.keymap_items.new(
            VIEW3D_OT_rotate_selected_90_snap_axis.bl_idname,
            type='RIGHT_ARROW',
            value='PRESS',
            ctrl=True
        )
        kmi.properties.direction = 'PLUS'
        addon_keymaps.append((km, kmi))

        kmi = km.keymap_items.new(
            VIEW3D_OT_rotate_selected_90_snap_axis.bl_idname,
            type='LEFT_ARROW',
            value='PRESS',
            ctrl=True
        )
        kmi.properties.direction = 'MINUS'
        addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass

    addon_keymaps.clear()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()