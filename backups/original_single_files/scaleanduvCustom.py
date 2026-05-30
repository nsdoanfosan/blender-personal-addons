import bpy

# You should be able to customize the keybindings regularly from View 3D
# Cheers friend, enjoy!

bl_info = {
    "name": "Scale Align",
    "description": "Zero scale any axis, quickly.",
    "author": "Amaral Krichman",
    "version": (0, 0, 1),
    "blender": (2, 80, 0),
    "location": "",
    "warning": "",
    "wiki_url": "",
    "category": "Object",
}


class OBJECT_OT_scale_align(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "object.scale_align"
    bl_label = "Scale Align"
    bl_options = {'REGISTER', 'UNDO'}
    
    parameter : bpy.props.EnumProperty(items=[
    ('X', "X", ""),
                                    ('Y', "Y", ""),
                                    ('Z', "Z", ""),
                                    ('A', "All", ""),
                                    ('LEFT', "LEFT", ""),
                                    ('RIGHT', "RIGHT", ""),],
                                    name="UV Parameter", default='X')
    
    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def scale(self, context):
        if self.parameter == 'LEFT':
             #S, X, 0:
            bpy.ops.uv.muv_flip_rotate_uv(rotate=1, seams=False)
        elif self.parameter == 'RIGHT':
            #S, Y, 0
            bpy.ops.uv.muv_flip_rotate_uv(rotate=3, seams=False)
        elif self.parameter == 'X':
             #S, X, 0:
            bpy.ops.transform.resize(value=(0, 1, 1), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(True, False, False), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
        elif self.parameter == 'Y':
            #S, Y, 0
            bpy.ops.transform.resize(value=(1, 0, 1), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(False, True, False), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
        elif self.parameter == 'Z':
            #S, Z, 0
            bpy.ops.transform.resize(value=(1, 1, 0), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(False, False, True), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
        elif self.parameter == 'A':
            # All of the above at once. Oh boy, looks scary.
            bpy.ops.transform.resize(value=(0, 1, 1), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(True, False, False), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
            bpy.ops.transform.resize(value=(1, 0, 1), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(False, True, False), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
            bpy.ops.transform.resize(value=(1, 1, 0), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', constraint_axis=(False, False, True), mirror=True, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False)
  
  
    def execute(self, context):
        self.scale(context)
        return {'FINISHED'}


addon_keymaps = []

def register():
    bpy.utils.register_class(OBJECT_OT_scale_align)

    idname = OBJECT_OT_scale_align.bl_idname   
    kc = bpy.context.window_manager.keyconfigs.addon
    
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    
    kmi = km.keymap_items.new(idname, 'X', 'CLICK', alt=True, shift=True)
    kmi.properties.parameter = 'X'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(idname, 'C', 'CLICK', alt=True, shift=True)
    kmi.properties.parameter = 'Y'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(idname, 'V', 'CLICK', alt=True, shift=True)
    kmi.properties.parameter = 'Z'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(idname, 'FOUR', 'CLICK', alt=True, shift=True)
    kmi.properties.parameter = 'A'
    addon_keymaps.append((km, kmi))
    
    kmi = km.keymap_items.new(idname, 'LEFT_ARROW', 'CLICK', ctrl=True)
    kmi.properties.parameter = 'LEFT'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(idname, 'RIGHT_ARROW', 'CLICK', ctrl=True)
    kmi.properties.parameter = 'RIGHT'
    addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(OBJECT_OT_scale_align)


if __name__ == "__main__":
    register()



