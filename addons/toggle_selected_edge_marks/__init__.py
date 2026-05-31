bl_info = {
    "name": "Toggle Selected Edge Marks",
    "author": "Custom",
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "category": "Mesh",
    "description": "Toggle seam, edge bevel weight, and sharpness on selected edges individually",
}

import bpy
import bmesh
from bpy.props import EnumProperty, BoolProperty


addon_keymaps = []


# ---------------------------------------------------------
# Keymap helpers
# ---------------------------------------------------------

KEY_ITEMS = [
    ('NONE', 'None', 'No shortcut'),

    ('A', 'A', ''),
    ('B', 'B', ''),
    ('C', 'C', ''),
    ('D', 'D', ''),
    ('E', 'E', ''),
    ('F', 'F', ''),
    ('G', 'G', ''),
    ('H', 'H', ''),
    ('I', 'I', ''),
    ('J', 'J', ''),
    ('K', 'K', ''),
    ('L', 'L', ''),
    ('M', 'M', ''),
    ('N', 'N', ''),
    ('O', 'O', ''),
    ('P', 'P', ''),
    ('Q', 'Q', ''),
    ('R', 'R', ''),
    ('S', 'S', ''),
    ('T', 'T', ''),
    ('U', 'U', ''),
    ('V', 'V', ''),
    ('W', 'W', ''),
    ('X', 'X', ''),
    ('Y', 'Y', ''),
    ('Z', 'Z', ''),

    ('ONE', '1', ''),
    ('TWO', '2', ''),
    ('THREE', '3', ''),
    ('FOUR', '4', ''),
    ('FIVE', '5', ''),
    ('SIX', '6', ''),
    ('SEVEN', '7', ''),
    ('EIGHT', '8', ''),
    ('NINE', '9', ''),
    ('ZERO', '0', ''),

    ('F1', 'F1', ''),
    ('F2', 'F2', ''),
    ('F3', 'F3', ''),
    ('F4', 'F4', ''),
    ('F5', 'F5', ''),
    ('F6', 'F6', ''),
    ('F7', 'F7', ''),
    ('F8', 'F8', ''),
    ('F9', 'F9', ''),
    ('F10', 'F10', ''),
    ('F11', 'F11', ''),
    ('F12', 'F12', ''),
]


def update_keymaps(self, context):
    unregister_keymaps()
    register_keymaps()


def get_addon_prefs():
    addon = bpy.context.preferences.addons.get(__name__)
    if addon:
        return addon.preferences
    return None


def add_keymap_item(km, operator_id, key, ctrl=False, alt=False, shift=False):
    if key == 'NONE':
        return None

    return km.keymap_items.new(
        operator_id,
        type=key,
        value='PRESS',
        ctrl=ctrl,
        alt=alt,
        shift=shift
    )


def register_keymaps():
    prefs = get_addon_prefs()
    if prefs is None:
        return

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if not kc:
        return

    km = kc.keymaps.new(name='Mesh', space_type='EMPTY')

    kmi = add_keymap_item(
        km,
        "mesh.toggle_each_selected_seam",
        prefs.seam_key,
        prefs.seam_ctrl,
        prefs.seam_alt,
        prefs.seam_shift
    )
    if kmi:
        addon_keymaps.append((km, kmi))

    kmi = add_keymap_item(
        km,
        "mesh.toggle_each_selected_edge_bevel_weight",
        prefs.bevel_key,
        prefs.bevel_ctrl,
        prefs.bevel_alt,
        prefs.bevel_shift
    )
    if kmi:
        addon_keymaps.append((km, kmi))

    kmi = add_keymap_item(
        km,
        "mesh.toggle_each_selected_sharp",
        prefs.sharp_key,
        prefs.sharp_ctrl,
        prefs.sharp_alt,
        prefs.sharp_shift
    )
    if kmi:
        addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass

    addon_keymaps.clear()


# ---------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------

def get_edit_mesh_objects(context):
    objs = getattr(context, "objects_in_mode_unique_data", None)

    if objs:
        return [obj for obj in objs if obj.type == 'MESH']

    obj = context.edit_object
    if obj and obj.type == 'MESH':
        return [obj]

    return []


def collect_target_edges(bm):
    target_edges = set()

    # 선택된 Edge
    for e in bm.edges:
        if e.select:
            target_edges.add(e)

    # 선택된 Face의 구성 Edge
    for f in bm.faces:
        if f.select:
            for e in f.edges:
                target_edges.add(e)

    return target_edges


def ensure_bevel_weight_layer(bm):
    """
    Blender 4.x / 5.x 기준 Edge Bevel Weight attribute.
    """
    layer = bm.edges.layers.float.get("bevel_weight_edge")

    if layer is None:
        layer = bm.edges.layers.float.new("bevel_weight_edge")

    return layer


# ---------------------------------------------------------
# Operators
# ---------------------------------------------------------

