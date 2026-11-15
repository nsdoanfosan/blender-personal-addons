"""Disposable QA: blender --factory-startup -b <reference DemoFile> --python this. Never saves."""
from pathlib import Path
import sys, hashlib, json
import bpy, addon_utils
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons'))
addon_utils.enable('ivy_generator', default_set=False)
import ivy_generator as ivy


def evaluated(obj):
    obj.update_tag(); bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    return [i.matrix_world.copy() for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == obj]


def digest(mats):
    # Sorted so the comparison is about the result, not the evaluation order.
    rows = sorted(tuple(round(v, 3) for r in m for v in r) for m in mats)
    return hashlib.sha256(repr(rows).encode()).hexdigest()[:16], len(rows)


if bpy.context.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')  # the demo file is saved in Edit Mode
results = {'blender': bpy.app.version_string}
ref = bpy.data.objects['Ivy']
ref_digest = digest(evaluated(ref))

# Same emitters, target and values as the reference: the band now stays flat on the surface,
# so the sprigs differ from the reference but must cover it about as much.
tree = ivy.build_generator(bpy.data.collections['Ivy_Instance'])
new = bpy.data.objects.new('New', ref.data.copy())
bpy.context.collection.objects.link(new); new.matrix_world = ref.matrix_world
demo = new.modifiers.new('Ivy Generator', 'NODES'); demo.node_group = tree
ivy.set_input(demo, 'Target', bpy.data.collections['Target'])
new_digest = digest(evaluated(new))
results['reference'] = ref_digest; results['rebuilt'] = new_digest
assert .8 < new_digest[1] / ref_digest[1] < 2., (ref_digest, new_digest)
ref.hide_viewport = ref.hide_render = new.hide_viewport = new.hide_render = True

# Create through the operator on a fresh target; sprigs come from the library copy.
bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection
bpy.ops.mesh.primitive_cube_add(size=1, location=(40, 0, 2.5)); wall = bpy.context.object; wall.scale = (6, 2, 5)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.context.scene.cursor.location = (40, -1, 2.5)
assert bpy.ops.object.ivy_generator_add() == {'FINISHED'}
obj = bpy.context.object; m = ivy.ivy_modifier(obj)
base = evaluated(obj); results['default_instances'] = len(base); assert 50 < len(base) < 20000
assert abs(ivy.get_input(m, 'Leaf Size') - 6 / ivy.REFERENCE_HEIGHT) < 1e-4
assert list(ivy.get_input(m, 'Target').objects) == [wall]
assert len(obj.data.vertices) == 1
assert digest(evaluated(obj)) == digest(base), 'repeatable'


def trial(name, value):
    old = ivy.get_input(m, name); ivy.set_input(m, name, value)
    out = evaluated(obj); ivy.set_input(m, name, old); return out


assert digest(trial('Seed', 7)) != digest(base)
assert len(trial('Leaf Density', 0.)) == 0
assert len(trial('Leaf Density', .25)) < len(base)
assert len(trial('Height', ivy.get_input(m, 'Height') * 2)) > len(base)
assert len(trial('Radius', ivy.get_input(m, 'Radius') * 2)) > len(base)
assert len(trial('Band Width', ivy.get_input(m, 'Band Width') * 3)) > len(base)
big = trial('Leaf Size', ivy.get_input(m, 'Leaf Size') * 2)
assert 0 < len(big) < len(base) and big[0].to_scale().x > base[0].to_scale().x

# Every sprig sits on the outside of the surface, lifted by a small offset.
lift = .06 * ivy.get_input(m, 'Leaf Size')
depths = [min(3 - abs(p.x - 40), 1 - abs(p.y), 2.5 - abs(p.z - 2.5)) for p in (mat.to_translation() for mat in base)]
assert all(abs(d) <= lift + .001 for d in depths), max(abs(d) for d in depths)
results['sprigs_sunk_by_lift'] = sum(d > .001 for d in depths)
assert results['sprigs_sunk_by_lift'] <= len(depths) * .02, (len(depths), sorted(round(d, 3) for d in depths if d > .001), [tuple(round(c, 2) for c in mat.to_translation()) for mat, d in zip(base, depths) if d > .001][:8])

# Moving the object moves the start point.
before = digest(base); obj.location.z += .5; assert digest(evaluated(obj)) != before; obj.location.z -= .5

# Emitters add up.
bpy.context.scene.cursor.location = (40, -1, 4.5)
assert bpy.ops.object.ivy_generator_add_emitter() == {'FINISHED'}
assert len(obj.data.vertices) == 2 and len(evaluated(obj)) > len(base)

# Replacing targets keeps the one owned collection; an empty target is safe.
bpy.ops.mesh.primitive_uv_sphere_add(radius=2, location=(40, -8, 2)); ball = bpy.context.object
owned = ivy.get_input(m, 'Target')
ball.select_set(True); obj.select_set(True); bpy.context.view_layer.objects.active = obj
assert bpy.ops.object.ivy_generator_set_targets() == {'FINISHED'}
assert ivy.get_input(m, 'Target') == owned and list(owned.objects) == [ball]
assert len(evaluated(obj)) > 0
owned.objects.unlink(ball)
assert len(evaluated(obj)) == 0
owned.objects.link(ball)

# A missing library is reported, not a crash.
leaf_col = next(c for c in bpy.data.collections if c.get('ivy_leaf_source'))
del leaf_col['ivy_leaf_source']
original = ivy.library_path; ivy.library_path = lambda: None
try:
    try:
        ivy.load_leaves(); raise SystemExit('expected FileNotFoundError')
    except FileNotFoundError:
        pass
finally:
    ivy.library_path = original; leaf_col['ivy_leaf_source'] = True

# Evaluates without the add-on.
count = len(evaluated(obj))
addon_utils.disable('ivy_generator', default_set=False)
assert len(evaluated(obj)) == count
results['after_disable'] = count
print('IVY_QA_PASS', json.dumps(results), flush=True)
