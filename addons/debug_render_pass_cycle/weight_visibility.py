"""Temporary guide-only visibility for the live Weight view."""
import bpy

_states = []


def restore():
    """Restore the exact per-view-layer states, including initially hidden guides."""
    while _states:
        state = _states.pop()
        try:
            obj = state['object']
            obj.hide_set(state['hidden'], view_layer=state['view_layer'])
            if state['local'] is not None:
                obj.local_view_set(state['space'], state['local'])
        except (ReferenceError, RuntimeError):
            # The object/view layer may have been removed while debugging.
            continue


def _remember(obj, context):
    if any(row['object'] == obj and row['view_layer'] == context.view_layer for row in _states):
        return
    space = context.space_data
    _states.append({'object': obj, 'view_layer': context.view_layer,
                    'hidden': obj.hide_get(view_layer=context.view_layer),
                    'space': space,
                    'local': obj.local_view_get(space) if space.local_view else None})


def _generator_guide(render, object_inputs):
    # This is the same authoritative immediate input used by Send2UE.find_guide.
    # Names, parent depth and the presence of authored weights are not identity tests.
    sources = {value for modifier, socket, value in object_inputs(render)
               if modifier.node_group.name.startswith('Hair_System_Setup')
               and socket.name.replace('_', ' ').strip().casefold() == 'source surface'
               and value is not None and value != render}
    return next(iter(sources)) if len(sources) == 1 else None


def show_guides(context):
    """Swap visible final Export outputs for their actual simulation sources."""
    restore()
    try:
        from send2ue.core import hair_tool_export, hair_guide_cloth
    except ImportError:
        return []
    export = bpy.data.collections.get('Export')
    if export is None:
        return []
    pairs = []
    for render in hair_tool_export._final_export_sources(export):
        if not render.visible_get(view_layer=context.view_layer, viewport=context.space_data):
            continue
        guide = _generator_guide(render, hair_guide_cloth._object_inputs)
        if (guide is None or guide.type not in {'MESH', 'CURVES', 'CURVE'}
                or guide.name not in context.view_layer.objects or guide.hide_viewport):
            continue
        pairs.append((render, guide))
    # Shared sources are shown once. Objects that also drive a later output are
    # retained as guides rather than hidden because of a shorter parallel chain.
    guides = {guide for _, guide in pairs}
    for guide in guides:
        _remember(guide, context)
        guide.hide_set(False, view_layer=context.view_layer)
        if context.space_data.local_view:
            guide.local_view_set(context.space_data, True)
    context.view_layer.update()
    applied = []
    for render, guide in pairs:
        if not guide.visible_get(view_layer=context.view_layer, viewport=context.space_data):
            continue
        if render not in guides:
            _remember(render, context)
            render.hide_set(True, view_layer=context.view_layer)
            applied.append((render.name, guide.name))
    return applied


def active():
    return bool(_states)
