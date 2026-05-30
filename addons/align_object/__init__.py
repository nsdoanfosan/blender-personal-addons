bl_info = {
    "name": "Move Each Selected Object To Clicked Object - Alt A",
    "author": "ChatGPT",
    "version": (1, 6, 0),
    "blender": (4, 0, 0),
    "category": "Object",
}

import bpy
import json
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils


addon_keymaps = []


def matrix_to_list(matrix):
    return [[matrix[row][col] for col in range(4)] for row in range(4)]


def list_to_matrix(data):
    return Matrix(data)


class OBJECT_OT_move_each_selected_to_clicked_object(bpy.types.Operator):
    bl_idname = "object.move_each_selected_to_clicked_object"
    bl_label = "Move Each Selected To Clicked Object"
    bl_description = "Alt+A로 실행 후, 선택 오브젝트 각각의 기준점을 클릭한 오브젝트 기준점으로 이동"
    bl_options = {'REGISTER', 'UNDO'}

    use_x: bpy.props.BoolProperty(
        name="X",
        description="X 위치 이동 활성화",
        default=True,
    )

    use_y: bpy.props.BoolProperty(
        name="Y",
        description="Y 위치 이동 활성화",
        default=True,
    )

    use_z: bpy.props.BoolProperty(
        name="Z",
        description="Z 위치 이동 활성화",
        default=True,
    )

    reference_mode: bpy.props.EnumProperty(
        name="Reference",
        description="위치를 맞출 기준",
        items=[
            ('PIVOT', "Pivot / Origin", "각 오브젝트의 피봇, 즉 Object Origin 기준"),
            ('BOUNDING_BOX', "Bounding Box Center", "각 오브젝트의 바운딩 박스 중심 기준"),
        ],
        default='PIVOT',
    )

    apply_rotation: bpy.props.BoolProperty(
        name="Apply Rotation",
        description="각 선택 오브젝트의 로테이션을 클릭한 오브젝트의 월드 로테이션에 맞춤",
        default=False,
    )

    source_names_json: bpy.props.StringProperty(
        name="Source Objects",
        default="[]",
        options={'HIDDEN'},
    )

    original_matrices_json: bpy.props.StringProperty(
        name="Original Matrices",
        default="{}",
        options={'HIDDEN'},
    )

    active_source_name: bpy.props.StringProperty(
        name="Active Source",
        default="",
        options={'HIDDEN'},
    )

    target_name: bpy.props.StringProperty(
        name="Target Object",
        default="",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "3D Viewport에서 실행해야 합니다.")
            return {'CANCELLED'}

        active = context.view_layer.objects.active

        if active is None:
            self.report({'ERROR'}, "Active Object가 없습니다.")
            return {'CANCELLED'}

        sources = list(context.selected_objects)

        if not sources:
            self.report({'ERROR'}, "이동시킬 오브젝트를 먼저 선택하세요.")
            return {'CANCELLED'}

        if active not in sources:
            sources.append(active)

        self.source_names_json = json.dumps([obj.name for obj in sources])
        self.original_matrices_json = json.dumps({
            obj.name: matrix_to_list(obj.matrix_world.copy())
            for obj in sources
        })

        self.active_source_name = active.name
        self.target_name = ""

        # 클릭 직후 기본 적용값
        self.use_x = True
        self.use_y = True
        self.use_z = True
        self.reference_mode = 'PIVOT'
        self.apply_rotation = False

        context.window_manager.modal_handler_add(self)
        context.window.cursor_set('EYEDROPPER')
        context.workspace.status_text_set(
            "타겟 오브젝트를 클릭하세요. 선택 오브젝트 각각의 기준점이 타겟 기준점으로 이동합니다. / ESC 또는 우클릭 취소"
        )

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self._finish_pick_mode(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            target = self._pick_object(context, event)

            if target is None:
                self.report({'WARNING'}, "오브젝트를 클릭하지 않았습니다.")
                return {'RUNNING_MODAL'}

            source_names = self._get_source_names()

            if target.name in source_names:
                self.report({'WARNING'}, "이동 대상에 포함되지 않은 다른 오브젝트를 클릭하세요.")
                return {'RUNNING_MODAL'}

            self.target_name = target.name

            # 클릭 즉시 기본 옵션으로 이동
            self._restore_original_matrices()
            self._apply_transform_from_original()

            self._restore_selection(context)
            self._finish_pick_mode(context)
            self._redraw_viewport(context)

            self.report(
                {'INFO'},
                "Moved. 왼쪽 아래 Adjust Last Operation 또는 F9에서 옵션 수정 가능."
            )

            # FINISHED가 되어야 왼쪽 아래 Adjust Last Operation 패널이 뜸
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        """
        왼쪽 아래 Adjust Last Operation 패널에서 옵션을 바꿀 때마다 호출됨.
        현재 위치에서 누적 이동하지 않고, 저장해둔 원래 matrix 기준으로 다시 계산.
        """
        if not self.target_name:
            self.report({'ERROR'}, "Target Object가 없습니다.")
            return {'CANCELLED'}

        self._restore_original_matrices()
        self._apply_transform_from_original()
        self._restore_selection(context)
        self._redraw_viewport(context)

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout

        target = bpy.data.objects.get(self.target_name)

        if target:
            box = layout.box()
            box.label(text=f"Target: {target.name}")

        box = layout.box()
        box.label(text="Move Axis")
        row = box.row(align=True)
        row.prop(self, "use_x", toggle=True)
        row.prop(self, "use_y", toggle=True)
        row.prop(self, "use_z", toggle=True)

        box = layout.box()
        box.prop(self, "reference_mode", text="Reference Mode")

        box = layout.box()
        box.prop(self, "apply_rotation")

    def _apply_transform_from_original(self):
        sources = self._get_source_objects()
        target = bpy.data.objects.get(self.target_name)

        if not sources or target is None:
            return

        target_anchor = self._get_reference_position(target)
        target_rotation = target.matrix_world.to_quaternion()

        for obj in sources:
            source_anchor = self._get_reference_position(obj)

            desired_anchor = source_anchor.copy()

            if self.use_x:
                desired_anchor.x = target_anchor.x
            if self.use_y:
                desired_anchor.y = target_anchor.y
            if self.use_z:
                desired_anchor.z = target_anchor.z

            if not self.apply_rotation:
                location_delta = desired_anchor - source_anchor

                matrix = obj.matrix_world.copy()
                matrix.translation += location_delta
                obj.matrix_world = matrix

                continue

            old_matrix = obj.matrix_world.copy()
            old_rotation = old_matrix.to_quaternion()

            rotation_delta = target_rotation @ old_rotation.inverted()

            # 각 오브젝트 자신의 기준점 Pivot / Bounding Box Center를 중심으로 회전
            rotation_matrix = rotation_delta.to_matrix().to_4x4()

            rotated_matrix = (
                Matrix.Translation(source_anchor)
                @ rotation_matrix
                @ Matrix.Translation(-source_anchor)
                @ old_matrix
            )

            obj.matrix_world = rotated_matrix

            # 회전 후 기준점 위치를 다시 계산해서 타겟 기준점으로 보정
            rotated_anchor = self._get_reference_position(obj)

            corrected_anchor = rotated_anchor.copy()

            if self.use_x:
                corrected_anchor.x = target_anchor.x
            if self.use_y:
                corrected_anchor.y = target_anchor.y
            if self.use_z:
                corrected_anchor.z = target_anchor.z

            location_delta = corrected_anchor - rotated_anchor

            final_matrix = obj.matrix_world.copy()
            final_matrix.translation += location_delta
            obj.matrix_world = final_matrix

    def _restore_original_matrices(self):
        try:
            original_data = json.loads(self.original_matrices_json)
        except Exception:
            return

        for name, matrix_data in original_data.items():
            obj = bpy.data.objects.get(name)
            if obj:
                obj.matrix_world = list_to_matrix(matrix_data)

    def _get_source_names(self):
        try:
            return json.loads(self.source_names_json)
        except Exception:
            return []

    def _get_source_objects(self):
        return [
            bpy.data.objects[name]
            for name in self._get_source_names()
            if name in bpy.data.objects
        ]

    def _get_reference_position(self, obj):
        if self.reference_mode == 'PIVOT':
            return obj.matrix_world.translation.copy()

        return self._get_world_bounding_box_center(obj)

    def _get_world_bounding_box_center(self, obj):
        corners = [
            obj.matrix_world @ Vector(corner)
            for corner in obj.bound_box
        ]

        center = Vector((0.0, 0.0, 0.0))

        for corner in corners:
            center += corner

        center /= 8.0

        return center

    def _pick_object(self, context, event):
        region = context.region
        rv3d = context.space_data.region_3d

        coord = (
            event.mouse_region_x,
            event.mouse_region_y
        )

        ray_origin = view3d_utils.region_2d_to_origin_3d(
            region,
            rv3d,
            coord
        )

        ray_direction = view3d_utils.region_2d_to_vector_3d(
            region,
            rv3d,
            coord
        )

        depsgraph = context.evaluated_depsgraph_get()

        hit, location, normal, face_index, obj, matrix = context.scene.ray_cast(
            depsgraph,
            ray_origin,
            ray_direction
        )

        if not hit:
            return None

        return getattr(obj, "original", obj)

    def _restore_selection(self, context):
        bpy.ops.object.select_all(action='DESELECT')

        for obj in self._get_source_objects():
            obj.select_set(True)

        active_source = bpy.data.objects.get(self.active_source_name)
        if active_source:
            context.view_layer.objects.active = active_source

    def _finish_pick_mode(self, context):
        context.window.cursor_set('DEFAULT')
        context.workspace.status_text_set(None)

    def _redraw_viewport(self, context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


classes = (
    OBJECT_OT_move_each_selected_to_clicked_object,
)


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc is None:
        return

    km = kc.keymaps.new(
        name='3D View',
        space_type='VIEW_3D'
    )

    kmi = km.keymap_items.new(
        OBJECT_OT_move_each_selected_to_clicked_object.bl_idname,
        type='A',
        value='PRESS',
        alt=True
    )

    addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)

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