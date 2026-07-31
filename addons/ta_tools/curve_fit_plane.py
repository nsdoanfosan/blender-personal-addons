import bpy
import bmesh
import math
from bpy.props import EnumProperty, FloatProperty, IntProperty
from mathutils import Matrix, Vector
from mathutils.geometry import interpolate_bezier


def _point_co(point):
    return point.co.xyz if hasattr(point.co, "xyz") else point.co


def _curve_local_length(curve_obj):
    curve = curve_obj.data
    resolution = max(1, curve.resolution_u)
    total = 0.0

    for spline in curve.splines:
        if spline.type == 'BEZIER':
            points = spline.bezier_points
            count = len(points)
            if count < 2:
                continue

            segment_count = count if spline.use_cyclic_u else count - 1
            for index in range(segment_count):
                p0 = points[index]
                p1 = points[(index + 1) % count]
                samples = interpolate_bezier(
                    p0.co,
                    p0.handle_right,
                    p1.handle_left,
                    p1.co,
                    resolution + 1,
                )
                total += sum((samples[i] - samples[i - 1]).length for i in range(1, len(samples)))

        elif spline.type == 'POLY':
            points = spline.points
            count = len(points)
            if count < 2:
                continue

            segment_count = count if spline.use_cyclic_u else count - 1
            for index in range(segment_count):
                p0 = _point_co(points[index])
                p1 = _point_co(points[(index + 1) % count])
                total += (p1 - p0).length

        else:
            return _curve_mesh_fallback_length(curve_obj)

    return total


def _sample_curve_points_world(curve_obj):
    curve = curve_obj.data
    resolution = max(1, curve.resolution_u)
    best_points = []
    best_length = 0.0

    for spline in curve.splines:
        local_points = []

        if spline.type == 'BEZIER':
            points = spline.bezier_points
            count = len(points)
            if count < 2:
                continue

            segment_count = count if spline.use_cyclic_u else count - 1
            for index in range(segment_count):
                p0 = points[index]
                p1 = points[(index + 1) % count]
                samples = interpolate_bezier(
                    p0.co,
                    p0.handle_right,
                    p1.handle_left,
                    p1.co,
                    max(8, resolution * 4),
                )
                if local_points:
                    samples = samples[1:]
                local_points.extend(point.copy() for point in samples)

        elif spline.type == 'POLY':
            points = spline.points
            local_points = [_point_co(point).copy() for point in points]
            if spline.use_cyclic_u and local_points:
                local_points.append(local_points[0].copy())

        else:
            continue

        if len(local_points) < 2:
            continue

        world_points = [curve_obj.matrix_world @ point for point in local_points]
        length = sum(
            (world_points[index] - world_points[index - 1]).length
            for index in range(1, len(world_points))
        )

        if length > best_length:
            best_points = world_points
            best_length = length

    return best_points, best_length


