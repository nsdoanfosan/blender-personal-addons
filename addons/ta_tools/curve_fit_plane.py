import bpy
import bmesh
from bpy.props import EnumProperty, FloatProperty, IntProperty
from mathutils.geometry import interpolate_bezier


def _point_co(point):
    return point.co.xyz if hasattr(point.co, "xyz") else point.co


def _curve_local_length(curve_obj):
    curve = curve_obj.data
    resolution = max(1, curve.resolution_u)
    total = 0.0

    for spline in curve.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            count = len(points)
            if count < 2:
                continue

            segment_count = count if spline.use_cyclic_u else count - 1
            for index in range(segment_count):
                p0 = points[index]
                p1 = points[(index + 1) % count]
                samples = interpolate_bezier(
                    p0.co,
                    p0.handle_right,
                    p1.handle_left,
                    p1.co,
                    resolution + 1,
                )
                total += sum((samples[i] - samples[i - 1]).length for i in range(1, len(samples)))

        elif spline.type == 'POLY':
            points = spline.points
            count = len(points)
            if count < 2:
                continue

            segment_count = count if spline.use_cyclic_u else count - 1
            for index in range(segment_count):
                p0 = _point_co(points[index])
                p1 = _point_co(points[(index + 1) % count])
                total += (p1 - p0).length

        else:
            return _curve_mesh_fallback_length(curve_obj)

    return total


def _curve_mesh_fallback_length(curve_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = curve_obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(eval_obj, depsgraph=depsgraph)

    try:
        return sum(
            (mesh.vertices[edge.vertices[1]].co - mesh.vertices[edge.vertices[0]].co).length
            for edge in mesh.edges
        )
    finally:
        bpy.data.meshes.remove(mesh)


def create_curve_fit_plane(context, curve_obj, width, segments, deform_axis):
    length = _curve_local_length(curve_obj)
    if length <= 0.0:
        raise ValueError("Curve length is zero")

    mesh = bpy.data.meshes.new("Curve_Fit_Plane_Mesh")
    obj = bpy.data.objects.new("Curve_Fit_Plane", mesh)
    context.collection.objects.link(obj)

    bm = bmesh.new()
    try:
        for index in range(segments + 1):
            x = length * (index / segments)
            bm.verts.new((x, -width * 0.5, 0.0))
            bm.verts.new((x, width * 0.5, 0.0))

        bm.verts.ensure_lookup_table()

        for index in range(segments):
            bm.faces.new((
                bm.verts[index * 2],
                bm.verts[index * 2 + 1],
                bm.verts[index * 2 + 3],
                bm.verts[index * 2 + 2],
            ))

        bm.to_mesh(mesh)
    finally:
        bm.free()

    obj.matrix_world = curve_obj.matrix_world.copy()

    modifier = obj.modifiers.new("Follow Curve", 'CURVE')
    modifier.object = curve_obj
    modifier.deform_axis = deform_axis

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vert = mesh.vertices[mesh.loops[loop_index].vertex_index]
            u = vert.co.x / length if length else 0.0
            v = (vert.co.y / width) + 0.5 if width else 0.5
            uv_layer.data[loop_index].uv = (u, v)

    for selected in context.selected_objects:
        selected.select_set(False)

    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj, length


class TA_OT_create_curve_fit_plane(bpy.types.Operator):
    bl_idname = "object.ta_create_curve_fit_plane"
    bl_label = "Create Curve Fit Plane"
    bl_description = "Create a subdivided plane fitted to the active curve and add a Curve modifier"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE' and context.mode == 'OBJECT'

    def execute(self, context):
        scene = context.scene
        curve_obj = context.active_object

        try:
            obj, length = create_curve_fit_plane(
                context,
                curve_obj,
                scene.ta_curve_fit_plane_width,
                scene.ta_curve_fit_plane_segments,
                scene.ta_curve_fit_plane_deform_axis,
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Created {obj.name} / length {length:.4f}")
        return {'FINISHED'}


class TA_PT_curve_fit_plane_panel(bpy.types.Panel):
    bl_label = "Curve Fit Plane"
    bl_idname = "TA_PT_curve_fit_plane_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.prop(scene, "ta_curve_fit_plane_width")
        col.prop(scene, "ta_curve_fit_plane_segments")
        col.prop(scene, "ta_curve_fit_plane_deform_axis")

        row = layout.row()
        row.enabled = obj is not None and obj.type == 'CURVE'
        row.operator("object.ta_create_curve_fit_plane", icon='MOD_CURVE')


classes = (
    TA_OT_create_curve_fit_plane,
    TA_PT_curve_fit_plane_panel,
)


def register():
    bpy.types.Scene.ta_curve_fit_plane_width = FloatProperty(
        name="Width",
        default=0.1,
        min=0.0001,
        soft_max=10.0,
        precision=4,
        description="Plane width before the Curve modifier deforms it",
    )
    bpy.types.Scene.ta_curve_fit_plane_segments = IntProperty(
        name="Segments",
        default=128,
        min=1,
        soft_max=512,
        description="Subdivisions along the curve direction",
    )
    bpy.types.Scene.ta_curve_fit_plane_deform_axis = EnumProperty(
        name="Deform Axis",
        default='POS_X',
        items=(
            ('POS_X', '+X', 'Deform along positive local X'),
            ('NEG_X', '-X', 'Deform along negative local X'),
            ('POS_Y', '+Y', 'Deform along positive local Y'),
            ('NEG_Y', '-Y', 'Deform along negative local Y'),
            ('POS_Z', '+Z', 'Deform along positive local Z'),
            ('NEG_Z', '-Z', 'Deform along negative local Z'),
        ),
    )

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.ta_curve_fit_plane_deform_axis
    del bpy.types.Scene.ta_curve_fit_plane_segments
    del bpy.types.Scene.ta_curve_fit_plane_width
