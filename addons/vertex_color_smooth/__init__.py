"""Independent Handy-style color editing, active in Attribute viewports."""

bl_info = {
    "name": "Handy Vertex Color Edit",
    "author": "PARK / Codex",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Color > Handy Vertex Color Edit",
    "description": "Handy-style fill, gradient, smooth and RGB channel views for vertex colors",
    "category": "Paint",
}

import bpy
import bmesh
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from .core import (ColorSmoothError, smooth_colors, srgb_to_linear, linear_to_srgb,
                   edit_colors, VIEW_CHANNELS)
from . import viewport

_keymaps = []
CHANNELS = {'RGB': (0, 1, 2), 'RGBA': (0, 1, 2, 3),
            'R': (0,), 'G': (1,), 'B': (2,), 'A': (3,)}


def _factor():
    return FloatProperty(name="Strength", default=0.5, min=0.0, max=1.0,
                         description="Blend towards the average of edge neighbors each pass")


def _iterations():
    return IntProperty(name="Iterations", default=1, min=1, max=100)


def _outside():
    return BoolProperty(name="Use Outside Neighbors", default=True,
                        description="Read unselected visible neighbors, but never change them")


def _channels():
    return EnumProperty(name="Channels", default='RGB', items=[
        ('RGB', "RGB (Keep Alpha)", "Smooth RGB independently; preserve alpha"),
        ('RGBA', "RGBA", "Smooth all four channels independently"),
        ('R', "Red", "Smooth red only"), ('G', "Green", "Smooth green only"),
        ('B', "Blue", "Smooth blue only"), ('A', "Alpha", "Smooth alpha only"),
    ])


class VCS_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    factor: _factor()
    iterations: _iterations()
    use_outside: _outside()
    channels: EnumProperty(name="Channel", default='RGB', items=[
        ('RGB', "All", "Show and edit RGB; preserve alpha"),
        ('R', "R", "Black to red; edit red only"),
        ('G', "G", "Black to green; edit green only"),
        ('B', "B", "Black to blue; edit blue only"),
    ], update=lambda self, context: viewport.invalidate())
    increment_main: FloatProperty(name="Increment", default=0.1, min=0.001, max=1.0)
    increment_small: FloatProperty(name="Micro Increment", default=0.01, min=0.0001, max=0.1)
    enabled: BoolProperty(name="Attribute View Editing", default=True,
        description="Automatically enable color shortcuts only in Solid Attribute view",
        update=lambda self, context: viewport.invalidate())

    def draw(self, context):
        draw_settings(self.layout, self)
        self.layout.prop(self, 'enabled')
        self.layout.prop(self, 'increment_main')
        self.layout.prop(self, 'increment_small')
        self.layout.label(text="Shortcuts activate automatically in Solid > Color > Attribute.")


def active_color(obj):
    return obj.data.color_attributes.active_color if obj and obj.type == 'MESH' else None


def validate_context(context):
    obj = context.object
    if not obj or obj.type != 'MESH' or obj.mode not in {'EDIT', 'VERTEX_PAINT'}:
        return "Use Edit Mode or Vertex Paint on a mesh"
    if not obj.is_editable or not obj.data.is_editable:
        return "The mesh is linked and cannot be edited"
    if obj.data.users > 1:
        return "Mesh data is shared; make it single user first"
    if obj.mode == 'EDIT' and len(context.objects_in_mode_unique_data) != 1:
        return "Edit one mesh at a time"
    attr = active_color(obj)
    if not attr or attr.domain not in {'POINT', 'CORNER'}:
        return "Choose an active Color Attribute first"
    if obj.mode == 'VERTEX_PAINT' and not (obj.data.use_paint_mask_vertex or obj.data.use_paint_mask):
        return "Enable vertex or face selection masking and select the area to smooth"
    return None


