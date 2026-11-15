# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    'name': 'Ivy Generator — Geometry Nodes', 'author': 'PARK',
    'version': (0, 3, 1), 'blender': (5, 1, 0),
    'location': 'View3D > Sidebar > Create > Ivy Generator',
    'description': 'Spiral projected on target surfaces, covered with instanced ivy sprigs',
    'category': 'Add Curve',
}
from pathlib import Path
import bpy
from bpy.props import StringProperty
from mathutils import Vector

VERSION = 4
COMPATIBLE = {3, 4}  # 0.3.0 groups share the same inputs
LIBRARY_NAME = 'Ivy_Generator_Blender_3.0_NodeTree.blend'
LEAF_COLLECTION = 'Ivy_Instance'
REFERENCE_HEIGHT = 13.87  # target height in the reference demo; its defaults are sized for it
CONTROLS = ['Radius', 'Height', 'Loops', 'Band Width', 'Leaf Density', 'Leaf Size', 'Seed']
LABELS = ['퍼짐 반경', '높이', '감김 수', '띠 폭', '잎 밀도', '잎 크기', '랜덤 시드']


class Graph:
    def __init__(self, name):
        self.tree = bpy.data.node_groups.new(name, 'GeometryNodeTree')
        self.i = 0

    def socket(self, name, typ, default=None, low=None, high=None, direction='INPUT', description=''):
        s = self.tree.interface.new_socket(name=name, in_out=direction, socket_type=typ)
        if default is not None: s.default_value = default
        if low is not None: s.min_value = low
        if high is not None: s.max_value = high
        s.description = description
        return s

    def node(self, typ, label='', **props):
        n = self.tree.nodes.new(typ)
        for key, value in props.items(): setattr(n, key, value)
        n.label = label
        n.location = ((self.i % 8) * 220, -(self.i // 8) * 260)
        self.i += 1
        return n

    def put(self, n, key, value):
        s = n.inputs[key]
        if isinstance(value, bpy.types.NodeSocket): self.tree.links.new(value, s)
        else: s.default_value = value
        return n

    def math(self, op, a, b):
        n = self.node('ShaderNodeMath', operation=op)
        self.put(n, 0, a); self.put(n, 1, b)
        return n.outputs[0]

    def vec(self, op, a, b):
        n = self.node('ShaderNodeVectorMath', operation=op)
        self.put(n, 0, a); self.put(n, 1, b)
        return n.outputs['Vector']

    def combine(self, x=0., y=0., z=0.):
        n = self.node('ShaderNodeCombineXYZ')
        for k, v in zip('XYZ', (x, y, z)): self.put(n, k, v)
        return n.outputs[0]


def build_generator(leaves):
    existing = next((n for n in bpy.data.node_groups if n.get('ivy_generator_version') == VERSION), None)
    if existing: return existing
    g = Graph('Ivy Generator'); g.tree.is_modifier = True
    g.socket('Geometry', 'NodeSocketGeometry', direction='OUTPUT')
    g.socket('Emitters', 'NodeSocketGeometry', description='Each vertex starts one spiral')
    g.socket('Target', 'NodeSocketCollection', description='Surfaces the ivy covers')
    g.socket('Radius', 'NodeSocketFloat', 2., .001, 1000., description='Spiral radius around each start point')
    g.socket('Height', 'NodeSocketFloat', 3., 0., 1000., description='Spiral height, centered on each start point')
    g.socket('Loops', 'NodeSocketInt', 10, 1, 200, description='Spiral turns')
    g.socket('Band Width', 'NodeSocketFloat', .2, .001, 100., description='Width of the band the sprigs are scattered on')
    g.socket('Leaf Density', 'NodeSocketFloat', 1., 0., 1., description='Coverage; 1 is the densest spacing')
    g.socket('Leaf Size', 'NodeSocketFloat', 1., .001, 100., description='Sprig scale')
    g.socket('Seed', 'NodeSocketInt', 0, 0, 10000, description='A different repeatable sprig arrangement')
    a = g.node('NodeGroupInput').outputs
    size = g.math('MAXIMUM', a['Leaf Size'], .0001)

    # One spiral centered on every emitter vertex.
    spiral = g.node('GeometryNodeCurveSpiral')
    g.put(spiral, 'Resolution', 100); g.put(spiral, 'Rotations', a['Loops'])
    g.put(spiral, 'Start Radius', a['Radius']); g.put(spiral, 'End Radius', a['Radius']); g.put(spiral, 'Height', a['Height'])
    center = g.node('GeometryNodeTransform'); g.put(center, 'Geometry', spiral.outputs[0])
    g.put(center, 'Translation', g.combine(z=g.math('MULTIPLY', a['Height'], -.5)))
    spirals = g.node('GeometryNodeInstanceOnPoints')
    g.put(spirals, 'Points', a['Emitters']); g.put(spirals, 'Instance', center.outputs[0])
    curves = g.node('GeometryNodeRealizeInstances'); g.put(curves, 'Geometry', spirals.outputs[0])

    # Project the spiral onto the targets, then widen it into a band lying on them.
    info = g.node('GeometryNodeCollectionInfo', transform_space='RELATIVE')
    g.put(info, 'Collection', a['Target'])
    target = g.node('GeometryNodeRealizeInstances'); g.put(target, 'Geometry', info.outputs[0])
    prox = g.node('GeometryNodeProximity', target_element='FACES'); g.put(prox, 0, target.outputs[0])
    fine = g.node('GeometryNodeSubdivideCurve'); g.put(fine, 'Curve', curves.outputs[0]); g.put(fine, 'Cuts', 2)
    onto = g.node('GeometryNodeSetPosition'); g.put(onto, 'Geometry', fine.outputs[0]); g.put(onto, 'Position', prox.outputs['Position'])
    finer = g.node('GeometryNodeSubdivideCurve'); g.put(finer, 'Curve', onto.outputs[0]); g.put(finer, 'Cuts', 2)
    surface_normal = g.node('GeometryNodeSampleNearestSurface', data_type='FLOAT_VECTOR')
    g.put(surface_normal, 'Mesh', target.outputs[0]); g.put(surface_normal, 'Value', g.node('GeometryNodeInputNormal').outputs['Normal'])
    surface_normal = surface_normal.outputs['Value']
    # The reference keeps the curve's own twist, so on flat walls the band turns edge-on and
    # collapses when laid down, leaving empty stripes. Keep the band's width along the surface.
    across = g.vec('CROSS_PRODUCT', g.node('GeometryNodeInputTangent').outputs[0], surface_normal)
    frame = g.node('GeometryNodeSetCurveNormal')
    if 'Mode' in frame.inputs: frame.inputs['Mode'].default_value = 'Free'
    else: frame.mode = 'FREE'
    g.put(frame, 'Curve', finer.outputs[0]); g.put(frame, 'Normal', across)
    half = g.math('MULTIPLY', a['Band Width'], .5)
    end = g.combine(a['Band Width'], half)
    profile = g.node('GeometryNodeCurvePrimitiveLine', mode='POINTS')
    g.put(profile, 'Start', g.vec('MULTIPLY', end, (-1., -1., -1.))); g.put(profile, 'End', end)
    band = g.node('GeometryNodeCurveToMesh'); g.put(band, 'Curve', frame.outputs[0]); g.put(band, 'Profile Curve', profile.outputs[0])
    lay = g.node('GeometryNodeSetPosition'); g.put(lay, 'Geometry', band.outputs[0]); g.put(lay, 'Position', prox.outputs['Position'])

    # Scatter sprigs on the band. Spacing and offset follow Leaf Size so coverage survives resizing.
    # Lift and orientation use the target's own normal; the band's normal is unreliable where the
    # projected spiral folds back on itself.
    scatter = g.node('GeometryNodeDistributePointsOnFaces', distribute_method='POISSON', use_legacy_normal=True)
    density = g.math('DIVIDE', g.math('MULTIPLY', a['Leaf Density'], 100.), g.math('MULTIPLY', size, size))
    g.put(scatter, 'Mesh', lay.outputs[0]); g.put(scatter, 'Distance Min', g.math('MULTIPLY', size, .1))
    g.put(scatter, 'Density Max', density); g.put(scatter, 'Seed', a['Seed'])
    lift = g.math('MULTIPLY', size, .06)
    out_along = g.vec('MULTIPLY', surface_normal, g.combine(lift, lift, lift))
    position = g.node('GeometryNodeInputPosition').outputs[0]
    move = g.node('GeometryNodeSetPosition'); g.put(move, 'Geometry', scatter.outputs['Points']); g.put(move, 'Position', g.vec('ADD', position, out_along))
    spin = g.node('FunctionNodeRandomValue', data_type='FLOAT_VECTOR')
    g.put(spin, 'Min', (0., -100., 0.)); g.put(spin, 'Max', (0., 100., 0.)); g.put(spin, 'Seed', g.math('ADD', a['Seed'], 1.))
    align = g.node('FunctionNodeAlignEulerToVector', axis='Z', pivot_axis='AUTO')
    g.put(align, 'Rotation', g.vec('ADD', scatter.outputs['Rotation'], spin.outputs['Value'])); g.put(align, 'Vector', surface_normal)
    sprigs = g.node('GeometryNodeCollectionInfo', transform_space='RELATIVE')
    g.put(sprigs, 'Collection', leaves); g.put(sprigs, 'Separate Children', True); g.put(sprigs, 'Reset Children', True)
    ivy = g.node('GeometryNodeInstanceOnPoints')
    g.put(ivy, 'Points', move.outputs[0]); g.put(ivy, 'Instance', sprigs.outputs[0]); g.put(ivy, 'Pick Instance', True)
    g.put(ivy, 'Rotation', align.outputs['Rotation']); g.put(ivy, 'Scale', g.combine(a['Leaf Size'], a['Leaf Size'], a['Leaf Size']))
    out = g.node('NodeGroupOutput'); g.put(out, 'Geometry', ivy.outputs[0])
    g.tree['ivy_generator_version'] = VERSION
    g.tree.description = 'Spirals projected on the target surfaces, covered with instanced ivy sprigs.'
    return g.tree


def library_path():
    addon = bpy.context.preferences.addons.get(__package__)
    custom = addon.preferences.library if addon else ''
    candidates = [Path(bpy.path.abspath(custom))] if custom else []
    candidates.append(Path.home() / 'Downloads' / LIBRARY_NAME)
    return next((p for p in candidates if p.is_file()), None)


def load_leaves():
    existing = next((c for c in bpy.data.collections if c.get('ivy_leaf_source')), None)
    if existing: return existing
    path = library_path()
    if path is None:
        raise FileNotFoundError(f'{LIBRARY_NAME}를 찾지 못했습니다. 애드온 환경설정에서 위치를 지정하세요.')
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if LEAF_COLLECTION not in src.collections:
            raise ValueError(f'{path.name}에 {LEAF_COLLECTION} 컬렉션이 없습니다.')
        dst.collections = [LEAF_COLLECTION]
    leaves = dst.collections[0]
    leaves['ivy_leaf_source'] = True
    return leaves


def ivy_modifier(obj):
    if not obj: return None
    return next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group and m.node_group.get('ivy_generator_version') in COMPATIBLE), None)


