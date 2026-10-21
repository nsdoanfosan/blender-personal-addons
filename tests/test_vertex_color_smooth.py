"""Run with Blender --factory-startup --background --python this_file.py.

Creates only disposable meshes. Never saves preferences or a .blend.
"""
import sys
from pathlib import Path
import unittest
import numpy as np
import bpy
import bmesh
import addon_utils
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons'))
import vertex_color_smooth as vcs
from vertex_color_smooth.core import smooth_colors, ColorSmoothError, edit_colors, isolate_rgb, VIEW_CHANNELS


class CoreTests(unittest.TestCase):
    def test_primary_color_preview_and_cycle_order(self):
        values = np.array([[.2, .4, .6, .3], [1., 0., .5, .8]])
        self.assertEqual(VIEW_CHANNELS, ('RGB', 'R', 'G', 'B'))
        for channel, index in [('R', 0), ('G', 1), ('B', 2)]:
            display = isolate_rgb(values, channel)
            np.testing.assert_array_equal(display[:, index], values[:, index])
            np.testing.assert_array_equal(display[:, [i for i in range(3) if i != index]], 0)
            np.testing.assert_array_equal(display[:, 3], 1)
        np.testing.assert_array_equal(isolate_rgb(values, 'RGB')[:, :3], values[:, :3])

    def test_handy_fill_gradient_copy_and_channel_preservation(self):
        values = np.array([[.2, .3, .4, .5], [.7, .8, .9, .6], [1., .1, .2, .3]])
        for action, expected in [('FILL_DELTA', [.3, .3]), ('GRADIENT', [.3, .8]), ('COPY', [.7, .7])]:
            output = edit_colors(values, [0, 1, 2], [True, True, False], channels=(0,),
                                 action=action, delta=.1, source_vertex=1 if action == 'COPY' else None)
            np.testing.assert_allclose(output[:2, 0], expected)
            np.testing.assert_array_equal(output[:, 1:], values[:, 1:])
            np.testing.assert_array_equal(output[2], values[2])
        output = edit_colors(values, [0, 1, 2], [True]*3, channels=(2,), action='SET', value=.25)
        np.testing.assert_allclose(output[:, 2], .25)
        np.testing.assert_array_equal(output[:, [0, 1, 3]], values[:, [0, 1, 3]])

    def smooth(self, **kwargs):
        colors = np.array([[0, .2, .6, .3], [1, .8, .4, .7], [0, .2, .6, .3]])
        return smooth_colors(colors, [0, 1, 2], [(0, 1), (1, 2)],
                             [False, True, False], [True] * 3, **kwargs)

    def test_selected_neighbors_and_alpha(self):
        output = self.smooth()
        np.testing.assert_allclose(output[1], [.5, .5, .5, .7])
        np.testing.assert_array_equal(output[[0, 2]], [[0, .2, .6, .3]] * 2)

    def test_outside_option_and_iterations(self):
        np.testing.assert_allclose(self.smooth(use_outside=False)[1], [1, .8, .4, .7])
        self.assertAlmostEqual(self.smooth(iterations=2)[1, 0], .25)

    def test_individual_channel_and_no_normalization(self):
        output = self.smooth(channels=(0,))
        np.testing.assert_allclose(output[1], [.5, .8, .4, .7])
        self.assertNotAlmostEqual(output[1, :3].sum(), 1.0)

    def test_simultaneous_order_independent(self):
        values = [[0] * 4, [1] * 4, [0] * 4]
        a = smooth_colors(values, [0, 1, 2], [(0, 1), (1, 2)], [True] * 3, [True] * 3)
        b = smooth_colors(values, [0, 1, 2], [(2, 1), (1, 0), (0, 1)], [True] * 3, [True] * 3)
        np.testing.assert_array_equal(a, b)
        np.testing.assert_allclose(a[:, 0], [.5, .5, .5])

    def test_hidden_neighbors_excluded(self):
        output = smooth_colors([[0]*4, [1]*4, [.5]*4], [0, 1, 2], [(0, 1), (1, 2)],
                               [False, True, False], [False, True, True])
        self.assertAlmostEqual(output[1, 0], .75)

    def test_disconnected_and_hdr(self):
        values = [[2., -1., .2, 1.], [0., 1., .2, 1.], [100.] * 4]
        output = smooth_colors(values, [0, 1, 2], [(0, 1)], [True] * 3, [True] * 3)
        np.testing.assert_allclose(output[0], [1., 0., .2, 1.])
        np.testing.assert_array_equal(output[2], values[2])

    def test_invalid_rejected_without_modification(self):
        values = np.array([[float('nan')]*4, [1.]*4])
        with self.assertRaises(ColorSmoothError):
            smooth_colors(values, [0, 1], [(0, 1)], [True]*2, [True]*2)
        self.assertTrue(np.isnan(values[0, 0]))


class BlenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert addon_utils.enable('vertex_color_smooth', default_set=False) is not None

    @classmethod
    def tearDownClass(cls):
        addon_utils.disable('vertex_color_smooth', default_set=False)

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        mesh = bpy.data.meshes.new('VCS_QA_Mesh')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
                         [], [(0, 1, 4, 3), (1, 2, 5, 4)])
        obj = bpy.data.objects.new('VCS_QA_Object', mesh)
        bpy.context.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.obj, self.mesh = obj, mesh
        self.groups = obj.vertex_groups.new(name='KeepWeights')
        self.groups.add([1, 4], .42, 'REPLACE')
        obj.shape_key_add(name='Basis')
        obj.shape_key_add(name='KeepShape').data[1].co.z = .123

    def tearDown(self):
        if self.obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(self.obj, do_unlink=True)
        bpy.data.meshes.remove(self.mesh)

    def attribute(self, domain, dtype):
        attr = self.mesh.color_attributes.new(name='QA_Color', type=dtype, domain=domain)
        self.mesh.color_attributes.active_color = attr
        vertices = list(range(6)) if domain == 'POINT' else [l.vertex_index for l in self.mesh.loops]
        for i, vertex in enumerate(vertices):
            attr.data[i].color = (1. if vertex in {1, 4} else 0., .2, .6, .35 + vertex * .05)
        for vertex in self.mesh.vertices:
            vertex.select = vertex.index in {1, 4}
        for edge in self.mesh.edges:
            edge.select = False
        for face in self.mesh.polygons:
            face.select = False
        return attr

    def values(self, attr):
        return np.array([tuple(x.color) for x in attr.data])

    def test_edit_point_corner_byte_float(self):
        for domain in ('POINT', 'CORNER'):
            for dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
                with self.subTest(domain=domain, dtype=dtype):
                    attr = self.attribute(domain, dtype)
                    other = self.mesh.color_attributes.new(name='KeepOther', type='FLOAT_COLOR', domain='POINT')
                    attr = self.mesh.color_attributes['QA_Color']
                    self.mesh.color_attributes.active_color = attr
                    for item in other.data:
                        item.color = (.1, .2, .3, .4)
                    original = self.values(attr)
                    other_before = self.values(other)
                    coords = [tuple(v.co) for v in self.mesh.vertices]
                    edges = [tuple(e.vertices) for e in self.mesh.edges]
                    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
                    bpy.ops.object.mode_set(mode='EDIT')
                    self.assertTrue(vcs.VCS_OT_smooth.poll(bpy.context))
                    self.assertEqual(bpy.ops.mesh.vertex_color_smooth_selected(factor=.5, iterations=1), {'FINISHED'})
                    self.assertEqual(self.obj.mode, 'EDIT')
                    bpy.ops.object.mode_set(mode='OBJECT')
                    attr = self.mesh.color_attributes['QA_Color']
                    after = self.values(attr)
                    self.assertEqual((attr.domain, attr.data_type), (domain, dtype))
                    vertices = list(range(6)) if domain == 'POINT' else [l.vertex_index for l in self.mesh.loops]
                    selected = np.array([v in {1, 4} for v in vertices])
                    np.testing.assert_array_equal(after[~selected], original[~selected])
                    np.testing.assert_allclose(after[selected, 0], 2 / 3, atol=.008)
                    np.testing.assert_array_equal(after[:, 1:], original[:, 1:])
                    np.testing.assert_array_equal(self.values(self.mesh.color_attributes['KeepOther']), other_before)
                    self.assertEqual(coords, [tuple(v.co) for v in self.mesh.vertices])
                    self.assertEqual(edges, [tuple(e.vertices) for e in self.mesh.edges])
                    self.assertAlmostEqual(self.obj.data.shape_keys.key_blocks['KeepShape'].data[1].co.z, .123)
                    self.assertAlmostEqual(self.groups.weight(1), .42)
                    for name in [a.name for a in self.mesh.color_attributes]:
                        self.mesh.color_attributes.remove(self.mesh.color_attributes[name])

    def test_vertex_paint_mask_and_alpha(self):
        attr = self.attribute('POINT', 'FLOAT_COLOR')
        before = self.values(attr)
        bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        self.mesh.use_paint_mask_vertex = True
        self.assertEqual(bpy.ops.mesh.vertex_color_smooth_selected(channels='A'), {'FINISHED'})
        after = self.values(attr)
        np.testing.assert_array_equal(after[:, :3], before[:, :3])
        unchanged = [0, 2, 3, 5]
        np.testing.assert_array_equal(after[unchanged], before[unchanged])
        self.mesh.use_paint_mask_vertex = False
        self.assertFalse(vcs.VCS_OT_smooth.poll(bpy.context))

    def test_face_mask_corner_does_not_write_other_face(self):
        attr = self.attribute('CORNER', 'BYTE_COLOR')
        before = self.values(attr)
        bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        self.mesh.use_paint_mask = True
        self.mesh.polygons[0].select = True
        self.mesh.polygons[1].select = False
        self.assertEqual(bpy.ops.mesh.vertex_color_smooth_selected(), {'FINISHED'})
        np.testing.assert_array_equal(self.values(attr)[4:], before[4:])

    def test_edit_hidden_and_no_selection(self):
        self.attribute('CORNER', 'FLOAT_COLOR')
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.faces.ensure_lookup_table()
        bm.faces[1].hide_set(True)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select_set(True)
        layer = bm.loops.layers.float_color['QA_Color']
        for loop in bm.verts[0].link_loops:
            loop[layer] = (1., .2, .6, .35)
        bmesh.update_edit_mesh(self.mesh)
        hidden = [(loop, tuple(loop[bm.loops.layers.float_color['QA_Color']])) for loop in bm.faces[1].loops]
        self.assertEqual(bpy.ops.mesh.vertex_color_smooth_selected(), {'FINISHED'})
        layer = bm.loops.layers.float_color['QA_Color']
        for loop, color in hidden:
            self.assertEqual(tuple(loop[layer]), color)
        for v in bm.verts:
            v.select_set(False)
        bmesh.update_edit_mesh(self.mesh)
        with self.assertRaises(ColorSmoothError):
            vcs.calculate(self.obj, bpy.context)

    def test_shared_mesh_rejected(self):
        self.attribute('POINT', 'FLOAT_COLOR')
        linked = bpy.data.objects.new('VCS_QA_Linked', self.mesh)
        bpy.context.collection.objects.link(linked)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            self.assertFalse(vcs.VCS_OT_smooth.poll(bpy.context))
        finally:
            bpy.data.objects.remove(linked, do_unlink=True)

    def test_attribute_view_activation_is_local_and_keeps_weight_mode(self):
        self.attribute('POINT', 'FLOAT_COLOR')
        bpy.ops.object.mode_set(mode='EDIT')
        space = SimpleNamespace(type='VIEW_3D', shading=SimpleNamespace(type='SOLID', color_type='VERTEX'),
                                overlay=SimpleNamespace(show_weight=False))
        context = SimpleNamespace(area=SimpleNamespace(type='VIEW_3D'), space_data=space,
            object=self.obj, preferences=bpy.context.preferences,
            objects_in_mode_unique_data=bpy.context.objects_in_mode_unique_data)
        self.assertTrue(vcs.VCS_OT_hotkey.poll(context))
        space.shading.color_type = 'MATERIAL'
        self.assertFalse(vcs.VCS_OT_hotkey.poll(context))
        space.shading.color_type = 'VERTEX'
        space.overlay.show_weight = True
        self.assertFalse(vcs.VCS_OT_hotkey.poll(context))
        self.assertTrue(vcs.viewport.attribute_shading(space, mode='OBJECT'))
        space.overlay.show_weight = False
        space.shading.type = 'MATERIAL'
        self.assertFalse(vcs.VCS_OT_hotkey.poll(context))

    def test_adjust_and_copy_active_in_edit_mode(self):
        self.attribute('CORNER', 'FLOAT_COLOR')
        before = self.values(self.mesh.color_attributes['QA_Color'])
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertEqual(bpy.ops.mesh.handy_color_adjust(action='GRADIENT', amount=-.1, channels='R'), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        after = self.values(self.mesh.color_attributes['QA_Color'])
        np.testing.assert_array_equal(after[:, 1:], before[:, 1:])
        selected = np.array([l.vertex_index in {1, 4} for l in self.mesh.loops])
        np.testing.assert_allclose(after[selected, 0], .9)
        np.testing.assert_array_equal(after[~selected], before[~selected])
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(self.mesh)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select_set(True)
        bm.select_history.clear()
        bm.select_history.add(bm.verts[0])
        bmesh.update_edit_mesh(self.mesh)
        self.assertEqual(bpy.ops.mesh.handy_color_adjust(action='COPY', channels='R'), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        np.testing.assert_allclose(self.values(self.mesh.color_attributes['QA_Color'])[:, 0], 0.)

    def test_keymaps_unregister_reregister(self):
        vcs.unregister()
        vcs.register()
        keymaps = vcs._keymaps
        if bpy.context.window_manager.keyconfigs.addon:
            self.assertEqual({km.name for km, _ in keymaps}, {'Mesh', 'Vertex Paint', 'Object Mode'})
            self.assertEqual(len(keymaps), 23)
            self.assertFalse(any(kmi.type == 'E' and kmi.ctrl and kmi.shift for _, kmi in keymaps))
            self.assertTrue(any(kmi.type == 'RIGHTMOUSE' and kmi.shift and kmi.alt
                                and kmi.idname == vcs.VCS_OT_cycle.bl_idname for _, kmi in keymaps))
        self.assertNotIn('vertex_color_smooth', bpy.context.preferences.addons)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
