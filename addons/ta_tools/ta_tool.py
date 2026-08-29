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

def _ta_geometry_nodes_input_values(modifier):
    inputs = getattr(getattr(modifier, "properties", None), "inputs", None)
    interface = getattr(getattr(modifier, "node_group", None), "interface", None)
    if inputs is not None and interface is not None:
        for item in interface.items_tree:
            if (
                getattr(item, "item_type", None) != "SOCKET"
                or getattr(item, "in_out", None) != "INPUT"
            ):
                continue
            try:
                input_group = inputs[item.identifier]
                if "value" in input_group:
                    yield input_group["value"]
            except (KeyError, TypeError):
                continue
        return

    try:
        for key in modifier.keys():
            yield modifier.get(key)
    except (AttributeError, TypeError):
        return


def _ta_gpro_instance_collections(obj):
    collections = []
    seen = set()

    for modifier in getattr(obj, "modifiers", []):
        modifier_name = _ta_name_key(getattr(modifier, "name", ""))
        node_group = getattr(modifier, "node_group", None)
        node_group_name = _ta_name_key(getattr(node_group, "name", "")) if node_group else ""
        is_gpro = "gproinstance" in {modifier_name, node_group_name}

        if not is_gpro:
            continue

        for value in _ta_geometry_nodes_input_values(modifier):
            if isinstance(value, bpy.types.Collection) and value.name not in seen:
                collections.append(value)
                seen.add(value.name)

    return collections


def _ta_name_key(name):
    return "".join(char for char in name.casefold() if char.isalnum())


def _ta_collect_uv_target_objects(objects):
    targets = []
    seen_objects = set()
    seen_collections = set()

    def visit_collection(collection):
        if collection is None or collection.name in seen_collections:
            return
        seen_collections.add(collection.name)

        for obj in collection.objects:
            visit_object(obj)
        for child in collection.children:
            visit_collection(child)

    def visit_object(obj):
        if obj is None or obj.name in seen_objects:
            return
        seen_objects.add(obj.name)

        if obj.type == 'MESH':
            targets.append(obj)

        for child in obj.children:
            visit_object(child)

        visit_collection(getattr(obj, "instance_collection", None))

        for collection in _ta_gpro_instance_collections(obj):
            visit_collection(collection)

    for obj in objects:
        visit_object(obj)

    return targets


def _ta_rename_mesh_primary_uv_to_uvmap(mesh):
    uv_layers = mesh.uv_layers
    if not uv_layers:
        return "no_uv"

    if len(uv_layers) > 1 and any(uv_layer.name == "UVMap" for uv_layer in uv_layers):
        return "already_has_uvmap"

    target_layer = uv_layers.active or uv_layers[0]
    if target_layer.name == "UVMap":
        return "already_uvmap"

    target_layer.name = "UVMap"
    return "renamed"


class TA_OT_rename_uv_maps_to_uvmap(bpy.types.Operator):
    bl_idname = "object.ta_rename_uv_maps_to_uvmap"
    bl_label = "Rename UV Maps to UVMap"
    bl_description = "Rename UV maps on selected objects, their children, collection instances, and gPro instance sources to UVMap"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        objects = _ta_collect_uv_target_objects(context.selected_objects)

        mesh_data_blocks = []
        seen_mesh_data = set()
        for obj in objects:
            mesh = obj.data
            mesh_key = mesh.as_pointer()
            if mesh_key in seen_mesh_data:
                continue
            seen_mesh_data.add(mesh_key)
            mesh_data_blocks.append(mesh)

        renamed_count = 0
        unchanged_count = 0
        skipped_no_uv = 0

        for mesh in mesh_data_blocks:
            result = _ta_rename_mesh_primary_uv_to_uvmap(mesh)
            if result == "renamed":
                renamed_count += 1
            elif result == "no_uv":
                skipped_no_uv += 1
            else:
                unchanged_count += 1

        if not mesh_data_blocks:
            self.report({'WARNING'}, "No mesh objects found in selection")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Renamed {renamed_count} mesh UV name(s). Unchanged {unchanged_count}. Skipped {skipped_no_uv} without UVs."
        )
        return {'FINISHED'}


class TA_PT_uv_map_panel(bpy.types.Panel):
    bl_label = "UV Map"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        self.layout.operator("object.ta_rename_uv_maps_to_uvmap", icon='GROUP_UVS')


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
    TA_OT_rename_uv_maps_to_uvmap,
    TA_PT_uv_map_panel,
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
