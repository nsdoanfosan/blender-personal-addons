bl_info = {
    "name": "Alpha Image To Mesh",
    "author": "Codex",
    "version": (1, 2, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > TA > Alpha Mesh",
    "description": "Create a mesh from the alpha channel of a selected plane's Base Color image.",
    "category": "Object",
}

import math
from collections import defaultdict

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


def _signed_area(points):
    area = 0.0
    count = len(points)
    for i, p in enumerate(points):
        q = points[(i + 1) % count]
        area += p[0] * q[1] - q[0] * p[1]
    return area * 0.5


def _point_in_polygon(point, polygon):
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, pi in enumerate(polygon):
        pj = polygon[j]
        if ((pi[1] > y) != (pj[1] > y)):
            cross_x = (pj[0] - pi[0]) * (y - pi[1]) / (pj[1] - pi[1]) + pi[0]
            if x < cross_x:
                inside = not inside
        j = i
    return inside


def _perpendicular_distance(point, start, end):
    sx, sy = start
    ex, ey = end
    px, py = point
    dx = ex - sx
    dy = ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-12:
        return math.hypot(px - sx, py - sy)
    t = ((px - sx) * dx + (py - sy) * dy) / length_sq
    nearest_x = sx + t * dx
    nearest_y = sy + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def _rdp(points, epsilon):
    if len(points) < 3:
        return points

    best_index = 0
    best_distance = 0.0
    start = points[0]
    end = points[-1]
    for index in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[index], start, end)
        if distance > best_distance:
            best_index = index
            best_distance = distance

    if best_distance > epsilon:
        left = _rdp(points[: best_index + 1], epsilon)
        right = _rdp(points[best_index:], epsilon)
        return left[:-1] + right

    return [start, end]


def _remove_collinear(points):
    if len(points) < 4:
        return points

    cleaned = []
    for index, point in enumerate(points):
        prev_point = points[index - 1]
        next_point = points[(index + 1) % len(points)]
        ax = point[0] - prev_point[0]
        ay = point[1] - prev_point[1]
        bx = next_point[0] - point[0]
        by = next_point[1] - point[1]
        if ax * by - ay * bx != 0:
            cleaned.append(point)
    return cleaned


def _simplify_closed_loop(points, epsilon):
    points = _remove_collinear(points)
    if epsilon <= 0.0 or len(points) < 5:
        return points

    simplified = _rdp(points + [points[0]], epsilon)
    if simplified and simplified[0] == simplified[-1]:
        simplified.pop()
    return _remove_collinear(simplified)


def _load_alpha_grid_from_image(image, max_dimension):
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Image has no readable pixel data.")

    if image.source == "FILE" and not image.has_data:
        image.reload()

    stride = max(1, math.ceil(max(width, height) / max_dimension))
    sampled_width = math.ceil(width / stride)
    sampled_height = math.ceil(height / stride)
    pixels = image.pixels[:]
    alpha_grid = [[0.0] * sampled_width for _ in range(sampled_height)]

    for sy in range(sampled_height):
        y0 = sy * stride
        y1 = min(height, y0 + stride)
        for sx in range(sampled_width):
            x0 = sx * stride
            x1 = min(width, x0 + stride)
            alpha_sum = 0.0
            samples = 0
            for y in range(y0, y1):
                row = y * width * 4
                for x in range(x0, x1):
                    alpha_sum += pixels[row + x * 4 + 3]
                    samples += 1
            alpha_grid[sy][sx] = alpha_sum / max(1, samples)

    return alpha_grid, width, height, stride


def _interpolate(threshold, point_a, value_a, point_b, value_b):
    if abs(value_b - value_a) <= 1.0e-8:
        factor = 0.5
    else:
        factor = (threshold - value_a) / (value_b - value_a)
    factor = max(0.0, min(1.0, factor))
    return (
        point_a[0] + (point_b[0] - point_a[0]) * factor,
        point_a[1] + (point_b[1] - point_a[1]) * factor,
    )


def _key(point):
    return (round(point[0], 6), round(point[1], 6))