def _bmesh_snapshot(obj, context, attr):
    # BMesh access may reallocate CustomData; do not retain a live RNA layer
    # pointer while obtaining the edit mesh or looking up its native layers.
    name, domain, dtype = attr.name, attr.domain, attr.data_type
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    if domain == 'POINT':
        elements = list(bm.verts)
        layers = bm.verts.layers
    else:
        elements = [loop for face in bm.faces for loop in face.loops]
        layers = bm.loops.layers
    layer = (layers.float_color if dtype == 'FLOAT_COLOR' else layers.color).get(name)
    if layer is None:
        raise ColorSmoothError("Active color layer is unavailable in Edit Mode")
    colors = np.array([tuple(element[layer]) for element in elements], dtype=float).reshape((-1, 4))
    if dtype == 'BYTE_COLOR':
        colors[:, :3] = srgb_to_linear(colors[:, :3])
    face_mode = context.tool_settings.mesh_select_mode[2] and not any(context.tool_settings.mesh_select_mode[:2])
    if domain == 'POINT':
        vertices = np.arange(len(elements))
        readable = np.array([not v.hide for v in elements])
        writable = np.array([v.select and not v.hide for v in elements])
    else:
        vertices = np.array([loop.vert.index for loop in elements], dtype=int)
        readable = np.array([not loop.face.hide and not loop.vert.hide for loop in elements])
        writable = np.array([(loop.face.select if face_mode else loop.vert.select) for loop in elements]) & readable
    edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges
             if not e.hide and not any(v.hide for v in e.verts)
             and (not e.link_faces or any(not face.hide for face in e.link_faces))]

    def write(output, changed):
        # Keep the wrapped edit BMesh alive until the write is complete.
        if not bm.is_valid:
            raise ColorSmoothError("The edit mesh changed; run smoothing again")
        if dtype == 'BYTE_COLOR':
            output[:, :3] = linear_to_srgb(output[:, :3])
        for index in changed:
            elements[index][layer] = output[index]
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

    return colors, vertices, edges, writable, readable, write


def _mesh_snapshot(obj, context, attr):
    mesh = obj.data
    colors = np.empty(len(attr.data) * 4, dtype=np.float64)
    attr.data.foreach_get('color', colors)
    colors = colors.reshape((-1, 4))
    vertex_visible = np.array([not v.hide for v in mesh.vertices])
    if mesh.use_paint_mask:
        selected_vertices = set(v for p in mesh.polygons if p.select and not p.hide for v in p.vertices)
        selected = np.array([v.index in selected_vertices for v in mesh.vertices])
    else:
        selected = np.array([v.select for v in mesh.vertices])
    visible_edges = set()
    for face in mesh.polygons:
        if not face.hide:
            visible_edges.update(tuple(sorted(edge)) for edge in face.edge_keys)
    edges = [tuple(e.vertices) for e in mesh.edges if not e.hide
             and all(vertex_visible[v] for v in e.vertices)
             and tuple(sorted(e.vertices)) in visible_edges]
    if attr.domain == 'POINT':
        vertices = np.arange(len(mesh.vertices))
        readable = vertex_visible
        writable = selected & readable
    else:
        vertices = np.array([loop.vertex_index for loop in mesh.loops], dtype=int)
        readable = vertex_visible[vertices].copy()
        writable = selected[vertices].copy()
        for face in mesh.polygons:
            indices = list(face.loop_indices)
            if face.hide:
                readable[indices] = False
            if mesh.use_paint_mask:
                writable[indices] = face.select and not face.hide
        writable &= readable

    def write(output, changed):
        # Only write changed samples. Preserve bytes of masked/hidden colors.
        for index in changed:
            attr.data[int(index)].color = output[index]
        mesh.update()

    return colors, vertices, edges, writable, readable, write


def calculate(obj, context, *, factor=0.5, iterations=1, channels='RGB', use_outside=True):
    """Preview without writes; used by the operator and live verification."""
    error = validate_context(context)
    if error:
        raise ColorSmoothError(error)
    attr = active_color(obj)
    snapshot = (_bmesh_snapshot if obj.mode == 'EDIT' else _mesh_snapshot)(obj, context, attr)
    colors, vertices, edges, writable, readable, write = snapshot
    output = smooth_colors(colors, vertices, edges, writable, readable,
                           factor=factor, iterations=iterations,
                           channels=CHANNELS[channels], use_outside=use_outside)
    changed = np.flatnonzero(writable & np.any(np.abs(output - colors) > 1e-12, axis=1))
    return output, changed, write


