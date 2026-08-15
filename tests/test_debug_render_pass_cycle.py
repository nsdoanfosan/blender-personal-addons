import addon_utils
import bpy
from types import SimpleNamespace


MODULE = "debug_render_pass_cycle"


def default_key_snapshot():
    key_config = bpy.context.window_manager.keyconfigs.default
    snapshot = []
    for keymap in key_config.keymaps:
        for keymap_item in keymap.keymap_items:
            if keymap_item.type in {"B", "M"}:
                snapshot.append(
                    (
                        keymap.name,
                        keymap_item.idname,
                        keymap_item.type,
                        keymap_item.value,
                        keymap_item.ctrl,
                        keymap_item.shift,
                        keymap_item.alt,
                        keymap_item.active,
                    )
                )
    return snapshot


before_default_keys = default_key_snapshot()

addon_utils.enable(MODULE, default_set=False)
addon = __import__(MODULE)

assert hasattr(bpy.ops.view3d, "cycle_debug_render_pass")
assert hasattr(bpy.ops.view3d, "set_debug_render_pass")
assert default_key_snapshot() == before_default_keys

hotkeys = {
    keymap_item.type: keymap_item
    for _keymap, keymap_item in addon.addon_keymaps
}
assert set(hotkeys) == {"B", "M"}
assert hotkeys["B"].idname == addon.OPERATOR_CYCLE_ID
assert hotkeys["M"].idname == addon.OPERATOR_CYCLE_ID
assert hotkeys["B"].properties.direction == "PREVIOUS"
assert hotkeys["M"].properties.direction == "NEXT"
assert not hotkeys["B"].ctrl and not hotkeys["B"].shift and not hotkeys["B"].alt
assert not hotkeys["M"].ctrl and not hotkeys["M"].shift and not hotkeys["M"].alt
hotkey_indices = sorted(
    index
    for keymap, keymap_item in addon.addon_keymaps
    for index, candidate in enumerate(keymap.keymap_items)
    if candidate == keymap_item
)
assert hotkey_indices == [0, 1]

passes = addon.available_render_pass_ids()
assert passes[0] == "COMBINED"
assert "DIFFUSE_COLOR" in passes
assert addon.render_pass_label("DIFFUSE_COLOR") == "Base Color (Diffuse Color)"
assert addon.adjacent_render_pass("COMBINED", 1, passes) == "DIFFUSE_COLOR"
assert addon.adjacent_render_pass("DIFFUSE_COLOR", -1, passes) == "COMBINED"
assert addon.adjacent_render_pass(passes[-1], 1, passes) == "COMBINED"
assert addon.adjacent_render_pass("UNKNOWN", 1, passes) == "DIFFUSE_COLOR"
assert addon.engine_supports_viewport_passes("BLENDER_EEVEE")
assert addon.engine_supports_viewport_passes("BLENDER_EEVEE_NEXT")
assert not addon.engine_supports_viewport_passes("CYCLES")


class SelectiveShading:
    def __init__(self, current, rejected):
        self._render_pass = current
        self.rejected = set(rejected)

    @property
    def render_pass(self):
        return self._render_pass

    @render_pass.setter
    def render_pass(self, value):
        if value in self.rejected:
            raise TypeError("unsupported test pass")
        self._render_pass = value


selective = SelectiveShading("COMBINED", {"DIFFUSE_COLOR", "NORMAL"})
chosen = addon.apply_adjacent_render_pass(
    selective,
    1,
    ("COMBINED", "DIFFUSE_COLOR", "NORMAL", "AO"),
)
assert chosen == "AO"
assert selective.render_pass == "AO"

fake_context = SimpleNamespace(
    area=SimpleNamespace(type="VIEW_3D"),
    space_data=SimpleNamespace(
        type="VIEW_3D",
        shading=SimpleNamespace(type="RENDERED"),
    ),
    scene=SimpleNamespace(render=SimpleNamespace(engine="CYCLES")),
)
assert addon.available_render_pass_ids(fake_context) == ()
fake_context.space_data.shading.type = "MATERIAL"
assert "DIFFUSE_COLOR" in addon.available_render_pass_ids(fake_context)
fake_context.space_data.shading.type = "RENDERED"
fake_context.scene.render.engine = "BLENDER_EEVEE"
assert "DIFFUSE_COLOR" in addon.available_render_pass_ids(fake_context)

layout_screen = bpy.data.screens.get("Layout")
viewport_area = next(area for area in layout_screen.areas if area.type == "VIEW_3D")
viewport_space = viewport_area.spaces.active
original_shading_type = viewport_space.shading.type
original_render_pass = viewport_space.shading.render_pass
viewport_space.shading.type = "MATERIAL"
real_shading_context = SimpleNamespace(
    area=viewport_area,
    space_data=viewport_space,
    scene=SimpleNamespace(render=SimpleNamespace(engine="BLENDER_EEVEE")),
)
real_passes = addon.available_render_pass_ids(real_shading_context)
assert addon.apply_adjacent_render_pass(viewport_space.shading, 1, real_passes) == "DIFFUSE_COLOR"
assert viewport_space.shading.render_pass == "DIFFUSE_COLOR"
viewport_space.shading.render_pass = original_render_pass
viewport_space.shading.type = original_shading_type

addon_utils.disable(MODULE, default_set=False)
assert not addon.addon_keymaps
assert default_key_snapshot() == before_default_keys
print("DEBUG_RENDER_PASS_CYCLE_SMOKE_OK")
