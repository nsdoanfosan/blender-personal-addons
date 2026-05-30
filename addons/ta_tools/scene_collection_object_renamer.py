bl_info = {
    "name": "Scene Collection Object Renamer",
    "author": "ChatGPT",
    "version": (1, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Rename Tools",
    "description": "Rename all objects in scene collections based on their collection names, excluding Export collection traversal",
    "category": "Object",
}

import bpy
import uuid


EXCLUDED_COLLECTION_NAMES = {"Export"}


def is_excluded_collection(collection):
    return collection.name in EXCLUDED_COLLECTION_NAMES


def get_all_scene_collections_excluding(scene):
    """
    Scene Collection 아래의 모든 하위 컬렉션을 가져오되,
    Export 컬렉션과 그 하위 컬렉션은 순회하지 않음.
    단, Export에 링크된 오브젝트라도 다른 일반 컬렉션에 있으면 이름 변경 가능.
    """
    result = []

    def walk(collection):
        for child in collection.children:
            if is_excluded_collection(child):
                continue

            result.append(child)
            walk(child)

    walk(scene.collection)
    return result


def collect_rename_pairs(scene, only_mesh=False):
    collections = get_all_scene_collections_excluding(scene)

    rename_pairs = []
    processed_objects = set()

    for collection in collections:
        objects = list(collection.objects)

        if only_mesh:
            objects = [obj for obj in objects if obj.type == "MESH"]

        objects.sort(key=lambda obj: obj.name)

        index = 1

        for obj in objects:
            obj_id = obj.as_pointer()

            if obj_id in processed_objects:
                continue

            processed_objects.add(obj_id)

            new_name = f"{collection.name}_{index:02d}"
            rename_pairs.append((obj, new_name))

            index += 1

    return rename_pairs


class SCOR_Settings(bpy.types.PropertyGroup):
    only_mesh_objects: bpy.props.BoolProperty(
        name="Only Mesh Objects",
        description="Mesh 오브젝트만 이름을 변경합니다",
        default=False
    )


class SCOR_OT_RenameAllSceneObjects(bpy.types.Operator):
    bl_idname = "scor.rename_all_scene_objects"
    bl_label = "Rename All Scene Objects"
    bl_description = "현재 Scene 안의 모든 컬렉션을 기준으로 오브젝트 이름을 변경합니다. Export 컬렉션은 순회하지 않습니다"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.scor_settings

        rename_pairs = collect_rename_pairs(
            context.scene,
            only_mesh=settings.only_mesh_objects
        )

        if not rename_pairs:
            self.report({"WARNING"}, "No objects to rename")
            return {"CANCELLED"}

        temp_id = uuid.uuid4().hex[:8]

        for i, (obj, new_name) in enumerate(rename_pairs):
            obj.name = f"__temp_scor_{temp_id}_{i:04d}"

        for obj, new_name in rename_pairs:
            obj.name = new_name

        self.report(
            {"INFO"},
            f"Renamed {len(rename_pairs)} objects. Export collection traversal was excluded."
        )

        return {"FINISHED"}


class SCOR_PT_Panel(bpy.types.Panel):
    bl_label = "Scene Object Renamer"
    bl_idname = "SCOR_PT_scene_object_renamer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rename Tools"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.scor_settings

        box = layout.box()
        box.label(text="Scene Collection Rename")
        box.label(text="Rename objects by collection name")

        box.separator()
        box.label(text="Excluded Traversal: Export", icon="HIDE_ON")
        box.prop(settings, "only_mesh_objects")

        layout.separator()

        layout.operator(
            "scor.rename_all_scene_objects",
            text="Rename All Scene Objects",
            icon="OUTLINER_COLLECTION"
        )


classes = (
    SCOR_Settings,
    SCOR_OT_RenameAllSceneObjects,
    SCOR_PT_Panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.scor_settings = bpy.props.PointerProperty(type=SCOR_Settings)


def unregister():
    del bpy.types.Scene.scor_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()