class VCS_OT_smooth(bpy.types.Operator):
    bl_idname = "mesh.vertex_color_smooth_selected"
    bl_label = "Smooth Selected Vertex Colors"
    bl_description = "Average active color values along mesh edges, only on selected vertices or faces"
    bl_options = {'REGISTER', 'UNDO'}
    factor: _factor()
    iterations: _iterations()
    use_outside: _outside()
    channels: EnumProperty(name="Channels", default='AUTO', items=[
        ('AUTO', "Displayed Channel", "Use All/R/G/B from Handy Vertex Color Edit"),
        ('RGB', "RGB (Keep Alpha)", ""), ('RGBA', "RGBA", ""),
        ('R', "Red", ""), ('G', "Green", ""), ('B', "Blue", ""), ('A', "Alpha", ""),
    ])

    @classmethod
    def poll(cls, context):
        error = validate_context(context)
        if error:
            cls.poll_message_set(error)
        return error is None

    def invoke(self, context, event):
        prefs = context.preferences.addons.get(__package__)
        if prefs:
            for prop in ('factor', 'iterations', 'use_outside'):
                if not self.properties.is_property_set(prop):
                    setattr(self, prop, getattr(prefs.preferences, prop))
        return self.execute(context)

    def execute(self, context):
        try:
            channels = self.channels
            if channels == 'AUTO':
                prefs = context.preferences.addons.get(__package__)
                channels = prefs.preferences.channels if prefs else 'RGB'
            output, changed, write = calculate(context.object, context, factor=self.factor,
                iterations=self.iterations, channels=channels, use_outside=self.use_outside)
            if not len(changed):
                self.report({'INFO'}, "No color changes; select connected colors with different values")
                return {'CANCELLED'}
            write(output, changed)
            viewport.invalidate()
            context.object.update_tag(refresh={'DATA'})
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            self.report({'INFO'}, f"Smoothed {len(changed)} color samples ({channels})")
            return {'FINISHED'}
        except ColorSmoothError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class VCS_OT_hotkey(bpy.types.Operator):
    bl_idname = "mesh.vertex_color_smooth_shortcut"
    bl_label = "Smooth Vertex Colors (Shift E)"
    bl_description = VCS_OT_smooth.bl_description

    @classmethod
    def poll(cls, context):
        return viewport.is_attribute_view(context) and validate_context(context) is None

    def execute(self, context):
        # The actual REGISTER/UNDO operator remains the last operation for F9.
        return bpy.ops.mesh.vertex_color_smooth_selected('INVOKE_DEFAULT')


