bl_info = {
    "name": "WIRE/BOUNDS Selection Visibility",
    "author": "PARK, Codex",
    "version": (1, 1, 2),
    "blender": (5, 1, 0),
    "location": "Background (no UI)",
    "description": "Hide WIRE/BOUNDS helpers until they are activated in the Outliner",
    "category": "3D View",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty


TARGET_DISPLAY_TYPES = {"WIRE", "BOUNDS"}

_MSGBUS_OWNER = object()
_active_name_by_view_layer = {}
_shown_names_by_view_layer = {}
_is_syncing = False
_is_unregistering = False


def _view_layer_key(view_layer):
    return view_layer.as_pointer()


def _layer_object(view_layer, name):
    if not name:
        return None
    return view_layer.objects.get(name)


def _iter_window_scene_view_layers():
    seen = set()
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager:
        for window in window_manager.windows:
            scene = window.scene
            view_layer = window.view_layer
            key = (scene.as_pointer(), view_layer.as_pointer())
            if key in seen:
                continue
            seen.add(key)
            yield scene, view_layer

    scene = getattr(bpy.context, "scene", None)
    view_layer = getattr(bpy.context, "view_layer", None)
    if not seen and scene and view_layer:
        yield scene, view_layer


def _set_object_property(obj, name, value):
    if getattr(obj, name) == value:
        return False
    setattr(obj, name, value)
    return True


def _has_external_geometry_preview(obj):
    """Return whether *obj* is a renderable mesh owned by a preview add-on.

    Unreal Material Bridge marks its viewport-only Geometry Nodes modifiers with
    ``send2ue_preview_only``.  Those objects can deliberately use WIRE display
    while the modifier supplies the visible result, so treating them as helper
    objects makes the complete preview disappear as soon as selection changes.
    """
    return any(
        modifier.type == "NODES"
        and getattr(modifier, "node_group", None) is not None
        and modifier.node_group.get("send2ue_preview_only", False)
        for modifier in obj.modifiers
    )


def _is_excluded(obj):
    return obj.wbsv_excluded or _has_external_geometry_preview(obj)


def _capture_object(obj, view_layer):
    if obj.wbsv_managed or _is_excluded(obj):
        return False
    if obj.display_type not in TARGET_DISPLAY_TYPES:
        return False

    obj.wbsv_original_display_type = obj.display_type
    obj.wbsv_original_hide_viewport = obj.hide_viewport
    obj.wbsv_original_hide_select = obj.hide_select
    obj.wbsv_original_hidden = obj.hide_get(view_layer=view_layer)
    obj.wbsv_managed = True
    return True


def _show_object(obj, view_layer, select=False):
    changed = False

    # A globally disabled object can still become active from the Outliner, but it
    # must re-enter the view layer before Blender will allow it to be selected.
    changed |= _set_object_property(obj, "hide_viewport", False)
    changed |= _set_object_property(obj, "hide_select", False)
    if obj.hide_get(view_layer=view_layer):
        obj.hide_set(False, view_layer=view_layer)
        changed = True
    changed |= _set_object_property(obj, "display_type", "WIRE")

    if select and not obj.select_get(view_layer=view_layer):
        obj.select_set(True, view_layer=view_layer)
        changed = True
    return changed


def _hide_object(obj, view_layer, deselect=False):
    changed = False
    original_display = obj.wbsv_original_display_type
    if original_display in TARGET_DISPLAY_TYPES:
        changed |= _set_object_property(obj, "display_type", original_display)
    changed |= _set_object_property(
        obj, "hide_select", obj.wbsv_original_hide_select
    )
    changed |= _set_object_property(
        obj, "hide_viewport", obj.wbsv_original_hide_viewport
    )
    if not obj.hide_get(view_layer=view_layer):
        obj.hide_set(True, view_layer=view_layer)
        changed = True
    if deselect and obj.select_get(view_layer=view_layer):
        obj.select_set(False, view_layer=view_layer)
        changed = True
    return changed


def _restore_object(obj, view_layer):
    if not obj.wbsv_managed:
        return False

    changed = False
    original_display = obj.wbsv_original_display_type
    if original_display in TARGET_DISPLAY_TYPES:
        changed |= _set_object_property(obj, "display_type", original_display)
    changed |= _set_object_property(
        obj, "hide_select", obj.wbsv_original_hide_select
    )
    changed |= _set_object_property(
        obj, "hide_viewport", obj.wbsv_original_hide_viewport
    )
    original_hidden = obj.wbsv_original_hidden
    if obj.hide_get(view_layer=view_layer) != original_hidden:
        obj.hide_set(original_hidden, view_layer=view_layer)
        changed = True
    return changed


def _release_object_after_display_change(obj):
    """Stop managing an object whose display mode was changed by the user.

    Display changes made by this add-on happen while ``_is_syncing`` is true, so
    reaching this function means an external edit changed a managed helper away
    from WIRE/BOUNDS.  Preserve that chosen display mode and restore only the
    visibility/selectability state captured when management began.
    """
    if not obj.wbsv_managed or obj.display_type in TARGET_DISPLAY_TYPES:
        return False

    chosen_display = obj.display_type
    changed = False
    changed |= _set_object_property(
        obj, "hide_select", obj.wbsv_original_hide_select
    )
    changed |= _set_object_property(
        obj, "hide_viewport", obj.wbsv_original_hide_viewport
    )

    for scene in bpy.data.scenes:
        for view_layer in scene.view_layers:
            if _layer_object(view_layer, obj.name) is not obj:
                continue
            if obj.hide_get(view_layer=view_layer) != obj.wbsv_original_hidden:
                obj.hide_set(obj.wbsv_original_hidden, view_layer=view_layer)
                changed = True

    # Keep the user's explicit SOLID/TEXTURED change.  This assignment is mostly
    # documentary, but also protects it from future changes to the restoration
    # code above.
    changed |= _set_object_property(obj, "display_type", chosen_display)
    obj.wbsv_managed = False
    for shown in _shown_names_by_view_layer.values():
        shown.discard(obj.name)
    return changed


def _restore_all_objects():
    managed_objects = [obj for obj in bpy.data.objects if obj.wbsv_managed]
    if not managed_objects:
        return

    for scene in bpy.data.scenes:
        for view_layer in scene.view_layers:
            for obj in managed_objects:
                layer_obj = _layer_object(view_layer, obj.name)
                if layer_obj is obj:
                    _restore_object(obj, view_layer)

    for obj in managed_objects:
        original_display = obj.wbsv_original_display_type
        if original_display in TARGET_DISPLAY_TYPES:
            _set_object_property(obj, "display_type", original_display)
        _set_object_property(obj, "hide_select", obj.wbsv_original_hide_select)
        _set_object_property(
            obj, "hide_viewport", obj.wbsv_original_hide_viewport
        )
        obj.wbsv_managed = False


def _initialize_view_layer(_scene, view_layer):
    key = _view_layer_key(view_layer)
    active = view_layer.objects.active
    shown = set()

    for obj in view_layer.objects:
        _capture_object(obj, view_layer)
        if not obj.wbsv_managed or _is_excluded(obj):
            continue
        if obj is active:
            _show_object(obj, view_layer, select=True)
            shown.add(obj.name)
        else:
            _hide_object(obj, view_layer, deselect=True)

    _active_name_by_view_layer[key] = active.name if active else ""
    _shown_names_by_view_layer[key] = shown


def _initialize_all_view_layers():
    global _is_syncing
    if _is_syncing or _is_unregistering:
        return

    _is_syncing = True
    try:
        for scene in bpy.data.scenes:
            for view_layer in scene.view_layers:
                _initialize_view_layer(scene, view_layer)
    finally:
        _is_syncing = False


def _initialize_after_register():
    """Run once after Blender leaves addon_utils' restricted register context."""
    if _is_unregistering:
        return None
    if hasattr(bpy.data, "scenes"):
        _initialize_all_view_layers()
    return None


def _sync_active_transition(_scene, view_layer):
    key = _view_layer_key(view_layer)
    active = view_layer.objects.active
    active_name = active.name if active else ""
    previous_name = _active_name_by_view_layer.get(key, "")
    shown = _shown_names_by_view_layer.setdefault(key, set())

    if active_name == previous_name:
        return False

    changed = False

    # Only objects that this add-on has actually revealed need inspection. This
    # keeps a selection change O(number of shown helpers), not O(scene objects).
    for name in tuple(shown):
        obj = _layer_object(view_layer, name)
        if obj is None or not obj.wbsv_managed or _is_excluded(obj):
            shown.discard(name)
            continue
        if obj is active or obj.select_get(view_layer=view_layer):
            continue
        changed |= _hide_object(obj, view_layer)
        shown.discard(name)

    if active is not None:
        _capture_object(active, view_layer)
        if active.wbsv_managed and not _is_excluded(active):
            changed |= _show_object(active, view_layer, select=True)
            shown.add(active.name)

    _active_name_by_view_layer[key] = active_name
    return changed


def _on_active_object_changed():
    global _is_syncing
    if _is_syncing or _is_unregistering:
        return

    _is_syncing = True
    try:
        for scene, view_layer in _iter_window_scene_view_layers():
            _sync_active_transition(scene, view_layer)
    finally:
        _is_syncing = False


def _capture_new_targets(_scene, view_layer):
    key = _view_layer_key(view_layer)
    shown = _shown_names_by_view_layer.setdefault(key, set())
    active = view_layer.objects.active

    # display_type changes are rare. A single scan here replaces a handler that
    # would otherwise run on every dependency-graph evaluation and animation frame.
    for obj in view_layer.objects:
        if obj.wbsv_managed or _is_excluded(obj):
            continue
        if not _capture_object(obj, view_layer):
            continue
        if obj is active or obj.select_get(view_layer=view_layer):
            _show_object(obj, view_layer, select=obj is active)
            shown.add(obj.name)
        else:
            _hide_object(obj, view_layer)


def _on_display_type_changed():
    global _is_syncing
    if _is_syncing or _is_unregistering:
        return

    _is_syncing = True
    try:
        # A managed helper that the user changes to SOLID/TEXTURED is no longer a
        # helper.  Release it before looking for newly-created WIRE/BOUNDS targets;
        # otherwise the next selection change restores the stale WIRE value.
        for obj in bpy.data.objects:
            _release_object_after_display_change(obj)
        for scene, view_layer in _iter_window_scene_view_layers():
            _capture_new_targets(scene, view_layer)
    finally:
        _is_syncing = False


def _subscribe_changes():
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, "active"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_active_object_changed,
        options={"PERSISTENT"},
    )
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Object, "display_type"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_display_type_changed,
        options={"PERSISTENT"},
    )


