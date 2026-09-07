"""Exercise both real addons together; never save user preferences."""
import addon_utils
import bpy
from types import SimpleNamespace
from send2ue.core import hair_tool_export as hair

addon_utils.enable('debug_render_pass_cycle', default_set=False)
addon_utils.enable('wire_bounds_selection_visibility', default_set=False)
import debug_render_pass_cycle as debug
import wire_bounds_selection_visibility as wire

export=bpy.data.collections.new('Export')
bpy.context.scene.collection.children.link(export)
layer=bpy.context.view_layer
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
area.spaces.active.shading.type='MATERIAL'
context=SimpleNamespace(area=area,space_data=area.spaces.active,view_layer=layer,scene=bpy.context.scene)

def mesh(name,exported=False):
    data=bpy.data.meshes.new(name)
    data.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    obj=bpy.data.objects.new(name,data)
    (export if exported else bpy.context.scene.collection).objects.link(obj)
    return obj

def generated(name,source):
    obj=mesh(name,True)
    group=bpy.data.node_groups.new('Hair_System_Setup_Test','GeometryNodeTree')
    group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    socket=group.interface.new_socket(name='Source Surface',in_out='INPUT',socket_type='NodeSocketObject')
    a=group.nodes.new('NodeGroupInput'); b=group.nodes.new('NodeGroupOutput')
    group.links.new(a.outputs['Geometry'],b.inputs['Geometry'])
    mod=obj.modifiers.new('Setup','NODES'); mod.node_group=group
    hair._modifier_input_set(mod,socket.identifier,source)
    mod=obj.modifiers.new('Profile','NODES'); mod.node_group=group.copy()
    mod.node_group.name='Hair_System_Profile_Test'
    return obj

root=mesh('Root')
guide=generated('IntermediateGuide',root); guide.display_type='BOUNDS'
render=generated('FinalRender',guide)
other=mesh('OrdinaryMesh')
helper=mesh('UnrelatedWire'); helper.display_type='WIRE'
layer.update()
wire._initialize_all_view_layers()

def select(obj):
    for item in layer.objects:
        if item.select_get(): item.select_set(False)
    layer.objects.active=obj
    wire._on_active_object_changed()
    if not obj.hide_get(): obj.select_set(True)

select(other)
debug.apply_debug_view(context,'ATTRIBUTE_WEIGHT_G')
assert not guide.hide_get() and render.hide_get()
select(guide)
select(other)
assert not guide.hide_get(), 'selection addon hid the Weight guide after selection changed'
assert guide.display_type=='TEXTURED', 'Weight guide must remain a visible surface'
assert guide.show_wire and guide.show_all_edges, 'Unselected Weight guides need wire'

# The display-type notification must not release managed debug guides.
wire._on_display_type_changed()
assert guide.wbsv_managed and not guide.hide_get()

# An ordinary wire helper retains its selection behavior during Weight display.
select(helper); assert not helper.hide_get()
select(other); assert helper.hide_get()

# Even a managed render activated in the Outliner stays hidden during Weight.
render.display_type='WIRE'
wire._on_display_type_changed()
select(render)
assert render.hide_get(), 'selection addon revealed the hidden final render'
select(helper)
helper.select_set(False)
layer.objects.active=guide
guide.select_set(True)  # Exit before the queued active-object notification runs.
debug.apply_debug_view(context,'COMBINED')
assert not guide.hide_get() and guide.display_type=='WIRE'
assert helper.hide_get(), 'debug exit swallowed the unrelated helper selection transition'
select(other)
assert guide.hide_get() and guide.display_type=='BOUNDS'

# Repeated Weight entry must not leave helpers permanently excluded.
for leave in ('other_pass','save','export','disable'):
    select(render)
    debug.apply_debug_view(context,'ATTRIBUTE_WEIGHT_G')
    assert not guide.hide_get() and render.hide_get(), leave
    select(guide); select(other)
    assert not guide.hide_get(), leave
    if leave=='other_pass': debug.apply_debug_view(context,'ATTRIBUTE_FACTOR')
    elif leave=='save': debug._save_pre_remove_debug_materials(None)
    elif leave=='export': debug.prepare_for_export()
    else: addon_utils.disable('debug_render_pass_cycle',default_set=False)
    assert not debug.weight_visibility.active()
    assert guide.hide_get() and guide.display_type=='BOUNDS', leave
    assert not guide.show_wire and not guide.show_all_edges, leave
    select(guide); assert not guide.hide_get() and guide.display_type=='WIRE', leave
    select(other); assert guide.hide_get(), leave

assert not guide.wbsv_excluded and not render.wbsv_excluded
print('DEBUG_WEIGHT_SELECTION_VISIBILITY_OK')
