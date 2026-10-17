"""Expose the installed MCP bridge's start command in Blender's F3 search."""

import importlib

import bpy


class WM_OT_ta_start_mcp_server(bpy.types.Operator):
    bl_idname = "wm.ta_start_mcp_server"
    bl_label = "MCP: Start Server"
    bl_description = "Start the MCP bridge server for this Blender window"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            native_operator = bpy.ops.blmcp.server_start
            rna = native_operator.get_rna_type()
            operator_class = bpy.types.Operator.bl_rna_get_subclass_py(rna.identifier)
        except (AttributeError, RuntimeError):
            self.report({"ERROR"}, "Enable the Blender MCP add-on in Preferences first")
            return {"CANCELLED"}

        try:
            # Resolve the installed operator's package, including extension namespaces.
            bridge = importlib.import_module(
                operator_class.__module__ + ".mcp_to_blender_server"
            )
            if bridge.is_running():
                self.report({"INFO"}, "MCP server is already running")
                return {"FINISHED"}
            return native_operator("EXEC_DEFAULT")
        except (ImportError, AttributeError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


classes = (WM_OT_ta_start_mcp_server,)


def draw_window_menu(self, context):
    self.layout.separator()
    self.layout.operator(WM_OT_ta_start_mcp_server.bl_idname, icon="PLAY")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Normal F3 searches menu entries; REGISTER alone only covers Operator Search.
    bpy.types.TOPBAR_MT_window.append(draw_window_menu)


def unregister():
    bpy.types.TOPBAR_MT_window.remove(draw_window_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
