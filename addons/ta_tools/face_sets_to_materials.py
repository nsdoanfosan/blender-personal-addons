import bpy


PALETTE = (
    (0.95, 0.16, 0.18, 1.0),
    (0.12, 0.47, 0.95, 1.0),
    (0.10, 0.70, 0.28, 1.0),
    (1.00, 0.72, 0.08, 1.0),
    (0.70, 0.22, 0.95, 1.0),
    (0.00, 0.76, 0.78, 1.0),
    (1.00, 0.42, 0.00, 1.0),
    (0.86, 0.08, 0.47, 1.0),
    (0.52, 0.82, 0.10, 1.0),
    (0.36, 0.31, 0.97, 1.0),
    (0.58, 0.36, 0.16, 1.0),
    (0.04, 0.62, 0.56, 1.0),
    (0.98, 0.50, 0.68, 1.0),
    (0.25, 0.75, 1.00, 1.0),
    (0.72, 0.92, 0.22, 1.0),
    (0.92, 0.36, 1.00, 1.0),
    (0.00, 0.50, 0.92, 1.0),
    (0.96, 0.88, 0.20, 1.0),
    (0.90, 0.28, 0.10, 1.0),
    (0.18, 0.88, 0.58, 1.0),
    (0.50, 0.16, 0.72, 1.0),
    (0.66, 0.70, 0.78, 1.0),
    (0.20, 0.42, 0.16, 1.0),
    (0.78, 0.08, 0.18, 1.0),
)


def _material_name(face_set_id, order):
    return f"TA_FS_{order:02d}_ID_{face_set_id}"


def _set_material_color(mat, color):
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        base_color = bsdf.inputs.get("Base Color")
        if base_color:
            base_color.default_value = color
        roughness = bsdf.inputs.get("Roughness")
        if roughness:
            roughness.default_value = 0.55


def _ensure_material_slot(mesh, face_set_id, order):
    name = _material_name(face_set_id, order)
    color = PALETTE[(order - 1) % len(PALETTE)]

    for index, mat in enumerate(mesh.materials):
        if mat and mat.name == name:
            _set_material_color(mat, color)
            return index

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    _set_material_color(mat, color)
    mesh.materials.append(mat)
    return len(mesh.materials) - 1


def apply_face_sets_to_materials(obj):
    mesh = obj.data
    face_set_attr = mesh.attributes.get(".sculpt_face_set")
    if not face_set_attr or face_set_attr.domain != "FACE":
        return 0, 0

    values = [item.value for item in face_set_attr.data]
    face_set_ids = sorted({value for value in values if value > 0})
    if not face_set_ids:
        return 0, 0

    slot_by_face_set = {
        face_set_id: _ensure_material_slot(mesh, face_set_id, order)
        for order, face_set_id in enumerate(face_set_ids, start=1)
    }

    changed = 0
    for poly, face_set_id in zip(mesh.polygons, values):
        slot_index = slot_by_face_set.get(face_set_id)
        if slot_index is None:
            continue
        if poly.material_index != slot_index:
            poly.material_index = slot_index
            changed += 1

    mesh.update()
    return len(face_set_ids), changed


class TA_OT_face_sets_to_materials(bpy.types.Operator):
    bl_idname = "object.ta_face_sets_to_materials"
    bl_label = "Face Sets to Materials"
    bl_description = "Create high-contrast materials from sculpt Face Sets and assign real material slot indices"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        objects = context.selected_objects or []
        return any(obj.type == "MESH" for obj in objects)

    def execute(self, context):
        total_sets = 0
        total_faces = 0
        mesh_count = 0

        for obj in context.selected_objects:
            if obj.type != "MESH":
                continue
            set_count, changed = apply_face_sets_to_materials(obj)
            if set_count == 0:
                continue
            mesh_count += 1
            total_sets += set_count
            total_faces += changed

        if mesh_count == 0:
            self.report({"WARNING"}, "No selected mesh has .sculpt_face_set data")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Face Sets to Materials: {mesh_count} mesh, {total_sets} sets, {total_faces} faces remapped",
        )
        return {"FINISHED"}


class TA_PT_face_sets_to_materials_panel(bpy.types.Panel):
    bl_label = "Face Sets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TA"

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def draw(self, context):
        self.layout.operator(TA_OT_face_sets_to_materials.bl_idname, icon="MATERIAL")


classes = (
    TA_OT_face_sets_to_materials,
    TA_PT_face_sets_to_materials_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