class VCS_OT_adjust(bpy.types.Operator):
    bl_idname = "mesh.handy_color_adjust"
    bl_label = "Edit Selected Vertex Colors"
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(name="Method", default='GRADIENT', items=[
        ('FILL_DELTA', "Fill from First Vertex", "Set selection to lowest-index selected vertex plus increment"),
        ('GRADIENT', "Relative to Each Vertex", "Add to each color; preserve differences"),
        ('SET', "Set Value", "Set displayed channels to the value"),
        ('COPY', "Copy Active Vertex", "Copy last selected vertex into the selection"),
    ])
    direction: IntProperty(default=1, min=-1, max=1)
    micro: BoolProperty(name="Micro", default=False)
    value: FloatProperty(name="Value", default=1.0, min=0.0, max=1.0)
    amount: FloatProperty(name="Increment", default=0.1)
    channels: EnumProperty(name="Channels", default='AUTO', items=[
        ('AUTO', "Displayed Channel", ""), ('RGB', "All", ""),
        ('R', "Red", ""), ('G', "Green", ""), ('B', "Blue", ""),
    ])

    @classmethod
    def poll(cls, context):
        error = validate_context(context)
        if error:
            cls.poll_message_set(error)
        return error is None

    def invoke(self, context, event):
        prefs = context.preferences.addons.get(__package__)
        if prefs and not self.properties.is_property_set('amount'):
            self.amount = prefs.preferences.increment_small if self.micro else prefs.preferences.increment_main
        return self.execute(context)

    def execute(self, context):
        try:
            obj = context.object
            attr = active_color(obj)
            snapshot = (_bmesh_snapshot if obj.mode == 'EDIT' else _mesh_snapshot)(obj, context, attr)
            colors, vertices, edges, writable, readable, write = snapshot
            prefs = context.preferences.addons.get(__package__)
            channel = self.channels
            if channel == 'AUTO':
                channel = prefs.preferences.channels if prefs else 'RGB'
            source = None
            if self.action == 'COPY':
                if obj.mode != 'EDIT':
                    raise ColorSmoothError("Copy Active Vertex requires Edit Mode selection history")
                bm = bmesh.from_edit_mesh(obj.data)
                active = bm.select_history.active
                if not isinstance(active, bmesh.types.BMVert) or not active.select or active.hide:
                    raise ColorSmoothError("Select a vertex last to choose the copy source")
                source = active.index
            output = edit_colors(colors, vertices, writable, channels=CHANNELS[channel],
                action=self.action, delta=self.amount * self.direction,
                value=self.value, source_vertex=source)
            changed = np.flatnonzero(writable & np.any(np.abs(output - colors) > 1e-12, axis=1))
            if not len(changed):
                self.report({'INFO'}, "No color changes")
                return {'CANCELLED'}
            write(output, changed)
            obj.update_tag(refresh={'DATA'})
            viewport.invalidate()
            self.report({'INFO'}, f"Edited {len(changed)} color samples ({channel})")
            return {'FINISHED'}
        except ColorSmoothError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class VCS_OT_adjust_shortcut(bpy.types.Operator):
    bl_idname = "mesh.handy_color_adjust_shortcut"
    bl_label = "Handy Vertex Color Edit"
    action: EnumProperty(items=[('FILL_DELTA', "Fill", ""), ('GRADIENT', "Gradient", ""), ('COPY', "Copy", "")])
    direction: IntProperty(default=1, min=-1, max=1)
    micro: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return viewport.is_attribute_view(context) and validate_context(context) is None

    def execute(self, context):
        return bpy.ops.mesh.handy_color_adjust('INVOKE_DEFAULT', action=self.action,
                                              direction=self.direction, micro=self.micro)


class VCS_OT_cycle(bpy.types.Operator):
    bl_idname = "view3d.handy_color_cycle"
    bl_label = "Cycle Color Channel: All / R / G / B"
    bl_description = "Show and edit All, Red, Green, Blue in order; primary-color channel preview"

    @classmethod
    def poll(cls, context):
        return viewport.is_attribute_view(context)

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.channels = VIEW_CHANNELS[(VIEW_CHANNELS.index(prefs.channels) + 1) % 4]
        viewport.invalidate()
        return {'FINISHED'}


class VCS_OT_attribute_view(bpy.types.Operator):
    bl_idname = "view3d.handy_color_attribute_view"
    bl_label = "Attribute View"
    bl_description = "Toggle Solid Attribute view; color editing activates automatically in this viewport"

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'VIEW_3D'
                and context.object and context.object.type == 'MESH')

    def execute(self, context):
        space = context.space_data
        key = space.as_pointer()
        if viewport.attribute_shading(space, context.object.mode):
            previous = viewport.view_backups.pop(key, ('SOLID', 'MATERIAL', space.overlay.show_weight))
            space.shading.type, space.shading.color_type, space.overlay.show_weight = previous
        else:
            viewport.view_backups[key] = (space.shading.type, space.shading.color_type, space.overlay.show_weight)
            space.shading.type = 'SOLID'
            space.shading.color_type = 'VERTEX'
            space.overlay.show_weight = False
        viewport.invalidate()
        return {'FINISHED'}


def draw_settings(layout, settings):
    row = layout.row(align=True)
    row.prop(settings, 'factor')
    row.prop(settings, 'iterations')
    layout.prop(settings, 'channels')
    layout.prop(settings, 'use_outside')