def input_access(mod, identifier):
    # Blender 5.2 moved modifier inputs from ID properties to typed RNA sockets.
    if hasattr(mod, 'properties') and mod.properties is not None:
        return getattr(mod.properties.inputs, identifier), 'value'
    return mod, '["' + identifier + '"]'


def sockets(tree):
    return {s.name: s for s in tree.interface.items_tree if s.item_type == 'SOCKET' and s.in_out == 'INPUT'}


def set_input(mod, name, value):
    identifier = sockets(mod.node_group)[name].identifier
    data, prop = input_access(mod, identifier)
    if prop == 'value': data.value = value
    else: mod[identifier] = value


def get_input(mod, name):
    identifier = sockets(mod.node_group)[name].identifier
    data, prop = input_access(mod, identifier)
    return data.value if prop == 'value' else mod[identifier]


def target_meshes(context, exclude=None):
    return [o for o in context.selected_objects if o.type == 'MESH' and o != exclude and not ivy_modifier(o)]


def set_targets(mod, meshes):
    current = get_input(mod, 'Target')
    if current is not None and current.get('ivy_target'):
        for o in list(current.objects): current.objects.unlink(o)
        target = current
    else:
        target = bpy.data.collections.new('Ivy Target'); target['ivy_target'] = True
        set_input(mod, 'Target', target)
    for o in meshes: target.objects.link(o)


