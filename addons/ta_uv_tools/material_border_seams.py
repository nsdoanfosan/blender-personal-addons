import bpy
import bmesh


def get_mesh_objects(context):
    selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
    if selected:
        return selected

    active = context.active_object
    if active and active.type == 'MESH':
        return [active]

    return []


def mark_object_mode(obj, clear_existing, include_open_borders, select_edges):
    mesh = obj.data
    edge_key_to_index = {edge.key: edge.index for edge in mesh.edges}
    face_materials_by_edge = {edge.index: [] for edge in mesh.edges}
    touched = 0

    if clear_existing:
        for edge in mesh.edges:
            edge.use_seam = False
            edge.select = False

    for poly in mesh.polygons:
        for edge_key in poly.edge_keys:
            edge_index = edge_key_to_index.get(edge_key)
            if edge_index is not None:
                face_materials_by_edge[edge_index].append(poly.material_index)

    for edge in mesh.edges:
        materials = face_materials_by_edge.get(edge.index, [])
        is_material_border = len(materials) >= 2 and len(set(materials)) > 1
        is_open_border = include_open_borders and len(materials) == 1

        if is_material_border or is_open_border:
            edge.use_seam = True
            if select_edges:
                edge.select = True
            touched += 1
        elif select_edges:
            edge.select = False

    mesh.update()
    return touched


def mark_edit_mode(obj, clear_existing, include_open_borders, select_edges):
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    touched = 0

    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if clear_existing:
        for edge in bm.edges:
            edge.seam = False
            edge.select = False

    for edge in bm.edges:
        materials = [face.material_index for face in edge.link_faces]
        is_material_border = len(materials) >= 2 and len(set(materials)) > 1
        is_open_border = include_open_borders and len(materials) == 1

        if is_material_border or is_open_border:
            edge.seam = True
            if select_edges:
                edge.select = True
            touched += 1
        elif select_edges:
            edge.select = False

    bmesh.update_edit_mesh(mesh)
    return touched


class UV_OT_mark_material_border_seams(bpy.types.Operator):
    bl_idname = "uv.mark_material_border_seams"
    bl_label = "Mark Material Border Seams"
    bl_description = "Mark UV seams on mesh edges between different material slots"
    bl_options = {'REGISTER', 'UNDO'}

    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing Seams",
        description="Remove existing seams before marking material borders",
        default=False,
    )

    include_open_borders: bpy.props.BoolProperty(
        name="Include Open Borders",
        description="Also mark mesh boundary edges that have only one connected face",
        default=False,
    )

    select_edges: bpy.props.BoolProperty(
        name="Select Result Edges",
        description="Select the marked material border edges after running",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return bool(get_mesh_objects(context))

    def execute(self, context):
        objects = get_mesh_objects(context)
        total_edges = 0

        if context.mode == 'EDIT_MESH':
            bpy.ops.mesh.select_mode(type='EDGE')
            for obj in objects:
                if obj.mode == 'EDIT':
                    total_edges += mark_edit_mode(
                        obj,
                        self.clear_existing,
                        self.include_open_borders,
                        self.select_edges,
                    )
        else:
            for obj in objects:
                total_edges += mark_object_mode(
                    obj,
                    self.clear_existing,
                    self.include_open_borders,
                    self.select_edges,
                )

        self.report({'INFO'}, f"Marked {total_edges} material border seam edge(s).")
        return {'FINISHED'}


class UV_PT_material_border_seams(bpy.types.Panel):
    bl_label = "Material Border Seams"
    bl_idname = "UV_PT_material_border_seams"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Tools"

    def draw(self, context):
        self.layout.operator(
            UV_OT_mark_material_border_seams.bl_idname,
            text="Mark Material Border Seams",
        )


def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(
        UV_OT_mark_material_border_seams.bl_idname,
        text="Mark Material Border Seams"
    )


classes = (
    UV_OT_mark_material_border_seams,
    UV_PT_material_border_seams,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.IMAGE_MT_uvs.append(menu_func)


def unregister():
    bpy.types.IMAGE_MT_uvs.remove(menu_func)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