def _adaptive_curve_cut_fractions(curve_obj, segment_count, curvature_boost, end_boost):
    if curve_obj is None or segment_count <= 1 or (curvature_boost <= 0.0 and end_boost <= 0.0):
        return []

    points, curve_length = _sample_curve_points_world(curve_obj)
    if len(points) < 3 or curve_length <= 0.0:
        return []

    segment_lengths = []
    turn_angles = []
    for index in range(1, len(points)):
        segment_lengths.append((points[index] - points[index - 1]).length)

        turn_angle = 0.0
        if 1 <= index < len(points) - 1:
            previous_vector = points[index] - points[index - 1]
            next_vector = points[index + 1] - points[index]
            if previous_vector.length > 0.000001 and next_vector.length > 0.000001:
                turn_angle = previous_vector.angle(next_vector)
        turn_angles.append(turn_angle)

    max_turn_angle = max(turn_angles) if turn_angles else 0.0
    if max_turn_angle <= 0.000001 and end_boost <= 0.0:
        return []

    weighted_segments = []
    accumulated_length = 0.0
    end_region = max(curve_length * 0.18, curve_length / max(segment_count, 1))
    for segment_length, turn_angle in zip(segment_lengths, turn_angles):
        mid_fraction = (accumulated_length + segment_length * 0.5) / curve_length
        end_distance = min(mid_fraction, 1.0 - mid_fraction)
        end_factor = max(0.0, 1.0 - (end_distance * curve_length / end_region))
        turn_factor = turn_angle / max_turn_angle if max_turn_angle > 0.000001 else 0.0
        weight = segment_length * (1.0 + curvature_boost * turn_factor + end_boost * end_factor)
        weighted_segments.append(weight)
        accumulated_length += segment_length

    total_weight = sum(weighted_segments)
    if total_weight <= 0.0:
        return []

    fractions = []
    accumulated_weight = 0.0
    accumulated_length = 0.0
    target_index = 1
    target_weight = total_weight * (target_index / segment_count)

    for segment_length, segment_weight in zip(segment_lengths, weighted_segments):
        next_weight = accumulated_weight + segment_weight

        while target_index < segment_count and target_weight <= next_weight:
            local_weight = target_weight - accumulated_weight
            factor = local_weight / segment_weight if segment_weight > 0.0 else 0.0
            curve_distance = accumulated_length + segment_length * factor
            fractions.append(curve_distance / curve_length)
            target_index += 1
            target_weight = total_weight * (target_index / segment_count)

        accumulated_weight = next_weight
        accumulated_length += segment_length

    return [max(0.0, min(1.0, fraction)) for fraction in fractions]


def _first_curve_point_local(curve_obj):
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER' and spline.bezier_points:
            return spline.bezier_points[0].co.copy()
        if spline.type == 'POLY' and spline.points:
            return _point_co(spline.points[0]).copy()

    return None


def _move_curve_origin_to_first_point(curve_obj):
    offset = _first_curve_point_local(curve_obj)
    if offset is None or offset.length <= 0.000001:
        return

    if curve_obj.data.users > 1:
        curve_obj.data = curve_obj.data.copy()

    matrix = curve_obj.matrix_world.copy()

    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER':
            for point in spline.bezier_points:
                point.co -= offset
                point.handle_left -= offset
                point.handle_right -= offset
        elif spline.type == 'POLY':
            for point in spline.points:
                point.co.xyz -= offset

    curve_obj.data.update_tag()
    curve_obj.matrix_world = matrix @ Matrix.Translation(offset)


def _curve_mesh_fallback_length(curve_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = curve_obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(eval_obj, depsgraph=depsgraph)

    try:
        return sum(
            (mesh.vertices[edge.vertices[1]].co - mesh.vertices[edge.vertices[0]].co).length
            for edge in mesh.edges
        )
    finally:
        bpy.data.meshes.remove(mesh)


def _cm_to_scene_units(context, value_cm):
    scale_length = context.scene.unit_settings.scale_length or 1.0
    return (value_cm * 0.01) / scale_length


def _shape_axis_setup(deform_axis):
    axis_index, is_positive_axis = _axis_info(deform_axis)
    if axis_index is None:
        raise ValueError("Unsupported Curve modifier deform axis")

    cross_axes = [index for index in range(3) if index != axis_index]
    sign = 1.0 if is_positive_axis else -1.0
    return axis_index, cross_axes[0], cross_axes[1], sign


def _shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b):
    co = [0.0, 0.0, 0.0]
    co[axis_index] = length_value
    co[cross_a_index] = cross_a
    co[cross_b_index] = cross_b
    return tuple(co)


def _set_curve_fit_uvs(mesh, axis_index, cross_a_index, cross_b_index, axis_span, cross_a_span, cross_b_span):
    uv_layer = mesh.uv_layers.new(name="UVMap")
    axis_span = axis_span if abs(axis_span) > 0.000001 else 1.0
    cross_a_span = cross_a_span if abs(cross_a_span) > 0.000001 else 1.0
    cross_b_span = cross_b_span if abs(cross_b_span) > 0.000001 else 1.0

    for polygon in mesh.polygons:
        use_b_axis = abs(polygon.normal[cross_b_index]) < abs(polygon.normal[cross_a_index])
        for loop_index in polygon.loop_indices:
            vert = mesh.vertices[mesh.loops[loop_index].vertex_index]
            u = vert.co[axis_index] / axis_span
            if use_b_axis:
                v = (vert.co[cross_b_index] / cross_b_span) + 0.5
            else:
                v = (vert.co[cross_a_index] / cross_a_span) + 0.5
            uv_layer.data[loop_index].uv = (u, v)


