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

user_key_config = bpy.context.window_manager.keyconfigs.user
legacy_keymap = user_key_config.keymaps.get("3D View")
if legacy_keymap is None:
    legacy_keymap = user_key_config.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
        region_type="WINDOW",
    )
legacy_item = legacy_keymap.keymap_items.new(
    "view3d.cycle_debug_render_pass",
    type="M",
    value="PRESS",
)
custom_item = legacy_keymap.keymap_items.new(
    "view3d.cycle_debug_render_pass",
    type="B",
    value="PRESS",
    shift=True,
)
assert any(candidate == legacy_item for candidate in legacy_keymap.keymap_items)

addon_utils.enable(MODULE, default_set=False)
addon = __import__(MODULE)

assert hasattr(bpy.ops.view3d, "cycle_debug_render_pass")
assert hasattr(bpy.ops.view3d, "set_debug_render_pass")
assert hasattr(bpy.ops.wm, "debug_render_pass_input_listener")
assert default_key_snapshot() == before_default_keys
assert not any(
    keymap_item.idname in {addon.OPERATOR_CYCLE_ID, addon.OPERATOR_SET_ID}
    and keymap_item.type in {"B", "M"}
    and not keymap_item.ctrl
    and not keymap_item.shift
    and not keymap_item.alt
    for keymap in user_key_config.keymaps
    for keymap_item in keymap.keymap_items
)
assert any(
    keymap_item == custom_item
    for keymap in user_key_config.keymaps
    for keymap_item in keymap.keymap_items
)

addon_key_config = bpy.context.window_manager.keyconfigs.addon
assert not any(
    keymap_item.idname
    in {
        addon.OPERATOR_CYCLE_ID,
        addon.OPERATOR_SET_ID,
        "wm.debug_render_pass_input_listener",
    }
    for keymap in addon_key_config.keymaps
    for keymap_item in keymap.keymap_items
)
assert addon._listener_enabled
assert addon._load_post_start_input_listeners in bpy.app.handlers.load_post
assert addon._save_pre_remove_debug_materials in bpy.app.handlers.save_pre
assert addon._draw_handler is not None
assert addon._register_draw_handler.header_registered

passes = addon.available_render_pass_ids()
assert passes[0] == "COMBINED"
assert "DIFFUSE_COLOR" in passes
assert passes[:5] == (
    "COMBINED",
    "DIFFUSE_COLOR",
    "NORMAL",
    "SPECULAR_COLOR",
    "AO",
)
assert passes == (
    "COMBINED",
    "DIFFUSE_COLOR",
    "NORMAL",
    "SPECULAR_COLOR",
    "AO",
    "TRANSPARENT",
    "MIST",
    "POSITION",
)
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
    view_layer=bpy.context.view_layer,
    scene=SimpleNamespace(render=SimpleNamespace(engine="BLENDER_EEVEE")),
)
real_passes = addon.available_render_pass_ids(real_shading_context)
real_views = addon.available_debug_view_ids(real_shading_context)
assert real_views[:6] == (
    "COMBINED",
    "DIFFUSE_COLOR",
    "ATTRIBUTE_FACTOR",
    "ATTRIBUTE_RANDOM",
    "ATTRIBUTE_MESH_AO",
    "NORMAL",
)

ao_mesh = bpy.data.meshes.new("DebugRenderPassCycle_AO_TestMesh")
ao_object = bpy.data.objects.new("DebugRenderPassCycle_AO_TestObject", ao_mesh)
bpy.context.scene.collection.objects.link(ao_object)
ao_group = bpy.data.node_groups.new("HT_Mesh_AO_Test", "GeometryNodeTree")
ao_group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
ao_group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ao_input = ao_group.nodes.new("NodeGroupInput")
ao_output = ao_group.nodes.new("NodeGroupOutput")
ao_group.links.new(ao_input.outputs["Geometry"], ao_output.inputs["Geometry"])
ao_modifier = ao_object.modifiers.new("HT_Mesh_AO", "NODES")
ao_modifier.node_group = ao_group
ao_modifier.show_viewport = True

assert addon.apply_debug_view(real_shading_context, "COMBINED") == "COMBINED"
assert not ao_modifier.show_viewport
assert ao_modifier[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP]
assert addon.apply_debug_hotkey(real_shading_context, "B") == "DIFFUSE_COLOR"
assert viewport_space.shading.render_pass == "DIFFUSE_COLOR"
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_FACTOR"
assert addon.current_debug_view_id(real_shading_context) == "ATTRIBUTE_FACTOR"
assert bpy.context.view_layer.material_override is not None
assert bpy.context.view_layer.material_override.get(addon.DEBUG_MATERIAL_TAG)
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_RANDOM"
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_MESH_AO"
assert ao_modifier.show_viewport
assert addon.apply_debug_hotkey(real_shading_context, "B") == "NORMAL"
assert not ao_modifier.show_viewport
ao_modifier[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP] = False
assert addon._set_mesh_ao_viewport_enabled(True) == 1
assert ao_modifier.show_viewport
assert ao_modifier[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP]
addon._set_mesh_ao_viewport_enabled(False)
assert bpy.context.view_layer.material_override is None
assert addon.apply_debug_hotkey(real_shading_context, "M") == "COMBINED"
assert viewport_space.shading.render_pass == "COMBINED"
viewport_space.shading.render_pass = original_render_pass
viewport_space.shading.type = original_shading_type

addon_utils.disable(MODULE, default_set=False)
assert ao_modifier.show_viewport
assert addon.MESH_AO_ORIGINAL_VIEWPORT_PROP not in ao_modifier
assert not addon._listener_enabled
assert addon._load_post_start_input_listeners not in bpy.app.handlers.load_post
assert addon._save_pre_remove_debug_materials not in bpy.app.handlers.save_pre
assert addon._draw_handler is None
assert not addon._register_draw_handler.header_registered
assert not any(material.get(addon.DEBUG_MATERIAL_TAG) for material in bpy.data.materials)
assert default_key_snapshot() == before_default_keys
print("DEBUG_RENDER_PASS_CYCLE_SMOKE_OK")
