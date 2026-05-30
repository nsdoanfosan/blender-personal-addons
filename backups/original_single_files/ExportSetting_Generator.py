bl_info = {
    "name":        "Collection FBX Exporter",
    "author":      "YourName",
    "version":     (1, 1, 0),
    "blender":     (3, 0, 0),
    "location":    "View3D > Sidebar > TA Tools",
    "description": "Exports every direct child collection (and all nested sub-collections) "
                   "to individual FBX files with fixed settings.",
    "category":    "Import-Export",
}

import bpy
import os
from bpy.props import StringProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup


# ─────────────────────────────────────────────────────────────
# 1) 사용자 설정 : 저장 경로만 UI로 입력받도록 정의
# ─────────────────────────────────────────────────────────────
class TAExportSettings(PropertyGroup):
    export_path: StringProperty(
        name="Export Folder",
        description="FBX가 저장될 폴더 (공백이면 //exported_fbx)",
        default="",
        subtype='DIR_PATH'
    )


# ─────────────────────────────────────────────────────────────
# 2) 헬퍼 : 재귀적으로 오브젝트 수집
# ─────────────────────────────────────────────────────────────
def gather_objects_recursive(col):
    """col 및 그 모든 하위 컬렉션의 오브젝트를 리스트로 반환."""
    objs = list(col.objects)
    for sub in col.children:
        objs.extend(gather_objects_recursive(sub))
    return objs


# ─────────────────────────────────────────────────────────────
# 3) 메인 Operator
# ─────────────────────────────────────────────────────────────
class OBJECT_OT_export_fbx_child_collections_fixed(Operator):
    bl_idname = "object.ta_export_child_collections_fbx"
    bl_label = "Export Child Collections to FBX"
    bl_description = "지정된 설정으로 하위 컬렉션들을 FBX로 자동 저장합니다."

    def execute(self, context):
        settings   = context.scene.ta_export_settings
        export_dir = settings.export_path.strip() or bpy.path.abspath("//exported_fbx")
        os.makedirs(export_dir, exist_ok=True)

        active_col = context.view_layer.active_layer_collection.collection
        if not active_col or not active_col.children:
            self.report({'WARNING'}, "활성 컬렉션에 하위 컬렉션이 없습니다.")
            return {'CANCELLED'}

        exported = 0
        for child in active_col.children:
            # ── 재귀적으로 모든 오브젝트 수집 ────────────────────
            objs = [o for o in gather_objects_recursive(child) if o.visible_get()]
            if not objs:
                continue

            # 선택 상태 세팅
            bpy.ops.object.select_all(action='DESELECT')
            for o in objs:
                o.select_set(True)
            context.view_layer.objects.active = objs[0]

            # 파일 경로 결정
            filepath = os.path.join(export_dir, f"{child.name}.fbx")

            # FBX Export 호출 (지정된 고정 세팅)
            bpy.ops.export_scene.fbx(
                filepath           = filepath,
                use_selection      = True,           # Selected Objects ✅
                apply_unit_scale   = False,          # 100배 축소 방지
                apply_scale_options= 'FBX_SCALE_NONE',
                object_types       = {'MESH'},
                mesh_smooth_type   = 'FACE',
                use_space_transform= False,          # Use Space Transform ❌
                axis_forward       = '-Y',           # Forward  -Y
                axis_up            = 'Z'             # Up       Z
            )

            exported += 1
            self.report({'INFO'}, f"✅ Exported: {child.name}.fbx")

        if exported == 0:
            self.report({'WARNING'}, "익스포트된 컬렉션이 없습니다.")
        else:
            self.report({'INFO'}, f"{exported}개 컬렉션을 익스포트했습니다.")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────
# 4) UI 패널 (N 패널 > TA Tools)
# ─────────────────────────────────────────────────────────────
class OBJECT_PT_ta_fbx_export_panel(Panel):
    bl_label       = "Collection FBX Exporter"
    bl_idname      = "OBJECT_PT_ta_fbx_export_panel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'TA Tools'

    def draw(self, context):
        layout   = self.layout
        settings = context.scene.ta_export_settings

        layout.prop(settings, "export_path")
        layout.operator("object.ta_export_child_collections_fbx", icon="EXPORT")


# ─────────────────────────────────────────────────────────────
# 5) Register / Unregister
# ─────────────────────────────────────────────────────────────
classes = (
    TAExportSettings,
    OBJECT_OT_export_fbx_child_collections_fixed,
    OBJECT_PT_ta_fbx_export_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ta_export_settings = PointerProperty(type=TAExportSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ta_export_settings