def _build_plane_shape(length, width, segments, axis_index, cross_a_index, cross_b_index, sign):
    verts = []
    faces = []

    for index in range(segments + 1):
        length_value = sign * length * (index / segments)
        verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, -width * 0.5, 0.0))
        verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, width * 0.5, 0.0))

    for index in range(segments):
        faces.append((index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2))

    return verts, faces, width, width


def _build_box_shape(length, width, height, segments, axis_index, cross_a_index, cross_b_index, sign):
    verts = []
    faces = []
    corners = (
        (-width * 0.5, -height * 0.5),
        (width * 0.5, -height * 0.5),
        (width * 0.5, height * 0.5),
        (-width * 0.5, height * 0.5),
    )

    for index in range(segments + 1):
        length_value = sign * length * (index / segments)
        for cross_a, cross_b in corners:
            verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b))

    for index in range(segments):
        ring = index * 4
        next_ring = (index + 1) * 4
        for corner_index in range(4):
            next_corner = (corner_index + 1) % 4
            faces.append((
                ring + corner_index,
                ring + next_corner,
                next_ring + next_corner,
                next_ring + corner_index,
            ))

    faces.append((3, 2, 1, 0))
    end = segments * 4
    faces.append((end, end + 1, end + 2, end + 3))

    return verts, faces, width, height


def _build_cylinder_shape(length, radius, sides, segments, axis_index, cross_a_index, cross_b_index, sign):
    verts = []
    faces = []
    sides = max(3, sides)

    for index in range(segments + 1):
        length_value = sign * length * (index / segments)
        for side_index in range(sides):
            angle = (math.tau * side_index) / sides
            cross_a = math.cos(angle) * radius
            cross_b = math.sin(angle) * radius
            verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b))

    for index in range(segments):
        ring = index * sides
        next_ring = (index + 1) * sides
        for side_index in range(sides):
            next_side = (side_index + 1) % sides
            faces.append((
                ring + side_index,
                ring + next_side,
                next_ring + next_side,
                next_ring + side_index,
            ))

    faces.append(tuple(reversed(range(sides))))
    end = segments * sides
    faces.append(tuple(end + side_index for side_index in range(sides)))

    diameter = radius * 2.0
    return verts, faces, diameter, diameter


