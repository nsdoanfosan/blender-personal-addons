import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, PointerProperty, BoolProperty


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def get_selected_objects(context):
    objs = list(context.selected_objects)
    if not objs and context.active_object:
        objs = [context.active_object]
    return objs


def get_object_collections(obj):
    return list(obj.users_collection)


def build_collection_tree(root_collection):
    result = []
    path_map = {}

    def walk(col, path, depth=0, is_last=True, guide_flags=None):
        if guide_flags is None:
            guide_flags = []

        if depth == 0:
            label = col.name
        else:
            prefix = ""
            for has_vertical in guide_flags[:-1]:
                prefix += "│   " if has_vertical else "    "
            prefix += "└─ " if is_last else "├─ "
            label = prefix + col.name

        item = {
            "collection": col,
            "path": path,
            "label": label,
            "depth": depth,
            "is_last": is_last,
        }
        result.append(item)
        path_map[path] = col

        children = list(col.children)
        child_count = len(children)

        for i, child in enumerate(children):
            child_is_last = (i == child_count - 1)
            child_path = path + "/" + child.name
            child_guides = list(guide_flags)
            if depth >= 0:
                child_guides.append(not is_last)
            walk(
                child,
                child_path,
                depth=depth + 1,
                is_last=child_is_last,
                guide_flags=child_guides,
            )

    walk(root_collection, root_collection.name, depth=0, is_last=True, guide_flags=[])
    return result, path_map


def ensure_object_in_at_least_one_collection(obj, fallback_collection):
    if not obj.users_collection:
        fallback_collection.objects.link(obj)


def get_layer_collection_path(view_layer, collection_path):
    path_parts = collection_path.split("/")
    layer_collection = view_layer.layer_collection

    if not path_parts or path_parts[0] != layer_collection.collection.name:
        return []

    result = [layer_collection]
    for collection_name in path_parts[1:]:
        layer_collection = next(
            (
                child
                for child in layer_collection.children
                if child.collection.name == collection_name
            ),
            None,
        )
        if layer_collection is None:
            return []
        result.append(layer_collection)

    return result


def ensure_collection_path_in_view_layer(view_layer, collection_path):
    layer_collections = get_layer_collection_path(view_layer, collection_path)
    if not layer_collections:
        return False

    for layer_collection in layer_collections:
        layer_collection.exclude = False

    return True


def filter_match(text, keyword):
    if not keyword:
        return True
    return keyword.lower() in text.lower()


# ---------------------------------------------------
# Properties
# ---------------------------------------------------

class QCM_Properties(PropertyGroup):
    search: StringProperty(
        name="Search",
        description="Filter collections by name or path",
        default=""
    )

    show_current_only: BoolProperty(
        name="Current Only",
        description="Show only collections linked to the active object",
        default=False
    )


# ---------------------------------------------------
# Operators
# ---------------------------------------------------

class OBJECT_OT_qcm_move_to_collection(Operator):
    bl_idname = "object.qcm_move_to_collection"
    bl_label = "Move to Collection"
    bl_description = "Move selected objects to this collection"
    bl_options = {"REGISTER", "UNDO"}

    collection_path: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and (context.selected_objects or context.active_object)

    def execute(self, context):
        _, path_map = build_collection_tree(context.scene.collection)
        target = path_map.get(self.collection_path)

        if target is None:
            self.report({"ERROR"}, f"Collection path not found: {self.collection_path}")
            return {"CANCELLED"}

        if not ensure_collection_path_in_view_layer(context.view_layer, self.collection_path):
            self.report(
                {"ERROR"},
                f"Collection is not available in the current View Layer: {self.collection_path}"
            )
            return {"CANCELLED"}

        objs = get_selected_objects(context)
        if not objs:
            self.report({"WARNING"}, "No objects selected")
            return {"CANCELLED"}

        moved_count = 0

        for obj in objs:
            current_collections = list(obj.users_collection)

            if len(current_collections) == 1 and current_collections[0] == target:
                continue

            if obj.name not in target.objects:
                target.objects.link(obj)

            for col in current_collections:
                if col != target:
                    try:
                        col.objects.unlink(obj)
                    except RuntimeError:
                        pass

            ensure_object_in_at_least_one_collection(obj, target)
            moved_count += 1

        self.report({"INFO"}, f"Moved {moved_count} object(s) to: {target.name}")
        return {"FINISHED"}


class OBJECT_OT_qcm_link_to_collection(Operator):
    bl_idname = "object.qcm_link_to_collection"
    bl_label = "Link to Collection"
    bl_description = "Link selected objects to this collection"
    bl_options = {"REGISTER", "UNDO"}

    collection_path: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and (context.selected_objects or context.active_object)

    def execute(self, context):
        _, path_map = build_collection_tree(context.scene.collection)
        target = path_map.get(self.collection_path)

        if target is None:
            self.report({"ERROR"}, f"Collection path not found: {self.collection_path}")
            return {"CANCELLED"}

        if not ensure_collection_path_in_view_layer(context.view_layer, self.collection_path):
            self.report(
                {"ERROR"},
                f"Collection is not available in the current View Layer: {self.collection_path}"
            )
            return {"CANCELLED"}

        objs = get_selected_objects(context)
        if not objs:
            self.report({"WARNING"}, "No objects selected")
            return {"CANCELLED"}

        linked_count = 0

        for obj in objs:
            if obj.name not in target.objects:
                target.objects.link(obj)
                linked_count += 1

        self.report({"INFO"}, f"Linked {linked_count} object(s) to: {target.name}")
        return {"FINISHED"}


