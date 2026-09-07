"""Run in a live Blender GPU context; creates no scene data or preferences."""
import json
from types import SimpleNamespace

import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

import debug_render_pass_cycle as addon


def test_overlapping_weight_triangles():
    shader = addon._weight_shader()
    # Front is submitted first, back last. With depth writes disabled, the
    # farther triangle would incorrectly replace 0.25 with 0.75.
    vertices = [point for z in (-0.4, 0.4)
                for point in ((-0.8, -0.8, z), (0.8, -0.8, z), (0.0, 0.8, z))]
    batch = batch_for_shader(shader, "TRIS", {
        "pos": vertices,
        "color": [(0.25, 0.25, 0.25, 1.0)] * 3 + [(0.75, 0.75, 0.75, 1.0)] * 3,
    })
    offscreen = gpu.types.GPUOffScreen(32, 32, format="RGBA32F")
    previous_cache = addon._weight_overlay_cache
    previous_wire = addon._weight_wire_cache
    previous_viewport = gpu.state.viewport_get()
    previous_state = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get(), gpu.state.line_width_get())
    try:
        addon._weight_overlay_cache = {1: batch}
        addon._weight_wire_cache = {1: batch_for_shader(shader, "LINES", {
            "pos": [(-0.2, -0.21875, -0.4), (0.2, -0.21875, -0.4),
                    (-0.2, 0.28125, 0.4), (0.2, 0.28125, 0.4)],
            "color": [(0.9, 0.9, 0.9, 1.0)] * 4,
        })}
        with offscreen.bind():
            gpu.state.viewport_set(0, 0, 32, 32)
            framebuffer = gpu.state.active_framebuffer_get()
            gpu.state.depth_mask_set(True)
            framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            gpu.state.depth_test_set("NONE")
            gpu.state.depth_mask_set(False)
            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(3.0)
            addon._draw_weight_batches(
                shader, {1: SimpleNamespace(matrix_world=Matrix.Identity(4), show_wire=True)}, Matrix.Identity(4),
            )
            restored = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get(), gpu.state.line_width_get())
            assert restored == ("NONE", False, "ALPHA", 3.0), restored
            pixel = tuple(framebuffer.read_color(16, 16, 1, 1, 4, 0, "FLOAT")[0][0])
            assert max(abs(pixel[channel] - 0.25) for channel in range(3)) < 0.0001, pixel
            front_wire = tuple(framebuffer.read_color(16, 12, 1, 1, 4, 0, "FLOAT")[0][0])
            back_wire = tuple(framebuffer.read_color(16, 20, 1, 1, 4, 0, "FLOAT")[0][0])
            assert abs(front_wire[0] - 0.9) < 0.0001, front_wire
            assert abs(back_wire[0] - 0.25) < 0.0001, back_wire
            return {"status": "passed", "front_weight": 0.25, "back_weight": 0.75,
                    "visible_pixel_rgba": pixel, "front_wire": front_wire,
                    "occluded_wire": back_wire, "gpu_state_restored": True}
    finally:
        addon._weight_overlay_cache = previous_cache
        addon._weight_wire_cache = previous_wire
        gpu.state.viewport_set(*previous_viewport)
        gpu.state.depth_test_set(previous_state[0])
        gpu.state.depth_mask_set(previous_state[1])
        gpu.state.blend_set(previous_state[2])
        gpu.state.line_width_set(previous_state[3])
        offscreen.free()


result = test_overlapping_weight_triangles()
print("DEBUG_WEIGHT_GPU_OCCLUSION_OK " + json.dumps(result))
