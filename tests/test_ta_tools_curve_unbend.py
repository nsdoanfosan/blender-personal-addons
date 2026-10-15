import addon_utils
import math
import os
import sys

import bpy
import numpy as np

MODULE = "ta_tools"
WORKTREE_ADDONS = os.environ.get("TA_TOOLS_ADDONS_DIR")
if WORKTREE_ADDONS:
    sys.path.insert(0, WORKTREE_ADDONS)

addon_utils.enable(MODULE, default_set=False)
cfp = sys.modules[MODULE + ".curve_fit_plane"]
unb = sys.modules[MODULE + ".curve_unbend"]
if WORKTREE_ADDONS:
    assert os.path.normcase(unb.__file__).startswith(os.path.normcase(WORKTREE_ADDONS)), unb.__file__
scene = bpy.context.scene


def poly_curve(name, coords, cyclic=False, tilts=None, bezier=False):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.resolution_u = 24
    if bezier:
        sp = data.splines.new('BEZIER')
        sp.bezier_points.add(len(coords) - 1)
        for i, (bp, c) in enumerate(zip(sp.bezier_points, coords)):
            bp.co = c
            bp.handle_left_type = bp.handle_right_type = 'AUTO'
            if tilts:
                bp.tilt = tilts[i]
    else:
        sp = data.splines.new('POLY')
        sp.points.add(len(coords) - 1)
        for i, (p, c) in enumerate(zip(sp.points, coords)):
            p.co = (*c, 1.0)
            if tilts:
                p.tilt = tilts[i]
    sp.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    return obj


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def sweep_and_bake(curve, profile, segments, thickness_cm=0.0):
    scene.ta_curve_fit_shape_type = 'SWEEP'
    scene.ta_curve_fit_profile_object = profile
    scene.ta_curve_fit_sweep_thickness_cm = thickness_cm
    scene.ta_curve_fit_plane_segments = segments
    scene.ta_curve_fit_split_splines = False
    select_only(curve)
    assert bpy.ops.object.ta_create_curve_fit_plane() == {'FINISHED'}
    shaped = bpy.context.active_object
    straight = np.array([v.co[:] for v in shaped.data.vertices])
    bpy.context.view_layer.update()
    ev = shaped.evaluated_get(bpy.context.evaluated_depsgraph_get())
    baked = bpy.data.meshes.new_from_object(ev)
    obj = bpy.data.objects.new(curve.name + "_baked", baked)
    scene.collection.objects.link(obj)
    bpy.data.objects.remove(shaped, do_unlink=True)
    return obj, straight


def run_unbend(obj, **kw):
    select_only(obj)
    return unb.unbend_object(bpy.context, obj, **kw)


scene.ta_curve_fit_generate_chain_rig = False
scene.ta_curve_fit_plane_deform_axis = 'POS_X'
line = poly_curve("ProfLine", [(0, -0.2, 0), (0, 0, 0), (0, 0.2, 0)])
hexa = poly_curve("ProfHex", [(math.cos(a) * 0.15, math.sin(a) * 0.15, 0) for a in [i * math.tau / 6 for i in range(6)]], cyclic=True)

# 1) open S ribbon with tilt -> unbend (geodesic, islands)
s_curve = poly_curve("SCurve", [(0, 0, 0), (2, 1.5, 0.3), (4, -1.0, 0.8), (6, 0.5, 0.2), (8, 0, 0)],
                     tilts=[0.0, 0.6, 1.2, 0.4, 0.0], bezier=True)
ribbon, _ = sweep_and_bake(s_curve, line, 96, thickness_cm=4.0)
rep = run_unbend(ribbon, split_mode='ISLANDS', control_points=12, samples=128)
assert len(rep["created"]) == 1, rep
c = rep["created"][0]
assert c["method"] == "geodesic" and not c["cyclic"], c
assert c["roundtrip_p50_p95_max"][2] / c["size"] < 0.01, c
straight_obj = bpy.data.objects[c["mesh"]]
co = np.array([v.co[:] for v in straight_obj.data.vertices])
ext = np.ptp(co, axis=0)
assert ext[0] > 7.0, ext                      # unrolled length ~ curve length
assert ext[2] < ext[1] * 0.5, ext             # flat: thickness axis much thinner than width
assert len(straight_obj.data.uv_layers) >= 1
assert straight_obj.modifiers[0].type == 'CURVE'
assert straight_obj.name.endswith('_low'), straight_obj.name
assert straight_obj.parent == bpy.data.objects[c['curve']]
assert straight_obj.parent.parent == ribbon

