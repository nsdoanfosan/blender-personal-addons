import addon_utils
import math

import bpy


MODULE = "ta_tools"


def make_cyclic_poly_curve(name):
    curve = bpy.data.curves.new(name + "_Curve", type='CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 12
    spline = curve.splines.new('POLY')
    spline.points.add(3)
    coordinates = (
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (2.0, 2.0, 0.0),
        (0.0, 2.0, 0.0),
    )
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = True

    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def seam_polygons(mesh_obj):
    axis_values = [vertex.co.x for vertex in mesh_obj.data.vertices]
    axis_span = max(axis_values) - min(axis_values)
    return [
        polygon
        for polygon in mesh_obj.data.polygons
        if max(mesh_obj.data.vertices[index].co.x for index in polygon.vertices)
        - min(mesh_obj.data.vertices[index].co.x for index in polygon.vertices)
        > axis_span * 0.5
    ]


def assert_seam_uvs(mesh_obj, expected_seam_faces):
    seam_faces = seam_polygons(mesh_obj)
    assert len(seam_faces) == expected_seam_faces
    uv_data = mesh_obj.data.uv_layers.active.data
    for polygon in seam_faces:
        u_values = [uv_data[loop_index].uv.x for loop_index in polygon.loop_indices]
        assert max(u_values) - min(u_values) < 0.25


def edge_face_counts(mesh_obj):
    counts = {edge.key: 0 for edge in mesh_obj.data.edges}
    for polygon in mesh_obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, vertex in enumerate(vertices):
            key = tuple(sorted((vertex, vertices[(index + 1) % len(vertices)])))
            counts[key] += 1
    return counts


addon_utils.enable(MODULE, default_set=False)
addon = __import__(MODULE + ".curve_fit_plane", fromlist=["curve_fit_plane"])
scene = bpy.context.scene
scene.ta_curve_fit_generate_chain_rig = False
scene.ta_curve_fit_cylinder_sides = 8
scene.ta_curve_fit_plane_segments = 12
scene.ta_curve_fit_plane_deform_axis = 'POS_X'

shape_expectations = {
    'PLANE': (2, 1, False),
    'BOX': (4, 4, True),
    'CYLINDER': (8, 8, True),
}
created = {}

for shape_type, (ring_size, seam_face_count, manifold) in shape_expectations.items():
    curve_obj = make_cyclic_poly_curve("Cyclic" + shape_type.title())
    scene.ta_curve_fit_shape_type = shape_type
    select_only(curve_obj)
    result = bpy.ops.object.ta_create_curve_fit_plane()
    assert result == {'FINISHED'}

    mesh_obj = bpy.context.active_object
    created[shape_type] = (curve_obj, mesh_obj)
    assert mesh_obj.get("_ta_curve_fit_generated_shape") is True
    assert mesh_obj.get("_ta_curve_fit_cyclic") is True
    assert len(mesh_obj.data.vertices) == 12 * ring_size
    assert len(mesh_obj.data.polygons) == 12 * seam_face_count
    assert len(mesh_obj.data.uv_layers) == 1
    assert_seam_uvs(mesh_obj, seam_face_count)

    counts = edge_face_counts(mesh_obj)
    if manifold:
        assert set(counts.values()) == {2}

    axis_values = [vertex.co.x for vertex in mesh_obj.data.vertices]
    axis_span = max(axis_values) - min(axis_values)
    seam_edges = [
        edge
        for edge in mesh_obj.data.edges
        if abs(
            mesh_obj.data.vertices[edge.vertices[0]].co.x
            - mesh_obj.data.vertices[edge.vertices[1]].co.x
        ) > axis_span * 0.5
    ]
    assert len(seam_edges) == ring_size

    bpy.context.view_layer.update()
    evaluated = mesh_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_lengths = [
        (
            evaluated.matrix_world @ evaluated.data.vertices[edge.vertices[0]].co
            - evaluated.matrix_world @ evaluated.data.vertices[edge.vertices[1]].co
        ).length
        for edge in seam_edges
    ]
    assert max(evaluated_lengths) < 2.0

cylinder_curve, cylinder_mesh = created['CYLINDER']
cylinder_curve.data.splines[0].points[2].co = (2.5, 2.25, 0.0, 1.0)
cylinder_curve.data.update_tag()
bpy.context.view_layer.update()
assert len(seam_polygons(cylinder_mesh)) == 8
assert set(edge_face_counts(cylinder_mesh).values()) == {2}

scene.ta_curve_fit_existing_segment_length_cm = 100.0
select_only(cylinder_mesh)
result = bpy.ops.object.ta_segment_object_by_length()
assert result == {'FINISHED'}

expected_segments = max(3, math.ceil(addon._curve_local_length(cylinder_curve) / 1.0))
assert len(cylinder_mesh.data.vertices) == expected_segments * 8
assert len(cylinder_mesh.data.polygons) == expected_segments * 8
assert len(cylinder_mesh.data.uv_layers) == 1
assert_seam_uvs(cylinder_mesh, 8)
assert set(edge_face_counts(cylinder_mesh).values()) == {2}

scene.ta_curve_fit_generate_chain_rig = True
blocked_curve = make_cyclic_poly_curve("CyclicChainBlocked")
select_only(blocked_curve)
mesh_count_before = len(bpy.data.meshes)
result = bpy.ops.object.ta_create_curve_fit_plane()
assert result == {'CANCELLED'}
assert len(bpy.data.meshes) == mesh_count_before

addon_utils.disable(MODULE, default_set=False)
print("TA_TOOLS_CURVE_FIT_CYCLIC_OK")