def _trace_segments_to_loops(segments):
    adjacency = defaultdict(list)
    keyed_points = {}
    unused = set()
    for point_a, point_b in segments:
        key_a = _key(point_a)
        key_b = _key(point_b)
        if key_a == key_b:
            continue
        keyed_points[key_a] = point_a
        keyed_points[key_b] = point_b
        adjacency[key_a].append(key_b)
        adjacency[key_b].append(key_a)
        unused.add(tuple(sorted((key_a, key_b))))

    loops = []
    while unused:
        edge = next(iter(unused))
        unused.remove(edge)
        start, current = edge
        previous = None
        loop = [start]

        while current != start:
            loop.append(current)
            next_key = None
            candidates = adjacency[current]
            ordered = [candidate for candidate in candidates if candidate != previous] + [
                candidate for candidate in candidates if candidate == previous
            ]
            for candidate in ordered:
                edge = tuple(sorted((current, candidate)))
                if edge in unused:
                    unused.remove(edge)
                    next_key = candidate
                    break
            if next_key is None:
                break
            previous, current = current, next_key

        if len(loop) >= 3:
            loops.append([keyed_points[point] for point in loop])

    return loops


def _trace_alpha_contours(alpha_grid, threshold):
    source_height = len(alpha_grid)
    source_width = len(alpha_grid[0]) if source_height else 0
    if source_width < 1 or source_height < 1:
        return []

    alpha_grid = (
        [[0.0] * (source_width + 2)]
        + [[0.0] + row + [0.0] for row in alpha_grid]
        + [[0.0] * (source_width + 2)]
    )
    height = len(alpha_grid)
    width = len(alpha_grid[0])

    # Edges are named around the cell: bottom, right, top, left.
    segment_table = {
        1: [("left", "bottom")],
        2: [("bottom", "right")],
        3: [("left", "right")],
        4: [("right", "top")],
        5: [("left", "top"), ("bottom", "right")],
        6: [("bottom", "top")],
        7: [("left", "top")],
        8: [("top", "left")],
        9: [("bottom", "top")],
        10: [("bottom", "left"), ("right", "top")],
        11: [("right", "top")],
        12: [("left", "right")],
        13: [("bottom", "right")],
        14: [("left", "bottom")],
    }
    segments = []

    for y in range(height - 1):
        for x in range(width - 1):
            v0 = alpha_grid[y][x]
            v1 = alpha_grid[y][x + 1]
            v2 = alpha_grid[y + 1][x + 1]
            v3 = alpha_grid[y + 1][x]
            case = 0
            if v0 >= threshold:
                case |= 1
            if v1 >= threshold:
                case |= 2
            if v2 >= threshold:
                case |= 4
            if v3 >= threshold:
                case |= 8
            if case == 0 or case == 15:
                continue

            p0 = (x - 1, y - 1)
            p1 = (x, y - 1)
            p2 = (x, y)
            p3 = (x - 1, y)
            edge_points = {
                "bottom": _interpolate(threshold, p0, v0, p1, v1),
                "right": _interpolate(threshold, p1, v1, p2, v2),
                "top": _interpolate(threshold, p3, v3, p2, v2),
                "left": _interpolate(threshold, p0, v0, p3, v3),
            }
            for edge_a, edge_b in segment_table[case]:
                segments.append((edge_points[edge_a], edge_points[edge_b]))

    return _trace_segments_to_loops(segments)


def _smooth_loop(points, iterations):
    smoothed = points
    for _ in range(iterations):
        if len(smoothed) < 3:
            return smoothed
        next_points = []
        for index, point in enumerate(smoothed):
            following = smoothed[(index + 1) % len(smoothed)]
            next_points.append(
                (point[0] * 0.75 + following[0] * 0.25, point[1] * 0.75 + following[1] * 0.25)
            )
            next_points.append(
                (point[0] * 0.25 + following[0] * 0.75, point[1] * 0.25 + following[1] * 0.75)
            )
        smoothed = next_points
    return smoothed


