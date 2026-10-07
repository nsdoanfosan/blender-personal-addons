"""Handy Weight Edit companion: normalized smoothing and active-group HUD."""

bl_info = {
    "name": "Selected All Weights Smooth",
    "author": "PARK / Codex",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Skinning > Handy Weight Edit; Ctrl+Shift+E",
    "description": "Smooth all selected skin influences together, with total weight 1",
    "category": "Rigging",
}

import bpy
import bmesh
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from .core import WeightError, smooth_weights
from . import active_group_hud

_keymaps = []
_handy_panel = None


def _strength():
    return FloatProperty(name="Strength", description="Blend toward adjacent weight vectors",
                         default=0.5, min=0.0, max=1.0)


def _iterations():
    return IntProperty(name="Iterations", default=5, min=1, max=100)


def _outside():
    return BoolProperty(name="Use Outside Neighbors", default=False,
                        description="Read edge neighbors outside the selection; never modify them")


def _scope():
    return EnumProperty(name="Groups", default='AUTO', items=[
        ('AUTO', "Bone Weights (Auto)", "Use deform bones of bound armatures; all groups if no armature"),
        ('ALL', "All Vertex Groups", "Include every group, including masks, in the sum of 1"),
    ])


class NWS_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    factor: _strength()
    iterations: _iterations()
    use_outside: _outside()
    group_scope: _scope()
    show_group_hud: BoolProperty(name="Show Active Group in Viewport", default=True,
                                description="Show the active vertex group while Handy's Vertex Weight Toggle is on")
    group_hud_corner: EnumProperty(name="Group Label Position", default='BOTTOM_LEFT', items=[
        ('BOTTOM_LEFT', "Bottom Left", "Above the last-operation panel"),
        ('TOP_RIGHT', "Top Right", "Below the navigation gizmo, beside the sidebar"),
    ])

    def draw(self, context):
        self.layout.label(text="Edit Mode: select vertices, then Ctrl+Shift+E.")
        self.layout.label(text="Weight Paint: enable vertex or face selection masking.")
        for prop in ('factor', 'iterations', 'use_outside', 'group_scope',
                     'show_group_hud', 'group_hud_corner'):
            self.layout.prop(self, prop)


def _group_indices(obj, scope):
    armatures = [m.object for m in obj.modifiers
                 if m.type == 'ARMATURE' and m.object and m.object.type == 'ARMATURE'
                 and m.use_vertex_groups]
    if scope == 'ALL' or not armatures:
        return {g.index for g in obj.vertex_groups}
    bones = {b.name for arm in armatures for b in arm.data.bones if b.use_deform}
    return {g.index for g in obj.vertex_groups if g.name in bones}


