"""Matched stills in disposable Blender; never saves. Args after --: demo | wall."""
from pathlib import Path
import sys, json, time
import bpy, addon_utils
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons'))
sys.path.insert(0, 'C:/UnrealProjects/MyProject2/Docs/Tools/Media')
from review_storage import output_path
addon_utils.enable('ivy_generator', default_set=False)
import ivy_generator as ivy

mode = sys.argv[sys.argv.index('--') + 1]
FOLDER = 'Blender/IvyGenerator20261108/'
PREFIX = 'v%d%d%d_' % ivy.bl_info['version']
if bpy.context.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
scene = bpy.context.scene


def look(obj, at): obj.rotation_euler = (Vector(at) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def setup(location, at, scale, lights):
    scene.render.engine = 'CYCLES'; scene.cycles.samples = 24; scene.cycles.use_denoising = True; scene.cycles.device = 'CPU'
    scene.render.resolution_x = scene.render.resolution_y = 1200; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGB'; scene.render.film_transparent = False
    if scene.world is None: scene.world = bpy.data.worlds.new('QA')
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (.5, .55, .65, 1); bg.inputs['Strength'].default_value = .35
    scene.view_settings.view_transform = 'AgX'
    data = bpy.data.cameras.new('QA Camera'); cam = bpy.data.objects.new('QA Camera', data); scene.collection.objects.link(cam); scene.camera = cam
    cam.location = location; look(cam, at); data.type = 'ORTHO'; data.ortho_scale = scale
    for name, where, power, size in lights:
        d = bpy.data.lights.new(name, 'AREA'); d.energy = power; d.shape = 'DISK'; d.size = size
        o = bpy.data.objects.new(name, d); scene.collection.objects.link(o); o.location = where; look(o, at)


records = {}


def shoot(name, shown, every):
    for o in every: o.hide_render = o is not shown
    path = output_path(FOLDER + name + '.png')
    if name == 'reference_demo' and path.exists(): return  # the reference itself never changes
    scene.render.filepath = str(path); t = time.perf_counter(); bpy.ops.render.render(write_still=True)
    records[name] = {'path': str(path), 'seconds': round(time.perf_counter() - t, 2)}


if mode == 'demo':
    ref = bpy.data.objects['Ivy']
    new = bpy.data.objects.new('New', ref.data.copy()); scene.collection.objects.link(new); new.matrix_world = ref.matrix_world
    mod = new.modifiers.new('Ivy Generator', 'NODES'); mod.node_group = ivy.build_generator(bpy.data.collections['Ivy_Instance'])
    ivy.set_input(mod, 'Target', bpy.data.collections['Target'])
    setup((1, -32, 5), (1, -5, 5), 16, [('Key', (-14, -24, 20), 9000, 12), ('Fill', (16, -20, 10), 3400, 10)])
    shoot('reference_demo', ref, [ref, new])
    shoot(PREFIX + 'rebuilt_demo', new, [ref, new])
else:
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, .1, 2.5)); wall = bpy.context.object; wall.name = 'QA Wall'; wall.scale = (6, .2, 5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mat = bpy.data.materials.new('QA • Limestone'); mat.use_nodes = True
    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.33, .30, .25, 1); wall.data.materials.append(mat)
    scene.cursor.location = (0, 0, 2.2)
    default = ivy.create_ivy(bpy.context, [wall])
    tuned = ivy.create_ivy(bpy.context, [wall]); m = ivy.ivy_modifier(tuned)
    ivy.set_input(m, 'Radius', 2.2); ivy.set_input(m, 'Height', 4.4); ivy.set_input(m, 'Loops', 26)
    records['default_instances'] = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance and i.parent and i.parent.original == default)
    setup((0, -10, 2.2), (0, 0, 2.2), 5.2, [('Key', (-3, -4, 6), 950, 4), ('Fill', (4, -3, 4), 350, 3)])
    shoot(PREFIX + 'wall_default', default, [default, tuned])
    shoot(PREFIX + 'wall_tuned', tuned, [default, tuned])

record_path = output_path(FOLDER + 'render_v030.json')
previous = json.loads(record_path.read_text('utf8')) if record_path.exists() else {}
previous.update(records); record_path.write_text(json.dumps(previous, indent=2), encoding='utf8')
print('IVY_RENDER_PASS', json.dumps(records), flush=True)