class VCS_PT_panel(bpy.types.Panel):
    bl_idname = "VCS_PT_panel"
    bl_label = "Handy Vertex Color Edit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Color"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        settings = context.preferences.addons[__package__].preferences
        active = viewport.is_attribute_view(context)
        row = layout.row()
        row.scale_y = 1.4
        row.operator(VCS_OT_attribute_view.bl_idname, text="Attribute View",
                     icon='GROUP_VCOL', depress=viewport.attribute_shading(context.space_data, context.object.mode))
        layout.label(text="Active in this viewport" if active else "Solid > Color > Attribute to activate",
                     icon='CHECKMARK' if active else 'INFO')
        layout.prop(settings, 'enabled')
        attr = active_color(context.object)
        if attr:
            layout.prop(context.object.data.color_attributes, 'active_color', text="Attribute")
            layout.label(text=f"{attr.domain} · {attr.data_type}")
        else:
            layout.label(text="Choose a Color Attribute first", icon='ERROR')
        row = layout.row(align=True)
        row.prop(settings, 'channels', expand=True)
        layout.label(text="Cycle: Shift+Alt+RMB · All > R > G > B")
        column = layout.column()
        column.enabled = active and validate_context(context) is None
        box = column.box()
        box.label(text="Set Value")
        row = box.row(align=True)
        for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            op = row.operator(VCS_OT_adjust.bl_idname, text=f"{value:g}")
            op.action, op.value = 'SET', value
        for method, text in [('FILL_DELTA', "Fill"), ('GRADIENT', "Gradient")]:
            row = column.row(align=True)
            for direction, label in [(-1, "−"), (1, "+")]:
                op = row.operator(VCS_OT_adjust.bl_idname, text=f"{text} {label}")
                op.action, op.direction = method, direction
        column.operator(VCS_OT_adjust.bl_idname, text="Copy Active Vertex").action = 'COPY'
        box = column.box()
        row = box.row(align=True)
        row.prop(settings, 'factor')
        row.prop(settings, 'iterations')
        box.prop(settings, 'use_outside')
        box.operator(VCS_OT_smooth.bl_idname, text="Smooth · Shift+E", icon='MOD_SMOOTH')
        layout.prop(settings, 'increment_main')
        layout.prop(settings, 'increment_small')
        layout.label(text="Shift+Wheel: Fill · +Alt: Gradient")
        layout.label(text="Shift+Ctrl+Wheel: Micro Gradient")
        layout.label(text="Shift+Ctrl+Alt+Wheel: Micro Fill")
        layout.label(text="Shift+Ctrl+RMB: Copy Active Vertex")
        error = validate_context(context)
        if error:
            layout.label(text=error, icon='INFO')
        if viewport.last_error:
            layout.label(text=viewport.last_error, icon='ERROR')


_classes = (VCS_Preferences, VCS_OT_smooth, VCS_OT_hotkey, VCS_OT_adjust,
            VCS_OT_adjust_shortcut, VCS_OT_cycle, VCS_OT_attribute_view, VCS_PT_panel)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for name in ('Mesh', 'Vertex Paint'):
            km = kc.keymaps.new(name=name, space_type='EMPTY')
            kmi = km.keymap_items.new(VCS_OT_hotkey.bl_idname, 'E', 'PRESS', shift=True, head=True)
            _keymaps.append((km, kmi))
            for event, direction in [('WHEELUPMOUSE', 1), ('WHEELDOWNMOUSE', -1)]:
                for ctrl, alt, action, micro in [
                    (False, False, 'FILL_DELTA', False),
                    (False, True, 'GRADIENT', False),
                    (True, False, 'GRADIENT', True),
                    (True, True, 'FILL_DELTA', True),
                ]:
                    kmi = km.keymap_items.new(VCS_OT_adjust_shortcut.bl_idname, event, 'PRESS',
                        shift=True, ctrl=ctrl, alt=alt, head=True)
                    kmi.properties.action, kmi.properties.direction, kmi.properties.micro = action, direction, micro
                    _keymaps.append((km, kmi))
            kmi = km.keymap_items.new(VCS_OT_adjust_shortcut.bl_idname, 'RIGHTMOUSE', 'PRESS',
                                      shift=True, ctrl=True, head=True)
            kmi.properties.action = 'COPY'
            _keymaps.append((km, kmi))
            kmi = km.keymap_items.new(VCS_OT_cycle.bl_idname, 'RIGHTMOUSE', 'PRESS', shift=True, alt=True, head=True)
            _keymaps.append((km, kmi))
        km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new(VCS_OT_cycle.bl_idname, 'RIGHTMOUSE', 'PRESS', shift=True, alt=True, head=True)
        _keymaps.append((km, kmi))
    viewport.register()


def unregister():
    viewport.unregister()
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
