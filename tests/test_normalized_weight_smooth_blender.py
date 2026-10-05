"""Run with Blender --factory-startup --background --python <this file>."""

import importlib
import json
import math
from pathlib import Path
import sys
import unittest

import addon_utils
import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'addons'))
from normalized_weight_smooth.core import WeightError, smooth_weights


class CoreTests(unittest.TestCase):
    def test_simultaneous_average_and_no_group_order_bias(self):
        rows = {0: {0: 1.0}, 1: {1: 1.0}, 2: {2: 1.0}}
        result, _ = smooth_weights(rows, {0: [1], 1: [0, 2], 2: [1]}, [0, 1, 2], {0, 1, 2}, set(), 0.5, 1)
        self.assertEqual(result[1], {0: 0.25, 1: 0.5, 2: 0.25})
        self.assertEqual(result[0], {0: 0.5, 1: 0.5})
        reversed_rows = {v: dict(reversed(list(row.items()))) for v, row in reversed(list(rows.items()))}
        other, _ = smooth_weights(reversed_rows, {0: [1], 1: [0, 2], 2: [1]}, [2, 1, 0], {2, 1, 0}, set(), 0.5, 1)
        self.assertEqual(result, other)

    def test_selection_and_outside_boundary(self):
        rows = {0: {0: 1.0}, 1: {1: 1.0}}
        result, _ = smooth_weights(rows, {0: [1]}, [0], {0, 1}, set(), 0.5, 3)
        self.assertEqual(result, {0: {0: 1.0}})
        result, _ = smooth_weights(rows, {0: [1]}, [0], {0, 1}, set(), 0.5, 3, True)
        self.assertEqual(result[0], {0: 0.125, 1: 0.875})
        self.assertNotIn(1, result)
        self.assertEqual(rows[0], {0: 1.0})

    def test_locks_and_mask_domain(self):
        rows = {0: {0: 0.3, 1: 0.7, 3: 0.91}, 1: {0: 0.2, 2: 0.8, 3: 0.13}}
        output, _ = smooth_weights(rows, {0: [1], 1: [0]}, [0, 1], {0, 1, 2}, {0}, 0.5, 12)
        for v in output:
            self.assertEqual(output[v][0], rows[v][0])
            self.assertEqual(output[v][3], rows[v][3])
            self.assertAlmostEqual(sum(w for g, w in output[v].items() if g != 3), 1.0)

    def test_impossible_lock_cancels_without_mutation(self):
        rows = {0: {0: 0.7, 1: 0.7}, 1: {2: 1.0}}
        with self.assertRaises(WeightError):
            smooth_weights(rows, {0: [1], 1: [0]}, [1, 0], {0, 1, 2}, {0, 1})
        self.assertEqual(rows[0], {0: 0.7, 1: 0.7})
        with self.assertRaises(WeightError):
            smooth_weights({0: {0: 0.3}}, {}, [0], {0, 1}, {0})

    def test_empty_vertices_and_disconnected_islands(self):
        rows = {0: {}, 1: {1: 1.0}, 2: {2: 1.0}, 3: {}}
        output, skipped = smooth_weights(rows, {0: [1], 1: [0], 2: [], 3: []}, [0, 1, 2, 3], {1, 2}, set(), 0.5, 5)
        self.assertEqual(output[0], {1: 1.0})
        self.assertEqual(output[2], {2: 1.0})
        self.assertNotIn(3, output)
        self.assertEqual(skipped, 1)

    def test_many_influences_remain_normalized(self):
        rows = {v: {g: (v + g + 1) / 10000 for g in range(50)} for v in range(20)}
        neighbors = {v: [n for n in (v - 1, v + 1) if 0 <= n < 20] for v in rows}
        output, _ = smooth_weights(rows, neighbors, rows, range(50), set(), 0.27, 40)
        self.assertTrue(all(len(row) == 50 for row in output.values()))
        self.assertTrue(all(abs(math.fsum(row.values()) - 1.0) < 1e-12 for row in output.values()))

    def test_invalid_values(self):
        for value in (float('nan'), float('inf'), -0.1):
            with self.assertRaises(WeightError):
                smooth_weights({0: {0: value}}, {}, [0], {0}, set())


class BlenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pref_path = Path(bpy.utils.user_resource('CONFIG')) / 'userpref.blend'
        cls.pref_before = cls.pref_path.read_bytes() if cls.pref_path.exists() else None
        cls.module = addon_utils.enable('normalized_weight_smooth', default_set=False)
        assert cls.module is not None

    @classmethod
    def tearDownClass(cls):
        addon_utils.disable('normalized_weight_smooth', default_set=False)
        after = cls.pref_path.read_bytes() if cls.pref_path.exists() else None
        assert after == cls.pref_before, 'Registration test wrote user preferences'

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        self.mesh = bpy.data.meshes.new('NWS_Test_Mesh')
        self.mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (10, 0, 0)], [(0, 1), (1, 2)], [])
        self.obj = bpy.data.objects.new('NWS_Test', self.mesh)
        bpy.context.collection.objects.link(self.obj)
        self.obj.select_set(True)
        bpy.context.view_layer.objects.active = self.obj
        for name in ('Bone_A', 'Bone_B', 'Bone_C', 'Cloth_Pin'):
            self.obj.vertex_groups.new(name=name)
        for v, g in ((0, 0), (1, 1), (2, 2), (3, 0)):
            self.obj.vertex_groups[g].add([v], 1.0, 'REPLACE')
        self.obj.vertex_groups[3].add([0, 1, 2, 3], 0.42, 'REPLACE')
        self.obj.vertex_groups.active_index = 2
        for edge in self.mesh.edges:
            edge.select = False
        for v in self.mesh.vertices:
            v.select = v.index in (0, 1)
        self.mesh.update()
        self.baseline = self.read_object()

    def tearDown(self):
        if self.obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(self.obj, do_unlink=True)
        if self.mesh.users == 0:
            bpy.data.meshes.remove(self.mesh)
        for obj in list(bpy.data.objects):
            if obj.name.startswith('NWS_Arm'):
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.armatures.remove(data)

    def read_object(self):
        return {v.index: {g.group: g.weight for g in v.groups} for v in self.mesh.vertices}

    def edit_rows(self):
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.verts.ensure_lookup_table()
        deform = bm.verts.layers.deform.active
        return {v.index: dict(v[deform]) for v in bm.verts}

    def armature(self):
        data = bpy.data.armatures.new('NWS_Arm')
        arm = bpy.data.objects.new('NWS_Arm', data)
        bpy.context.collection.objects.link(arm)
        self.obj.select_set(False)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        for name in ('Bone_A', 'Bone_B', 'Bone_C'):
            b = data.edit_bones.new(name)
            b.head = (0, 0, 0)
            b.tail = (0, 0, 1)
        bpy.ops.object.mode_set(mode='OBJECT')
        arm.select_set(False)
        self.obj.select_set(True)
        bpy.context.view_layer.objects.active = self.obj
        mod = self.obj.modifiers.new('NWS_Arm', 'ARMATURE')
        mod.object = arm

    def test_edit_preserves_selection_active_group_shape_keys_and_outside(self):
        self.armature()
        self.obj.shape_key_add(name='Basis')
        key = self.obj.shape_key_add(name='Pose')
        key.data[1].co.z = 0.5
        shape_before = [tuple(v.co) for v in key.data]
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.verts.ensure_lookup_table()
        for edge in bm.edges:
            edge.select_set(False)
        for v in bm.verts:
            v.select_set(v.index in (0, 1))
        bmesh.update_edit_mesh(self.mesh, loop_triangles=False, destructive=False)
        selection = [(v.select, v.hide) for v in bm.verts]
        coords = [tuple(v.co) for v in bm.verts]
        self.assertEqual(bpy.ops.mesh.normalized_weight_smooth(factor=0.5, iterations=1), {'FINISHED'})
        output = self.edit_rows()
        self.assertAlmostEqual(output[0][0], 0.5)
        self.assertAlmostEqual(output[0][1], 0.5)
        for v in (0, 1):
            self.assertAlmostEqual(sum(w for g, w in output[v].items() if g != 3), 1.0, places=6)
            self.assertEqual(output[v][3], self.baseline[v][3])
        for v in (2, 3):
            self.assertEqual(output[v], self.baseline[v])
        self.assertEqual(self.obj.mode, 'EDIT')
        self.assertEqual(self.obj.vertex_groups.active_index, 2)
        self.assertEqual([(v.select, v.hide) for v in bm.verts], selection)
        self.assertEqual([tuple(v.co) for v in bm.verts], coords)
        self.assertEqual([tuple(v.co) for v in key.data], shape_before)

    def test_weight_paint_mask_and_shape_keys(self):
        self.obj.shape_key_add(name='Basis')
        key = self.obj.shape_key_add(name='Pose')
        key.data[0].co.z = 0.8
        shape_before = [tuple(v.co) for v in key.data]
        self.mesh.use_paint_mask_vertex = True
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        for v in self.mesh.vertices:
            v.select = v.index in (0, 1)
        self.assertEqual(bpy.ops.mesh.normalized_weight_smooth(iterations=3, group_scope='ALL'), {'FINISHED'})
        output = self.read_object()
        for v in (0, 1):
            self.assertAlmostEqual(sum(output[v].values()), 1.0, places=6)
        self.assertEqual(output[2], self.baseline[2])
        self.assertEqual(self.obj.mode, 'WEIGHT_PAINT')
        self.assertEqual([tuple(v.co) for v in key.data], shape_before)

    def test_hidden_and_outside_weights_unchanged(self):
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.verts.ensure_lookup_table()
        bm.verts[2].hide_set(True)
        self.assertEqual(bpy.ops.mesh.normalized_weight_smooth(use_outside=True, group_scope='ALL'), {'FINISHED'})
        rows = self.edit_rows()
        self.assertEqual(rows[2], self.baseline[2])
        self.assertEqual(rows[3], self.baseline[3])
        self.assertTrue(bm.verts[2].hide)

    def test_shared_mesh_rejected(self):
        other = bpy.data.objects.new('NWS_Shared', self.mesh)
        try:
            bpy.context.collection.objects.link(other)
            bpy.ops.object.mode_set(mode='EDIT')
            self.assertFalse(bpy.ops.mesh.normalized_weight_smooth.poll())
        finally:
            bpy.data.objects.remove(other, do_unlink=True)

    def test_lock_error_is_atomic(self):
        self.obj.vertex_groups[0].lock_weight = True
        self.obj.vertex_groups[3].lock_weight = True
        bpy.ops.object.mode_set(mode='EDIT')
        before = self.edit_rows()
        try:
            result = bpy.ops.mesh.normalized_weight_smooth(group_scope='ALL')
            self.assertEqual(result, {'CANCELLED'})
        except RuntimeError as exc:
            self.assertIn('locked weights exceed 1', str(exc))
        self.assertEqual(self.edit_rows(), before)

    def test_registration_reload_and_shortcuts(self):
        module = self.module
        keys = module._keymaps
        self.assertEqual(len(keys), 2)
        for km, k in keys:
            self.assertEqual(k.type, 'E')
            self.assertTrue(k.ctrl and k.shift)
            self.assertFalse(k.alt)
        module.unregister()
        importlib.reload(module)
        module.register()
        self.assertEqual(len(module._keymaps), 2)

    def test_handy_panel_attachment(self):
        icons = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys()
        for name in ('MOD_VERTEX_WEIGHT', 'MOD_SMOOTH'):
            self.assertIn(name, icons)
        class HANDY_WEIGHT_EDIT_PT_main(bpy.types.Panel):
            bl_idname = 'HANDY_WEIGHT_EDIT_PT_main'
            bl_label = 'Test Handy'
            bl_space_type = 'VIEW_3D'
            bl_region_type = 'UI'
            bl_category = 'Test'
            def draw(self, context):
                pass
        bpy.utils.register_class(HANDY_WEIGHT_EDIT_PT_main)
        try:
            self.module._attach_handy()
            self.assertIs(self.module._handy_panel, HANDY_WEIGHT_EDIT_PT_main)
            self.assertIn(self.module._draw_handy, HANDY_WEIGHT_EDIT_PT_main.draw._draw_funcs)
        finally:
            if self.module._handy_panel:
                self.module._handy_panel.remove(self.module._draw_handy)
                self.module._handy_panel = None
            bpy.utils.unregister_class(HANDY_WEIGHT_EDIT_PT_main)


if __name__ == '__main__':
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests),
                               unittest.defaultTestLoader.loadTestsFromTestCase(BlenderTests)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('NWS_RESULT=' + json.dumps({'tests': result.testsRun,
                                     'failures': len(result.failures), 'errors': len(result.errors)}))
    if not result.wasSuccessful():
        sys.exit(1)
