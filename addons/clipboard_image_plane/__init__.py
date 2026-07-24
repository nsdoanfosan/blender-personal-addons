bl_info = {
    "name": "Clipboard Image Plane",
    "author": "PARK / OpenAI",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Add > Image",
    "description": "Paste a Windows clipboard image as a textured mesh plane",
    "category": "Import-Export",
}

from datetime import datetime
from pathlib import Path
import subprocess
import sys
import uuid

import bpy
from bpy.props import BoolProperty, FloatProperty


ADDON_ID = __package__ or __name__
OPERATOR_ID = "object.paste_clipboard_image_plane"
CLIPBOARD_SCRIPT = Path(__file__).with_name("clipboard_to_png.ps1")

addon_keymaps = []
registered_menus = []


def _preferences(context):
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def _cache_directory():
    path = Path(
        bpy.utils.user_resource(
            "DATAFILES",
            path="clipboard_image_plane",
            create=True,
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_clipboard_path():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    token = uuid.uuid4().hex[:8]
    return _cache_directory() / f"Clipboard_{stamp}_{token}.png"


def capture_clipboard_image(output_path):
    if sys.platform != "win32":
        raise RuntimeError("Clipboard Image Plane currently supports Windows only")

    if not CLIPBOARD_SCRIPT.is_file():
        raise RuntimeError(f"Clipboard helper is missing: {CLIPBOARD_SCRIPT}")

    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(CLIPBOARD_SCRIPT),
        "-OutputPath",
        str(output_path),
    ]

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Timed out while reading the Windows clipboard") from error

    if completed.returncode == 2:
        raise RuntimeError("The clipboard does not contain an image")

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or "Could not read the Windows clipboard")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Clipboard capture did not create a valid PNG")

    return output_path


def _set_transparency(material):
    if hasattr(material, "surface_render_method"):
        try:
            material.surface_render_method = "DITHERED"
            return
        except (TypeError, ValueError):
            pass

    if hasattr(material, "blend_method"):
        try:
            material.blend_method = "BLEND"
        except (TypeError, ValueError):
            pass


def create_image_material(image, name):
    material = bpy.data.materials.new(name=f"{name}_Material")
    material.use_nodes = True
    material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    material.use_backface_culling = False
    _set_transparency(material)

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520.0, 0.0)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (180.0, 0.0)

    texture = nodes.new("ShaderNodeTexImage")
    texture.location = (-180.0, 0.0)
    texture.image = image
    texture.interpolation = "Linear"
    texture.extension = "CLIP"

    base_color = principled.inputs.get("Base Color")
    alpha = principled.inputs.get("Alpha")
    roughness = principled.inputs.get("Roughness")
    emission_color = (
        principled.inputs.get("Emission Color")
        or principled.inputs.get("Emission")
    )
    emission_strength = principled.inputs.get("Emission Strength")

    if base_color:
        links.new(texture.outputs["Color"], base_color)
    if alpha:
        links.new(texture.outputs["Alpha"], alpha)
    if roughness:
        roughness.default_value = 1.0
    if emission_color:
        links.new(texture.outputs["Color"], emission_color)
    if emission_strength:
        emission_strength.default_value = 0.25

    links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return material


def _plane_dimensions(image, longest_side):
    width_px, height_px = image.size

    if width_px <= 0 or height_px <= 0:
        raise RuntimeError("Clipboard image has invalid dimensions")

    if width_px >= height_px:
        return longest_side, longest_side * height_px / width_px

    return longest_side * width_px / height_px, longest_side


