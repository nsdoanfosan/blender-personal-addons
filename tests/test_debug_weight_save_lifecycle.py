"""Actual undo and save/reload with both visibility addons; no user file writes."""
import addon_utils,bpy,pathlib,tempfile,json
from types import SimpleNamespace
from send2ue.core import hair_tool_export as hair

addon_utils.enable('debug_render_pass_cycle',default_set=False)
addon_utils.enable('wire_bounds_selection_visibility',default_set=False)
import debug_render_pass_cycle as debug
import wire_bounds_selection_visibility as wire

out=pathlib.Path(tempfile.mkdtemp(prefix='weight-save-lifecycle-'))
export=bpy.data.collections.new('Export')
bpy.context.scene.collection.children.link(export)

def mesh(name,exported=False):
    data=bpy.data.meshes.new(name)
    data.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    obj=bpy.data.objects.new(name,data)
    (export if exported else bpy.context.scene.collection).objects.link(obj)
    return obj

guide=mesh('LifecycleGuide'); guide.display_type='BOUNDS'
render=mesh('LifecycleRender',True)
group=bpy.data.node_groups.new('Hair_System_Setup_Test','GeometryNodeTree')
group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
socket=group.interface.new_socket(name='Source Surface',in_out='INPUT',socket_type='NodeSocketObject')
source_identifier=socket.identifier
a=group.nodes.new('NodeGroupInput'); b=group.nodes.new('NodeGroupOutput')
group.links.new(a.outputs['Geometry'],b.inputs['Geometry'])
mod=render.modifiers.new('Setup','NODES'); mod.node_group=group
hair._modifier_input_set(mod,source_identifier,guide)
mod=render.modifiers.new('Profile','NODES'); mod.node_group=group.copy()
mod.node_group.name='Hair_System_Profile_Test'
bpy.context.view_layer.update()
wire._initialize_all_view_layers()

def context():
    area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
    area.spaces.active.shading.type='MATERIAL'
    return SimpleNamespace(area=area,space_data=area.spaces.active,view_layer=bpy.context.view_layer,scene=bpy.context.scene)

# Keep a ViewLayer snapshot across a real undo that replaces Blender Main.
bpy.ops.ed.undo_push(message='Before Weight')
debug.apply_debug_view(context(),'ATTRIBUTE_WEIGHT_G')
# A long-lived restore snapshot must remain serializable across Main replacement.
json.dumps(debug.weight_visibility._states)
json.dumps(debug._material_override_states)
json.dumps(debug._debug_materials)
bpy.data.objects['LifecycleGuide'].location.x=2
bpy.ops.ed.undo_push(message='Edited Weight guide')
bpy.ops.ed.undo()
print('AFTER_REAL_UNDO',flush=True)
bpy.ops.ed.redo()
bpy.ops.ed.undo()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'after_undo.blend'),check_existing=False)
print('SAVED_AFTER_UNDO',flush=True)
assert not bpy.data.objects['LifecycleRender'].hide_get()
assert bpy.data.objects['LifecycleGuide'].hide_get()
assert not bpy.data.objects['LifecycleGuide'].show_wire
assert not bpy.data.objects['LifecycleGuide'].show_all_edges

# Deletion and name reuse must not make an old restore record own a new object.
debug.apply_debug_view(context(),'ATTRIBUTE_WEIGHT_G')
old=bpy.data.objects['LifecycleGuide']
bpy.data.objects.remove(old,do_unlink=True)
replacement=mesh('LifecycleGuide')
replacement.hide_set(False)
replacement.display_type='SOLID'
debug.apply_debug_view(context(),'COMBINED')
assert not replacement.hide_get() and replacement.display_type=='SOLID'
setup=bpy.data.objects['LifecycleRender'].modifiers['Setup']
hair._modifier_input_set(setup,source_identifier,replacement)
replacement.display_type='BOUNDS'
wire._on_display_type_changed()

# Save directly from Weight as well, including a renamed object and view layer.
debug.apply_debug_view(context(),'ATTRIBUTE_WEIGHT_G')
bpy.context.view_layer.name='Renamed Layer'
bpy.data.objects['LifecycleGuide'].name='Renamed Guide'
bpy.ops.wm.save_as_mainfile(filepath=str(out/'weight_saved.blend'),check_existing=False)
assert bpy.context.view_layer.material_override is None
assert not bpy.data.objects['LifecycleRender'].hide_get()
assert bpy.data.objects['Renamed Guide'].hide_get()
assert bpy.data.objects['Renamed Guide'].display_type=='BOUNDS'
assert not bpy.data.objects['Renamed Guide'].show_wire

# Loading another Main must discard old runtime references before it is freed.
debug.apply_debug_view(context(),'ATTRIBUTE_WEIGHT_G')
bpy.ops.wm.open_mainfile(filepath=str(out/'weight_saved.blend'),load_ui=True)
assert bpy.context.view_layer.material_override is None
assert not bpy.data.objects['LifecycleRender'].hide_get()
assert bpy.data.objects['Renamed Guide'].hide_get()
assert not bpy.data.objects['Renamed Guide'].show_wire
assert not debug.weight_visibility.active()
addon_utils.disable('debug_render_pass_cycle',default_set=False)
assert debug._history_post_invalidate_runtime not in bpy.app.handlers.undo_post
assert debug._history_post_invalidate_runtime not in bpy.app.handlers.redo_post
assert debug._load_pre_clear_runtime not in bpy.app.handlers.load_pre
print('DEBUG_WEIGHT_SAVE_LIFECYCLE_OK',str(out),flush=True)
