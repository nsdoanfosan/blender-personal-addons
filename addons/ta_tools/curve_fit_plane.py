import bpy
import bmesh
import math
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Matrix, Vector
from mathutils.geometry import interpolate_bezier


_CHAIN_RIG_MARKER = "_ta_curve_fit_generated_chain_rig"
_CHAIN_BONE_COUNT = "_ta_curve_fit_chain_bone_count"
_CHAIN_ADD_END_BONE = "_ta_curve_fit_chain_add_end_bone"
_FIT_SHAPE_MARKER = "_ta_curve_fit_generated_shape"
_FIT_SHAPE_CYCLIC = "_ta_curve_fit_cyclic"
_FIT_SHAPE_TYPE = "_ta_curve_fit_shape_type"
_FIT_SHAPE_WIDTH = "_ta_curve_fit_width"
_FIT_SHAPE_HEIGHT = "_ta_curve_fit_height"
_FIT_SHAPE_RADIUS = "_ta_curve_fit_radius"
_FIT_SHAPE_SIDES = "_ta_curve_fit_sides"
_FIT_SHAPE_SEGMENTS = "_ta_curve_fit_segments"
_FIT_SHAPE_LENGTH = "_ta_curve_fit_length"
_FIT_SHAPE_PROFILE_SCALE = "_ta_curve_fit_profile_scale"
_FIT_SHAPE_PROFILE_ROTATION = "_ta_curve_fit_profile_rotation"
_FIT_SHAPE_PROFILE_FLIP = "_ta_curve_fit_profile_flip"
_FIT_SHAPE_THICKNESS = "_ta_curve_fit_thickness"
_FIT_SHAPE_CAPS = "_ta_curve_fit_caps"
_SPLIT_CURVE_MARKER = "_ta_curve_fit_split_source"
_SPLIT_CURVE_INDEX = "_ta_curve_fit_split_index"
_SHAPE_TYPES = {'PLANE', 'CYLINDER', 'BOX', 'SWEEP'}
_length_follow_guard = False


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


def _chain_source_spline(curve_obj):
    usable_splines = []

    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER' and len(spline.bezier_points) >= 2:
            usable_splines.append(spline)
        elif spline.type == 'POLY' and len(spline.points) >= 2:
            usable_splines.append(spline)

    if len(usable_splines) != 1:
        raise ValueError("Chain Rig requires exactly one open Bezier or Poly spline")

    spline = usable_splines[0]
    if spline.use_cyclic_u:
        raise ValueError("Chain Rig does not support cyclic splines")

    return spline


def _resample_polyline_by_length(points, sample_count):
    if len(points) < 2 or sample_count < 2:
        raise ValueError("Curve does not contain enough points for a Chain Rig")

    cumulative_lengths = [0.0]
    for index in range(1, len(points)):
        cumulative_lengths.append(
            cumulative_lengths[-1] + (points[index] - points[index - 1]).length
        )

    total_length = cumulative_lengths[-1]
    if total_length <= 0.000001:
        raise ValueError("Curve length is zero")

    result = []
    segment_index = 1

    for sample_index in range(sample_count):
        target_length = total_length * (sample_index / (sample_count - 1))

        while segment_index < len(cumulative_lengths) - 1 and cumulative_lengths[segment_index] < target_length:
            segment_index += 1

        previous_index = max(0, segment_index - 1)
        segment_start = cumulative_lengths[previous_index]
        segment_end = cumulative_lengths[segment_index]
        segment_length = segment_end - segment_start
        factor = (target_length - segment_start) / segment_length if segment_length > 0.000001 else 0.0
        result.append(points[previous_index].lerp(points[segment_index], factor))

    return result, total_length


def _sample_chain_points_world(curve_obj, bone_count):
    _chain_source_spline(curve_obj)
    points, _curve_length = _sample_curve_points_world(curve_obj)
    sampled_points, curve_length = _resample_polyline_by_length(points, bone_count + 1)

    curve_origin = curve_obj.matrix_world.translation
    reverse_direction = (
        (sampled_points[-1] - curve_origin).length_squared
        < (sampled_points[0] - curve_origin).length_squared
    )
    if reverse_direction:
        sampled_points.reverse()

    return sampled_points, curve_length, reverse_direction


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


def _curve_fit_is_cyclic(curve_obj):
    usable_splines = []

    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER' and len(spline.bezier_points) >= 2:
            usable_splines.append(spline)
        elif spline.type in {'POLY', 'NURBS'} and len(spline.points) >= 2:
            usable_splines.append(spline)

    cyclic_splines = [spline for spline in usable_splines if spline.use_cyclic_u]
    if not cyclic_splines:
        return False
    if len(usable_splines) != 1:
        raise ValueError("Cyclic Curve Fit Shape requires exactly one spline")
    return True


def _shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b):
    co = [0.0, 0.0, 0.0]
    co[axis_index] = length_value
    co[cross_a_index] = cross_a
    co[cross_b_index] = cross_b
    return tuple(co)


def _set_curve_fit_uvs(
    mesh,
    axis_index,
    cross_a_index,
    cross_b_index,
    axis_span,
    cross_a_span,
    cross_b_span,
    cyclic=False,
):
    uv_layer = mesh.uv_layers.new(name="UVMap")
    axis_span = axis_span if abs(axis_span) > 0.000001 else 1.0
    cross_a_span = cross_a_span if abs(cross_a_span) > 0.000001 else 1.0
    cross_b_span = cross_b_span if abs(cross_b_span) > 0.000001 else 1.0

    for polygon in mesh.polygons:
        use_b_axis = abs(polygon.normal[cross_b_index]) < abs(polygon.normal[cross_a_index])
        polygon_u_values = [
            mesh.vertices[mesh.loops[loop_index].vertex_index].co[axis_index] / axis_span
            for loop_index in polygon.loop_indices
        ]
        wraps_u = cyclic and max(polygon_u_values) - min(polygon_u_values) > 0.5
        for loop_index in polygon.loop_indices:
            vert = mesh.vertices[mesh.loops[loop_index].vertex_index]
            u = vert.co[axis_index] / axis_span
            if wraps_u and u < 0.5:
                u += 1.0
            if use_b_axis:
                v = (vert.co[cross_b_index] / cross_b_span) + 0.5
            else:
                v = (vert.co[cross_a_index] / cross_a_span) + 0.5
            uv_layer.data[loop_index].uv = (u, v)


def _build_plane_shape(
    length,
    width,
    segments,
    axis_index,
    cross_a_index,
    cross_b_index,
    sign,
    cyclic=False,
):
    verts = []
    faces = []
    ring_count = segments if cyclic else segments + 1

    for index in range(ring_count):
        length_value = sign * length * (index / segments)
        verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, -width * 0.5, 0.0))
        verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, width * 0.5, 0.0))

    for index in range(segments):
        next_index = (index + 1) % ring_count
        faces.append((index * 2, index * 2 + 1, next_index * 2 + 1, next_index * 2))

    return verts, faces, width, width


