import bpy
import bmesh


EPS = 1e-6


def uv_close(a, b, eps=EPS):
    return abs(a.x - b.x) <= eps and abs(a.y - b.y) <= eps


def get_edit_mesh_objects(context):
    objs = []

    if hasattr(context, "objects_in_mode_unique_data"):
        objs = [
            obj for obj in context.objects_in_mode_unique_data
            if obj and obj.type == 'MESH'
        ]

    if not objs and context.object and context.object.type == 'MESH':
        objs = [context.object]

    return objs


def collect_selected_uv_loops(context, bm, uv_layer):
    selected = []
    seen = set()

    tool_settings = context.tool_settings
    use_uv_sync = tool_settings.use_uv_select_sync

    if hasattr(bm, "uv_select_sync_from_mesh"):
        try:
            bm.uv_select_sync_from_mesh()
        except Exception:
            pass

    if hasattr(bm, "uv_select_flush_mode"):
        try:
            bm.uv_select_flush_mode()
        except Exception:
            pass

    for face in bm.faces:
        if face.hide:
            continue

        for loop in face.loops:
            is_selected = False

            if use_uv_sync:
                select_mode = tool_settings.mesh_select_mode

                if select_mode[2] and face.select:
                    is_selected = True
                elif select_mode[1] and loop.edge.select:
                    is_selected = True
                elif select_mode[0] and loop.vert.select:
                    is_selected = True

            else:
                if getattr(loop, "uv_select_vert", False):
                    is_selected = True
                if getattr(loop, "uv_select_edge", False):
                    is_selected = True
                if getattr(face, "uv_select", False):
                    is_selected = True

            if is_selected:
                key = id(loop)
                if key not in seen:
                    selected.append(loop)
                    seen.add(key)

    return selected


def get_bmesh_infos(context):
    if context.mode != 'EDIT_MESH':
        return None, "Run this in Edit Mode."

    objs = get_edit_mesh_objects(context)

    if not objs:
        return None, "No edit mesh objects found."

    infos = []

    for obj in objs:
        mesh = obj.data

        if not mesh.uv_layers.active:
            continue

        bm = bmesh.from_edit_mesh(mesh)

        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        uv_layer = bm.loops.layers.uv.active

        if uv_layer is None:
            continue

        selected_loops = collect_selected_uv_loops(context, bm, uv_layer)

        if not selected_loops:
            continue

        infos.append({
            "object": obj,
            "mesh": mesh,
            "bm": bm,
            "uv_layer": uv_layer,
            "selected_loops": selected_loops,
        })

    if not infos:
        return None, "No selected UVs found in edit mesh objects."

    return infos, None


def make_uv_entries_from_loops(loops, uv_layer):
    entries = []

    for loop in loops:
        luv = loop[uv_layer]
        entries.append({
            "luv": luv,
            "u": luv.uv.x,
            "v": luv.uv.y,
        })

    return entries


def update_all_edit_meshes(infos):
    updated_meshes = set()

    for info in infos:
        mesh = info["mesh"]

        if mesh.name in updated_meshes:
            continue

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        updated_meshes.add(mesh.name)


def fit_entries_uniform_to_u_0_1(entries):
    min_u = min(e["u"] for e in entries)
    max_u = max(e["u"] for e in entries)
    min_v = min(e["v"] for e in entries)
    max_v = max(e["v"] for e in entries)

    width_u = max_u - min_u

    if abs(width_u) < EPS:
        return False

    scale = 1.0 / width_u

    pivot_u = (min_u + max_u) * 0.5
    pivot_v = (min_v + max_v) * 0.5

    transformed = []

    for e in entries:
        old_u = e["u"]
        old_v = e["v"]

        new_u = pivot_u + (old_u - pivot_u) * scale
        new_v = pivot_v + (old_v - pivot_v) * scale

        transformed.append((e["luv"], new_u, new_v))

    new_min_u = min(u for _, u, _ in transformed)

    for luv, new_u, new_v in transformed:
        luv.uv.x = new_u - new_min_u
        luv.uv.y = new_v

    return True


def scale_entries_uniform(entries, scale):
    min_u = min(e["u"] for e in entries)
    max_u = max(e["u"] for e in entries)
    min_v = min(e["v"] for e in entries)
    max_v = max(e["v"] for e in entries)

    pivot_u = (min_u + max_u) * 0.5
    pivot_v = (min_v + max_v) * 0.5

    for e in entries:
        luv = e["luv"]
        old_u = e["u"]
        old_v = e["v"]

        luv.uv.x = pivot_u + (old_u - pivot_u) * scale
        luv.uv.y = pivot_v + (old_v - pivot_v) * scale


