bl_info = {
    "name": "Linked Data Info Panel",
    "author": "OpenAI",
    "version": (1, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Item",
    "description": "Show objects sharing the same object data and select them",
    "category": "3D View",
}

import bpy
from bpy.props import StringProperty


def get_shared_objects(context, obj):
    if obj is None or getattr(obj, "data", None) is None:
        return []

    target_data = obj.data
    shared = []

    for other in context.view_layer.objects:
        if getattr(other, "data", None) == target_data:
            shared.append(other)

    shared.sort(key=lambda x: x.name.lower())
    return shared


class OBJECT_OT_select_linked_data_target(bpy.types.Operator):
    bl_idname = "object.select_linked_data_target"
    bl_label = "Select Linked Object"
    bl_description = "Select this object"

    object_name: StringProperty()

    def execute(self, context):
        obj = context.view_layer.objects.get(self.object_name)

        if obj is None:
            self.report({'WARNING'}, f"Object not found in current view layer: {self.object_name}")
            return {'CANCELLED'}

        if obj.hide_select:
            self.report({'WARNING'}, f"Object is not selectable: {obj.name}")
            return {'CANCELLED'}

        if obj.hide_get():
            self.report({'WARNING'}, f"Object is hidden: {obj.name}")
            return {'CANCELLED'}

        for other in context.view_layer.objects:
            other.select_set(False)

        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class VIEW3D_PT_linked_data_info(bpy.types.Panel):
    bl_label = "Linked Data Info"
    bl_idname = "VIEW3D_PT_linked_data_info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        obj = context.active_object

        if obj is None:
            box = layout.box()
            row = box.row()
            row.label(text="No active object", icon='INFO')
            return

        data = getattr(obj, "data", None)
        if data is None:
            box = layout.box()
            row = box.row()
            row.label(text=obj.name, icon='OBJECT_DATA')
            row = box.row()
            row.label(text="This object has no object data", icon='INFO')
            return

        shared = get_shared_objects(context, obj)
        linked_count = max(0, len(shared) - 1)

        # Header
        header = layout.box()
        row = header.row(align=True)
        row.label(text=obj.name, icon='OBJECT_DATA')

        status_row = header.row(align=True)
        if len(shared) > 1:
            status_row.label(text=f"Linked duplicates: {linked_count}", icon='LINKED')
        else:
            status_row.label(text="Single user data", icon='UNLINKED')

        # Data info
        info = layout.box()
        col = info.column(align=True)
        row = col.row(align=True)
        row.label(text="Data")
        row.label(text=data.name, icon='MESH_DATA' if obj.type == 'MESH' else 'DOT')

        row = col.row(align=True)
        row.label(text="Users")
        row.label(text=str(data.users))

        # Shared list
        shared_box = layout.box()
        row = shared_box.row()
        row.label(text="Shared Objects", icon='OUTLINER_OB_GROUP_INSTANCE')

        if len(shared) <= 1:
            row = shared_box.row()
            row.enabled = False
            row.label(text="No linked duplicates found")
            return

        col = shared_box.column(align=True)

        for other in shared:
            row = col.row(align=True)

            icon = 'RESTRICT_SELECT_OFF'
            if other == obj:
                icon = 'CHECKMARK'

            op = row.operator(
                "object.select_linked_data_target",
                text=other.name,
                icon=icon,
                emboss=True
            )
            op.object_name = other.name

            if other == obj:
                row.label(text="", icon='RADIOBUT_ON')


classes = (
    OBJECT_OT_select_linked_data_target,
    VIEW3D_PT_linked_data_info,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()