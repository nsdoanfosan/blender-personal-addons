from pathlib import Path
import tempfile

import addon_utils
import bpy


MODULE = "clipboard_image_plane"


addon_utils.enable(MODULE, default_set=False)
addon = __import__(MODULE)

operator_rna = addon.CLIPBOARDIMAGEPLANE_OT_paste
assert operator_rna.bl_idname == "object.paste_clipboard_image_plane"
assert hasattr(bpy.ops.object, "paste_clipboard_image_plane")

hotkeys = [
    keymap_item
    for keymap, keymap_item in addon.addon_keymaps
    if keymap_item.idname == operator_rna.bl_idname
]
assert len(hotkeys) == 1
assert hotkeys[0].type == "V"
assert hotkeys[0].ctrl
assert hotkeys[0].shift
assert hotkeys[0].alt

temp_path = Path(tempfile.gettempdir()) / "clipboard_image_plane_smoke.png"
source = bpy.data.images.new(
    "ClipboardImagePlane_Smoke_Source",
    width=8,
    height=4,
    alpha=True,
)
source.generated_color = (0.25, 0.5, 0.75, 0.5)
source.filepath_raw = str(temp_path)
source.file_format = "PNG"
source.save()
bpy.data.images.remove(source)

image = bpy.data.images.load(str(temp_path), check_existing=False)
obj = addon.create_image_plane(
    bpy.context,
    image,
    longest_side=2.0,
    orient_to_view=False,
)
bpy.context.view_layer.update()

assert obj.type == "MESH"
assert len(obj.data.vertices) == 4
assert len(obj.data.polygons) == 1
assert len(obj.data.uv_layers) == 1
assert len(obj.data.materials) == 1
assert abs(obj.dimensions.x - 2.0) < 1.0e-6
assert abs(obj.dimensions.y - 1.0) < 1.0e-6
assert obj.data.materials[0].node_tree is not None

material = obj.data.materials[0]
mesh = obj.data
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.materials.remove(material)
bpy.data.meshes.remove(mesh)
bpy.data.images.remove(image)
temp_path.unlink(missing_ok=True)

addon_utils.disable(MODULE, default_set=False)
print("CLIPBOARD_IMAGE_PLANE_SMOKE_OK")
