"""Real Blender visibility regression; no preference or source-file writes."""
import addon_utils
import bpy
from types import SimpleNamespace
from send2ue.core import hair_tool_export as hair

addon_utils.enable('debug_render_pass_cycle', default_set=False)
import debug_render_pass_cycle as debug

export = bpy.data.collections.new('Export')
bpy.context.scene.collection.children.link(export)
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.shading.type = 'MATERIAL'
context = SimpleNamespace(area=area, space_data=area.spaces.active,
                          view_layer=bpy.context.view_layer, scene=bpy.context.scene)


def mesh_object(name, exported=False):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    (export if exported else bpy.context.scene.collection).objects.link(obj)
    return obj


def generated(name, source, exported=True):
    obj = mesh_object(name, exported)
    group = bpy.data.node_groups.new('Hair_System_Setup_Test', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    socket = group.interface.new_socket(name='Source Surface', in_out='INPUT', socket_type='NodeSocketObject')
    a = group.nodes.new('NodeGroupInput'); b = group.nodes.new('NodeGroupOutput')
    group.links.new(a.outputs['Geometry'], b.inputs['Geometry'])
    mod = obj.modifiers.new('GeneratorSetup', 'NODES'); mod.node_group = group
    hair._modifier_input_set(mod, socket.identifier, source)
    profile = group.copy(); profile.name = 'Hair_System_Profile_Test'
    mod = obj.modifiers.new('Profile', 'NODES'); mod.node_group = profile
    return obj


root = mesh_object('UnrelatedRoot')
guide = generated('IntermediateWithNoNamingConvention', root)
render = generated('FinalCards', guide)
render.parent = root  # Deliberately different from the generator source.
direct = mesh_object('DirectTwoStageGuide')
direct.hide_set(True)
two_stage = generated('TwoStageFinal', direct)
hidden = generated('InitiallyHiddenFinal', guide); hidden.hide_set(True)
orphan = generated('NoGuideFinal', None)
unrelated = mesh_object('OrdinarySceneMesh')
bpy.context.view_layer.update()
before = {o.name: (o.hide_get(), o.hide_render) for o in bpy.context.scene.objects}
sources_before = {o.name for o in hair._final_export_sources(export)}

for exit_kind in ('combined', 'other_pass', 'save', 'export', 'disable'):
    assert debug.apply_debug_view(context, 'ATTRIBUTE_WEIGHT_G') == 'ATTRIBUTE_WEIGHT_G'
    assert render.hide_get() and two_stage.hide_get()
    assert guide.visible_get() and direct.visible_get()
    assert hidden.hide_get() and orphan.visible_get() and unrelated.visible_get()
    assert all(o.hide_render == before[o.name][1] for o in bpy.context.scene.objects)
    # Re-entering the same pass must not replace the original visibility snapshot.
    assert debug.apply_debug_view(context, 'ATTRIBUTE_WEIGHT_G') == 'ATTRIBUTE_WEIGHT_G'
    if exit_kind == 'combined': debug.apply_debug_view(context, 'COMBINED')
    elif exit_kind == 'other_pass': debug.apply_debug_view(context, 'ATTRIBUTE_FACTOR')
    elif exit_kind == 'save': debug._save_pre_remove_debug_materials(None)
    elif exit_kind == 'export': hair.restore_debug_view()
    else: addon_utils.disable('debug_render_pass_cycle', default_set=False)
    assert {o.name: (o.hide_get(), o.hide_render) for o in bpy.context.scene.objects} == before, exit_kind
    assert {o.name for o in hair._final_export_sources(export)} == sources_before, exit_kind
    assert not debug.weight_visibility.active()
print('DEBUG_WEIGHT_VISIBILITY_OK: two/three stages, actual input, no guide/weight, hidden preservation, repeated entry, five restore paths, export candidates')
