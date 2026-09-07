"""By-value references; Blender RNA subdata must not survive undo/load in caches."""
import bpy


def id_key(value):
    return (value.session_uid, value.name_full) if value is not None else None


def resolve_id(collection, key):
    if key is None:
        return None
    uid, name = key
    value = collection.get(name)
    if value is not None and value.session_uid == uid:
        return value
    # A name can change while the same ID remains live. Never accept a new ID
    # that merely reuses the old object's name.
    return next((value for value in collection if value.session_uid == uid), None)


def layer_key(view_layer):
    return (id_key(view_layer.id_data), view_layer.name, view_layer.as_pointer())


def resolve_layer(key):
    scene_key, name, pointer = key
    scene = resolve_id(bpy.data.scenes, scene_key)
    if scene is None:
        return None
    # Pointer values are compared only against CURRENT RNA, never dereferenced.
    # The name resolves a rebuilt ViewLayer after undo; the pointer handles rename.
    return next((layer for layer in scene.view_layers if layer.as_pointer() == pointer),
                scene.view_layers.get(name))


def resolve_space(pointer):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D' and space.as_pointer() == pointer:
                    return space
    return None
