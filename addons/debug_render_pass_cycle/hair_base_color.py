"""Runtime-only albedo closure for Hair Tool's reflection/SSS-only Eevee shader.

Diffuse Color cannot display that shader's color stack faithfully. Keep its
authored color and alpha, but use a diffuse closure while the buffer is viewed.
No color settings, geometry or export payloads are changed.
"""
import bpy

NODE_NAME = ".DebugRenderPassCycle_HairAlbedo"
_states = {}


def restore():
    for name, state in tuple(_states.items()):
        group = bpy.data.node_groups.get(name)
        if group is None:
            continue
        preview = group.nodes.get(NODE_NAME)
        target_node = group.nodes.get(state[0])
        original_node = group.nodes.get(state[2])
        if preview is not None and target_node is not None:
            target = target_node.inputs[state[1]]
            if any(link.from_node == preview for link in target.links):
                for link in tuple(target.links):
                    group.links.remove(link)
                if original_node is not None:
                    group.links.new(original_node.outputs[state[3]], target)
        if preview is not None:
            group.nodes.remove(preview)
    _states.clear()


def _enable():
    changed = 0
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        shader = tree.nodes.get("HairShaderMain")
        group = getattr(shader, "node_tree", None)
        if group is None or group.library is not None:
            continue
        stack = group.nodes.get("HTUE Color Stack")
        if stack is None or stack.outputs.get("Color") is None:
            continue
        output = next((n for n in group.nodes if n.type == 'GROUP_OUTPUT'
                       and n.is_active_output), None)
        surface = output.inputs.get("EEVEE") if output else None
        if surface is None or len(surface.links) != 1:
            continue
        mix = surface.links[0].from_node
        if mix.type != 'MIX_SHADER':
            continue
        # Hair Tool uses (1 - opacity) with its Transparent BSDF in input 2.
        # Replacing that input destroys the cutout. Find the transparent branch
        # and replace only its opaque sibling, preserving the original mask.
        transparent = [index for index in (1, 2)
                       if len(mix.inputs[index].links) == 1
                       and mix.inputs[index].links[0].from_node.type == 'BSDF_TRANSPARENT']
        if len(transparent) != 1:
            continue
        opaque_index = 3 - transparent[0]
        if len(mix.inputs[opaque_index].links) != 1:
            continue
        current = mix.inputs[opaque_index].links[0]
        preview = group.nodes.get(NODE_NAME)
        if preview is not None and current.from_node == preview:
            continue
        # Bridge refreshes can replace a clone between watchdog ticks.
        _states.pop(group.name, None)
        if preview is not None:
            group.nodes.remove(preview)
        _states[group.name] = (
            mix.name, opaque_index, current.from_node.name,
            list(current.from_node.outputs).index(current.from_socket),
        )
        preview = group.nodes.new('ShaderNodeBsdfDiffuse')
        preview.name = NODE_NAME
        preview.label = "Temporary Base Color buffer"
        preview.hide = True
        group.links.new(stack.outputs['Color'], preview.inputs['Color'])
        group.links.new(preview.outputs[0], mix.inputs[opaque_index])
        changed += 1
    return changed


def sync():
    if bpy.app.background or bpy.app.is_job_running('RENDER'):
        restore()
        return 0
    visible = any(
        area.type == 'VIEW_3D'
        and area.spaces.active.shading.type in {'MATERIAL', 'RENDERED'}
        and area.spaces.active.shading.render_pass == 'DIFFUSE_COLOR'
        for window in bpy.context.window_manager.windows
        for area in window.screen.areas
    )
    if visible:
        return _enable()
    restore()
    return 0
