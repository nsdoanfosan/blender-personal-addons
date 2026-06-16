import bpy
import bmesh

# ─────────────────────────────────────────────
# ① Vertex Group + White Color Setup
# ─────────────────────────────────────────────

class TA_OT_setup_vertex_color(bpy.types.Operator):
    bl_idname = "object.ta_setup_vertex_color"
    bl_label = "Setup Group & Color"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            mesh = obj.data

            obj.vertex_groups.clear()
            obj.vertex_groups.new(name="Group")

            for attr in list(mesh.color_attributes):
                mesh.color_attributes.remove(attr)

            col = mesh.color_attributes.new(
                name="Color",
                domain='POINT',
                type='FLOAT_COLOR'
            )

            white = (1.0, 1.0, 1.0, 1.0)
            for elem in col.data:
                elem.color = white

        self.report({'INFO'}, "빈 Group + 흰색 Color 세팅 완료!")
        return {'FINISHED'}


class TA_PT_vertex_color_panel(bpy.types.Panel):
    bl_label = "Vertex Group & Color"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        self.layout.operator("object.ta_setup_vertex_color", icon='GROUP_VERTEX')


# ─────────────────────────────────────────────
# ② Max-style Connect Edge (신규 엣지만 선택)
# ─────────────────────────────────────────────

class TA_OT_connect_edge(bpy.types.Operator):
    bl_idname = "mesh.ta_connect_edge"
    bl_label = "Connect Edge"
    bl_options = {"REGISTER", "UNDO"}

    cuts: bpy.props.IntProperty(
        name="Cuts",
        default=1,
        min=1,
        max=10,
    )

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob and ob.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        selected_edges = [e for e in bm.edges if e.select]
        if not selected_edges:
            self.report({'WARNING'}, "No edges selected")
            return {'CANCELLED'}

        # 기존 선택 해제
        for e in bm.edges:
            e.select = False

        result = bmesh.ops.subdivide_edges(
            bm,
            edges=selected_edges,
            cuts=self.cuts,
            use_grid_fill=False
        )

        new_edges = [
            ele for ele in result["geom_split"]
            if isinstance(ele, bmesh.types.BMEdge)
        ]

        for e in new_edges:
            e.select = True

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}


class TA_PT_connect_edge_panel(bpy.types.Panel):
    bl_label = "Connect Edge"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA'

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        op = layout.operator("mesh.ta_connect_edge", icon='EDGESEL')
        layout.prop(op, "cuts")


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────

classes = (
    TA_OT_setup_vertex_color,
    TA_PT_vertex_color_panel,
    TA_OT_connect_edge,
    TA_PT_connect_edge_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
