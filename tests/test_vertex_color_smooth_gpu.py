"""Call run() in an existing GUI Blender. No production mesh or UI writes."""
import bpy
import gpu
import numpy as np
from mathutils import Matrix
from vertex_color_smooth import viewport
from vertex_color_smooth.core import isolate_rgb


def run():
    old_viewport = gpu.state.viewport_get()
    old_depth = gpu.state.depth_test_get()
    old_mask = gpu.state.depth_mask_get()
    old_blend = gpu.state.blend_get()
    offscreen = gpu.types.GPUOffScreen(16, 16)
    pixels = {}
    try:
        with offscreen.bind():
            gpu.state.viewport_set(0, 0, 16, 16)
            gpu.state.depth_test_set('NONE')
            gpu.state.depth_mask_set(False)
            gpu.state.blend_set('NONE')
            framebuffer = gpu.state.active_framebuffer_get()
            shader = viewport.color_shader()
            for channel in ('RGB', 'R', 'G', 'B'):
                colors = isolate_rgb(np.array([[.25, .5, .75, .1]] * 3), channel)
                batch = viewport.make_batch('TRIS', [(-1, -1, 0), (1, -1, 0), (0, 1, 0)], colors)
                framebuffer.clear(color=(0., 0., 0., 1.))
                shader.bind()
                shader.uniform_float('mvp', Matrix.Identity(4))
                shader.uniform_float('depthOffset', 0.0)
                shader.uniform_float('viewportSize', (16., 16.))
                shader.uniform_float('pixelSize', 0.0)
                batch.draw(shader)
                pixel = np.array(framebuffer.read_color(8, 8, 1, 1, 4, 0, 'FLOAT')).reshape(4)
                np.testing.assert_allclose(pixel, colors[0], atol=.002)
                pixels[channel] = pixel.tolist()
    finally:
        offscreen.free()
        gpu.state.viewport_set(*old_viewport)
        gpu.state.depth_test_set(old_depth)
        gpu.state.depth_mask_set(old_mask)
        gpu.state.blend_set(old_blend)
    return {'gpu_channels_passed': True, 'pixels': pixels}
