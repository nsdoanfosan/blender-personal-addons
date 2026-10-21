"""Read-only RGB channel visualization. No temporary production attributes."""

import bpy
import bmesh
import blf
import numpy as np
from bpy.app.handlers import persistent
from .core import isolate_rgb

view_backups = {}
last_error = ''
_handlers = []
_cache = {}
_generation = 0
_shader = None


def settings(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def attribute_shading(space, mode='EDIT'):
    return (space and space.type == 'VIEW_3D' and space.shading.type == 'SOLID'
            and space.shading.color_type == 'VERTEX'
            and (mode != 'EDIT' or not space.overlay.show_weight))


def is_attribute_view(context):
    obj = context.object
    prefs = settings(context)
    return bool(context.area and context.area.type == 'VIEW_3D'
        and attribute_shading(context.space_data, obj.mode if obj else 'EDIT') and (prefs is None or prefs.enabled)
        and obj and obj.type == 'MESH' and obj.mode in {'EDIT', 'OBJECT', 'VERTEX_PAINT'}
        and obj.data.color_attributes.active_color)


def invalidate(*_args):
    global _generation
    _generation += 1
    _cache.clear()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


@persistent
def _changed(*_args):
    global _generation
    _generation += 1
    _cache.clear()


def color_shader():
    global _shader
    if _shader is None:
        import gpu
        interface = gpu.types.GPUStageInterfaceInfo('handy_color_interface')
        interface.smooth('VEC4', 'vcolor')
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'mvp')
        info.push_constant('FLOAT', 'depthOffset')
        info.push_constant('VEC2', 'viewportSize')
        info.push_constant('FLOAT', 'pixelSize')
        info.vertex_in(0, 'VEC3', 'pos')
        info.vertex_in(1, 'VEC4', 'color')
        info.vertex_in(2, 'VEC2', 'offset')
        info.vertex_out(interface)
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source('''
            void main() {
                gl_Position = mvp * vec4(pos, 1.0);
                gl_Position.z -= depthOffset * gl_Position.w;
                gl_Position.xy += offset * pixelSize * 2.0 / viewportSize * gl_Position.w;
                vcolor = color;
            }
        ''')
        info.fragment_source('void main() { fragColor = vec4(vcolor.rgb, 1.0); }')
        _shader = gpu.shader.create_from_info(info)
    return _shader


def make_batch(mode, positions, colors, offsets=None):
    from gpu_extras.batch import batch_for_shader
    if offsets is None:
        offsets = np.zeros((len(positions), 2), dtype=np.float32)
    return batch_for_shader(color_shader(), mode,
        {'pos': np.asarray(positions, dtype=np.float32),
         'color': np.asarray(colors, dtype=np.float32), 'offset': offsets})


def preview_arrays(context):
    """Read the evaluated surface, including armature deformation and color data."""
    obj = context.object
    name = obj.data.color_attributes.active_color.name
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        attr = mesh.color_attributes.get(name)
        if not attr or attr.domain not in {'POINT', 'CORNER'}:
            raise RuntimeError('Evaluated mesh does not contain the active Color Attribute')
        mesh.calc_loop_triangles()
        positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', positions)
        positions = positions.reshape((-1, 3))
        colors = np.empty(len(attr.data) * 4, dtype=np.float32)
        attr.data.foreach_get('color', colors)
        colors = colors.reshape((-1, 4))
        triangle_vertices = []
        triangle_samples = []
        for tri in mesh.loop_triangles:
            if mesh.polygons[tri.polygon_index].hide or any(mesh.vertices[i].hide for i in tri.vertices):
                continue
            triangle_vertices.extend(tri.vertices)
            triangle_samples.extend(tri.vertices if attr.domain == 'POINT' else tri.loops)
        indices = np.asarray(triangle_vertices, dtype=int)
        samples = np.asarray(triangle_samples, dtype=int)
        # Selection flags of the evaluated surface can lag behind Edit Mode.
        selected = [v.select for v in mesh.vertices]
        hidden = [v.hide for v in mesh.vertices]
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            if len(bm.verts) == len(mesh.vertices):
                selected = [v.select for v in bm.verts]
                hidden = [v.hide for v in bm.verts]
        edges = [(tuple(e.vertices), e.select) for e in mesh.edges
                 if not e.hide and not any(hidden[v] for v in e.vertices)]
        return {'positions': positions, 'colors': colors,
                'triangle_positions': positions[indices], 'triangle_colors': colors[samples],
                'edges': edges, 'selected': selected, 'hidden': hidden,
                'vertices': len(mesh.vertices), 'triangles': len(indices) // 3}
    finally:
        evaluated.to_mesh_clear()


def _batches(context, channel):
    obj = context.object
    signature = None
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        signature = tuple((v.select, v.hide) for v in bm.verts)
    key = (obj.as_pointer(), obj.mode, obj.data.color_attributes.active_color.name,
           channel, _generation, signature)
    if key in _cache:
        return _cache[key]
    arrays = preview_arrays(context)
    surface = make_batch('TRIS', arrays['triangle_positions'], isolate_rgb(arrays['triangle_colors'], channel))
    theme = context.preferences.themes[0].view_3d
    edge_positions, edge_colors = [], []
    for vertices, selected in arrays['edges']:
        selected = all(arrays['selected'][v] for v in vertices)
        color = (*theme.edge_select, 1.0) if selected else (0.025, 0.025, 0.025, 1.0)
        edge_positions.extend(arrays['positions'][list(vertices)])
        edge_colors.extend((color, color))
    edges = make_batch('LINES', edge_positions, edge_colors) if edge_positions else None
    point_positions, point_colors, offsets = [], [], []
    for index, selected in enumerate(arrays['selected']):
        if arrays['hidden'][index]:
            continue
        color = (*theme.vertex_select, 1.0) if selected else (*theme.vertex, 1.0)
        for offset in [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, -.5), (.5, .5), (-.5, .5)]:
            point_positions.append(arrays['positions'][index])
            point_colors.append(color)
            offsets.append(offset)
    points = make_batch('TRIS', point_positions, point_colors, offsets) if point_positions else None
    # One active object/channel batch is sufficient; do not accumulate meshes.
    _cache.clear()
    _cache[key] = (surface, edges, points)
    return _cache[key]