# 2) closed ring tube -> cyclic detected
ring_pts = [(math.cos(a) * 3, math.sin(a) * 3, math.sin(2 * a) * 0.4) for a in [i * math.tau / 8 for i in range(8)]]
ring = poly_curve("Ring", ring_pts, cyclic=True, bezier=True)
tube, _ = sweep_and_bake(ring, hexa, 96)
rep = run_unbend(tube, split_mode='ISLANDS', control_points=16, samples=192, fit_tilt=False)
assert len(rep["created"]) == 1, rep
c = rep["created"][0]
assert c["cyclic"], c
assert c["roundtrip_p50_p95_max"][1] / c["size"] < 0.01, c
assert c["roundtrip_p50_p95_max"][2] / c["size"] < 0.03, c
ring_straight = bpy.data.objects[c["mesh"]].data
xs = np.array([v.co.x for v in ring_straight.vertices])
spans = [max(xs[list(p.vertices)]) - min(xs[list(p.vertices)]) for p in ring_straight.polygons]
assert max(spans) < c["length"] * 0.25, max(spans)   # seam opened: no face wraps the strip
assert abs(np.ptp(xs) - c["length"]) < c["length"] * 0.1, (np.ptp(xs), c["length"])

# 3) attribute mode: give the baked ribbon cloth_path_* attributes
arc = poly_curve("Arc", [(0, 5, 0), (2, 7, 0), (4, 5, 0.5)], bezier=True)
arc_mesh_obj, straight = sweep_and_bake(arc, line, 64, thickness_cm=2.0)
length = cfp._curve_local_length(arc)
mesh = arc_mesh_obj.data
xs = straight[:, 0]
# centres: deform (x,0,0) through the arc
probe_curve_frames = unb._probe_frames(arc, xs, scene.collection)[0]
u = np.clip(xs / length, 0, 1)
for name, dtype in (("cloth_path_u", 'FLOAT'), ("cloth_path_center", 'FLOAT_VECTOR'), ("cloth_path_id", 'INT')):
    mesh.attributes.new(name, dtype, 'POINT')
mesh.attributes["cloth_path_u"].data.foreach_set("value", u.astype(np.float32))
mesh.attributes["cloth_path_center"].data.foreach_set("vector", probe_curve_frames.astype(np.float32).ravel())
mesh.attributes["cloth_path_id"].data.foreach_set("value", np.zeros(len(u), np.int32))
rep = run_unbend(arc_mesh_obj, control_points=10, samples=128)
assert len(rep["created"]) == 1, rep
c = rep["created"][0]
assert c["method"] == "attributes", c
assert c["roundtrip_p50_p95_max"][2] / c["size"] < 0.01, c

# 4) two islands -> two parts
r2, _ = sweep_and_bake(poly_curve("Line2", [(0, -5, 0), (3, -5, 1)], bezier=True), line, 32, thickness_cm=2.0)
two = bpy.data.meshes.new("Two")
import bmesh
bm = bmesh.new(); bm.from_mesh(r2.data)
bm2 = bmesh.new(); bm2.from_mesh(ribbon.data)
offset = len(bm.verts)
for v in bm2.verts:
    bm.verts.new(v.co)
bm.verts.ensure_lookup_table()
for f in bm2.faces:
    bm.faces.new([bm.verts[offset + v.index] for v in f.verts])
bm.to_mesh(two); bm.free(); bm2.free()
two_obj = bpy.data.objects.new("TwoParts", two); scene.collection.objects.link(two_obj)
rep = run_unbend(two_obj, split_mode='ISLANDS')
assert len(rep["created"]) == 2, rep