class NWS_OT_smooth(bpy.types.Operator):
    bl_idname = "mesh.normalized_weight_smooth"
    bl_label = "Smooth All Selected Weights"
    bl_description = "Smooth all influences together on selected vertices; keep sum 1 and respect group locks"
    bl_options = {'REGISTER', 'UNDO'}

    factor: _strength()
    iterations: _iterations()
    use_outside: _outside()
    group_scope: _scope()

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH' or not obj.vertex_groups:
            cls.poll_message_set("Select a mesh with vertex groups")
            return False
        if obj.mode not in {'EDIT', 'WEIGHT_PAINT'}:
            cls.poll_message_set("Use Edit Mode or Weight Paint with selection masking")
            return False
        if obj.data.users > 1:
            cls.poll_message_set("Mesh data is shared; make it single user first")
            return False
        if obj.mode == 'WEIGHT_PAINT' and not (obj.data.use_paint_mask_vertex or obj.data.use_paint_mask):
            cls.poll_message_set("Enable vertex or face selection masking first")
            return False
        if obj.library or obj.data.library:
            cls.poll_message_set("Mesh must be local and editable")
            return False
        return True

    def invoke(self, context, event):
        addon = context.preferences.addons.get(__package__)
        if addon:
            for prop in ('factor', 'iterations', 'use_outside', 'group_scope'):
                if not self.properties.is_property_set(prop):
                    setattr(self, prop, getattr(addon.preferences, prop))
        return self.execute(context)

    def execute(self, context):
        obj = context.object
        edit = obj.mode == 'EDIT'
        bm = bmesh.from_edit_mesh(obj.data) if edit else bmesh.new()
        try:
            if not edit:
                bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            deform = bm.verts.layers.deform.active
            if deform is None:
                self.report({'WARNING'}, "No vertex weights on this mesh")
                return {'CANCELLED'}
            if not edit and obj.data.use_paint_mask and not obj.data.use_paint_mask_vertex:
                selected = {v.index for f in bm.faces if f.select and not f.hide
                            for v in f.verts if not v.hide}
            else:
                selected = {v.index for v in bm.verts if v.select and not v.hide}
            if not selected:
                self.report({'WARNING'}, "Select vertices to smooth")
                return {'CANCELLED'}
            allowed = _group_indices(obj, self.group_scope)
            if not allowed:
                self.report({'WARNING'}, "No deform-bone groups; choose All Vertex Groups if needed")
                return {'CANCELLED'}
            locked = {g.index for g in obj.vertex_groups if g.lock_weight}
            neighbors = {v: [e.other_vert(bm.verts[v]).index for e in bm.verts[v].link_edges
                             if not e.other_vert(bm.verts[v]).hide] for v in selected}
            needed = selected | {n for ns in neighbors.values() for n in ns}
            rows = {v: dict(bm.verts[v][deform]) for v in needed}
            output, skipped = smooth_weights(rows, neighbors, selected, allowed, locked,
                                             self.factor, self.iterations, self.use_outside)
            changed = {v: row for v, row in output.items() if row != rows[v]}
            if not changed:
                self.report({'WARNING'} if skipped else {'INFO'},
                            f"No weight changes; {skipped} vertices have no available influences")
                return {'CANCELLED'}
            for v, row in changed.items():
                weights = bm.verts[v][deform]
                for g in list(weights.keys()):
                    if g in allowed and g not in locked and g not in row:
                        del weights[g]
                for g, w in row.items():
                    if g in allowed and g not in locked:
                        weights[g] = w
            if edit:
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            else:
                bm.to_mesh(obj.data)
                obj.data.update()
            obj.update_tag(refresh={'DATA'})
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            self.report({'INFO'}, f"Smoothed {len(changed)} vertices; sum 1, locks preserved"
                        + (f"; skipped {skipped} unweighted vertices" if skipped else ""))
            return {'FINISHED'}
        except WeightError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        finally:
            if not edit:
                bm.free()


def draw_tools(layout, context):
    addon = context.preferences.addons.get(__package__)
    if not addon:
        return
    prefs = addon.preferences
    box = layout.box()
    box.label(text="All Weights Smooth · Ctrl+Shift+E", icon='MOD_VERTEX_WEIGHT')
    row = box.row(align=True)
    row.prop(prefs, 'factor')
    row.prop(prefs, 'iterations')
    box.prop(prefs, 'group_scope')
    box.prop(prefs, 'use_outside')
    box.operator(NWS_OT_smooth.bl_idname, text="Smooth All Selected Weights", icon='MOD_SMOOTH')
    box.label(text="Selected vertices only · Total 1 · Keep locks")
    box.prop(prefs, 'show_group_hud')
    if prefs.show_group_hud:
        box.prop(prefs, 'group_hud_corner')


def _draw_handy(self, context):
    draw_tools(self.layout, context)


class NWS_PT_panel(bpy.types.Panel):
    bl_idname = "NWS_PT_panel"
    bl_label = "All Weights Smooth"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Skinning"

    @classmethod
    def poll(cls, context):
        return _handy_panel is None and context.object and context.object.type == 'MESH'

    def draw(self, context):
        draw_tools(self.layout, context)


def _attach_handy():
    global _handy_panel
    if not NWS_OT_smooth.is_registered:
        return None
    panel = getattr(bpy.types, 'HANDY_WEIGHT_EDIT_PT_main', None)
    if panel is not _handy_panel:
        if _handy_panel is not None:
            _handy_panel.remove(_draw_handy)
        _handy_panel = panel
        if panel:
            panel.append(_draw_handy)
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    return 2.0  # Follow Handy enable/reload and any N-panel tab customization.


_classes = (NWS_Preferences, NWS_OT_smooth, NWS_PT_panel)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for name in ('Mesh', 'Weight Paint'):
            km = kc.keymaps.new(name=name, space_type='EMPTY')
            kmi = km.keymap_items.new(NWS_OT_smooth.bl_idname, 'E', 'PRESS', ctrl=True, shift=True)
            _keymaps.append((km, kmi))
    _attach_handy()
    bpy.app.timers.register(_attach_handy, first_interval=2.0, persistent=True)
    active_group_hud.register()


def unregister():
    global _handy_panel
    active_group_hud.unregister()
    if bpy.app.timers.is_registered(_attach_handy):
        bpy.app.timers.unregister(_attach_handy)
    if _handy_panel:
        _handy_panel.remove(_draw_handy)
        _handy_panel = None
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