def create_curve_fit_shape(
    context,
    curve_obj,
    shape_type,
    width,
    height,
    radius,
    sides,
    segments,
    deform_axis,
):
    length = _curve_local_length(curve_obj)
    if length <= 0.0:
        raise ValueError("Curve length is zero")

    axis_index, cross_a_index, cross_b_index, sign = _shape_axis_setup(deform_axis)
    segments = max(1, segments)

    if shape_type == 'PLANE':
        verts, faces, cross_a_span, cross_b_span = _build_plane_shape(
            length,
            width,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
        )
        object_name = "Curve_Fit_Plane"
    elif shape_type == 'CYLINDER':
        verts, faces, cross_a_span, cross_b_span = _build_cylinder_shape(
            length,
            radius,
            sides,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
        )
        object_name = "Curve_Fit_Cylinder"
    elif shape_type == 'BOX':
        verts, faces, cross_a_span, cross_b_span = _build_box_shape(
            length,
            width,
            height,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
        )
        object_name = "Curve_Fit_Box"
    else:
        raise ValueError("Unsupported curve fit shape")

    mesh = bpy.data.meshes.new(f"{object_name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(object_name, mesh)
    context.collection.objects.link(obj)

    obj.matrix_world = curve_obj.matrix_world.copy()

    modifier = obj.modifiers.new("Follow Curve", 'CURVE')
    modifier.object = curve_obj
    modifier.deform_axis = deform_axis
    curve_obj.show_in_front = True

    _set_curve_fit_uvs(
        mesh,
        axis_index,
        cross_a_index,
        cross_b_index,
        sign * length,
        cross_a_span,
        cross_b_span,
    )

    for selected in context.selected_objects:
        selected.select_set(False)

    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj, length


def create_curve_fit_plane(context, curve_obj, width, segments, deform_axis):
    return create_curve_fit_shape(
        context,
        curve_obj,
        'PLANE',
        width,
        width,
        width * 0.5,
        16,
        segments,
        deform_axis,
    )


def _curve_modifier_for_object(obj, curve_obj=None):
    if obj is None or obj.type != 'MESH':
        return None

    for modifier in obj.modifiers:
        if modifier.type != 'CURVE' or modifier.object is None:
            continue
        if curve_obj is None or modifier.object == curve_obj:
            return modifier

    return None


def _find_curve_fit_target(context):
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)

    modifier = _curve_modifier_for_object(active)
    if modifier is not None:
        return active, modifier

    if active is not None and active.type == 'CURVE':
        for obj in selected:
            modifier = _curve_modifier_for_object(obj, active)
            if modifier is not None:
                return obj, modifier

        for obj in context.scene.objects:
            modifier = _curve_modifier_for_object(obj, active)
            if modifier is not None:
                return obj, modifier

    for obj in selected:
        modifier = _curve_modifier_for_object(obj)
        if modifier is not None:
            return obj, modifier

    return None, None


def _axis_info(deform_axis):
    axis_index = {
        'POS_X': 0,
        'NEG_X': 0,
        'POS_Y': 1,
        'NEG_Y': 1,
        'POS_Z': 2,
        'NEG_Z': 2,
    }.get(deform_axis)

    return axis_index, deform_axis.startswith('POS_')


def _apply_scale_to_mesh_data(obj):
    scale = obj.scale.copy()
    if all(abs(scale[index] - 1.0) <= 0.000001 for index in range(3)):
        return

    obj.data.transform(Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0)))
    obj.scale = (1.0, 1.0, 1.0)
    obj.data.update()


def _matrix_without_scale(matrix):
    location, rotation, _scale = matrix.decompose()
    return Matrix.LocRotScale(location, rotation, (1.0, 1.0, 1.0))


def _center_mesh_cross_section(obj, deform_axis_index):
    offsets = [0.0, 0.0, 0.0]

    for axis_index in range(3):
        if axis_index == deform_axis_index:
            continue

        axis_values = [vertex.co[axis_index] for vertex in obj.data.vertices]
        if axis_values:
            offsets[axis_index] = (min(axis_values) + max(axis_values)) * 0.5

    if all(abs(offset) <= 0.000001 for offset in offsets):
        return

    for vertex in obj.data.vertices:
        for axis_index, offset in enumerate(offsets):
            vertex.co[axis_index] -= offset
    obj.data.update()