def _build_box_shape(
    length,
    width,
    height,
    segments,
    axis_index,
    cross_a_index,
    cross_b_index,
    sign,
    cyclic=False,
):
    verts = []
    faces = []
    ring_count = segments if cyclic else segments + 1
    corners = (
        (-width * 0.5, -height * 0.5),
        (width * 0.5, -height * 0.5),
        (width * 0.5, height * 0.5),
        (-width * 0.5, height * 0.5),
    )

    for index in range(ring_count):
        length_value = sign * length * (index / segments)
        for cross_a, cross_b in corners:
            verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b))

    for index in range(segments):
        ring = index * 4
        next_ring = ((index + 1) % ring_count) * 4
        for corner_index in range(4):
            next_corner = (corner_index + 1) % 4
            faces.append((
                ring + corner_index,
                ring + next_corner,
                next_ring + next_corner,
                next_ring + corner_index,
            ))

    if not cyclic:
        faces.append((3, 2, 1, 0))
        end = segments * 4
        faces.append((end, end + 1, end + 2, end + 3))

    return verts, faces, width, height


def _build_cylinder_shape(
    length,
    radius,
    sides,
    segments,
    axis_index,
    cross_a_index,
    cross_b_index,
    sign,
    cyclic=False,
):
    verts = []
    faces = []
    sides = max(3, sides)
    ring_count = segments if cyclic else segments + 1

    for index in range(ring_count):
        length_value = sign * length * (index / segments)
        for side_index in range(sides):
            angle = (math.tau * side_index) / sides
            cross_a = math.cos(angle) * radius
            cross_b = math.sin(angle) * radius
            verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b))

    for index in range(segments):
        ring = index * sides
        next_ring = ((index + 1) % ring_count) * sides
        for side_index in range(sides):
            next_side = (side_index + 1) % sides
            faces.append((
                ring + side_index,
                ring + next_side,
                next_ring + next_side,
                next_ring + side_index,
            ))

    if not cyclic:
        faces.append(tuple(reversed(range(sides))))
        end = segments * sides
        faces.append(tuple(end + side_index for side_index in range(sides)))

    diameter = radius * 2.0
    return verts, faces, diameter, diameter


def _profile_source_spline(profile_obj):
    if profile_obj is None or profile_obj.type != 'CURVE':
        raise ValueError("Sweep needs a profile curve object")
    for spline in profile_obj.data.splines:
        if spline.type == 'BEZIER' and len(spline.bezier_points) >= 2:
            return spline
        if spline.type in {'POLY', 'NURBS'} and len(spline.points) >= 2:
            return spline
    raise ValueError("Profile curve has no usable spline")