def create_image_plane(context, image, longest_side=2.0, orient_to_view=True):
    width, height = _plane_dimensions(image, longest_side)
    half_width = width * 0.5
    half_height = height * 0.5

    base_name = Path(image.filepath).stem or image.name or "Clipboard_Image"
    mesh = bpy.data.meshes.new(name=f"{base_name}_Mesh")
    mesh.from_pydata(
        [
            (-half_width, -half_height, 0.0),
            (half_width, -half_height, 0.0),
            (half_width, half_height, 0.0),
            (-half_width, half_height, 0.0),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()

    uv_layer = mesh.uv_layers.new(name="UVMap")
    uv_by_vertex = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    )

    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uv_by_vertex[vertex_index]

    material = create_image_material(image, base_name)
    mesh.materials.append(material)

    obj = bpy.data.objects.new(name=base_name, object_data=mesh)
    target_collection = context.collection or context.scene.collection
    target_collection.objects.link(obj)
    obj.location = context.scene.cursor.location

    if orient_to_view and context.region_data is not None:
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (
            context.region_data.view_matrix.inverted().to_quaternion()
        )

    for selected in context.selected_objects:
        selected.select_set(False)

    obj.select_set(True)
    context.view_layer.objects.active = obj
    obj["clipboard_image_path"] = image.filepath
    return obj


def _show_textures_in_viewport(context):
    space = context.space_data
    if space and space.type == "VIEW_3D" and space.shading.type == "SOLID":
        space.shading.color_type = "TEXTURE"


class CLIPBOARDIMAGEPLANE_OT_paste(bpy.types.Operator):
    bl_idname = OPERATOR_ID
    bl_label = "Paste Clipboard Image as Plane"
    bl_description = (
        "Create a textured mesh plane from the image currently in the Windows clipboard"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object Mode before pasting an image")
            return {"CANCELLED"}

        prefs = _preferences(context)
        longest_side = prefs.plane_size if prefs else 2.0
        orient_to_view = prefs.orient_to_view if prefs else True
        pack_image = prefs.pack_image if prefs else True
        show_textures = prefs.show_textures if prefs else True

        image_path = _new_clipboard_path()
        image = None

        try:
            capture_clipboard_image(image_path)
            image = bpy.data.images.load(str(image_path), check_existing=False)
            image.name = image_path.stem
            image.alpha_mode = "STRAIGHT"

            obj = create_image_plane(
                context,
                image,
                longest_side=longest_side,
                orient_to_view=orient_to_view,
            )

            if pack_image:
                image.pack()

            if show_textures:
                _show_textures_in_viewport(context)

        except Exception as error:
            if image is not None and image.users == 0:
                bpy.data.images.remove(image)

            if image_path.exists():
                image_path.unlink()

            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Pasted {image.size[0]} x {image.size[1]} image as {obj.name}",
        )
        return {"FINISHED"}


class CLIPBOARDIMAGEPLANE_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    plane_size: FloatProperty(
        name="Longest Side",
        description="World-space length of the plane's longest side",
        default=2.0,
        min=0.01,
        soft_max=20.0,
        subtype="DISTANCE",
        unit="LENGTH",
    )

    orient_to_view: BoolProperty(
        name="Face Current View",
        description="Orient the new plane to face the current 3D viewport",
        default=True,
    )

    pack_image: BoolProperty(
        name="Pack Image into Blend",
        description="Pack clipboard image data into the blend file",
        default=True,
    )

    show_textures: BoolProperty(
        name="Show Textures in Solid View",
        description="Switch Solid viewport color mode to Texture after pasting",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Shortcut: Ctrl + Shift + Alt + V", icon="KEYINGSET")
        layout.prop(self, "plane_size")
        layout.prop(self, "orient_to_view")
        layout.prop(self, "pack_image")
        layout.prop(self, "show_textures")


classes = (
    CLIPBOARDIMAGEPLANE_OT_paste,
    CLIPBOARDIMAGEPLANE_Preferences,
)


def draw_image_add_menu(self, context):
    self.layout.operator(
        OPERATOR_ID,
        text="Paste Clipboard Image as Plane",
        icon="IMAGE_DATA",
    )


def register_keymaps():
    key_config = bpy.context.window_manager.keyconfigs.addon
    if key_config is None:
        return

    keymap = key_config.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
        region_type="WINDOW",
    )
    keymap_item = keymap.keymap_items.new(
        OPERATOR_ID,
        type="V",
        value="PRESS",
        ctrl=True,
        shift=True,
        alt=True,
    )
    addon_keymaps.append((keymap, keymap_item))


def unregister_keymaps():
    for keymap, keymap_item in addon_keymaps:
        try:
            keymap.keymap_items.remove(keymap_item)
        except (ReferenceError, RuntimeError):
            pass

    addon_keymaps.clear()


def register_menus():
    menu_type = getattr(bpy.types, "VIEW3D_MT_image_add", None)
    if menu_type is None:
        menu_type = bpy.types.VIEW3D_MT_add

    menu_type.append(draw_image_add_menu)
    registered_menus.append(menu_type)


def unregister_menus():
    for menu_type in registered_menus:
        try:
            menu_type.remove(draw_image_add_menu)
        except (ReferenceError, RuntimeError):
            pass

    registered_menus.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_menus()
    register_keymaps()


def unregister():
    unregister_keymaps()
    unregister_menus()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