def scene_scale(meshes):
    # The reference's defaults fit a ~14 unit target; size them to the actual one.
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    span = max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3))
    return max(span, .001) / REFERENCE_HEIGHT


def create_ivy(context, meshes):
    if not meshes: raise ValueError('대상 메시를 선택하세요.')
    tree = build_generator(load_leaves())
    data = bpy.data.meshes.new('Ivy'); data.vertices.add(1)
    obj = bpy.data.objects.new('Ivy', data)
    context.collection.objects.link(obj)
    obj.location = context.scene.cursor.location
    mod = obj.modifiers.new('Ivy Generator', 'NODES'); mod.node_group = tree
    mod.show_in_editmode = True
    set_targets(mod, meshes)
    k = scene_scale(meshes)
    for name, value in (('Radius', 2. * k), ('Height', 3. * k), ('Band Width', .2 * k), ('Leaf Size', k)):
        set_input(mod, name, value)
    obj.update_tag(); context.view_layer.update()
    return obj


def add_emitter(context, obj):
    data = obj.data
    data.vertices.add(1)
    data.vertices[-1].co = obj.matrix_world.inverted() @ context.scene.cursor.location
    data.update(); obj.update_tag(); context.view_layer.update()


class IVY_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    library: StringProperty(name='잎가지 원본 .blend', subtype='FILE_PATH',
        description=f'{LIBRARY_NAME}. 원본은 변경하지 않고 잎가지 컬렉션만 읽습니다.')
    def draw(self, context):
        self.layout.prop(self, 'library')
        self.layout.label(text='다운로드 폴더의 원본은 자동으로 찾습니다.')


