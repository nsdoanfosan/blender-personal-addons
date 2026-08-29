import addon_utils
import bpy


MODULE = "ta_tools"


addon_utils.enable(MODULE, default_set=False)
try:
    from ta_tools.ta_tool import (
        _ta_collect_uv_target_objects,
        _ta_geometry_nodes_input_values,
    )

    source_collection = bpy.data.collections.new("TA_GPro_SourceCollection")
    bpy.context.scene.collection.children.link(source_collection)
    source_mesh = bpy.data.meshes.new("TA_GPro_SourceMesh")
    source = bpy.data.objects.new("TA_GPro_Source", source_mesh)
    source_collection.objects.link(source)

    instance_mesh = bpy.data.meshes.new("TA_GPro_InstanceMesh")
    instance = bpy.data.objects.new("TA_GPro_Instance", instance_mesh)
    bpy.context.scene.collection.objects.link(instance)

    node_group = bpy.data.node_groups.new("gPro_Instance", "GeometryNodeTree")
    collection_socket = node_group.interface.new_socket(
        name="Collection",
        in_out="INPUT",
        socket_type="NodeSocketCollection",
    )
    modifier = instance.modifiers.new("gPro_Instance", "NODES")
    modifier.node_group = node_group
    modifier.properties.inputs[collection_socket.identifier]["value"] = source_collection

    targets = _ta_collect_uv_target_objects([instance])
    assert instance in targets, targets
    assert source in targets, targets

    class LegacyModifier:
        def keys(self):
            return ("Socket_2",)

        def get(self, key):
            return source_collection if key == "Socket_2" else None

    assert list(_ta_geometry_nodes_input_values(LegacyModifier())) == [source_collection]
    print("TA_TOOLS_GPRO_API52_OK")
finally:
    addon_utils.disable(MODULE, default_set=False)