class OBJECT_OT_qcm_unlink_from_collection(Operator):
    bl_idname = "object.qcm_unlink_from_collection"
    bl_label = "Unlink from Collection"
    bl_description = "Unlink selected objects from this collection"
    bl_options = {"REGISTER", "UNDO"}

    collection_path: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and (context.selected_objects or context.active_object)

    def execute(self, context):
        _, path_map = build_collection_tree(context.scene.collection)
        target = path_map.get(self.collection_path)

        if target is None:
            self.report({"ERROR"}, f"Collection path not found: {self.collection_path}")
            return {"CANCELLED"}

        objs = get_selected_objects(context)
        if not objs:
            self.report({"WARNING"}, "No objects selected")
            return {"CANCELLED"}

        skipped = 0
        unlinked = 0

        for obj in objs:
            current_cols = list(obj.users_collection)

            if len(current_cols) <= 1 and target in current_cols:
                skipped += 1
                continue

            if target in current_cols:
                try:
                    target.objects.unlink(obj)
                    unlinked += 1
                except RuntimeError:
                    pass

        msg = f"Unlinked {unlinked} object(s) from: {target.name}"
        if skipped:
            msg += f" | Skipped {skipped} last-link object(s)"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# ---------------------------------------------------
# UI
# ---------------------------------------------------

class OBJECT_PT_qcm_panel(Panel):
    bl_label = "Quick Collection Move"
    bl_idname = "OBJECT_PT_qcm_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.qcm_props
        obj = context.active_object

        all_cols, _ = build_collection_tree(scene.collection)
        col_to_path = {item["collection"]: item["path"] for item in all_cols}

        selected = get_selected_objects(context)
        selected_count = len(selected)

        obj_cols = get_object_collections(obj)
        obj_col_paths = {col_to_path[c] for c in obj_cols if c in col_to_path}

        header = layout.box()
        col = header.column(align=True)
        col.label(text=f"Active: {obj.name}", icon="OBJECT_DATA")
        col.label(text=f"Selected: {selected_count}", icon="RESTRICT_SELECT_OFF")

        tools = layout.box()
        tools.prop(props, "search", text="", icon="VIEWZOOM")
        tools.prop(props, "show_current_only", toggle=True)

        current_box = layout.box()
        current_box.label(text="Current Collections", icon="OUTLINER_COLLECTION")

        if obj_cols:
            sorted_current = sorted(
                [c for c in obj_cols if c in col_to_path],
                key=lambda c: col_to_path[c].lower()
            )
            for col_obj in sorted_current:
                path = col_to_path[col_obj]
                row = current_box.row(align=True)
                row.scale_y = 0.95
                row.label(text=path, icon="COLLECTION_COLOR_04")
                op = row.operator(
                    "object.qcm_unlink_from_collection",
                    text="",
                    icon="X"
                )
                op.collection_path = path
        else:
            current_box.label(text="No linked collections", icon="INFO")

        all_box = layout.box()
        all_box.label(text="All Scene Collections", icon="OUTLINER")

        search_keyword = props.search.strip()
        visible_count = 0

        for item in all_cols:
            col_obj = item["collection"]
            path = item["path"]
            label = item["label"]

            if props.show_current_only and path not in obj_col_paths:
                continue

            if not (
                filter_match(col_obj.name, search_keyword)
                or filter_match(path, search_keyword)
            ):
                continue

            visible_count += 1
            is_current = path in obj_col_paths

            row = all_box.row(align=True)
            row.scale_y = 1.0

            name_row = row.row(align=True)
            name_row.alignment = 'LEFT'
            icon = "COLLECTION_COLOR_04" if is_current else "OUTLINER_COLLECTION"
            name_row.label(text=label, icon=icon)

            if is_current:
                badge = row.row(align=True)
                badge.enabled = False
                badge.label(text="Current", icon="CHECKMARK")

            move = row.operator(
                "object.qcm_move_to_collection",
                text="Move",
                emboss=True,
                icon="FILE_PARENT"
            )
            move.collection_path = path

            link = row.operator(
                "object.qcm_link_to_collection",
                text="Link",
                emboss=True,
                icon="LINKED"
            )
            link.collection_path = path

        if visible_count == 0:
            all_box.label(text="No collections match", icon="INFO")


# ---------------------------------------------------
# Register
# ---------------------------------------------------

classes = (
    QCM_Properties,
    OBJECT_OT_qcm_move_to_collection,
    OBJECT_OT_qcm_link_to_collection,
    OBJECT_OT_qcm_unlink_from_collection,
    OBJECT_PT_qcm_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.qcm_props = PointerProperty(type=QCM_Properties)


def unregister():
    del bpy.types.Scene.qcm_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
