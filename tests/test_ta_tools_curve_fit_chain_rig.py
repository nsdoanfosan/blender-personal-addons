import addon_utils
import bpy


MODULE = "ta_tools"


def make_curve(name, reverse=False, spline_type='BEZIER'):
    curve = bpy.data.curves.new(name + "_Curve", type='CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 16
    spline = curve.splines.new(spline_type)
    if spline_type == 'BEZIER':
        spline.bezier_points.add(3)
        points = spline.bezier_points
    else:
        spline.points.add(3)
        points = spline.points

    coordinates = (
        (0.0, 0.0, 0.0),
        (1.5, 0.2, 0.5),
        (3.0, 1.0, 0.2),
        (4.5, 1.5, -0.5),
    )
    if reverse:
        coordinates = tuple(reversed(coordinates))
    for point, coordinate in zip(points, coordinates):
        if spline_type == 'BEZIER':
            point.co = coordinate
            point.handle_left_type = 'AUTO'
            point.handle_right_type = 'AUTO'
        else:
            point.co = (*coordinate, 1.0)

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
assert scene.ta_curve_fit_add_end_bone is False

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
assert rig.data.display_type == 'OCTAHEDRAL'

rope_bone_names = [f"rope_{index:03d}" for index in range(1, 7)]
assert [bone.name for bone in rig.data.bones] == rope_bone_names

modifier_types = [modifier.type for modifier in on_mesh.modifiers]
assert modifier_types == ['CURVE', 'ARMATURE']
assert_chain_weights(on_mesh, rope_bone_names)

scene.ta_curve_fit_add_end_bone = True
select_only(on_mesh)
result = bpy.ops.object.ta_build_curve_fit_chain_rig()
assert result == {'FINISHED'}

bone_names = rope_bone_names + ["rope_end"]
assert on_mesh.ta_curve_fit_chain_rig == rig
assert len(rig.data.bones) == 7
assert [bone.name for bone in rig.data.bones] == bone_names
end_bone = rig.data.bones["rope_end"]
last_rope_bone = rig.data.bones["rope_006"]
assert end_bone.parent == last_rope_bone
assert end_bone.use_connect is True
assert end_bone.use_deform is True
assert (end_bone.head_local - last_rope_bone.tail_local).length <= 0.000001
assert end_bone.length > 0.000001
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
scene.ta_curve_fit_add_end_bone = False
scene.ta_curve_fit_existing_segment_length_cm = 50.0
select_only(on_mesh)
result = bpy.ops.object.ta_segment_object_by_length()
assert result == {'FINISHED'}

assert on_mesh.ta_curve_fit_chain_rig == rig
assert len(rig.data.bones) == 7
assert [bone.name for bone in rig.data.bones] == bone_names
assert_chain_weights(on_mesh, bone_names)

select_only(on_mesh)
result = bpy.ops.object.ta_fit_object_to_curve()
assert result == {'FINISHED'}
assert on_mesh.ta_curve_fit_chain_rig == rig
assert len(rig.data.bones) == 7
assert [bone.name for bone in rig.data.bones] == bone_names
assert_chain_weights(on_mesh, bone_names)

scene.ta_curve_fit_generate_chain_rig = True
scene.ta_curve_fit_chain_bone_count = 6
scene.ta_curve_fit_add_end_bone = True
reverse_curve = make_curve("ChainRigReverse", reverse=True, spline_type='POLY')
select_only(reverse_curve)
result = bpy.ops.object.ta_create_curve_fit_plane()
assert result == {'FINISHED'}

reverse_mesh = bpy.context.active_object
reverse_rig = reverse_mesh.ta_curve_fit_chain_rig
assert reverse_rig is not None
assert reverse_rig.data.display_type == 'OCTAHEDRAL'

root_world = reverse_rig.matrix_world @ reverse_rig.data.bones[0].head_local
chain_end_world = reverse_rig.matrix_world @ reverse_rig.data.bones["rope_end"].head_local
end_tail_world = reverse_rig.matrix_world @ reverse_rig.data.bones["rope_end"].tail_local
curve_origin_world = reverse_curve.matrix_world.translation
source_first_world = reverse_curve.matrix_world @ reverse_curve.data.splines[0].points[0].co.xyz
assert (root_world - curve_origin_world).length <= 0.00001
assert (chain_end_world - source_first_world).length <= 0.00001
assert (end_tail_world - chain_end_world).length > 0.00001

axis_values = [vertex.co.x for vertex in reverse_mesh.data.vertices]
axis_min = min(axis_values)
axis_max = max(axis_values)
tolerance = max(axis_max - axis_min, 1.0) * 0.000001
group_names = {group.index: group.name for group in reverse_mesh.vertex_groups}

for vertex in reverse_mesh.data.vertices:
    if abs(vertex.co.x - axis_min) <= tolerance:
        weighted_names = {
            group_names[element.group]
            for element in vertex.groups
            if element.weight > 0.99999
        }
        assert weighted_names == {"rope_end"}
    elif abs(vertex.co.x - axis_max) <= tolerance:
        weighted_names = {
            group_names[element.group]
            for element in vertex.groups
            if element.weight > 0.99999
        }
        assert weighted_names == {"rope_001"}

addon_utils.disable(MODULE, default_set=False)
print("TA_TOOLS_CURVE_FIT_CHAIN_RIG_OK")
