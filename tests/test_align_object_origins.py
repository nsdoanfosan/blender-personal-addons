"""Blender --factory-startup --background --python-exit-code 1 --python this_file."""
import json
import sys
from pathlib import Path

import addon_utils
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons'))
assert addon_utils.enable('align_object', default_set=False) is not None
import align_object


def mesh(name, location=(0, 0, 0)):
    data = bpy.data.meshes.new(name)
    data.from_pydata([(1, 0, 0), (0, 2, 0), (0, 0, 3)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    bpy.context.view_layer.update()
    return obj


def points(obj, key=None):
    data = obj.data.vertices if key is None else obj.data.shape_keys.key_blocks[key].data
    return [obj.matrix_world @ p.co for p in data]


def close(a, b):
    assert (Vector(a) - Vector(b)).length < 0.0002, (a, b)


def same_points(obj, expected, key=None):
    for a, b in zip(points(obj, key), expected):
        close(a, b)


def params(sources, target, **kw):
    return dict(source_names_json=json.dumps([o.name for o in sources]),
                original_matrices_json=json.dumps({o.name: align_object.matrix_to_list(o.matrix_world)
                                                   for o in sources}),
                active_source_name=sources[0].name, target_name=target.name, **kw)


def run(args):
    assert bpy.ops.object.move_each_selected_to_clicked_object(**args) == {'FINISHED'}
    bpy.context.view_layer.update()


target = mesh('Target', (9, -4, 7))
target.rotation_euler = (0.4, -0.2, 0.6)
source = mesh('Source', (2, 3, 4))
source.rotation_euler = (0.1, 0.2, -0.3)
source.scale = (2, 3, 0.5)
source.shape_key_add(name='Basis')
source.shape_key_add(name='Raised').data[0].co.z += 1.5
child = mesh('Child', (1, 2, 3))
child.parent = source
child.rotation_euler = (0.3, 0.1, -0.2)
child.scale = (0.3, 0.9, 1.1)
grandchild = mesh('Grandchild', (4, 1, 2))
grandchild.parent = child
bpy.context.view_layer.update()
original = points(source)
key_original = points(source, 'Raised')
child_original = points(child)
grand_original = points(grandchild)
original_location = source.matrix_world.translation.copy()
args = params([source], target)

# The actual scene toggle is sufficient; callers do not need a new option.
bpy.context.scene.tool_settings.use_transform_data_origin = True
run(args)
close(source.matrix_world.translation, target.matrix_world.translation)
same_points(source, original)
same_points(source, key_original, 'Raised')
same_points(child, child_original)
same_points(grandchild, grand_original)

# Repeated execute/F9 computation restores the original frame without accumulating.
run(dict(args, use_y=False, percent=0.5, apply_rotation=True))
close(source.matrix_world.translation,
      (5.5, original_location.y, 5.5))
same_points(source, original)
same_points(source, key_original, 'Raised')
same_points(child, child_original)
same_points(grandchild, grand_original)
run(dict(args, apply_rotation=True))
assert source.matrix_world.to_quaternion().rotation_difference(
    target.matrix_world.to_quaternion()).angle < 0.0002
same_points(source, original)
same_points(child, child_original)
run(dict(args, percent=0))
close(source.matrix_world.translation, original_location)
same_points(source, original)

# Target bounds and cursor align the origin, regardless of old source reference.
run(dict(args, target_reference_mode='CENTER', source_reference_mode='MIN'))
corners = [target.matrix_world @ Vector(p) for p in target.bound_box]
center = Vector(tuple((min(p[i] for p in corners) + max(p[i] for p in corners)) / 2
                      for i in range(3)))
close(source.matrix_world.translation, center)
same_points(source, original)
bpy.context.scene.cursor.location = (-8, 2, 5)
run(dict(args, target_reference_mode='CURSOR'))
close(source.matrix_world.translation, bpy.context.scene.cursor.location)
same_points(source, original)

# Linked duplicates and target data stay untouched.
linked = bpy.data.objects.new('Linked', target.data)
bpy.context.collection.objects.link(linked)
linked.location = (-4, 3, 2)
bpy.context.view_layer.update()
linked_original = points(linked)
target_original = points(target)
run(params([linked], target))
assert linked.data != target.data
same_points(linked, linked_original)
same_points(target, target_original)

# Parent + child selected together: both origins align, both surfaces stay put.
run(params([child, source], target, apply_rotation=True))
close(child.matrix_world.translation, target.matrix_world.translation)
close(source.matrix_world.translation, target.matrix_world.translation)
same_points(source, original)
same_points(child, child_original)
same_points(grandchild, grand_original)

# Curve control points/handles keep their world positions.
curve_data = bpy.data.curves.new('Curve', 'CURVE')
curve_data.dimensions = '3D'
spline = curve_data.splines.new('BEZIER')
spline.bezier_points.add(1)
for i, p in enumerate(spline.bezier_points):
    p.co = (i * 2, 1, i)
    p.handle_left = p.co + Vector((-0.5, 0, 0))
    p.handle_right = p.co + Vector((0.5, 0, 0))
curve = bpy.data.objects.new('Curve', curve_data)
bpy.context.collection.objects.link(curve)
curve.location = (-1, 5, 2)
bpy.context.view_layer.update()
curve_before = [curve.matrix_world @ getattr(p, attr) for p in spline.bezier_points
                for attr in ('co', 'handle_left', 'handle_right')]
run(params([curve], target, apply_rotation=True))
curve_after = [curve.matrix_world @ getattr(p, attr) for p in spline.bezier_points
               for attr in ('co', 'handle_left', 'handle_right')]
for a, b in zip(curve_before, curve_after):
    close(a, b)

# Ordinary object alignment still moves the surface and shares the same data.
bpy.context.scene.tool_settings.use_transform_data_origin = False
normal = mesh('Normal', (1, 2, 3))
normal_before = points(normal)
normal_data = normal.data
run(params([normal], target))
close(normal.matrix_world.translation, target.matrix_world.translation)
assert normal.data == normal_data
for a, b in zip(points(normal), normal_before):
    close(a - b, (8, -6, 4))

# Unsupported types and singular transforms cancel before any object changes.
bpy.context.scene.tool_settings.use_transform_data_origin = True
camera = bpy.data.objects.new('CameraTest', bpy.data.cameras.new('CameraTest'))
bpy.context.collection.objects.link(camera)
zero = mesh('Zero')
zero.scale.z = 0
bpy.context.view_layer.update()
for invalid in (camera, zero):
    before = source.matrix_world.copy()
    try:
        result = bpy.ops.object.move_each_selected_to_clicked_object(**params([source, invalid], target))
        assert result == {'CANCELLED'}
    except RuntimeError as error:
        assert '피봇 정렬' in str(error)
    assert source.matrix_world == before

# Exercise Blender's undo data snapshots, including single-user data and children.
undo_source = mesh('UndoSource', (3, 1, -2))
undo_child = mesh('UndoChild', (1, 0, 2))
undo_child.parent = undo_source
bpy.context.view_layer.update()
undo_points = points(undo_source)
undo_child_points = points(undo_child)
bpy.ops.ed.undo_push(message='Before origin alignment')
run(params([undo_source], target, apply_rotation=True))
bpy.ops.ed.undo_push(message='After origin alignment')
assert bpy.ops.ed.undo() == {'FINISHED'}
undo_source = bpy.data.objects['UndoSource']
undo_child = bpy.data.objects['UndoChild']
close(undo_source.matrix_world.translation, (3, 1, -2))
same_points(undo_source, undo_points)
same_points(undo_child, undo_child_points)
assert bpy.ops.ed.redo() == {'FINISHED'}
undo_source = bpy.data.objects['UndoSource']
undo_child = bpy.data.objects['UndoChild']
close(undo_source.matrix_world.translation, bpy.data.objects['Target'].matrix_world.translation)
same_points(undo_source, undo_points)
same_points(undo_child, undo_child_points)

assert not bpy.context.preferences.addons.get('align_object')
addon_utils.disable('align_object', default_set=False)
assert addon_utils.enable('align_object', default_set=False) is not None
print('PASS: origin toggle, translation, rotation, axes, percent, repeat, shape keys, children, shared mesh, bounds, cursor, curve, normal mode, cancellation, undo/redo, registration')
