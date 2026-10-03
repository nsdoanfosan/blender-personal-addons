import addon_utils
import math
import os
import sys

import bpy

MODULE = "ta_tools"
WORKTREE_ADDONS = os.environ.get("TA_TOOLS_ADDONS_DIR")
if WORKTREE_ADDONS:
    sys.path.insert(0, WORKTREE_ADDONS)


def make_poly_curve(name, coordinates, cyclic=False, radii=None, tilts=None, link=True):
    curve = bpy.data.curves.new(name + "_Curve", type='CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 12
    spline = curve.splines.new('POLY')
    spline.points.add(len(coordinates) - 1)
    for index, (point, coordinate) in enumerate(zip(spline.points, coordinates)):
        point.co = (*coordinate, 1.0)
        if radii:
            point.radius = radii[index]
        if tilts:
            point.tilt = tilts[index]
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    if link:
        bpy.context.scene.collection.objects.link(obj)
    return obj


def add_spline(curve_obj, coordinates, cyclic=False):
    spline = curve_obj.data.splines.new('POLY')
    spline.points.add(len(coordinates) - 1)
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = cyclic


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def edge_face_counts(mesh):
    counts = {edge.key: 0 for edge in mesh.edges}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            counts[key] += 1
    return counts


def uv_bounds(mesh):
    uvs = [loop.uv for loop in mesh.uv_layers.active.data]
    return (min(uv.x for uv in uvs), min(uv.y for uv in uvs), max(uv.x for uv in uvs), max(uv.y for uv in uvs))


def evaluated_coords(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    coords = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return coords


addon_utils.enable(MODULE, default_set=False)
addon = sys.modules[MODULE + ".curve_fit_plane"]
if WORKTREE_ADDONS:
    assert os.path.normcase(os.path.abspath(addon.__file__)).startswith(os.path.normcase(os.path.abspath(WORKTREE_ADDONS))), addon.__file__

scene = bpy.context.scene
scene.ta_curve_fit_generate_chain_rig = False
scene.ta_curve_fit_plane_deform_axis = 'POS_X'
scene.ta_curve_fit_shape_type = 'SWEEP'
scene.ta_curve_fit_split_splines = True
scene.ta_curve_fit_split_use_evaluated = True

# profiles: open line (ribbon) and closed hexagon
line_profile = make_poly_curve("ProfileLine", [(0.0, -0.5, 0.0), (0.0, 0.0, 0.0), (0.0, 0.5, 0.0)])
hexagon = [(math.cos(a) * 0.3, math.sin(a) * 0.3, 0.0) for a in [i * math.tau / 6 for i in range(6)]]
hex_profile = make_poly_curve("ProfileHex", hexagon, cyclic=True)

# 1) open path + open line profile, radius honoured by the Curve modifier
open_path = make_poly_curve("OpenPath", [(0, 0, 0), (2, 0, 0), (4, 0, 0)], radii=[1.0, 2.0, 1.0])
scene.ta_curve_fit_profile_object = line_profile
scene.ta_curve_fit_sweep_thickness_cm = 0.0
scene.ta_curve_fit_plane_segments = 20
select_only(open_path)
assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
ribbon = bpy.context.active_object
assert ribbon.get("_ta_curve_fit_type" if False else "_ta_curve_fit_shape_type") == 'SWEEP'
assert ribbon.ta_curve_fit_profile_curve == line_profile
profile_n = len(addon._sample_profile_2d(line_profile)[0])
assert len(ribbon.data.vertices) == 21 * profile_n, len(ribbon.data.vertices)
assert len(ribbon.data.polygons) == 20 * (profile_n - 1)
lo_u, lo_v, hi_u, hi_v = uv_bounds(ribbon.data)
assert lo_u >= -1e-6 and lo_v >= -1e-6 and hi_u <= 1.0 + 1e-6 and hi_v <= 1.0 + 1e-6
assert abs(hi_u - 1.0) < 1e-5  # length (4) > profile (1) -> U spans 0..1
assert abs(hi_v - 0.25) < 1e-5  # uniform texel density: 1/4
coords = evaluated_coords(ribbon)
width_start = (coords[profile_n - 1] - coords[0]).length
mid_ring = 10 * profile_n
width_mid = (coords[mid_ring + profile_n - 1] - coords[mid_ring]).length
assert abs(width_start - 1.0) < 0.05, width_start
assert abs(width_mid - 2.0) < 0.1, width_mid

# 2) closed path + closed profile: manifold, seam UVs, small seam twist
square = make_poly_curve("ClosedPath", [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], cyclic=True)
scene.ta_curve_fit_profile_object = hex_profile
scene.ta_curve_fit_plane_segments = 32
select_only(square)
assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
tube = bpy.context.active_object
assert tube.get("_ta_curve_fit_cyclic") is True
assert len(tube.data.vertices) == 32 * 6
assert set(edge_face_counts(tube.data).values()) == {2}
uv_data = tube.data.uv_layers.active.data
for polygon in tube.data.polygons:
    us = [uv_data[i].uv.x for i in polygon.loop_indices]
    vs = [uv_data[i].uv.y for i in polygon.loop_indices]
    assert max(us) - min(us) < 0.1 and max(vs) - min(vs) < 0.2
twist = addon.seam_twist_degrees(tube)
assert twist is not None and twist < 5.0, twist
coords = evaluated_coords(tube)
seam_gap = max((coords[k] - coords[31 * 6 + k]).length for k in range(6))
ring_step = (coords[6] - coords[0]).length
assert seam_gap < ring_step * 3.0, (seam_gap, ring_step)

# 3) open profile + thickness on open path -> closed profile with caps, manifold
scene.ta_curve_fit_profile_object = line_profile
scene.ta_curve_fit_sweep_thickness_cm = 10.0  # 0.1 m
scene.ta_curve_fit_sweep_caps = True
scene.ta_curve_fit_plane_segments = 8
select_only(open_path)
assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
slab = bpy.context.active_object
assert set(edge_face_counts(slab.data).values()) == {2}
scene.ta_curve_fit_sweep_thickness_cm = 0.0

# 4) multi-spline curve -> split per spline, source untouched
multi = make_poly_curve("MultiSpline", [(0, 0, 0), (1, 0, 0), (2, 0.5, 0)])
add_spline(multi, [(0, 1, 0), (1, 2, 0), (0, 3, 0), (-1, 2, 0)], cyclic=True)
scene.ta_curve_fit_profile_object = line_profile
scene.ta_curve_fit_plane_segments = 16
select_only(multi)
assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
assert len(multi.data.splines) == 2
collection = bpy.data.collections.get("MultiSpline · Curve Fit")
assert collection is not None
split_curves = [o for o in collection.objects if o.type == 'CURVE']
split_meshes = [o for o in collection.objects if o.type == 'MESH']
assert len(split_curves) == 2 and len(split_meshes) == 2
assert sorted(c.get("_ta_curve_fit_split_index") for c in split_curves) == [0, 1]
for mesh_obj in split_meshes:
    modifier = addon._curve_modifier_for_object(mesh_obj)
    assert modifier is not None and modifier.object in split_curves
assert any(m.get("_ta_curve_fit_cyclic") for m in split_meshes)

# 5) evaluated shape: GN resample keeps curves -> split copies 25 evaluated points
gn_curve = make_poly_curve("GNCurve", [(0, 5, 0), (3, 5, 0), (3, 8, 0)])
tree = bpy.data.node_groups.new("ResampleTest", 'GeometryNodeTree')
tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
gin = tree.nodes.new('NodeGroupInput')
gout = tree.nodes.new('NodeGroupOutput')
resample = tree.nodes.new('GeometryNodeResampleCurve')
count_socket = [s for s in resample.inputs if s.name == 'Count'][0]
count_socket.default_value = 25
tree.links.new(gin.outputs[0], resample.inputs[0])
tree.links.new(resample.outputs[0], gout.inputs[0])
gn_mod = gn_curve.modifiers.new("Resample", 'NODES')
gn_mod.node_group = tree
select_only(gn_curve)
assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
gn_split = [o for o in bpy.data.collections["GNCurve · Curve Fit"].objects if o.type == 'CURVE']
assert len(gn_split) == 1
assert len(gn_split[0].data.splines[0].points) == 25, len(gn_split[0].data.splines[0].points)
assert gn_curve.modifiers[0].show_viewport  # restored

# 6) follow length: closed tube keeps topology + UVs and closes again
tube.ta_curve_fit_follow_length = True
uv_before = [tuple(loop.uv) for loop in tube.data.uv_layers.active.data]
vert_count = len(tube.data.vertices)
square.data.splines[0].points[2].co = (3.0, 3.0, 0.0, 1.0)
square.data.update_tag()
bpy.context.view_layer.update()
bpy.context.view_layer.update()
new_length = addon._curve_local_length(square)
if abs(float(tube.get("_ta_curve_fit_length")) - new_length) > 1e-5:
    # background mode may not fire depsgraph handlers; use the operator path
    select_only(tube)
    assert bpy.ops.object.ta_curve_fit_follow_length() == {'FINISHED'}
assert abs(float(tube.get("_ta_curve_fit_length")) - new_length) < 1e-5
assert len(tube.data.vertices) == vert_count
assert [tuple(loop.uv) for loop in tube.data.uv_layers.active.data] == uv_before
coords = evaluated_coords(tube)
seam_gap = max((coords[k] - coords[31 * 6 + k]).length for k in range(6))
ring_step = (coords[6] - coords[0]).length
assert seam_gap < ring_step * 3.0, (seam_gap, ring_step)

addon_utils.disable(MODULE, default_set=False)
print("TA_TOOLS_CURVE_FIT_SWEEP_OK")
