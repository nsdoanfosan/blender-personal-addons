import bpy


MENU_IDNAME = "TA_MT_quick_menu"


def _draw_section(layout, title, icon, items):
    box = layout.box()
    column = box.column(align=True)
    column.label(text=title, icon=icon)

    for operator_idname, label, operator_icon in items:
        column.operator(operator_idname, text=label, icon=operator_icon)

    return box


def _draw_collection_section(layout):
    box = layout.box()
    column = box.column(align=True)
    column.label(text="Collections", icon="OUTLINER_COLLECTION")
    column.operator_context = "INVOKE_DEFAULT"

    column.operator(
        "object.move_to_collection",
        text="Move to Collection",
        icon="FILE_PARENT",
    )
    column.operator(
        "object.link_to_collection",
        text="Link to Collection",
        icon="LINKED",
    )
    new_collection = column.operator(
        "object.move_to_collection",
        text="New Collection",
        icon="ADD",
    )
    new_collection.is_new = True

    return box


class TA_MT_quick_menu(bpy.types.Menu):
    bl_idname = MENU_IDNAME
    bl_label = "TA Quick Menu"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def draw(self, context):
        pie = self.layout.menu_pie()

        # Left
        _draw_section(
            pie,
            "Create & Fit",
            "MOD_CURVE",
            (
                ("object.ta_alpha_mesh_from_base_color", "Alpha Mesh From Base Color", "IMAGE_DATA"),
                ("object.ta_create_curve_fit_plane", "Create Curve Fit Shape", "CURVE_DATA"),
                ("object.ta_fit_object_to_curve", "Fit Existing Object To Curve", "MOD_CURVE"),
                ("object.ta_segment_object_by_length", "Rebuild Segments By Length", "MOD_ARRAY"),
            ),
        )

        # Right
        _draw_collection_section(pie)

        # Bottom
        _draw_section(
            pie,
            "Export",
            "EXPORT",
            (
                ("object.ta_export_child_collections_fbx", "Export Child Collections To FBX", "FILE_TICK"),
            ),
        )

        # Top
        _draw_section(
            pie,
            "Mesh & Data",
            "MESH_DATA",
            (
                ("mesh.ta_connect_edge", "Connect Edge", "EDGESEL"),
                ("object.ta_rename_uv_maps_to_uvmap", "Rename UV Maps To UVMap", "GROUP_UVS"),
                ("object.ta_setup_vertex_color", "Setup Group & Color", "GROUP_VERTEX"),
                ("object.ta_face_sets_to_materials", "Face Sets To Materials", "MATERIAL"),
            ),
        )

        # Top-left is intentionally kept open so Scene & Objects sits on the
        # upper-right without crowding the collection controls.
        pie.separator()

        # Top-right
        _draw_section(
            pie,
            "Scene & Objects",
            "OUTLINER_OB_GROUP_INSTANCE",
            (
                ("object.select_linked_data_target", "Select Linked Object", "LINKED"),
                ("object.renameobjects", "Rename Object(s)", "SORTALPHA"),
                ("scor.rename_all_scene_objects", "Rename All Scene Objects", "OUTLINER_COLLECTION"),
            ),
        )


classes = (TA_MT_quick_menu,)
addon_keymaps = []


def _register_keymap():
    window_manager = bpy.context.window_manager
    key_config = window_manager.keyconfigs.addon if window_manager else None
    if key_config is None:
        return

    keymap = key_config.keymaps.new(name="3D View", space_type="VIEW_3D")

    # Remove a stale copy left by a script reload before adding the current binding.
    for keymap_item in list(keymap.keymap_items):
        if keymap_item.idname != "wm.call_menu_pie":
            continue
        if getattr(keymap_item.properties, "name", "") == MENU_IDNAME:
            keymap.keymap_items.remove(keymap_item)

    keymap_item = keymap.keymap_items.new(
        "wm.call_menu_pie",
        type="J",
        value="PRESS",
        ctrl=True,
        shift=True,
    )
    keymap_item.properties.name = MENU_IDNAME
    addon_keymaps.append((keymap, keymap_item))


def _unregister_keymap():
    for keymap, keymap_item in addon_keymaps:
        try:
            keymap.keymap_items.remove(keymap_item)
        except (ReferenceError, RuntimeError):
            pass
    addon_keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_keymap()


def unregister():
    _unregister_keymap()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