def _build_mesh_from_loops(
    loops,
    image_width,
    image_height,
    sample_stride,
    x_min,
    x_max,
    y_min,
    y_max,
    simplify_epsilon,
    smooth_iterations,
    min_area,
):
    x_scale = (x_max - x_min) / max(1.0, image_width / sample_stride)
    y_scale = (y_max - y_min) / max(1.0, image_height / sample_stride)
    simplify_pixels = simplify_epsilon / max(abs(x_scale), abs(y_scale), 1.0e-9)
    converted = []

    for loop in loops:
        simplified = _simplify_closed_loop(loop, simplify_pixels)
        simplified = _smooth_loop(simplified, smooth_iterations)
        world_loop = [
            (x_min + point[0] * x_scale, y_min + point[1] * y_scale)
            for point in simplified
        ]
        area = _signed_area(world_loop)
        if abs(area) >= min_area:
            converted.append({"points": world_loop, "area": area})

    for loop in converted:
        point = loop["points"][0]
        loop["depth"] = sum(
            1
            for other in converted
            if other is not loop
            and abs(other["area"]) > abs(loop["area"])
            and _point_in_polygon(point, other["points"])
        )

    outers = [loop for loop in converted if loop["depth"] % 2 == 0]
    holes = [loop for loop in converted if loop["depth"] % 2 == 1]

    vertices = []
    faces = []

    for outer in outers:
        outer_points = outer["points"]
        if _signed_area(outer_points) < 0.0:
            outer_points = list(reversed(outer_points))

        group = [outer_points]
        for hole in holes:
            first_point = hole["points"][0]
            if _point_in_polygon(first_point, outer_points):
                hole_points = hole["points"]
                if _signed_area(hole_points) > 0.0:
                    hole_points = list(reversed(hole_points))
                group.append(hole_points)

        base_index = len(vertices)
        group_vectors = []
        for polygon in group:
            poly_vectors = [Vector((x, y, 0.0)) for x, y in polygon]
            group_vectors.append(poly_vectors)
            vertices.extend((vector.x, vector.y, vector.z) for vector in poly_vectors)

        triangles = tessellate_polygon(group_vectors)
        faces.extend(tuple(base_index + index for index in triangle) for triangle in triangles)

    mesh = bpy.data.meshes.new("Alpha_Image_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh, len(outers), len(holes), len(vertices), len(faces)


def _find_upstream_image(socket, visited=None):
    if visited is None:
        visited = set()
    if not socket or not socket.is_linked:
        return None

    for link in socket.links:
        node = link.from_node
        if node in visited:
            continue
        visited.add(node)
        if node.type == "TEX_IMAGE" and node.image:
            return node.image
        for input_socket in node.inputs:
            image = _find_upstream_image(input_socket, visited)
            if image:
                return image
    return None


def _find_base_color_image(obj):
    for slot in obj.material_slots:
        material = slot.material
        if not material or not material.use_nodes or not material.node_tree:
            continue
        for node in material.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            base_color = node.inputs.get("Base Color")
            image = _find_upstream_image(base_color)
            if image:
                return image, material
    return None, None


def _plane_xy_bounds(obj):
    if obj.type != "MESH":
        raise ValueError("Select a mesh plane with an image material.")
    if not obj.data.vertices:
        raise ValueError("Selected mesh has no vertices.")

    xs = [vertex.co.x for vertex in obj.data.vertices]
    ys = [vertex.co.y for vertex in obj.data.vertices]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    if abs(x_max - x_min) <= 1.0e-9 or abs(y_max - y_min) <= 1.0e-9:
        raise ValueError("Selected object needs usable local XY size.")
    return x_min, x_max, y_min, y_max


class OBJECT_OT_alpha_mesh_from_base_color(bpy.types.Operator):
    bl_idname = "object.alpha_mesh_from_base_color"
    bl_label = "Alpha Mesh From Base Color"
    bl_options = {"REGISTER", "UNDO"}

    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        description="Pixels at or above this alpha value become solid",
        default=0.5,
        min=0.0,
        max=1.0,
    )
    max_dimension: IntProperty(
        name="Max Sample Dimension",
        description="Large images are sampled down to this size before tracing",
        default=1024,
        min=16,
        max=4096,
    )
    simplify_epsilon: FloatProperty(
        name="Simplify",
        description="Local-space outline simplification tolerance",
        default=0.003,
        min=0.0,
    )
    smooth_iterations: IntProperty(
        name="Smooth Passes",
        description="Chaikin smoothing passes applied to the traced contour",
        default=1,
        min=0,
        max=5,
    )
    min_area: FloatProperty(
        name="Minimum Area",
        description="Discard tiny islands and holes below this world-space area",
        default=0.0001,
        min=0.0,
    )
    extrusion: FloatProperty(
        name="Extrusion",
        description="Optional Solidify thickness after import",
        default=0.0,
        min=0.0,
    )
    copy_material: BoolProperty(
        name="Copy Material",
        description="Assign the source plane's material to the generated mesh",
        default=True,
    )
    hide_source: BoolProperty(
        name="Hide Source Plane",
        description="Hide the source plane after the alpha mesh is created",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        try:
            source_obj = context.object
            image, material = _find_base_color_image(source_obj)
            if not image:
                self.report({"ERROR"}, "No Image Texture was found upstream of Base Color.")
                return {"CANCELLED"}

            alpha_grid, width, height, stride = _load_alpha_grid_from_image(
                image,
                self.max_dimension,
            )
            loops = _trace_alpha_contours(alpha_grid, self.alpha_threshold)
            if not loops:
                self.report({"ERROR"}, "No alpha silhouette was found.")
                return {"CANCELLED"}

            x_min, x_max, y_min, y_max = _plane_xy_bounds(source_obj)
            mesh, outer_count, hole_count, vertex_count, face_count = _build_mesh_from_loops(
                loops,
                width,
                height,
                stride,
                x_min,
                x_max,
                y_min,
                y_max,
                self.simplify_epsilon,
                self.smooth_iterations,
                self.min_area,
            )
            if not face_count:
                self.report({"ERROR"}, "The traced silhouette could not be tessellated.")
                return {"CANCELLED"}

            name = source_obj.name
            obj = bpy.data.objects.new(f"{name}_alpha_mesh", mesh)
            context.collection.objects.link(obj)
            obj.matrix_world = source_obj.matrix_world
            if self.copy_material and material:
                obj.data.materials.append(material)
            context.view_layer.objects.active = obj
            source_obj.select_set(False)
            obj.select_set(True)

            if self.extrusion > 0.0:
                solidify = obj.modifiers.new("Alpha Thickness", "SOLIDIFY")
                solidify.thickness = self.extrusion
                solidify.offset = 0.0
            if self.hide_source:
                source_obj.hide_set(True)
                source_obj.hide_render = True

            self.report(
                {"INFO"},
                f"Created alpha mesh from {image.name}: {outer_count} islands, {hole_count} holes, "
                f"{vertex_count} vertices, {face_count} triangles.",
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def menu_func_object(self, context):
    self.layout.operator(OBJECT_OT_alpha_mesh_from_base_color.bl_idname, text="Alpha Mesh From Base Color")


class VIEW3D_PT_alpha_mesh_from_base_color(bpy.types.Panel):
    bl_label = "Alpha Mesh"
    bl_idname = "VIEW3D_PT_alpha_mesh_from_base_color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TA"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        if obj is None:
            layout.label(text="Select a plane with an image material.", icon="INFO")
            return

        image, _material = _find_base_color_image(obj) if obj.type == "MESH" else (None, None)
        row = layout.row()
        row.enabled = obj.type == "MESH" and image is not None
        row.operator(OBJECT_OT_alpha_mesh_from_base_color.bl_idname, icon="MOD_TRIANGULATE")

        if obj.type != "MESH":
            layout.label(text="Active object is not a mesh.", icon="ERROR")
        elif image is None:
            layout.label(text="No Base Color image found.", icon="ERROR")
        else:
            layout.label(text=f"Image: {image.name}", icon="IMAGE_DATA")


classes = (
    OBJECT_OT_alpha_mesh_from_base_color,
    VIEW3D_PT_alpha_mesh_from_base_color,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object.append(menu_func_object)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_func_object)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