# 5) a part made of many islands keeps only the largest island
many = bpy.data.meshes.new("Many")
bm = bmesh.new(); bm.from_mesh(ribbon.data)
for i in range(10):
    vs = [bm.verts.new((20 + i, 0, 0)), bm.verts.new((20 + i, 0.01, 0)), bm.verts.new((20 + i, 0, 0.01))]
    bm.faces.new(vs)
bm.to_mesh(many); bm.free()
pid = many.attributes.new("cloth_path_id", 'INT', 'POINT')
many_obj = bpy.data.objects.new("ManyIslands", many); scene.collection.objects.link(many_obj)
rep = run_unbend(many_obj, split_mode='ATTRIBUTE', max_islands=4)
assert len(rep["created"]) == 1 and "largest island" in rep["created"][0]["note"], rep

# 6) explicit attribute mode must not silently fall back to mesh islands.
before_ids = {o.as_pointer() for o in bpy.data.objects}
before_collections = {c.as_pointer() for c in bpy.data.collections}
try:
    run_unbend(ribbon, split_mode='ATTRIBUTE')
except ValueError as exc:
    assert 'cloth_path_id' in str(exc)
else:
    raise AssertionError('Missing path attributes must cancel explicit ATTRIBUTE mode')
assert before_ids == {o.as_pointer() for o in bpy.data.objects}
assert before_collections == {c.as_pointer() for c in bpy.data.collections}

# 7) terminal role names survive duplicate source labels and repeat generation.
ribbon.name = 'Ribbon_low.009'
rep = run_unbend(ribbon, output_base_name='Ribbon_low.009')
assert rep['created'][0]['mesh'] == 'Ribbon_part_00_low', rep
rep2 = run_unbend(ribbon, output_base_name='Ribbon_low.009')
assert rep2['created'][0]['mesh'] == 'Ribbon_02_part_00_low', rep2

# 8) a failure after curve creation cleans every generated ID and collection.
before_ids = {o.as_pointer() for o in bpy.data.objects}
before_meshes = {m.as_pointer() for m in bpy.data.meshes}
before_curves = {c.as_pointer() for c in bpy.data.curves}
before_collections = {c.as_pointer() for c in bpy.data.collections}
original_unbend = unb._unbend_coords
def fail_unbend(*args, **kwargs):
    raise RuntimeError('injected frame failure')
unb._unbend_coords = fail_unbend
try:
    try:
        run_unbend(ribbon)
    except RuntimeError as exc:
        assert 'injected frame failure' in str(exc)
    else:
        raise AssertionError('Expected frame failure')
finally:
    unb._unbend_coords = original_unbend
assert before_ids == {o.as_pointer() for o in bpy.data.objects}
assert before_meshes == {m.as_pointer() for m in bpy.data.meshes}
assert before_curves == {c.as_pointer() for c in bpy.data.curves}
assert before_collections == {c.as_pointer() for c in bpy.data.collections}

# 9) scaled/rotated parents keep world geometry and report real millimetres.
ribbon.location = (3, -2, 1)
ribbon.rotation_euler = (0.2, 0.3, -0.4)
ribbon.scale = (2, 0.8, 1.3)
bpy.context.view_layer.update()
rep = run_unbend(ribbon)
c = rep['created'][0]
low = bpy.data.objects[c['mesh']]
assert np.allclose(np.array(low.matrix_world), np.array(ribbon.matrix_world), atol=1e-6)
assert max(low['_ta_unbend_roundtrip_mm']) > 0
ev = low.evaluated_get(bpy.context.evaluated_depsgraph_get())
mesh = ev.to_mesh()
try:
    delta = unb._mesh_positions(mesh) - unb._mesh_positions(ribbon.data)
finally:
    ev.to_mesh_clear()
world_error = np.linalg.norm(delta @ np.array(ribbon.matrix_world.to_3x3()).T, axis=1)
expected_mm = np.array([np.percentile(world_error, 50), np.percentile(world_error, 95), world_error.max()]) * 1000
assert np.allclose(np.array(low['_ta_unbend_roundtrip_mm']), expected_mm, rtol=1e-5, atol=1e-5)

addon_utils.disable(MODULE, default_set=False)
print("TA_TOOLS_CURVE_UNBEND_OK")
