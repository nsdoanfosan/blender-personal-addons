import bpy
import os
from bpy.props import StringProperty
from bpy.types import Operator, Panel, PropertyGroup


# 🧩 경로 저장용 속성 정의
class ExportSettings(PropertyGroup):
    export_path: StringProperty(
        name="Export Folder",
        description="FBX가 저장될 폴더 경로입니다.",
        default="",
        subtype='DIR_PATH'
    )


# 🚀 실제 익스포트 실행
class OBJECT_OT_export_child_collections_fixed(bpy.types.Operator):
    bl_idname = "object.export_fbx_child_collections_fixed"
    bl_label = "Export Collections with Fixed Settings"
    bl_description = "하위 컬렉션을 지정된 설정 및 경로로 FBX로 자동 저장합니다."

    def execute(self, context):
        settings = context.scene.ta_export_settings
        path = settings.export_path.strip()

        if not path:
            path = bpy.path.abspath("//exported_fbx")

        os.makedirs(path, exist_ok=True)

        active_col = context.view_layer.active_layer_collection.collection
        if not active_col or not active_col.children:
            self.report({'WARNING'}, "활성 컬렉션에 하위 컬렉션이 없습니다.")
            return {'CANCELLED'}

        exported = 0
        for child_col in active_col.children:
            objs = [obj for obj in child_col.objects if obj.visible_get()]
            if not objs:
                continue

            bpy.ops.object.select_all(action='DESELECT')
            for obj in objs:
                obj.select_set(True)
            context.view_layer.objects.active = objs[0]

            fbx_path = os.path.join(path, f"{child_col.name}.fbx")

            bpy.ops.export_scene.fbx(
                filepath=fbx_path,
                use_selection=True,
                apply_unit_scale=False,  # 🔥 단위 적용 비활성화!
                apply_scale_options='FBX_SCALE_NONE',  # 🔥 스케일 보정 없음!
                object_types={'MESH'},
                mesh_smooth_type='FACE',
                use_space_transform=False,
                axis_forward='-Y',
                axis_up='Z'
            )

            exported += 1
            self.report({'INFO'}, f"✅ Exported: {child_col.name}.fbx")

        if exported == 0:
            self.report({'WARNING'}, "익스포트된 항목이 없습니다.")
        else:
            self.report({'INFO'}, f"{exported}개 컬렉션이 익스포트되었습니다.")
        return {'FINISHED'}


# 🖼️ UI Panel
class OBJECT_PT_fbx_export_panel_fixed(bpy.types.Panel):
    bl_label = "Collection FBX Exporter"
    bl_idname = "OBJECT_PT_fbx_export_panel_fixed"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA Tools'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.ta_export_settings

        layout.label(text="📦 Export FBX by Collection Name")
        layout.prop(settings, "export_path")
        layout.operator("object.export_fbx_child_collections_fixed", icon="EXPORT")


# 📦 등록
classes = (
    ExportSettings,
    OBJECT_OT_export_child_collections_fixed,
    OBJECT_PT_fbx_export_panel_fixed,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ta_export_settings = bpy.props.PointerProperty(type=ExportSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ta_export_settings


if __name__ == "__main__":
    register()