class MESH_OT_toggle_each_selected_seam(bpy.types.Operator):
    bl_idname = "mesh.toggle_each_selected_seam"
    bl_label = "Toggle Each Selected Seam"
    bl_description = "Toggle seam individually on selected edges or selected face edges"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and len(get_edit_mesh_objects(context)) > 0

    def execute(self, context):
        total = 0

        for obj in get_edit_mesh_objects(context):
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            target_edges = collect_target_edges(bm)

            for e in target_edges:
                e.seam = not e.seam

            total += len(target_edges)
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if total == 0:
            self.report({'WARNING'}, "No selected edges or faces")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Toggled seam on {total} edges")
        return {'FINISHED'}


class MESH_OT_toggle_each_selected_edge_bevel_weight(bpy.types.Operator):
    bl_idname = "mesh.toggle_each_selected_edge_bevel_weight"
    bl_label = "Toggle Each Selected Edge Bevel Weight"
    bl_description = "Toggle edge bevel weight individually between 0 and 1"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and len(get_edit_mesh_objects(context)) > 0

    def execute(self, context):
        total = 0

        for obj in get_edit_mesh_objects(context):
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            # Bevel weight layer 생성 후 edge를 수집해야 BMEdge reference error를 피할 수 있음
            bevel_layer = ensure_bevel_weight_layer(bm)

            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            target_edges = collect_target_edges(bm)

            for e in target_edges:
                current_value = e[bevel_layer]
                e[bevel_layer] = 0.0 if current_value > 0.0 else 1.0

            total += len(target_edges)
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if total == 0:
            self.report({'WARNING'}, "No selected edges or faces")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Toggled bevel weight on {total} edges")
        return {'FINISHED'}


class MESH_OT_toggle_each_selected_sharp(bpy.types.Operator):
    bl_idname = "mesh.toggle_each_selected_sharp"
    bl_label = "Toggle Each Selected Sharp"
    bl_description = "Toggle sharpness individually on selected edges or selected face edges"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and len(get_edit_mesh_objects(context)) > 0

    def execute(self, context):
        total = 0

        for obj in get_edit_mesh_objects(context):
            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            target_edges = collect_target_edges(bm)

            for e in target_edges:
                # e.smooth == True  : sharp 아님
                # e.smooth == False : sharp
                e.smooth = not e.smooth

            total += len(target_edges)
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if total == 0:
            self.report({'WARNING'}, "No selected edges or faces")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Toggled sharp on {total} edges")
        return {'FINISHED'}


# ---------------------------------------------------------
# Addon Preferences
# ---------------------------------------------------------

class TOGGLE_EDGE_MARKS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    seam_key: EnumProperty(
        name="Key",
        items=KEY_ITEMS,
        default='B',
        update=update_keymaps
    )
    seam_ctrl: BoolProperty(name="Ctrl", default=False, update=update_keymaps)
    seam_alt: BoolProperty(name="Alt", default=False, update=update_keymaps)
    seam_shift: BoolProperty(name="Shift", default=True, update=update_keymaps)

    bevel_key: EnumProperty(
        name="Key",
        items=KEY_ITEMS,
        default='C',
        update=update_keymaps
    )
    bevel_ctrl: BoolProperty(name="Ctrl", default=False, update=update_keymaps)
    bevel_alt: BoolProperty(name="Alt", default=False, update=update_keymaps)
    bevel_shift: BoolProperty(name="Shift", default=True, update=update_keymaps)

    sharp_key: EnumProperty(
        name="Key",
        items=KEY_ITEMS,
        default='V',
        update=update_keymaps
    )
    sharp_ctrl: BoolProperty(name="Ctrl", default=False, update=update_keymaps)
    sharp_alt: BoolProperty(name="Alt", default=False, update=update_keymaps)
    sharp_shift: BoolProperty(name="Shift", default=True, update=update_keymaps)

    def draw_hotkey_row(self, layout, title, key_prop, ctrl_prop, alt_prop, shift_prop):
        box = layout.box()
        box.label(text=title)

        row = box.row(align=True)
        row.prop(self, key_prop, text="")
        row.prop(self, ctrl_prop)
        row.prop(self, alt_prop)
        row.prop(self, shift_prop)

    def draw(self, context):
        layout = self.layout

        layout.label(text="Hotkeys", icon='KEYINGSET')

        self.draw_hotkey_row(
            layout,
            "Toggle Each Selected Seam",
            "seam_key",
            "seam_ctrl",
            "seam_alt",
            "seam_shift"
        )

        self.draw_hotkey_row(
            layout,
            "Toggle Each Selected Edge Bevel Weight",
            "bevel_key",
            "bevel_ctrl",
            "bevel_alt",
            "bevel_shift"
        )

        self.draw_hotkey_row(
            layout,
            "Toggle Each Selected Sharp",
            "sharp_key",
            "sharp_ctrl",
            "sharp_alt",
            "sharp_shift"
        )

        layout.separator()
        layout.label(text="Changes are stored in Blender Preferences.", icon='INFO')


classes = (
    MESH_OT_toggle_each_selected_seam,
    MESH_OT_toggle_each_selected_edge_bevel_weight,
    MESH_OT_toggle_each_selected_sharp,
    TOGGLE_EDGE_MARKS_AddonPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_keymaps()


def unregister():
    unregister_keymaps()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
