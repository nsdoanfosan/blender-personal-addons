"""Read-only POST_PIXEL label driven by Handy's existing scene toggle.

No mesh writes, operators, scene properties, keymaps or saved UI changes.
"""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

_handler = None
_shader = None
_states = {}


def label_state(context):
    props = getattr(context.scene, 'handy_weight_edit_props', None)
    obj = context.active_object
    if not props or not props.toggle_vertex_weight or not obj or obj.type != 'MESH':
        return None
    addon = context.preferences.addons.get(__package__)
    prefs = addon.preferences if addon else None
    if prefs and not prefs.show_group_hud:
        return None
    group = obj.vertex_groups.active
    return (obj.name, group.name if group else 'No active vertex group',
            bool(group and group.lock_weight),
            prefs.group_hud_corner if prefs else 'BOTTOM_LEFT')


def _visible_bounds(context):
    """Regions can overlap WINDOW; keep the label outside toolbar and sidebar."""
    region = context.region
    left, right = 0, region.width
    for other in context.area.regions:
        if other.type not in {'TOOLS', 'UI'} or other.width <= 1:
            continue
        x = other.x - region.x
        if other.type == 'TOOLS':
            left = max(left, x + other.width)
        else:
            right = min(right, x)
    return max(0, left), min(region.width, right)


def _wrap(text, width, measure):
    """Keep the complete group name, including CJK, in narrow viewports."""
    lines, current = [], ''
    for char in text:
        if current and measure(current + char) > width:
            lines.append(current)
            current = ''
        current += char
    return lines + [current]


def draw():
    context = bpy.context
    if not context.area or context.area.type != 'VIEW_3D' or not context.region or context.region.type != 'WINDOW':
        return
    if not context.space_data.overlay.show_overlays:
        return
    state = label_state(context)
    if not state:
        return
    _draw_label(context, state)


def _draw_label(context, state):
    global _shader
    obj_name, group_name, locked, corner = state
    scale = context.preferences.system.ui_scale
    left, right = _visible_bounds(context)
    margin, padding = 16 * scale, 12 * scale
    available = right - left - 2 * margin
    if available < 100 * scale or context.region.height < 140 * scale:
        return
    font = 0
    blf.size(font, 16 * scale)
    max_text = min(560 * scale, available - 2 * padding)
    measure = lambda text: blf.dimensions(font, text)[0]
    group_lines = _wrap(group_name + ('  [Locked]' if locked else ''), max_text, measure)
    blf.size(font, 12 * scale)
    lines = [(line, 12, (0.65, 0.82, 1.0, 1.0)) for line in
             _wrap('Handy · Active Vertex Group', max_text,
                   lambda text: blf.dimensions(font, text)[0])]
    lines += [(line, 16, (1.0, 0.87, 0.35, 1.0)) for line in group_lines]
    blf.size(font, 11 * scale)
    lines += [(line, 11, (0.85, 0.85, 0.85, 1.0)) for line in
              _wrap(obj_name, max_text, lambda text: blf.dimensions(font, text)[0])]
    widths = []
    for text, size, color in lines:
        blf.size(font, size * scale)
        widths.append(blf.dimensions(font, text)[0])
    width = min(available, max(widths) + 2 * padding)
    height = sum((size + 8) * scale for _, size, _ in lines) + 2 * padding
    if height > context.region.height - 100 * scale:
        return
    x = left + margin if corner == 'BOTTOM_LEFT' else right - margin - width
    y = min(72 * scale, context.region.height - height - margin) if corner == 'BOTTOM_LEFT' else context.region.height - 130 * scale - height
    y = max(margin, y)
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    previous_blend = gpu.state.blend_get()
    try:
        gpu.state.blend_set('ALPHA')
        batch = batch_for_shader(_shader, 'TRIS', {'pos': [
            (x, y), (x + width, y), (x + width, y + height), (x, y + height)]},
            indices=[(0, 1, 2), (0, 2, 3)])
        _shader.bind()
        _shader.uniform_float('color', (0.018, 0.025, 0.035, 0.85))
        batch.draw(_shader)
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, 3, 0, 0, 0, 0.85)
        blf.shadow_offset(font, 1, -1)
        cursor = y + height - padding
        for text, size, color in lines:
            cursor -= (size + 8) * scale
            blf.size(font, size * scale)
            blf.position(font, x + padding, cursor + 4 * scale, 0)
            blf.color(font, *color)
            blf.draw(font, text)
    finally:
        blf.disable(font, blf.SHADOW)
        gpu.state.blend_set(previous_blend)


def _refresh():
    current = {}
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            with bpy.context.temp_override(window=window, area=area):
                state = label_state(bpy.context)
            key = (window.as_pointer(), area.as_pointer())
            current[key] = state
            if _states.get(key) != state:
                area.tag_redraw()
    _states.clear()
    _states.update(current)
    return 0.25  # Only redraw when the label changes; follows non-viewport group edits.


def register():
    global _handler
    if bpy.app.background:
        return
    if _handler is None:
        _handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_refresh):
        bpy.app.timers.register(_refresh, first_interval=0.25, persistent=True)


def unregister():
    global _handler, _shader
    if bpy.app.timers.is_registered(_refresh):
        bpy.app.timers.unregister(_refresh)
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, 'WINDOW')
        _handler = None
    _shader = None
    _states.clear()