def split_selected_loops_by_uv_island(bm, uv_layer, selected_loops):
    selected_map = {id(loop): loop for loop in selected_loops}
    graph = {id(loop): set() for loop in selected_loops}

    def add_link(a, b):
        aid = id(a)
        bid = id(b)

        if aid in graph and bid in graph:
            graph[aid].add(bid)
            graph[bid].add(aid)

    # 같은 Face 내부에서 선택된 UV corner 연결
    for face in bm.faces:
        if face.hide:
            continue

        for loop in face.loops:
            add_link(loop, loop.link_loop_next)

    # 인접 Face 사이에서 UV가 실제로 이어진 Edge만 연결
    for edge in bm.edges:
        linked_loops = list(edge.link_loops)

        if len(linked_loops) < 2:
            continue

        for i in range(len(linked_loops)):
            for j in range(i + 1, len(linked_loops)):
                a0 = linked_loops[i]
                a1 = a0.link_loop_next

                b0 = linked_loops[j]
                b1 = b0.link_loop_next

                a0_uv = a0[uv_layer].uv
                a1_uv = a1[uv_layer].uv
                b0_uv = b0[uv_layer].uv
                b1_uv = b1[uv_layer].uv

                if uv_close(a0_uv, b0_uv) and uv_close(a1_uv, b1_uv):
                    add_link(a0, b0)
                    add_link(a1, b1)

                elif uv_close(a0_uv, b1_uv) and uv_close(a1_uv, b0_uv):
                    add_link(a0, b1)
                    add_link(a1, b0)

    islands = []
    visited = set()

    for start_id in graph.keys():
        if start_id in visited:
            continue

        stack = [start_id]
        visited.add(start_id)
        island_ids = []

        while stack:
            current = stack.pop()
            island_ids.append(current)

            for neighbor in graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)

        island_loops = [selected_map[loop_id] for loop_id in island_ids]
        islands.append(island_loops)

    return islands


class UV_OT_fit_selected_uniform_u_0_1(bpy.types.Operator):
    bl_idname = "uv.fit_selected_uniform_u_0_1"
    bl_label = "Uniform Fit Selected UV to U 0-1"
    bl_description = "Uniformly scale all selected UVs from all edit objects as one group so their U width becomes 0 to 1"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        infos, error = get_bmesh_infos(context)

        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        all_entries = []

        for info in infos:
            entries = make_uv_entries_from_loops(
                info["selected_loops"],
                info["uv_layer"]
            )
            all_entries.extend(entries)

        if not all_entries:
            self.report({'ERROR'}, "No selected UVs found.")
            return {'CANCELLED'}

        success = fit_entries_uniform_to_u_0_1(all_entries)

        if not success:
            self.report({'ERROR'}, "Selected UV U width is too small.")
            return {'CANCELLED'}

        update_all_edit_meshes(infos)

        self.report({'INFO'}, "Selected UVs from all edit objects fitted to U 0-1 as one group.")
        return {'FINISHED'}


class UV_OT_fit_each_island_uniform_u_0_1(bpy.types.Operator):
    bl_idname = "uv.fit_each_island_uniform_u_0_1"
    bl_label = "Uniform Fit Each UV Island to U 0-1"
    bl_description = "Uniformly scale each selected UV island separately across all edit objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        infos, error = get_bmesh_infos(context)

        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        fitted_count = 0
        skipped_count = 0

        for info in infos:
            bm = info["bm"]
            uv_layer = info["uv_layer"]
            selected_loops = info["selected_loops"]

            islands = split_selected_loops_by_uv_island(
                bm,
                uv_layer,
                selected_loops
            )

            for island_loops in islands:
                entries = make_uv_entries_from_loops(island_loops, uv_layer)

                if fit_entries_uniform_to_u_0_1(entries):
                    fitted_count += 1
                else:
                    skipped_count += 1

        update_all_edit_meshes(infos)

        self.report(
            {'INFO'},
            f"Fitted {fitted_count} UV island(s) across edit objects. Skipped {skipped_count}."
        )

        return {'FINISHED'}


class UV_OT_scale_selected_uv_half(bpy.types.Operator):
    bl_idname = "uv.scale_selected_uv_half"
    bl_label = "Scale Selected UV 1/2"
    bl_description = "Uniformly scale selected UVs from all edit objects to half size around their shared center"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        infos, error = get_bmesh_infos(context)

        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        all_entries = []

        for info in infos:
            entries = make_uv_entries_from_loops(
                info["selected_loops"],
                info["uv_layer"]
            )
            all_entries.extend(entries)

        if not all_entries:
            self.report({'ERROR'}, "No selected UVs found.")
            return {'CANCELLED'}

        scale_entries_uniform(all_entries, 0.5)

        update_all_edit_meshes(infos)

        self.report({'INFO'}, "Selected UVs from all edit objects scaled to 1/2.")
        return {'FINISHED'}


class UV_PT_fit_selected_uniform_u_panel(bpy.types.Panel):
    bl_label = "Fit UV Uniform"
    bl_idname = "UV_PT_fit_selected_uniform_u_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Tools"

    def draw(self, context):
        layout = self.layout

        layout.label(text="Fit as one group:")
        layout.operator(
            "uv.fit_selected_uniform_u_0_1",
            text="Uniform Fit U to 0-1"
        )

        layout.separator()

        layout.label(text="Fit each UV island:")
        layout.operator(
            "uv.fit_each_island_uniform_u_0_1",
            text="Uniform Fit Each Island U to 0-1"
        )

        layout.separator()

        layout.label(text="Scale:")
        layout.operator(
            "uv.scale_selected_uv_half",
            text="Scale Selected UV 1/2"
        )


def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(
        "uv.fit_selected_uniform_u_0_1",
        text="Uniform Fit U to 0-1"
    )
    self.layout.operator(
        "uv.fit_each_island_uniform_u_0_1",
        text="Uniform Fit Each Island U to 0-1"
    )
    self.layout.operator(
        "uv.scale_selected_uv_half",
        text="Scale Selected UV 1/2"
    )


classes = (
    UV_OT_fit_selected_uniform_u_0_1,
    UV_OT_fit_each_island_uniform_u_0_1,
    UV_OT_scale_selected_uv_half,
    UV_PT_fit_selected_uniform_u_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.IMAGE_MT_uvs.append(menu_func)


def unregister():
    bpy.types.IMAGE_MT_uvs.remove(menu_func)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()