def _sample_profile_2d(profile_obj, scale=1.0, rotation_deg=0.0, flip=False):
    """Profile local X/Y (like Curve to Mesh) -> 2D points, cyclic flag."""
    spline = _profile_source_spline(profile_obj)
    resolution = max(1, profile_obj.data.resolution_u)
    cyclic = bool(spline.use_cyclic_u)
    local_points = []

    if spline.type == 'BEZIER':
        points = spline.bezier_points
        count = len(points)
        segment_count = count if cyclic else count - 1
        for index in range(segment_count):
            p0 = points[index]
            p1 = points[(index + 1) % count]
            samples = interpolate_bezier(p0.co, p0.handle_right, p1.handle_left, p1.co, resolution + 1)
            local_points.extend(sample.copy() for sample in samples[:-1])
        if not cyclic:
            local_points.append(points[-1].co.copy())
    else:
        local_points = [_point_co(point).copy() for point in spline.points]

    angle = math.radians(rotation_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    result = []
    for point in local_points:
        x = point.x * scale
        y = point.y * scale
        if flip:
            x = -x
        result.append((x * cos_a - y * sin_a, x * sin_a + y * cos_a))

    cleaned = [result[0]]
    for point in result[1:]:
        if math.dist(point, cleaned[-1]) > 1e-9:
            cleaned.append(point)
    if cyclic and len(cleaned) > 2 and math.dist(cleaned[0], cleaned[-1]) <= 1e-9:
        cleaned.pop()
    if len(cleaned) < 2:
        raise ValueError("Profile curve is too short")
    return cleaned, cyclic


def _thicken_open_profile(points, thickness):
    """Offset an open 2D profile to both sides and return a closed loop."""
    half = thickness * 0.5
    normals = []
    count = len(points)
    for index in range(count):
        p_prev = points[max(0, index - 1)]
        p_next = points[min(count - 1, index + 1)]
        tx = p_next[0] - p_prev[0]
        ty = p_next[1] - p_prev[1]
        length = math.hypot(tx, ty) or 1.0
        normals.append((-ty / length, tx / length))
    upper = [(p[0] + n[0] * half, p[1] + n[1] * half) for p, n in zip(points, normals)]
    lower = [(p[0] - n[0] * half, p[1] - n[1] * half) for p, n in zip(points, normals)]
    return upper + list(reversed(lower))


def _profile_arc_lengths(points, cyclic):
    lengths = [0.0]
    for index in range(1, len(points)):
        lengths.append(lengths[-1] + math.dist(points[index], points[index - 1]))
    total = lengths[-1] + (math.dist(points[-1], points[0]) if cyclic else 0.0)
    return lengths, total


def _build_sweep_shape(
    length,
    profile_points,
    profile_cyclic,
    segments,
    axis_index,
    cross_a_index,
    cross_b_index,
    sign,
    cyclic=False,
    caps=True,
):
    """Straight sweep of a 2D profile along the deform axis.

    Vertices are stored ring by ring (profile_count per ring) so ring-based
    tools keep working. Returns verts, faces, face_uvs (world-unit UV per
    corner), cross spans.
    """
    profile_count = len(profile_points)
    ring_count = segments if cyclic else segments + 1
    arc, profile_total = _profile_arc_lengths(profile_points, profile_cyclic)
    verts = []
    faces = []
    face_uvs = []

    for index in range(ring_count):
        length_value = sign * length * (index / segments)
        for cross_a, cross_b in profile_points:
            verts.append(_shape_vertex(axis_index, cross_a_index, cross_b_index, length_value, cross_a, cross_b))

    edge_count = profile_count if profile_cyclic else profile_count - 1
    for index in range(segments):
        ring = index * profile_count
        next_ring = ((index + 1) % ring_count) * profile_count
        u0 = length * (index / segments)
        u1 = length * ((index + 1) / segments)
        for k in range(edge_count):
            k1 = (k + 1) % profile_count
            v0 = arc[k]
            v1 = profile_total if k1 == 0 else arc[k1]
            faces.append((ring + k, ring + k1, next_ring + k1, next_ring + k))
            face_uvs.append(((u0, v0), (u0, v1), (u1, v1), (u1, v0)))

    cap_faces = 0
    if caps and profile_cyclic and not cyclic and profile_count >= 3:
        xs = [p[0] for p in profile_points]
        ys = [p[1] for p in profile_points]
        min_x, min_y = min(xs), min(ys)
        cap_gap = 0.0
        start = tuple(reversed(range(profile_count)))
        end_ring = segments * profile_count
        end = tuple(end_ring + k for k in range(profile_count))
        for cap_index, face in enumerate((start, end)):
            offset_u = cap_index * ((max(xs) - min_x) + cap_gap)
            faces.append(face)
            uvs = []
            for vertex_index in face:
                k = vertex_index % profile_count
                uvs.append((offset_u + profile_points[k][0] - min_x, profile_total + profile_points[k][1] - min_y))
            face_uvs.append(tuple(uvs))
            cap_faces += 1

    xs = [p[0] for p in profile_points]
    ys = [p[1] for p in profile_points]
    return verts, faces, face_uvs, (max(xs) - min(xs)), (max(ys) - min(ys)), profile_total, cap_faces


def _set_face_uvs(mesh, face_uvs, scale):
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = (uv[0] * scale, uv[1] * scale)


def _sweep_uv_scale(length, profile_total, cap_extent=0.0):
    extent = max(length, profile_total + cap_extent, 1e-9)
    return 1.0 / extent


def _sweep_profile_points(obj_or_settings):
    profile_obj, scale, rotation, flip, thickness = obj_or_settings
    points, profile_cyclic = _sample_profile_2d(profile_obj, scale, rotation, flip)
    if thickness > 0.0 and not profile_cyclic:
        points = _thicken_open_profile(points, thickness)
        profile_cyclic = True
    return points, profile_cyclic


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
    profile_obj=None,
    profile_scale=1.0,
    profile_rotation=0.0,
    profile_flip=False,
    thickness=0.0,
    caps=True,
    follow_length=False,
):
    length = _curve_local_length(curve_obj)
    if length <= 0.0:
        raise ValueError("Curve length is zero")

    axis_index, cross_a_index, cross_b_index, sign = _shape_axis_setup(deform_axis)
    cyclic = _curve_fit_is_cyclic(curve_obj)
    segments = max(3 if cyclic else 1, segments)
    face_uvs = None

    if shape_type == 'SWEEP':
        profile_points, profile_cyclic = _sweep_profile_points(
            (profile_obj, profile_scale, profile_rotation, profile_flip, thickness)
        )
        verts, faces, face_uvs, cross_a_span, cross_b_span, profile_total, cap_faces = _build_sweep_shape(
            length,
            profile_points,
            profile_cyclic,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
            cyclic,
            caps,
        )
        cap_extent = cross_b_span if cap_faces else 0.0
        object_name = f"{curve_obj.name}_Sweep"
    elif shape_type == 'PLANE':
        verts, faces, cross_a_span, cross_b_span = _build_plane_shape(
            length,
            width,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
            cyclic,
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
            cyclic,
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
            cyclic,
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
    obj.ta_curve_fit_source_curve = curve_obj
    obj[_FIT_SHAPE_MARKER] = True
    obj[_FIT_SHAPE_CYCLIC] = cyclic
    obj[_FIT_SHAPE_TYPE] = shape_type
    obj[_FIT_SHAPE_WIDTH] = width
    obj[_FIT_SHAPE_HEIGHT] = height
    obj[_FIT_SHAPE_RADIUS] = radius
    obj[_FIT_SHAPE_SIDES] = sides
    obj[_FIT_SHAPE_SEGMENTS] = segments
    obj[_FIT_SHAPE_LENGTH] = length
    obj.ta_curve_fit_follow_length = bool(follow_length)
    if shape_type == 'SWEEP':
        obj.ta_curve_fit_profile_curve = profile_obj
        obj[_FIT_SHAPE_PROFILE_SCALE] = profile_scale
        obj[_FIT_SHAPE_PROFILE_ROTATION] = profile_rotation
        obj[_FIT_SHAPE_PROFILE_FLIP] = bool(profile_flip)
        obj[_FIT_SHAPE_THICKNESS] = thickness
        obj[_FIT_SHAPE_CAPS] = bool(caps)
    curve_obj.show_in_front = True

    if face_uvs is not None:
        _set_face_uvs(mesh, face_uvs, _sweep_uv_scale(length, profile_total, cap_extent))
    else:
        _set_curve_fit_uvs(
            mesh,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign * length,
            cross_a_span,
            cross_b_span,
            cyclic,
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


def rebuild_generated_cyclic_shape(obj, modifier, segment_length):
    if not obj.get(_FIT_SHAPE_MARKER, False) or not obj.get(_FIT_SHAPE_CYCLIC, False):
        return None
    if segment_length <= 0.0:
        raise ValueError("Segment length must be greater than zero")

    curve_obj = modifier.object
    if curve_obj is None or curve_obj.type != 'CURVE' or not _curve_fit_is_cyclic(curve_obj):
        raise ValueError("The generated cyclic shape requires one cyclic source spline")

    length = _curve_local_length(curve_obj)
    if length <= 0.0:
        raise ValueError("Curve length is zero")

    shape_type = obj.get(_FIT_SHAPE_TYPE)
    if shape_type not in _SHAPE_TYPES:
        raise ValueError("Cyclic shape metadata is missing; recreate the Curve Fit Shape")

    segments = max(3, math.ceil(length / segment_length))
    axis_index, cross_a_index, cross_b_index, sign = _shape_axis_setup(modifier.deform_axis)
    width = float(obj.get(_FIT_SHAPE_WIDTH, 0.0))
    height = float(obj.get(_FIT_SHAPE_HEIGHT, 0.0))
    radius = float(obj.get(_FIT_SHAPE_RADIUS, 0.0))
    sides = max(3, int(obj.get(_FIT_SHAPE_SIDES, 3)))

    if shape_type == 'SWEEP':
        _rebuild_sweep_geometry(obj, length, segments, axis_index, cross_a_index, cross_b_index, sign, True)
        return segments, length

    if shape_type == 'PLANE':
        verts, faces, cross_a_span, cross_b_span = _build_plane_shape(
            length,
            width,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
            True,
        )
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
            True,
        )
    else:
        verts, faces, cross_a_span, cross_b_span = _build_box_shape(
            length,
            width,
            height,
            segments,
            axis_index,
            cross_a_index,
            cross_b_index,
            sign,
            True,
        )

    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    _set_curve_fit_uvs(
        mesh,
        axis_index,
        cross_a_index,
        cross_b_index,
        sign * length,
        cross_a_span,
        cross_b_span,
        True,
    )
    obj[_FIT_SHAPE_SEGMENTS] = segments
    obj[_FIT_SHAPE_LENGTH] = length
    return segments, length


def _rebuild_sweep_geometry(obj, length, segments, axis_index, cross_a_index, cross_b_index, sign, cyclic):
    profile_obj = obj.ta_curve_fit_profile_curve
    profile_points, profile_cyclic = _sweep_profile_points((
        profile_obj,
        float(obj.get(_FIT_SHAPE_PROFILE_SCALE, 1.0)),
        float(obj.get(_FIT_SHAPE_PROFILE_ROTATION, 0.0)),
        bool(obj.get(_FIT_SHAPE_PROFILE_FLIP, False)),
        float(obj.get(_FIT_SHAPE_THICKNESS, 0.0)),
    ))
    verts, faces, face_uvs, _a, cross_b_span, profile_total, cap_faces = _build_sweep_shape(
        length,
        profile_points,
        profile_cyclic,
        segments,
        axis_index,
        cross_a_index,
        cross_b_index,
        sign,
        cyclic,
        bool(obj.get(_FIT_SHAPE_CAPS, True)),
    )
    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    _set_face_uvs(mesh, face_uvs, _sweep_uv_scale(length, profile_total, cross_b_span if cap_faces else 0.0))
    obj[_FIT_SHAPE_SEGMENTS] = segments
    obj[_FIT_SHAPE_LENGTH] = length


def follow_curve_length(obj, modifier=None):
    """Stretch a generated shape along its deform axis to the current curve length.

    Keeps vertex count, faces and UVs (manual UV edits survive); closed curves
    close again because the mesh length equals the curve length.
    Returns the scale factor applied, or None when nothing changed.
    """
    modifier = modifier or _curve_modifier_for_object(obj)
    if modifier is None or modifier.object is None or not obj.get(_FIT_SHAPE_MARKER, False):
        return None
    old_length = float(obj.get(_FIT_SHAPE_LENGTH, 0.0))
    new_length = _curve_local_length(modifier.object)
    if old_length <= 0.0 or new_length <= 0.0 or abs(new_length - old_length) <= max(1e-7, old_length * 1e-6):
        return None
    axis_index, _positive = _axis_info(modifier.deform_axis)
    if axis_index is None:
        return None
    factor = new_length / old_length
    mesh = obj.data
    if mesh.users > 1:
        obj.data = mesh = mesh.copy()
    coords = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", coords)
    for index in range(axis_index, len(coords), 3):
        coords[index] *= factor
    mesh.vertices.foreach_set("co", coords)
    mesh.update()
    obj[_FIT_SHAPE_LENGTH] = new_length
    return factor


@bpy.app.handlers.persistent
def _curve_fit_follow_length_handler(scene, depsgraph):
    global _length_follow_guard
    if _length_follow_guard:
        return
    changed_curves = set()
    for update in depsgraph.updates:
        update_id = update.id
        if isinstance(update_id, bpy.types.Object) and update_id.type == 'CURVE' and update.is_updated_geometry:
            changed_curves.add(update_id.original.name)
        elif isinstance(update_id, bpy.types.Curve):
            for obj in bpy.data.objects:
                if obj.type == 'CURVE' and obj.data == update_id.original:
                    changed_curves.add(obj.name)
    if not changed_curves:
        return
    _length_follow_guard = True
    try:
        for obj in scene.objects:
            if obj.type != 'MESH' or not getattr(obj, "ta_curve_fit_follow_length", False):
                continue
            modifier = _curve_modifier_for_object(obj)
            if modifier is None or modifier.object is None or modifier.object.name not in changed_curves:
                continue
            try:
                follow_curve_length(obj, modifier)
            except Exception:
                pass
    finally:
        _length_follow_guard = False


def seam_twist_degrees(obj):
    """For a cyclic generated shape: extra cross-section rotation at the seam
    compared with the median ring-to-ring step (degrees). None if not cyclic."""
    if not obj.get(_FIT_SHAPE_CYCLIC, False):
        return None
    segments = int(obj.get(_FIT_SHAPE_SEGMENTS, 0))
    vert_count = len(obj.data.vertices)
    if segments < 3 or vert_count % segments:
        return None
    ring_size = vert_count // segments
    if ring_size < 2:
        return None
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != vert_count:
            return None
        rings = []
        for ring in range(segments):
            base = ring * ring_size
            pts = [mesh.vertices[base + k].co.copy() for k in range(ring_size)]
            center = sum(pts, Vector()) / ring_size
            far = max(range(ring_size), key=lambda k: (pts[k] - pts[0]).length)
            rings.append((center, pts[far] - pts[0]))
    finally:
        evaluated.to_mesh_clear()

    def step(a, b, tangent):
        va = a - tangent * a.dot(tangent)
        vb = b - tangent * b.dot(tangent)
        if va.length < 1e-9 or vb.length < 1e-9:
            return 0.0
        return math.degrees(va.angle(vb))

    steps = []
    for ring in range(segments):
        nxt = (ring + 1) % segments
        tangent = (rings[nxt][0] - rings[ring - 1][0])
        if tangent.length < 1e-12:
            continue
        tangent.normalize()
        steps.append(step(rings[ring][1], rings[nxt][1], tangent))
    if len(steps) < 3:
        return None
    seam = steps[-1]
    others = sorted(steps[:-1])
    median = others[len(others) // 2]
    return max(0.0, seam - median)


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


def _chain_rig_for_mesh(obj):
    if obj is None or obj.type != 'MESH':
        return None

    rig = getattr(obj, "ta_curve_fit_chain_rig", None)
    if rig is not None and rig.type == 'ARMATURE':
        return rig

    for modifier in obj.modifiers:
        if (
            modifier.type == 'ARMATURE'
            and modifier.object is not None
            and modifier.object.type == 'ARMATURE'
            and modifier.object.get(_CHAIN_RIG_MARKER, False)
        ):
            return modifier.object

    return None


def _chain_normal_for_tangent(reference_normal, tangent):
    tangent = tangent.normalized()
    normal = reference_normal - tangent * reference_normal.dot(tangent)

    if normal.length <= 0.000001:
        for fallback in (Vector((0.0, 0.0, 1.0)), Vector((0.0, 1.0, 0.0)), Vector((1.0, 0.0, 0.0))):
            normal = fallback - tangent * fallback.dot(tangent)
            if normal.length > 0.000001:
                break

    return normal.normalized()


def _ensure_chain_armature_modifier(obj, curve_modifier, rig_obj):
    armature_modifier = None
    for modifier in obj.modifiers:
        if modifier.type == 'ARMATURE' and modifier.object == rig_obj:
            armature_modifier = modifier
            break

    if armature_modifier is not None:
        curve_index = obj.modifiers.find(curve_modifier.name)
        armature_index = obj.modifiers.find(armature_modifier.name)
        if armature_index <= curve_index:
            obj.modifiers.remove(armature_modifier)
            armature_modifier = None

    if armature_modifier is None:
        armature_modifier = obj.modifiers.new("Chain Rig", 'ARMATURE')

    armature_modifier.object = rig_obj
    armature_modifier.use_vertex_groups = True
    armature_modifier.use_bone_envelopes = False
    armature_modifier.use_deform_preserve_volume = False
    return armature_modifier


def _assign_chain_weights(
    obj,
    deform_axis,
    bone_names,
    old_bone_names=(),
    reverse_direction=False,
    end_bone_name=None,
):
    axis_index, is_positive_axis = _axis_info(deform_axis)
    if axis_index is None:
        raise ValueError("Unsupported Curve modifier deform axis")

    axis_values = [vertex.co[axis_index] for vertex in obj.data.vertices]
    if not axis_values:
        raise ValueError("Object mesh has no vertices")

    min_axis = min(axis_values)
    max_axis = max(axis_values)
    axis_length = max_axis - min_axis
    if axis_length <= 0.000001:
        raise ValueError("Object has no length on the Curve modifier axis")

    new_group_names = list(bone_names)
    if end_bone_name is not None:
        new_group_names.append(end_bone_name)

    owned_group_names = set(old_bone_names) | set(new_group_names)
    for group_name in owned_group_names:
        group = obj.vertex_groups.get(group_name)
        if group is not None:
            obj.vertex_groups.remove(group)

    groups = [obj.vertex_groups.new(name=bone_name) for bone_name in bone_names]
    bone_count = len(groups)
    end_group = (
        obj.vertex_groups.new(name=end_bone_name)
        if end_bone_name is not None
        else None
    )
    end_blend_start = 1.0 - (0.5 / bone_count)

    for vertex in obj.data.vertices:
        if is_positive_axis:
            progress = (vertex.co[axis_index] - min_axis) / axis_length
        else:
            progress = (max_axis - vertex.co[axis_index]) / axis_length

        progress = max(0.0, min(1.0, progress))
        if reverse_direction:
            progress = 1.0 - progress

        if end_group is not None and progress >= end_blend_start:
            blend = (progress - end_blend_start) / (1.0 - end_blend_start)
            blend = max(0.0, min(1.0, blend))
            blend = blend * blend * (3.0 - 2.0 * blend)
            if blend < 1.0:
                groups[-1].add([vertex.index], 1.0 - blend, 'REPLACE')
            if blend > 0.0:
                end_group.add([vertex.index], blend, 'REPLACE')
            continue

        center_position = progress * bone_count - 0.5

        if center_position <= 0.0:
            groups[0].add([vertex.index], 1.0, 'REPLACE')
            continue

        if center_position >= bone_count - 1:
            groups[-1].add([vertex.index], 1.0, 'REPLACE')
            continue

        lower_index = int(math.floor(center_position))
        blend = center_position - lower_index
        blend = blend * blend * (3.0 - 2.0 * blend)
        groups[lower_index].add([vertex.index], 1.0 - blend, 'REPLACE')
        groups[lower_index + 1].add([vertex.index], blend, 'REPLACE')


def create_or_update_chain_rig(
    context,
    obj,
    curve_modifier,
    bone_count,
    add_end_bone=False,
):
    curve_obj = curve_modifier.object
    if curve_obj is None or curve_obj.type != 'CURVE':
        raise ValueError("Curve modifier has no valid curve target")

    bone_count = max(2, int(bone_count))
    world_points, curve_length, reverse_direction = _sample_chain_points_world(curve_obj, bone_count)
    rig_obj = _chain_rig_for_mesh(obj)

    if rig_obj is None:
        armature = bpy.data.armatures.new(f"{curve_obj.name}_ChainRig_Armature")
        rig_obj = bpy.data.objects.new(f"{curve_obj.name}_ChainRig", armature)
        target_collection = obj.users_collection[0] if obj.users_collection else context.collection
        target_collection.objects.link(rig_obj)
        old_bone_names = []
    else:
        armature = rig_obj.data
        old_bone_names = [bone.name for bone in armature.bones]

    rig_matrix = _matrix_without_scale(curve_obj.matrix_world)
    rig_obj.matrix_world = rig_matrix
    inverse_rig_matrix = rig_matrix.inverted_safe()
    local_points = [inverse_rig_matrix @ point for point in world_points]

    for selected in list(context.selected_objects):
        selected.select_set(False)
    rig_obj.hide_set(False)
    rig_obj.hide_viewport = False
    rig_obj.select_set(True)
    context.view_layer.objects.active = rig_obj
    bpy.ops.object.mode_set(mode='EDIT')

    for edit_bone in list(armature.edit_bones):
        armature.edit_bones.remove(edit_bone)

    bone_names = []
    previous_bone = None
    reference_normal = Vector((0.0, 0.0, 1.0))

    for index in range(bone_count):
        head = local_points[index]
        tail = local_points[index + 1]
        tangent = tail - head
        if tangent.length <= 0.000001:
            bpy.ops.object.mode_set(mode='OBJECT')
            raise ValueError("Curve contains a zero-length Chain Rig segment")

        edit_bone = armature.edit_bones.new(f"rope_{index + 1:03d}")
        edit_bone.head = head
        edit_bone.tail = tail
        edit_bone.parent = previous_bone
        edit_bone.use_connect = previous_bone is not None

        reference_normal = _chain_normal_for_tangent(reference_normal, tangent)
        edit_bone.align_roll(reference_normal)
        bone_names.append(edit_bone.name)
        previous_bone = edit_bone

    end_bone_name = None
    if add_end_bone:
        terminal_tangent = local_points[-1] - local_points[-2]
        if terminal_tangent.length <= 0.000001:
            bpy.ops.object.mode_set(mode='OBJECT')
            raise ValueError("Curve contains a zero-length terminal Chain Rig segment")

        end_bone = armature.edit_bones.new("rope_end")
        end_bone.head = local_points[-1]
        end_bone.tail = local_points[-1] + terminal_tangent
        end_bone.parent = previous_bone
        end_bone.use_connect = True
        end_bone.use_deform = True
        reference_normal = _chain_normal_for_tangent(reference_normal, terminal_tangent)
        end_bone.align_roll(reference_normal)
        end_bone_name = end_bone.name
        bone_names.append(end_bone_name)

    bpy.ops.object.mode_set(mode='OBJECT')

    rig_obj.show_in_front = True
    armature.display_type = 'OCTAHEDRAL'
    rig_obj[_CHAIN_RIG_MARKER] = True
    rig_obj[_CHAIN_BONE_COUNT] = bone_count
    rig_obj[_CHAIN_ADD_END_BONE] = bool(add_end_bone)
    rig_obj.ta_curve_fit_source_curve = curve_obj
    obj.ta_curve_fit_source_curve = curve_obj
    obj.ta_curve_fit_chain_rig = rig_obj

    _ensure_chain_armature_modifier(obj, curve_modifier, rig_obj)
    _assign_chain_weights(
        obj,
        curve_modifier.deform_axis,
        bone_names[:bone_count],
        old_bone_names,
        reverse_direction,
        end_bone_name,
    )

    rig_obj.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    context.view_layer.update()

    return rig_obj, bone_names, curve_length


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


def _usable_splines(curve_obj):
    result = []
    for spline in curve_obj.data.splines:
        if spline.type == 'BEZIER' and len(spline.bezier_points) >= 2:
            result.append(spline)
        elif spline.type in {'POLY', 'NURBS'} and len(spline.points) >= 2:
            result.append(spline)
    return result


def _evaluated_curve_splines(curve_obj):
    """Curves after the leading Geometry Nodes modifiers that still output curves
    (e.g. relax/normalize), before the modifier that turns them into a mesh.
    Returns list of dicts (positions, radius, tilt, cyclic) or None."""
    node_mods = [m for m in curve_obj.modifiers]
    if not node_mods:
        return None
    saved = [m.show_viewport for m in node_mods]
    best = None
    try:
        for keep in range(len(node_mods), 0, -1):
            for index, modifier in enumerate(node_mods):
                modifier.show_viewport = saved[index] and index < keep
            bpy.context.view_layer.update()
            evaluated = curve_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            try:
                geometry = evaluated.evaluated_geometry()
            except Exception:
                return None
            curves = geometry.curves
            if curves is None or len(curves.points) == 0:
                continue
            attrs = curves.attributes
            count = len(curves.points)
            positions = [0.0] * (count * 3)
            attrs["position"].data.foreach_get("vector", positions)

            def read(name, default):
                attr = attrs.get(name)
                if attr is None or attr.domain != 'POINT':
                    return [default] * count
                values = [0.0] * count
                attr.data.foreach_get("value", values)
                return values

            radius = read("radius", 1.0)
            tilt = read("tilt", 0.0)
            curve_count = len(curves.curves)
            types = [1] * curve_count
            if attrs.get("curve_type") is not None:
                attrs["curve_type"].data.foreach_get("value", types)
            cyclic = [False] * curve_count
            if attrs.get("cyclic") is not None:
                attrs["cyclic"].data.foreach_get("value", cyclic)
            if any(t != 1 for t in types):
                continue  # only poly curves give exact evaluated shape
            splines = []
            for curve_index, curve in enumerate(curves.curves):
                start = curve.first_point_index
                size = curve.points_length
                splines.append({
                    "positions": [Vector(positions[(start + k) * 3:(start + k) * 3 + 3]) for k in range(size)],
                    "radius": radius[start:start + size],
                    "tilt": tilt[start:start + size],
                    "cyclic": bool(cyclic[curve_index]),
                })
            best = (keep, splines)
            break
    finally:
        for modifier, value in zip(node_mods, saved):
            modifier.show_viewport = value
        bpy.context.view_layer.update()
    if best is None or best[0] == 0:
        return None
    return best[1]


def _copy_curve_settings(source, target):
    for attr in ("dimensions", "twist_mode", "twist_smooth", "use_radius", "use_stretch",
                 "use_deform_bounds", "resolution_u", "use_path"):
        if hasattr(source, attr):
            try:
                setattr(target, attr, getattr(source, attr))
            except Exception:
                pass


def split_curve_splines(context, curve_obj, use_evaluated=True):
    """One curve object per spline; the source curve is left untouched.
    Returns (list of new curve objects, used_evaluated_shape)."""
    evaluated = _evaluated_curve_splines(curve_obj) if use_evaluated else None
    control = _usable_splines(curve_obj)
    count = len(evaluated) if evaluated is not None else len(control)
    if count == 0:
        raise ValueError("Curve has no usable splines")

    parent_collection = curve_obj.users_collection[0] if curve_obj.users_collection else context.scene.collection
    collection_name = f"{curve_obj.name} · Curve Fit"
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        parent_collection.children.link(collection)

    created = []
    for index in range(count):
        data = bpy.data.curves.new(f"{curve_obj.name}_spline_{index:02d}", type='CURVE')
        _copy_curve_settings(curve_obj.data, data)
        if evaluated is not None:
            info = evaluated[index]
            spline = data.splines.new('POLY')
            spline.points.add(len(info["positions"]) - 1)
            for point, co, radius, tilt in zip(spline.points, info["positions"], info["radius"], info["tilt"]):
                point.co = (co.x, co.y, co.z, 1.0)
                point.radius = radius
                point.tilt = tilt
            spline.use_cyclic_u = info["cyclic"]
        else:
            source = control[index]
            spline = data.splines.new(source.type)
            if source.type == 'BEZIER':
                spline.bezier_points.add(len(source.bezier_points) - 1)
                for dst, src in zip(spline.bezier_points, source.bezier_points):
                    dst.co = src.co
                    dst.handle_left_type = src.handle_left_type
                    dst.handle_right_type = src.handle_right_type
                    dst.handle_left = src.handle_left
                    dst.handle_right = src.handle_right
                    dst.radius = src.radius
                    dst.tilt = src.tilt
            else:
                spline.points.add(len(source.points) - 1)
                for dst, src in zip(spline.points, source.points):
                    dst.co = src.co
                    dst.radius = src.radius
                    dst.tilt = src.tilt
                if source.type == 'NURBS':
                    spline.order_u = source.order_u
                    spline.use_endpoint_u = source.use_endpoint_u
            spline.use_cyclic_u = source.use_cyclic_u
            spline.resolution_u = source.resolution_u
        new_obj = bpy.data.objects.new(f"{curve_obj.name}_spline_{index:02d}", data)
        new_obj.matrix_world = curve_obj.matrix_world.copy()
        new_obj[_SPLIT_CURVE_MARKER] = curve_obj.name
        new_obj[_SPLIT_CURVE_INDEX] = index
        collection.objects.link(new_obj)
        created.append(new_obj)
    return created, evaluated is not None


class TA_OT_create_curve_fit_plane(bpy.types.Operator):
    bl_idname = "object.ta_create_curve_fit_plane"
    bl_label = "Create Curve Fit Shape"
    bl_description = "Create a subdivided plane, cylinder, or box fitted to the active curve and add a Curve modifier"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE' and context.mode == 'OBJECT'

    def _create_one(self, context, curve_obj):
        scene = context.scene
        return create_curve_fit_shape(
            context,
            curve_obj,
            scene.ta_curve_fit_shape_type,
            _cm_to_scene_units(context, scene.ta_curve_fit_width_cm),
            _cm_to_scene_units(context, scene.ta_curve_fit_height_cm),
            _cm_to_scene_units(context, scene.ta_curve_fit_radius_cm),
            scene.ta_curve_fit_cylinder_sides,
            scene.ta_curve_fit_plane_segments,
            scene.ta_curve_fit_plane_deform_axis,
            profile_obj=scene.ta_curve_fit_profile_object,
            profile_scale=scene.ta_curve_fit_profile_scale,
            profile_rotation=scene.ta_curve_fit_profile_rotation,
            profile_flip=scene.ta_curve_fit_profile_flip,
            thickness=_cm_to_scene_units(context, scene.ta_curve_fit_sweep_thickness_cm),
            caps=scene.ta_curve_fit_sweep_caps,
            follow_length=scene.ta_curve_fit_follow_length_default,
        )

    def execute(self, context):
        scene = context.scene
        curve_obj = context.active_object
        rig_obj = None

        if scene.ta_curve_fit_shape_type == 'SWEEP':
            profile = scene.ta_curve_fit_profile_object
            if profile is None or profile.type != 'CURVE':
                self.report({'WARNING'}, "Pick a profile curve for Sweep")
                return {'CANCELLED'}
            if profile == curve_obj:
                self.report({'WARNING'}, "The profile curve must be a different object")
                return {'CANCELLED'}

        if len(_usable_splines(curve_obj)) > 1 or (
            scene.ta_curve_fit_split_splines and curve_obj.modifiers and scene.ta_curve_fit_split_use_evaluated
        ):
            if not scene.ta_curve_fit_split_splines:
                self.report({'WARNING'}, "Curve has several splines; enable 'One Mesh Per Spline'")
                return {'CANCELLED'}
            if scene.ta_curve_fit_generate_chain_rig:
                self.report({'WARNING'}, "Chain Rig is not created when splitting splines; build it per spline afterwards")
            try:
                split_curves, used_evaluated = split_curve_splines(
                    context, curve_obj, scene.ta_curve_fit_split_use_evaluated
                )
                created = []
                twist_notes = []
                for split_curve in split_curves:
                    obj, length = self._create_one(context, split_curve)
                    for collection in list(obj.users_collection):
                        collection.objects.unlink(obj)
                    split_curve.users_collection[0].objects.link(obj)
                    created.append(obj)
                    twist = seam_twist_degrees(obj)
                    if twist is not None and twist > 5.0:
                        twist_notes.append(f"{obj.name} seam twist {twist:.1f}°")
            except ValueError as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            for selected in context.selected_objects:
                selected.select_set(False)
            for obj in created:
                obj.select_set(True)
            context.view_layer.objects.active = created[0]
            source_note = "evaluated shape" if used_evaluated else "control points"
            message = f"Created {len(created)} meshes from {len(split_curves)} splines ({source_note})"
            if twist_notes:
                message += " / " + ", ".join(twist_notes)
                self.report({'WARNING'}, message)
            else:
                self.report({'INFO'}, message)
            return {'FINISHED'}

        try:
            if scene.ta_curve_fit_generate_chain_rig:
                _sample_chain_points_world(curve_obj, scene.ta_curve_fit_chain_bone_count)

            obj, length = self._create_one(context, curve_obj)

            if scene.ta_curve_fit_generate_chain_rig:
                modifier = _curve_modifier_for_object(obj, curve_obj)
                rig_obj, _bone_names, _rig_length = create_or_update_chain_rig(
                    context,
                    obj,
                    modifier,
                    scene.ta_curve_fit_chain_bone_count,
                    scene.ta_curve_fit_add_end_bone,
                )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        rig_message = f" / rig {rig_obj.name}" if rig_obj is not None else ""
        twist = seam_twist_degrees(obj)
        if twist is not None and twist > 5.0:
            self.report({'WARNING'}, f"Created {obj.name} / seam twist {twist:.1f}° (adjust curve tilt)")
            return {'FINISHED'}
        self.report({'INFO'}, f"Created {obj.name} / length {length:.4f}{rig_message}")
        return {'FINISHED'}


class TA_OT_curve_fit_follow_length(bpy.types.Operator):
    bl_idname = "object.ta_curve_fit_follow_length"
    bl_label = "Match Curve Length"
    bl_description = "Stretch the generated shape to the current curve length without changing topology or UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        targets = [obj for obj in context.selected_objects if obj.type == 'MESH' and obj.get(_FIT_SHAPE_MARKER, False)]
        if not targets:
            obj, _modifier = _find_curve_fit_target(context)
            targets = [obj] if obj is not None and obj.get(_FIT_SHAPE_MARKER, False) else []
        if not targets:
            self.report({'WARNING'}, "Select generated Curve Fit shapes")
            return {'CANCELLED'}
        changed = sum(1 for obj in targets if follow_curve_length(obj) is not None)
        self.report({'INFO'}, f"Matched {changed} of {len(targets)} shapes to their curve length")
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

        generated_cyclic = (
            obj.get(_FIT_SHAPE_MARKER, False)
            and obj.get(_FIT_SHAPE_CYCLIC, False)
        )
        existing_rig = _chain_rig_for_mesh(obj)
        should_update_rig = (
            not generated_cyclic
            and (context.scene.ta_curve_fit_generate_chain_rig or existing_rig is not None)
        )
        if context.scene.ta_curve_fit_generate_chain_rig or existing_rig is None:
            rig_bone_count = context.scene.ta_curve_fit_chain_bone_count
            rig_add_end_bone = context.scene.ta_curve_fit_add_end_bone
        else:
            rig_bone_count = int(existing_rig.get(
                _CHAIN_BONE_COUNT,
                context.scene.ta_curve_fit_chain_bone_count,
            ))
            rig_add_end_bone = bool(existing_rig.get(_CHAIN_ADD_END_BONE, False))

        try:
            if should_update_rig:
                _sample_chain_points_world(modifier.object, rig_bone_count)

            curve_obj, length = fit_object_to_curve_modifier(context, obj, modifier)

            if should_update_rig:
                create_or_update_chain_rig(
                    context,
                    obj,
                    modifier,
                    rig_bone_count,
                    rig_add_end_bone,
                )
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

        existing_rig = _chain_rig_for_mesh(obj)
        should_update_rig = context.scene.ta_curve_fit_generate_chain_rig or existing_rig is not None
        if context.scene.ta_curve_fit_generate_chain_rig or existing_rig is None:
            rig_bone_count = context.scene.ta_curve_fit_chain_bone_count
            rig_add_end_bone = context.scene.ta_curve_fit_add_end_bone
        else:
            rig_bone_count = int(existing_rig.get(
                _CHAIN_BONE_COUNT,
                context.scene.ta_curve_fit_chain_bone_count,
            ))
            rig_add_end_bone = bool(existing_rig.get(_CHAIN_ADD_END_BONE, False))

        axis_index, _is_positive_axis = _axis_info(modifier.deform_axis)
        if axis_index is None:
            self.report({'WARNING'}, "Unsupported Curve modifier deform axis")
            return {'CANCELLED'}

        if obj.data.users > 1:
            obj.data = obj.data.copy()

        try:
            if should_update_rig:
                _sample_chain_points_world(modifier.object, rig_bone_count)

            segment_length = _cm_to_scene_units(
                context,
                context.scene.ta_curve_fit_existing_segment_length_cm,
            )
            cyclic_result = rebuild_generated_cyclic_shape(obj, modifier, segment_length)
            if cyclic_result is not None:
                cut_count, axis_length = cyclic_result
            else:
                cut_count, axis_length = segment_mesh_by_length(
                    obj,
                    axis_index,
                    segment_length,
                    modifier.object,
                    context.scene.ta_curve_fit_curvature_boost,
                    context.scene.ta_curve_fit_end_boost,
                )

            if should_update_rig:
                create_or_update_chain_rig(
                    context,
                    obj,
                    modifier,
                    rig_bone_count,
                    rig_add_end_bone,
                )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Segmented {obj.name}: {cut_count} cuts / length {axis_length:.4f}")
        return {'FINISHED'}


class TA_OT_build_curve_fit_chain_rig(bpy.types.Operator):
    bl_idname = "object.ta_build_curve_fit_chain_rig"
    bl_label = "Create / Update Chain Rig"
    bl_description = "Create or rebuild an arc-length bone chain and smooth longitudinal weights for the fitted mesh"
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
            rig_obj, bone_names, curve_length = create_or_update_chain_rig(
                context,
                obj,
                modifier,
                context.scene.ta_curve_fit_chain_bone_count,
                context.scene.ta_curve_fit_add_end_bone,
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Updated {rig_obj.name}: {len(bone_names)} bones / length {curve_length:.4f}",
        )
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
        elif scene.ta_curve_fit_shape_type == 'SWEEP':
            col.prop(scene, "ta_curve_fit_profile_object")
            col.prop(scene, "ta_curve_fit_profile_scale")
            col.prop(scene, "ta_curve_fit_profile_rotation")
            col.prop(scene, "ta_curve_fit_profile_flip")
            col.prop(scene, "ta_curve_fit_sweep_thickness_cm")
            col.prop(scene, "ta_curve_fit_sweep_caps")
        else:
            col.prop(scene, "ta_curve_fit_width_cm")
            if scene.ta_curve_fit_shape_type == 'BOX':
                col.prop(scene, "ta_curve_fit_height_cm")
        col.prop(scene, "ta_curve_fit_plane_segments")
        col.prop(scene, "ta_curve_fit_plane_deform_axis")

        split_col = layout.column(align=True)
        split_col.prop(scene, "ta_curve_fit_split_splines")
        sub = split_col.row()
        sub.enabled = scene.ta_curve_fit_split_splines
        sub.prop(scene, "ta_curve_fit_split_use_evaluated")
        split_col.prop(scene, "ta_curve_fit_follow_length_default")

        row = layout.row()
        row.enabled = obj is not None and obj.type == 'CURVE'
        row.operator("object.ta_create_curve_fit_plane", icon='MOD_CURVE')

        unbend_box = layout.box()
        unbend_box.label(text="Reverse: bent mesh -> curve + straight mesh")
        unbend_row = unbend_box.row()
        unbend_row.enabled = obj is not None and obj.type in {'MESH', 'CURVE'}
        unbend_row.operator("object.ta_unbend_mesh_to_curve", icon='MOD_SIMPLEDEFORM')

        if obj is not None and obj.type == 'MESH' and obj.get(_FIT_SHAPE_MARKER, False):
            shape_box = layout.box()
            shape_box.prop(obj, "ta_curve_fit_follow_length")
            shape_box.operator("object.ta_curve_fit_follow_length", icon='DRIVER_DISTANCE')

        rig_box = layout.box()
        rig_box.prop(scene, "ta_curve_fit_generate_chain_rig")
        if scene.ta_curve_fit_generate_chain_rig:
            rig_col = rig_box.column(align=True)
            rig_col.prop(scene, "ta_curve_fit_chain_bone_count")
            rig_col.prop(scene, "ta_curve_fit_add_end_bone")
            rig_col.operator("object.ta_build_curve_fit_chain_rig", icon='ARMATURE_DATA')

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
    TA_OT_build_curve_fit_chain_rig,
    TA_OT_curve_fit_follow_length,
    TA_PT_curve_fit_plane_panel,
)


def _is_curve_object(_self, obj):
    return obj.type == 'CURVE'


def register():
    bpy.types.Object.ta_curve_fit_source_curve = PointerProperty(
        name="Curve Fit Source",
        type=bpy.types.Object,
        description="Source curve used by this Curve Fit Shape or Chain Rig",
    )
    bpy.types.Object.ta_curve_fit_chain_rig = PointerProperty(
        name="Curve Fit Chain Rig",
        type=bpy.types.Object,
        description="Generated armature associated with this Curve Fit Shape",
    )
    bpy.types.Scene.ta_curve_fit_shape_type = EnumProperty(
        name="Shape",
        default='PLANE',
        items=(
            ('PLANE', 'Plane', 'Create a flat ribbon shape'),
            ('CYLINDER', 'Cylinder', 'Create a round tube shape'),
            ('BOX', 'Box', 'Create a rectangular box shape'),
            ('SWEEP', 'Sweep', 'Sweep a profile curve (local X/Y) along the curve as a real mesh with UVs'),
        ),
    )
    bpy.types.Object.ta_curve_fit_profile_curve = PointerProperty(
        name="Sweep Profile",
        type=bpy.types.Object,
        poll=_is_curve_object,
        description="Profile curve used to build this Sweep shape",
    )
    bpy.types.Object.ta_curve_fit_follow_length = BoolProperty(
        name="Follow Curve Length",
        default=False,
        description="Automatically stretch this shape when its curve length changes (keeps topology and UVs)",
    )
    bpy.types.Scene.ta_curve_fit_profile_object = PointerProperty(
        name="Profile",
        type=bpy.types.Object,
        poll=_is_curve_object,
        description="Profile curve; its local X/Y is swept along the target curve",
    )
    bpy.types.Scene.ta_curve_fit_profile_scale = FloatProperty(
        name="Profile Scale",
        default=1.0,
        min=0.0001,
        soft_max=100.0,
        description="Uniform scale applied to the profile before sweeping",
    )
    bpy.types.Scene.ta_curve_fit_profile_rotation = FloatProperty(
        name="Profile Rotation",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        description="Rotate the profile around the curve direction (degrees)",
    )
    bpy.types.Scene.ta_curve_fit_profile_flip = BoolProperty(
        name="Flip Profile",
        default=False,
        description="Mirror the profile X axis",
    )
    bpy.types.Scene.ta_curve_fit_sweep_thickness_cm = FloatProperty(
        name="Thickness (cm)",
        default=0.0,
        min=0.0,
        soft_max=10.0,
        precision=3,
        description="Give an open profile thickness by offsetting it to both sides (0 keeps a single sheet)",
    )
    bpy.types.Scene.ta_curve_fit_sweep_caps = BoolProperty(
        name="Cap Ends",
        default=True,
        description="Close both ends of a closed profile on an open curve",
    )
    bpy.types.Scene.ta_curve_fit_split_splines = BoolProperty(
        name="One Mesh Per Spline",
        default=True,
        description="Split a multi-spline curve into one curve object per spline (source left untouched) and build one mesh for each",
    )
    bpy.types.Scene.ta_curve_fit_split_use_evaluated = BoolProperty(
        name="Use Evaluated Shape",
        default=True,
        description="When the curve has Geometry Nodes, copy the curve after the curve-only modifiers (relax/normalize) instead of the raw control points",
    )
    bpy.types.Scene.ta_curve_fit_follow_length_default = BoolProperty(
        name="Follow Curve Length",
        default=False,
        description="New shapes stretch automatically when their curve length changes (keeps topology and UVs)",
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
    bpy.types.Scene.ta_curve_fit_generate_chain_rig = BoolProperty(
        name="Generate Chain Rig",
        default=False,
        description="Optionally create a bone chain, Armature modifier, and smooth rope weights",
    )
    bpy.types.Scene.ta_curve_fit_chain_bone_count = IntProperty(
        name="Chain Bones",
        default=12,
        min=2,
        soft_max=64,
        description="Number of deform bones distributed evenly by arc length along the source spline",
    )
    bpy.types.Scene.ta_curve_fit_add_end_bone = BoolProperty(
        name="Add End Bone",
        default=False,
        description="Add a rope_end child bone at the hanging end and blend the rope tip into it",
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
    if _curve_fit_follow_length_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_curve_fit_follow_length_handler)
    from . import curve_unbend
    curve_unbend.register()


def unregister():
    from . import curve_unbend
    curve_unbend.unregister()
    if _curve_fit_follow_length_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_curve_fit_follow_length_handler)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.ta_curve_fit_follow_length_default
    del bpy.types.Scene.ta_curve_fit_split_use_evaluated
    del bpy.types.Scene.ta_curve_fit_split_splines
    del bpy.types.Scene.ta_curve_fit_sweep_caps
    del bpy.types.Scene.ta_curve_fit_sweep_thickness_cm
    del bpy.types.Scene.ta_curve_fit_profile_flip
    del bpy.types.Scene.ta_curve_fit_profile_rotation
    del bpy.types.Scene.ta_curve_fit_profile_scale
    del bpy.types.Scene.ta_curve_fit_profile_object
    del bpy.types.Object.ta_curve_fit_follow_length
    del bpy.types.Object.ta_curve_fit_profile_curve

    del bpy.types.Scene.ta_curve_fit_end_boost
    del bpy.types.Scene.ta_curve_fit_curvature_boost
    del bpy.types.Scene.ta_curve_fit_existing_segment_length_cm
    del bpy.types.Scene.ta_curve_fit_add_end_bone
    del bpy.types.Scene.ta_curve_fit_chain_bone_count
    del bpy.types.Scene.ta_curve_fit_generate_chain_rig
    del bpy.types.Scene.ta_curve_fit_plane_deform_axis
    del bpy.types.Scene.ta_curve_fit_plane_segments
    del bpy.types.Scene.ta_curve_fit_cylinder_sides
    del bpy.types.Scene.ta_curve_fit_radius_cm
    del bpy.types.Scene.ta_curve_fit_height_cm
    del bpy.types.Scene.ta_curve_fit_width_cm
    del bpy.types.Scene.ta_curve_fit_shape_type
    del bpy.types.Object.ta_curve_fit_chain_rig
    del bpy.types.Object.ta_curve_fit_source_curve