def segment_mesh_by_length(
    obj,
    deform_axis_index,
    segment_length,
    curve_obj=None,
    curvature_boost=0.0,
    end_boost=0.0,
):
    if segment_length <= 0.0:
        raise ValueError("Segment length must be greater than zero")

    axis_values = [vertex.co[deform_axis_index] for vertex in obj.data.vertices]
    if not axis_values:
        raise ValueError("Object mesh has no vertices")

    min_axis = min(axis_values)
    max_axis = max(axis_values)
    axis_length = max_axis - min_axis
    if axis_length <= 0.0:
        raise ValueError("Object has no length on the Curve modifier axis")

    tolerance = max(axis_length, 1.0) * 0.000001
    segment_count = max(1, math.ceil(axis_length / segment_length))
    if segment_count <= 1:
        return 0, axis_length

    adaptive_fractions = _adaptive_curve_cut_fractions(
        curve_obj,
        segment_count,
        curvature_boost,
        end_boost,
    )
    adaptive_cut_positions = [
        min_axis + axis_length * fraction
        for fraction in adaptive_fractions
        if tolerance < fraction < 1.0 - tolerance
    ]

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        internal_cut_edges = [
            edge
            for edge in bm.edges
            if (
                abs(edge.verts[0].co[deform_axis_index] - edge.verts[1].co[deform_axis_index]) <= tolerance
                and abs(edge.verts[0].co[deform_axis_index] - min_axis) > tolerance
                and abs(edge.verts[0].co[deform_axis_index] - max_axis) > tolerance
            )
        ]
        if internal_cut_edges:
            bmesh.ops.dissolve_edges(
                bm,
                edges=internal_cut_edges,
                use_verts=True,
                use_face_split=False,
            )
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        if adaptive_cut_positions:
            plane_normal = Vector((
                1.0 if deform_axis_index == 0 else 0.0,
                1.0 if deform_axis_index == 1 else 0.0,
                1.0 if deform_axis_index == 2 else 0.0,
            ))
            for position in adaptive_cut_positions:
                plane_co = Vector((0.0, 0.0, 0.0))
                plane_co[deform_axis_index] = position
                bmesh.ops.bisect_plane(
                    bm,
                    geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                    dist=tolerance,
                    plane_co=plane_co,
                    plane_no=plane_normal,
                    use_snap_center=False,
                    clear_outer=False,
                    clear_inner=False,
                )
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
        else:
            length_edges = [
                edge
                for edge in bm.edges
                if abs(edge.verts[0].co[deform_axis_index] - edge.verts[1].co[deform_axis_index]) > tolerance
            ]
            if length_edges:
                bmesh.ops.subdivide_edges(
                    bm,
                    edges=length_edges,
                    cuts=segment_count - 1,
                    use_grid_fill=True,
                )

        bm.to_mesh(obj.data)
    finally:
        bm.free()

    obj.data.update()
    return segment_count - 1, axis_length


def fit_object_to_curve_modifier(context, obj, modifier):
    curve_obj = modifier.object
    _move_curve_origin_to_first_point(curve_obj)
    curve_obj.show_in_front = True

    curve_points, curve_length = _sample_curve_points_world(curve_obj)
    if len(curve_points) < 2 or curve_length <= 0.0:
        raise ValueError("Curve length is zero")

    axis_index, is_positive_axis = _axis_info(modifier.deform_axis)
    if axis_index is None:
        raise ValueError("Unsupported Curve modifier deform axis")

    if obj.data.users > 1:
        obj.data = obj.data.copy()

    axis_values = [vertex.co[axis_index] for vertex in obj.data.vertices]
    if not axis_values:
        raise ValueError("Object mesh has no vertices")

    min_axis = min(axis_values)
    max_axis = max(axis_values)
    mesh_length = max_axis - min_axis
    if mesh_length <= 0.0:
        raise ValueError("Object has no length on the Curve modifier axis")

    start_axis = min_axis if is_positive_axis else max_axis
    for vertex in obj.data.vertices:
        vertex.co[axis_index] -= start_axis
    obj.data.update()

    obj.matrix_world = _matrix_without_scale(curve_obj.matrix_world)

    sign = -1.0 if obj.scale[axis_index] < 0.0 else 1.0
    obj.scale[axis_index] = sign * (curve_length / mesh_length)
    _apply_scale_to_mesh_data(obj)
    _center_mesh_cross_section(obj, axis_index)

    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    curve_obj.select_set(True)
    context.view_layer.objects.active = obj
    context.view_layer.update()

    return curve_obj, curve_length


