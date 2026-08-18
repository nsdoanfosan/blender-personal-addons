import addon_utils
import bpy


MODULE = "ta_tools"


def make_curve(name):
    curve = bpy.data.curves.new(name + "_Curve", type='CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 16
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(3)

    coordinates = (
        (0.0, 0.0, 0.0),
        (1.5, 0.2, 0.5),
        (3.0, 1.0, 0.2),
        (4.5, 1.5, -0.5),
    )
    for point, coordinate in zip(spline.bezier_points, coordinates):
        point.co = coordinate
        point.handle_left_type = 'AUTO'
        point.handle_right_type = 'AUTO'

    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def assert_chain_weights(mesh_obj, expected_names):
    expected_names = set(expected_names)
    group_names = {group.index: group.name for group in mesh_obj.vertex_groups}

    assert expected_names.issubset(set(group_names.values()))
    for vertex in mesh_obj.data.vertices:
        weights = [
            element.weight
            for element in vertex.groups
            if group_names[element.group] in expected_names and element.weight > 0.000001
        ]
        assert 1 <= len(weights) <= 2
        assert abs(sum(weights) - 1.0) <= 0.00001


def evaluated_world_positions(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]


addon_utils.enable(MODULE, default_set=False)
scene = bpy.context.scene

assert scene.ta_curve_fit_generate_chain_rig is False

scene.ta_curve_fit_shape_type = 'CYLINDER'
scene.ta_curve_fit_cylinder_sides = 8
scene.ta_curve_fit_plane_segments = 16

off_curve = make_curve("ChainRigOff")
select_only(off_curve)
result = bpy.ops.object.ta_create_curve_fit_plane()
assert result == {'FINISHED'}

off_mesh = bpy.context.active_object
assert off_mesh.type == 'MESH'
assert off_mesh.ta_curve_fit_chain_rig is None
assert all(modifier.type != 'ARMATURE' for modifier in off_mesh.modifiers)

scene.ta_curve_fit_generate_chain_rig = True
scene.ta_curve_fit_chain_bone_count = 6

on_curve = make_curve("ChainRigOn")
select_only(on_curve)
result = bpy.ops.object.ta_create_curve_fit_plane()
assert result == {'FINISHED'}

on_mesh = bpy.context.active_object
rig = on_mesh.ta_curve_fit_chain_rig
assert rig is not None
assert rig.type == 'ARMATURE'
assert len(rig.data.bones) == 6

bone_names = [f"rope_{index:03d}" for index in range(1, 7)]
assert [bone.name for bone in rig.data.bones] == bone_names

modifier_types = [modifier.type for modifier in on_mesh.modifiers]
assert modifier_types == ['CURVE', 'ARMATURE']
assert_chain_weights(on_mesh, bone_names)

armature_modifier = on_mesh.modifiers[-1]
armature_modifier.show_viewport = False
bpy.context.view_layer.update()
curve_only_positions = evaluated_world_positions(on_mesh)

armature_modifier.show_viewport = True
bpy.context.view_layer.update()
rest_positions = evaluated_world_positions(on_mesh)
assert max(
    (rest - curve_only).length
    for rest, curve_only in zip(rest_positions, curve_only_positions)
) <= 0.00001

rig.pose.bones["rope_003"].rotation_mode = 'XYZ'
rig.pose.bones["rope_003"].rotation_euler.y = 0.35
bpy.context.view_layer.update()
posed_positions = evaluated_world_positions(on_mesh)
assert max(
    (posed - rest).length
    for posed, rest in zip(posed_positions, rest_positions)
) > 0.001
rig.pose.bones["rope_003"].rotation_euler.y = 0.0
bpy.context.view_layer.update()

scene.ta_curve_fit_generate_chain_rig = False
scene.ta_curve_fit_chain_bone_count = 9
scene.ta_curve_fit_existing_segment_length_cm = 50.0
select_only(on_mesh)
result = bpy.ops.object.ta_segment_object_by_length()
assert result == {'FINISHED'}

assert on_mesh.ta_curve_fit_chain_rig == rig
assert len(rig.data.bones) == 6
assert [bone.name for bone in rig.data.bones] == bone_names
assert_chain_weights(on_mesh, bone_names)

select_only(on_mesh)
result = bpy.ops.object.ta_fit_object_to_curve()
assert result == {'FINISHED'}
assert on_mesh.ta_curve_fit_chain_rig == rig
assert len(rig.data.bones) == 6
assert_chain_weights(on_mesh, bone_names)

addon_utils.disable(MODULE, default_set=False)
print("TA_TOOLS_CURVE_FIT_CHAIN_RIG_OK")
