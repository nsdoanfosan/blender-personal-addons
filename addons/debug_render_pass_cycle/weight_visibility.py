"""Temporary guide-only visibility for the live Weight view."""
import bpy
import sys

_states = []


def restore():
    """Restore the exact per-view-layer states, including initially hidden guides."""
    released = {}
    while _states:
        state = _states.pop()
        try:
            obj = state['object']
            if state.get('surface_override') and obj.display_type == 'TEXTURED':
                obj.display_type = state['display_type']
            obj.hide_set(state['hidden'], view_layer=state['view_layer'])
            if state['local'] is not None:
                obj.local_view_set(state['space'], state['local'])
            released.setdefault(state['view_layer'], []).append(obj)
        except (ReferenceError, RuntimeError):
            # The object/view layer may have been removed while debugging.
            continue
    # Selection can change while Weight owns visibility. Resume only these
    # helpers against the current selection, not the stale entry selection.
    wire = sys.modules.get('wire_bounds_selection_visibility')
    resume = getattr(wire, 'resume_objects', None)
    if resume is not None and hasattr(bpy.types.Object, 'wbsv_managed'):
        for view_layer, objects in released.items():
            resume(view_layer, objects)


def _remember(obj, context, surface_override=False):
    if any(row['object'] == obj and row['view_layer'] == context.view_layer for row in _states):
        return
    space = context.space_data
    _states.append({'object': obj, 'view_layer': context.view_layer,
                    'hidden': obj.hide_get(view_layer=context.view_layer),
                    'display_type': obj.display_type,
                    'surface_override': surface_override,
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
        _remember(guide, context, surface_override=True)
        guide.display_type = 'TEXTURED'
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


def controls(obj):
    """Runtime ownership only; never overwrite the user's exclusion property."""
    return any(state['object'] == obj for state in _states)