class TA_OT_create_curve_fit_plane(bpy.types.Operator):
    bl_idname = "object.ta_create_curve_fit_plane"
    bl_label = "Create Curve Fit Shape"
    bl_description = "Create a subdivided plane, cylinder, or box fitted to the active curve and add a Curve modifier"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE' and context.mode == 'OBJECT'

    def execute(self, context):
        scene = context.scene
        curve_obj = context.active_object

        try:
            obj, length = create_curve_fit_shape(
                context,
                curve_obj,
                scene.ta_curve_fit_shape_type,
                _cm_to_scene_units(context, scene.ta_curve_fit_width_cm),
                _cm_to_scene_units(context, scene.ta_curve_fit_height_cm),
                _cm_to_scene_units(context, scene.ta_curve_fit_radius_cm),
                scene.ta_curve_fit_cylinder_sides,
                scene.ta_curve_fit_plane_segments,
                scene.ta_curve_fit_plane_deform_axis,
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Created {obj.name} / length {length:.4f}")
        return {'FINISHED'}


class TA_OT_fit_object_to_curve(bpy.types.Operator):
    bl_idname = "object.ta_fit_object_to_curve"
    bl_label = "Fit Existing Object To Curve"
    bl_description = "Fit the existing object to the curve, apply scale, and center its cross-section on the curve"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        obj, modifier = _find_curve_fit_target(context)
        if obj is None or modifier is None:
            self.report({'WARNING'}, "Select a mesh with a Curve modifier, or select its target curve.")
            return {'CANCELLED'}

        try:
            curve_obj, length = fit_object_to_curve_modifier(context, obj, modifier)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Fit {obj.name} to {curve_obj.name} / length {length:.4f}")
        return {'FINISHED'}


class TA_OT_segment_object_by_length(bpy.types.Operator):
    bl_idname = "object.ta_segment_object_by_length"
    bl_label = "Rebuild Segments By Length"
    bl_description = "Dissolve existing Curve Modifier axis cuts and rebuild them using the target segment length"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        obj, modifier = _find_curve_fit_target(context)
        if obj is None or modifier is None:
            self.report({'WARNING'}, "Select a mesh with a Curve modifier, or select its target curve.")
            return {'CANCELLED'}

        axis_index, _is_positive_axis = _axis_info(modifier.deform_axis)
        if axis_index is None:
            self.report({'WARNING'}, "Unsupported Curve modifier deform axis")
            return {'CANCELLED'}

        if obj.data.users > 1:
            obj.data = obj.data.copy()

        try:
            cut_count, axis_length = segment_mesh_by_length(
                obj,
                axis_index,
                _cm_to_scene_units(context, context.scene.ta_curve_fit_existing_segment_length_cm),
                modifier.object,
                context.scene.ta_curve_fit_curvature_boost,
                context.scene.ta_curve_fit_end_boost,
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Segmented {obj.name}: {cut_count} cuts / length {axis_length:.4f}")
        return {'FINISHED'}


class TA_PT_curve_fit_plane_panel(bpy.types.Panel):
    bl_label = "Curve Fit Shape"
    bl_idname = "TA_PT_curve_fit_plane_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TA'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.prop(scene, "ta_curve_fit_shape_type")
        if scene.ta_curve_fit_shape_type == 'CYLINDER':
            col.prop(scene, "ta_curve_fit_radius_cm")
            col.prop(scene, "ta_curve_fit_cylinder_sides")
        else:
            col.prop(scene, "ta_curve_fit_width_cm")
            if scene.ta_curve_fit_shape_type == 'BOX':
                col.prop(scene, "ta_curve_fit_height_cm")
        col.prop(scene, "ta_curve_fit_plane_segments")
        col.prop(scene, "ta_curve_fit_plane_deform_axis")

        row = layout.row()
        row.enabled = obj is not None and obj.type == 'CURVE'
        row.operator("object.ta_create_curve_fit_plane", icon='MOD_CURVE')

        fit_row = layout.row()
        fit_row.operator("object.ta_fit_object_to_curve", icon='CURVE_DATA')

        col = layout.column(align=True)
        col.prop(scene, "ta_curve_fit_existing_segment_length_cm")
        col.prop(scene, "ta_curve_fit_curvature_boost")
        col.prop(scene, "ta_curve_fit_end_boost")
        col.operator("object.ta_segment_object_by_length", icon='MOD_EDGESPLIT')


classes = (
    TA_OT_create_curve_fit_plane,
    TA_OT_fit_object_to_curve,
    TA_OT_segment_object_by_length,
    TA_PT_curve_fit_plane_panel,
)


def register():
    bpy.types.Scene.ta_curve_fit_shape_type = EnumProperty(
        name="Shape",
        default='PLANE',
        items=(
            ('PLANE', 'Plane', 'Create a flat ribbon shape'),
            ('CYLINDER', 'Cylinder', 'Create a round tube shape'),
            ('BOX', 'Box', 'Create a rectangular box shape'),
        ),
    )
    bpy.types.Scene.ta_curve_fit_width_cm = FloatProperty(
        name="Width (cm)",
        default=10.0,
        min=0.01,
        soft_max=1000.0,
        precision=2,
        description="Shape width in centimeters before the Curve modifier deforms it",
    )
    bpy.types.Scene.ta_curve_fit_height_cm = FloatProperty(
        name="Height (cm)",
        default=10.0,
        min=0.01,
        soft_max=1000.0,
        precision=2,
        description="Box height in centimeters before the Curve modifier deforms it",
    )
    bpy.types.Scene.ta_curve_fit_radius_cm = FloatProperty(
        name="Radius (cm)",
        default=5.0,
        min=0.01,
        soft_max=500.0,
        precision=2,
        description="Cylinder radius in centimeters before the Curve modifier deforms it",
    )
    bpy.types.Scene.ta_curve_fit_cylinder_sides = IntProperty(
        name="Sides",
        default=24,
        min=3,
        soft_max=96,
        description="Cylinder side count",
    )
    bpy.types.Scene.ta_curve_fit_plane_segments = IntProperty(
        name="Segments",
        default=128,
        min=1,
        soft_max=512,
        description="Subdivisions along the curve direction",
    )
    bpy.types.Scene.ta_curve_fit_plane_deform_axis = EnumProperty(
        name="Deform Axis",
        default='POS_X',
        items=(
            ('POS_X', '+X', 'Deform along positive local X'),
            ('NEG_X', '-X', 'Deform along negative local X'),
            ('POS_Y', '+Y', 'Deform along positive local Y'),
            ('NEG_Y', '-Y', 'Deform along negative local Y'),
            ('POS_Z', '+Z', 'Deform along positive local Z'),
            ('NEG_Z', '-Z', 'Deform along negative local Z'),
        ),
    )
    bpy.types.Scene.ta_curve_fit_existing_segment_length_cm = FloatProperty(
        name="Segment Length (cm)",
        default=5.0,
        min=0.01,
        soft_max=1000.0,
        precision=2,
        description="Target segment length in centimeters for cutting the existing fitted object",
    )
    bpy.types.Scene.ta_curve_fit_curvature_boost = FloatProperty(
        name="Curvature Boost",
        default=0.0,
        min=0.0,
        soft_max=5.0,
        precision=3,
        description="Move more rebuilt segments toward stronger curve bends; zero keeps even spacing",
    )
    bpy.types.Scene.ta_curve_fit_end_boost = FloatProperty(
        name="End Boost",
        default=0.0,
        min=0.0,
        soft_max=5.0,
        precision=3,
        description="Move more rebuilt segments toward the start and end of the curve; zero disables endpoint bias",
    )

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.ta_curve_fit_end_boost
    del bpy.types.Scene.ta_curve_fit_curvature_boost
    del bpy.types.Scene.ta_curve_fit_existing_segment_length_cm
    del bpy.types.Scene.ta_curve_fit_plane_deform_axis
    del bpy.types.Scene.ta_curve_fit_plane_segments
    del bpy.types.Scene.ta_curve_fit_cylinder_sides
    del bpy.types.Scene.ta_curve_fit_radius_cm
    del bpy.types.Scene.ta_curve_fit_height_cm
    del bpy.types.Scene.ta_curve_fit_width_cm
    del bpy.types.Scene.ta_curve_fit_shape_type