@persistent
def _load_post(_unused):
    _active_name_by_view_layer.clear()
    _shown_names_by_view_layer.clear()
    _subscribe_changes()
    _initialize_all_view_layers()


def _register_properties():
    bpy.types.Object.wbsv_managed = BoolProperty(default=False, options={"HIDDEN"})
    bpy.types.Object.wbsv_excluded = BoolProperty(default=False, options={"HIDDEN"})
    bpy.types.Object.wbsv_original_display_type = StringProperty(
        default="WIRE", options={"HIDDEN"}
    )
    bpy.types.Object.wbsv_original_hide_viewport = BoolProperty(
        default=False, options={"HIDDEN"}
    )
    bpy.types.Object.wbsv_original_hide_select = BoolProperty(
        default=False, options={"HIDDEN"}
    )
    bpy.types.Object.wbsv_original_hidden = BoolProperty(
        default=False, options={"HIDDEN"}
    )


def register():
    global _is_unregistering
    _is_unregistering = False

    _register_properties()
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)

    _subscribe_changes()
    if hasattr(bpy.data, "scenes"):
        _initialize_all_view_layers()
    elif not bpy.app.timers.is_registered(_initialize_after_register):
        # This is a one-shot startup callback, not a polling loop.
        bpy.app.timers.register(_initialize_after_register, first_interval=0.0)


def unregister():
    global _is_unregistering
    _is_unregistering = True

    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    if bpy.app.timers.is_registered(_initialize_after_register):
        bpy.app.timers.unregister(_initialize_after_register)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)

    _restore_all_objects()

    for name in (
        "wbsv_original_hidden",
        "wbsv_original_hide_select",
        "wbsv_original_hide_viewport",
        "wbsv_original_display_type",
        "wbsv_excluded",
        "wbsv_managed",
    ):
        if hasattr(bpy.types.Object, name):
            delattr(bpy.types.Object, name)

    _active_name_by_view_layer.clear()
    _shown_names_by_view_layer.clear()
