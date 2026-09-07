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
assert real_views[:7] == (
    "COMBINED",
    "DIFFUSE_COLOR",
    "ATTRIBUTE_FACTOR",
    "ATTRIBUTE_RANDOM",
    "ATTRIBUTE_MESH_AO",
    "ATTRIBUTE_WEIGHT_G",
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
assert ao_object[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP][ao_modifier.name]
assert addon.apply_debug_hotkey(real_shading_context, "B") == "DIFFUSE_COLOR"
assert viewport_space.shading.render_pass == "DIFFUSE_COLOR"
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_FACTOR"
assert addon.current_debug_view_id(real_shading_context) == "ATTRIBUTE_FACTOR"
assert bpy.context.view_layer.material_override is not None
assert bpy.context.view_layer.material_override.get(addon.DEBUG_MATERIAL_TAG)
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_RANDOM"
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_MESH_AO"
assert ao_modifier.show_viewport
assert addon.apply_debug_hotkey(real_shading_context, "B") == "ATTRIBUTE_WEIGHT_G"
assert addon.current_debug_view_id(real_shading_context) == "ATTRIBUTE_WEIGHT_G"
assert not ao_modifier.show_viewport
assert addon.apply_debug_hotkey(real_shading_context, "M") == "COMBINED"
assert bpy.context.view_layer.material_override is None
assert addon._weight_draw_handler is None
assert addon._invalidate_weight_overlay not in bpy.app.handlers.depsgraph_update_post
assert addon.apply_debug_view(real_shading_context, "ATTRIBUTE_WEIGHT_G") == "ATTRIBUTE_WEIGHT_G"
assert addon.apply_debug_hotkey(real_shading_context, "B") == "NORMAL"
assert not ao_modifier.show_viewport
ao_object[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP][ao_modifier.name] = False
assert addon._set_mesh_ao_viewport_enabled(True) == 1
assert ao_modifier.show_viewport
assert ao_object[addon.MESH_AO_ORIGINAL_VIEWPORT_PROP][ao_modifier.name]
addon._set_mesh_ao_viewport_enabled(False)
assert bpy.context.view_layer.material_override is None
assert addon.apply_debug_hotkey(real_shading_context, "M") == "COMBINED"
assert viewport_space.shading.render_pass == "COMBINED"
viewport_space.shading.render_pass = original_render_pass
assert addon.apply_debug_view(real_shading_context, "ATTRIBUTE_WEIGHT_G") == "ATTRIBUTE_WEIGHT_G"

# A Curves object may output a Mesh component while evaluated Object.data stays
# empty. Read the actual generated color field, including subsequent node edits.
curve_data = bpy.data.hair_curves.new("DebugWeight_SourceCurves")
curve_object = bpy.data.objects.new("DebugWeight_SourceCurves", curve_data)
bpy.context.scene.collection.objects.link(curve_object)
weight_group = bpy.data.node_groups.new("DebugWeight_GeneratedMesh", "GeometryNodeTree")
weight_group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
grid = weight_group.nodes.new("GeometryNodeMeshGrid")
grid.inputs["Vertices X"].default_value = 2
grid.inputs["Vertices Y"].default_value = 2
position = weight_group.nodes.new("GeometryNodeInputPosition")
separate = weight_group.nodes.new("ShaderNodeSeparateXYZ")
remap = weight_group.nodes.new("ShaderNodeMath")
remap.operation = "MULTIPLY_ADD"
remap.inputs[1].default_value = 4.0
store_weight = weight_group.nodes.new("GeometryNodeStoreNamedAttribute")
store_weight.data_type = "FLOAT_COLOR"
store_weight.domain = "POINT"
store_weight.inputs["Name"].default_value = "ChaosWeight"
weight_output = weight_group.nodes.new("NodeGroupOutput")
links = weight_group.links
links.new(grid.outputs["Mesh"], store_weight.inputs["Geometry"])
links.new(position.outputs["Position"], separate.inputs[0])
links.new(separate.outputs["X"], remap.inputs[0])
links.new(remap.outputs[0], store_weight.inputs["Value"])
links.new(store_weight.outputs["Geometry"], weight_output.inputs[0])
weight_modifier = curve_object.modifiers.new("GeneratedMesh", "NODES")
weight_modifier.node_group = weight_group
bpy.context.view_layer.update()
draw_data = addon._weight_mesh_draw_data(curve_object, bpy.context.evaluated_depsgraph_get())
assert len(curve_data.points) == 0
assert len(draw_data["positions"]) == 4
assert len(draw_data["triangles"]) == 2
assert {color[0] for color in draw_data["colors"]} == {0.0, 1.0}
remap.inputs[1].default_value = 0.0
remap.inputs[2].default_value = 0.25
addon._weight_overlay_dirty = False
bpy.context.view_layer.update()
assert addon._weight_overlay_dirty
changed_data = addon._weight_mesh_draw_data(curve_object, bpy.context.evaluated_depsgraph_get())
assert changed_data["positions"] == draw_data["positions"]
assert {color[0] for color in changed_data["colors"]} == {0.25}
store_weight.inputs["Name"].default_value = "UnrelatedColor"
bpy.context.view_layer.update()
assert addon._weight_mesh_draw_data(curve_object, bpy.context.evaluated_depsgraph_get()) is None
assert addon._weight_draw_handler is not None
assert addon._invalidate_weight_overlay in bpy.app.handlers.depsgraph_update_post
# Saving/loading must discard runtime GPU state just like returning to Combined.
addon._save_pre_remove_debug_materials(None)
assert addon._weight_draw_handler is None
assert not addon._weight_overlay_cache
assert bpy.context.view_layer.material_override is None
assert addon.apply_debug_view(real_shading_context, "ATTRIBUTE_WEIGHT_G") == "ATTRIBUTE_WEIGHT_G"
addon._load_post_start_input_listeners(None)
assert addon._weight_draw_handler is None
assert addon._weight_overlay_shader is None
assert addon._invalidate_weight_overlay not in bpy.app.handlers.depsgraph_update_post
assert addon.apply_debug_view(real_shading_context, "ATTRIBUTE_WEIGHT_G") == "ATTRIBUTE_WEIGHT_G"
viewport_space.shading.type = original_shading_type

addon_utils.disable(MODULE, default_set=False)
assert ao_modifier.show_viewport
assert addon.MESH_AO_ORIGINAL_VIEWPORT_PROP not in ao_object
assert not addon._listener_enabled
assert addon._load_post_start_input_listeners not in bpy.app.handlers.load_post
assert addon._save_pre_remove_debug_materials not in bpy.app.handlers.save_pre
assert addon._draw_handler is None
assert addon._weight_draw_handler is None
assert addon._invalidate_weight_overlay not in bpy.app.handlers.depsgraph_update_post
assert not addon._register_draw_handler.header_registered
assert not any(material.get(addon.DEBUG_MATERIAL_TAG) for material in bpy.data.materials)
assert default_key_snapshot() == before_default_keys
print("DEBUG_RENDER_PASS_CYCLE_SMOKE_OK")