def draw_surface():
    global last_error
    context = bpy.context
    if not is_attribute_view(context):
        return
    prefs = settings(context)
    channel = prefs.channels if prefs else 'RGB'
    if channel == 'RGB':
        return  # Native Attribute view remains the full-color authority.
    import gpu
    old_depth = gpu.state.depth_test_get()
    old_mask = gpu.state.depth_mask_get()
    old_blend = gpu.state.blend_get()
    old_line = gpu.state.line_width_get()
    try:
        surface, edges, points = _batches(context, channel)
        shader = color_shader()
        shader.bind()
        shader.uniform_float('mvp', context.region_data.perspective_matrix @ context.object.matrix_world)
        shader.uniform_float('viewportSize', (max(1, context.region.width), max(1, context.region.height)))
        shader.uniform_float('pixelSize', 0.0)
        shader.uniform_float('depthOffset', .00001)
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set('NONE')
        surface.draw(shader)
        if context.object.mode == 'EDIT' and context.space_data.overlay.show_overlays:
            shader.uniform_float('depthOffset', .00002)
            if edges:
                gpu.state.line_width_set(1.0)
                edges.draw(shader)
            if points and context.tool_settings.mesh_select_mode[0]:
                shader.uniform_float('depthOffset', .00003)
                shader.uniform_float('pixelSize', float(context.preferences.themes[0].view_3d.vertex_size))
                points.draw(shader)
        last_error = ''
    except Exception as exc:
        last_error = 'Channel preview: ' + str(exc)[:100]
    finally:
        gpu.state.depth_test_set(old_depth)
        gpu.state.depth_mask_set(old_mask)
        gpu.state.blend_set(old_blend)
        gpu.state.line_width_set(old_line)


def draw_hud():
    context = bpy.context
    if not is_attribute_view(context) or not context.space_data.overlay.show_overlays:
        return
    prefs = settings(context)
    channel = prefs.channels if prefs else 'RGB'
    attr = context.object.data.color_attributes.active_color
    tint = {'RGB': (.9, .9, .9, 1), 'R': (1, .25, .25, 1),
            'G': (.3, 1, .3, 1), 'B': (.35, .55, 1, 1)}[channel]
    blf.size(0, 15)
    blf.color(0, *tint)
    blf.position(0, 65, max(30, context.region.height - 105), 0)
    blf.draw(0, f"Handy Color  |  {attr.name}  |  {'All' if channel == 'RGB' else channel}")
    blf.color(0, 1, 1, 1, 1)


def register():
    if not bpy.app.background:
        _handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_surface, (), 'WINDOW', 'POST_VIEW'))
        _handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_hud, (), 'WINDOW', 'POST_PIXEL'))
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.undo_post,
                     bpy.app.handlers.redo_post, bpy.app.handlers.load_post):
        if _changed not in handlers:
            handlers.append(_changed)


def unregister():
    global _shader, last_error
    for handle in _handlers:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _handlers.clear()
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.undo_post,
                     bpy.app.handlers.redo_post, bpy.app.handlers.load_post):
        if _changed in handlers:
            handlers.remove(_changed)
    _cache.clear()
    view_backups.clear()
    _shader = None
    last_error = ''
