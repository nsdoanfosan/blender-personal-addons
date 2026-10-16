"""Blender --factory-startup --background --python this_file; no saves."""
import importlib.util
from pathlib import Path
import bpy

path = Path(__file__).resolve().parents[1] / 'addons/debug_render_pass_cycle/hair_base_color.py'
spec = importlib.util.spec_from_file_location('hair_albedo_test', path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

for transparent_index in (1, 2):
    group = bpy.data.node_groups.new('HairAlphaFixture', 'ShaderNodeTree')
    group.interface.new_socket(name='EEVEE', in_out='OUTPUT', socket_type='NodeSocketShader')
    output = group.nodes.new('NodeGroupOutput')
    mix = group.nodes.new('ShaderNodeMixShader')
    mask = group.nodes.new('ShaderNodeValue')
    mask.outputs[0].default_value = .25
    transparent = group.nodes.new('ShaderNodeBsdfTransparent')
    opaque = group.nodes.new('ShaderNodeBsdfPrincipled')
    stack = group.nodes.new('ShaderNodeRGB')
    stack.name = 'HTUE Color Stack'
    stack.outputs[0].default_value = (.2, .1, .3, 1.)
    group.links.new(mask.outputs[0], mix.inputs[0])
    group.links.new(transparent.outputs[0], mix.inputs[transparent_index])
    group.links.new(opaque.outputs[0], mix.inputs[3-transparent_index])
    group.links.new(mix.outputs[0], output.inputs['EEVEE'])
    material = bpy.data.materials.new('HairAlphaFixture')
    material.use_nodes = True
    shader = material.node_tree.nodes.new('ShaderNodeGroup')
    shader.name = 'HairShaderMain'
    shader.node_tree = group
    before = {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
              for l in group.links}
    assert helper._enable() == 1
    assert mix.inputs[transparent_index].links[0].from_node == transparent
    assert mix.inputs[0].links[0].from_node == mask
    assert mix.inputs[3-transparent_index].links[0].from_node.type == 'BSDF_DIFFUSE'
    assert helper._enable() == 0
    helper.restore()
    assert group.nodes.get(helper.NODE_NAME) is None
    assert before == {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
                      for l in group.links}
    bpy.data.materials.remove(material)
    bpy.data.node_groups.remove(group)
print('HAIR_BASE_COLOR_ALPHA_PASS: both mix orders, original alpha and links, idempotence, cleanup')