class IVY_OT_add(bpy.types.Operator):
    bl_idname = 'object.ivy_generator_add'; bl_label = '아이비 생성'; bl_options = {'REGISTER', 'UNDO'}
    bl_description = '선택한 메시를 대상으로 3D 커서 위치에 아이비를 생성'
    @classmethod
    def poll(cls, context):
        o = context.active_object
        return context.mode == 'OBJECT' and o is not None and o.type == 'MESH' and not ivy_modifier(o)
    def execute(self, context):
        try: obj = create_ivy(context, target_meshes(context) or [context.active_object])
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        for o in context.selected_objects: o.select_set(False)
        obj.select_set(True); context.view_layer.objects.active = obj
        return {'FINISHED'}


class IVY_OT_add_emitter(bpy.types.Operator):
    bl_idname = 'object.ivy_generator_add_emitter'; bl_label = '3D 커서에 시작점 추가'; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ivy_modifier(context.active_object) is not None
    def execute(self, context):
        add_emitter(context, context.active_object)
        return {'FINISHED'}


class IVY_OT_set_targets(bpy.types.Operator):
    bl_idname = 'object.ivy_generator_set_targets'; bl_label = '선택 메시로 대상 교체'; bl_options = {'REGISTER', 'UNDO'}
    bl_description = '아이비와 함께 선택한 다른 메시들을 새 대상으로 지정'
    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ivy_modifier(context.active_object) is not None and bool(target_meshes(context, context.active_object))
    def execute(self, context):
        obj = context.active_object
        set_targets(ivy_modifier(obj), target_meshes(context, obj))
        obj.update_tag(); context.view_layer.update()
        return {'FINISHED'}


class IVY_PT_panel(bpy.types.Panel):
    bl_label = 'Ivy Generator'; bl_idname = 'IVY_PT_generator'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Create'
    def draw(self, context):
        l = self.layout; m = ivy_modifier(context.active_object)
        if m is None:
            l.label(text='1. 감쌀 메시 선택')
            l.label(text='2. 시작 위치에 3D 커서 배치')
            l.operator('object.ivy_generator_add', icon='CURVE_BEZCURVE')
            return
        s = sockets(m.node_group)
        l.use_property_split = True; l.use_property_decorate = False
        data, prop = input_access(m, s['Target'].identifier)
        l.prop(data, prop, text='대상')
        for name, label in zip(CONTROLS, LABELS):
            data, prop = input_access(m, s[name].identifier)
            l.prop(data, prop, text=label)
        l.operator('object.ivy_generator_add_emitter', icon='CURSOR')
        l.operator('object.ivy_generator_set_targets', icon='OBJECT_DATA')


CLASSES = (IVY_Preferences, IVY_OT_add, IVY_OT_add_emitter, IVY_OT_set_targets, IVY_PT_panel)
def register():
    for c in CLASSES: bpy.utils.register_class(c)
def unregister():
    for c in reversed(CLASSES): bpy.utils.unregister_class(c)
