"""Unbend Mesh to Curve: reverse a bent mesh into a centre curve + straight mesh.

The straight mesh is driven back by a Curve modifier (Follow Curve), so it can
be UV-unwrapped / baked straight while the curve keeps controlling the shape.

Correctness does not depend on how well the curve is fitted: the straight
coordinates are computed in the Curve modifier's own frames, measured by
deforming a probe mesh, so re-bending reproduces the source (round-trip error
is measured and reported).

Part sources:
  * Geometry Nodes curve results with cloth_path_* attributes (exact path
    parameter and centres).
  * Plain meshes: centre line from geodesic distance bands (open strips/tubes)
    or two band chains joined into a loop (closed rings).
"""

import heapq
import math

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector

from . import curve_fit_plane as cfp

_UNBEND_MARKER = "_ta_unbend_generated"
_UNBEND_ERROR = "_ta_unbend_roundtrip_mm"


# --------------------------------------------------------------------------- data

def _mesh_positions(mesh):
    co = np.zeros(len(mesh.vertices) * 3, np.float64)
    mesh.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def _mesh_edges(mesh):
    e = np.zeros(len(mesh.edges) * 2, np.int64)
    mesh.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def _point_attr(mesh, name, comp, dtype=np.float64):
    attr = mesh.attributes.get(name)
    if attr is None or attr.domain != 'POINT':
        return None
    buf = np.zeros(len(mesh.vertices) * comp, dtype)
    attr.data.foreach_get("value" if comp == 1 else "vector", buf)
    return buf.reshape(-1, comp) if comp > 1 else buf


def _components(count, edges, mask=None):
    """Union-find connected components; returns label array (-1 for masked out)."""
    parent = np.arange(count)

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    if mask is not None:
        keep = mask[edges[:, 0]] & mask[edges[:, 1]]
        edges = edges[keep]
        members = np.nonzero(mask)[0]
    else:
        members = np.arange(count)
    for a, b in edges.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    labels = np.full(count, -1, np.int64)
    labels[members] = [find(int(i)) for i in members]
    return labels


def _dijkstra(count, adjacency, source):
    dist = np.full(count, np.inf)
    dist[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for w, length in adjacency[v]:
            nd = d + length
            if nd < dist[w]:
                dist[w] = nd
                heapq.heappush(heap, (nd, w))
    return dist


def _resample(points, count, cyclic):
    pts = np.asarray(points, np.float64)
    if cyclic:
        pts = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 1e-12:
        raise ValueError("Centre line has zero length")
    targets = np.linspace(0.0, total, count, endpoint=not cyclic)
    out = np.empty((count, 3))
    for k in range(3):
        out[:, k] = np.interp(targets, cum, pts[:, k])
    return out, total


def _smooth(points, iterations, cyclic):
    pts = np.asarray(points, np.float64).copy()
    for _ in range(iterations):
        if cyclic:
            pts = 0.5 * pts + 0.25 * (np.roll(pts, 1, 0) + np.roll(pts, -1, 0))
        else:
            inner = 0.5 * pts[1:-1] + 0.25 * (pts[:-2] + pts[2:])
            pts[1:-1] = inner
    return pts


# ----------------------------------------------------------------- centre lines

def _centerline_from_attributes(pos, u, centers, cyclic_flag):
    order = np.argsort(u)
    keys = np.round(u[order], 6)
    _, first = np.unique(keys, return_index=True)
    sel = order[first]
    line = centers[sel]
    params = u[sel]
    cyclic = bool(cyclic_flag)
    # expected arc parameter per vertex: u scaled by centre length
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    expected = np.interp(u, params, cum)
    if cyclic:
        total = cum[-1] + np.linalg.norm(line[-1] - line[0])
    else:
        total = cum[-1]
    return line, cyclic, expected / max(total, 1e-12)


def _project_to_polyline(pos, line, cyclic, expected=None, window=0.15):
    """Arc parameter (0..1) of each vertex on a polyline; optional expected param window."""
    pts = np.vstack([line, line[:1]]) if cyclic else line
    a = pts[:-1]
    b = pts[1:]
    ab = b - a
    seg_len = np.linalg.norm(ab, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    seg_mid = cum[:-1] / total + seg_len / total * 0.5
    out = np.empty(len(pos))
    chunk = 4000
    for start in range(0, len(pos), chunk):
        p = pos[start:start + chunk]
        rel = p[:, None, :] - a[None, :, :]
        t = np.clip(np.einsum("nsk,sk->ns", rel, ab) / np.maximum(seg_len ** 2, 1e-18), 0.0, 1.0)
        proj = a[None] + ab[None] * t[..., None]
        d = np.linalg.norm(p[:, None, :] - proj, axis=2)
        if expected is not None:
            e = expected[start:start + chunk]
            diff = np.abs(seg_mid[None, :] - e[:, None])
            if cyclic:
                diff = np.minimum(diff, 1.0 - diff)
            d = np.where((e[:, None] >= 0) & (diff > window), d + 1e9, d)
        k = np.argmin(d, axis=1)
        out[start:start + chunk] = (cum[k] + t[np.arange(len(p)), k] * seg_len[k]) / total
    return out


def _refine_centerline(pos, line, cyclic, expected, bands, iterations=2):
    for _ in range(iterations):
        param = _project_to_polyline(pos, line, cyclic, expected)
        idx = np.clip((param * bands).astype(int), 0, bands - 1)
        new = []
        for k in range(bands):
            sel = idx == k
            if sel.any():
                new.append(pos[sel].mean(axis=0))
        if len(new) < 3:
            break
        line = _smooth(np.array(new), 2, cyclic)
        expected = _project_to_polyline(pos, line, cyclic, param, window=0.1)
    return line, expected


def _centerline_from_geodesic(pos, edges, bands, face_count=None):
    count = len(pos)
    euler = None if face_count is None else count - len(edges) + face_count
    lengths = np.linalg.norm(pos[edges[:, 0]] - pos[edges[:, 1]], axis=1)
    adjacency = [[] for _ in range(count)]
    for (a, b), length in zip(edges, lengths):
        adjacency[a].append((b, length))
        adjacency[b].append((a, length))
    d0 = _dijkstra(count, adjacency, 0)
    a = int(np.argmax(np.where(np.isfinite(d0), d0, -1)))
    da = _dijkstra(count, adjacency, a)
    finite = np.isfinite(da)
    dmax = da[finite].max()
    if dmax <= 1e-12:
        raise ValueError("Part is degenerate")
    band = np.clip((da / dmax * bands).astype(int), 0, bands - 1)
    band[~finite] = -1

    band_comps = []
    two = 0
    for k in range(bands):
        mask = band == k
        if not mask.any():
            band_comps.append([])
            continue
        # connectivity through neighbouring bands so slanted level sets do not fragment
        wide = (band >= k - 2) & (band <= k + 2)
        labels = _components(count, edges, wide)
        comps = []
        for lab in np.unique(labels[mask]):
            idx = np.nonzero(mask & (labels == lab))[0]
            if len(idx) >= 1:
                comps.append(idx)
        comps.sort(key=len, reverse=True)
        big = [c for c in comps if len(c) >= max(2, len(comps[0]) * 0.2)]
        band_comps.append(big)
        if len(big) >= 2:
            two += 1
    if euler in (1, 2):
        cyclic = False
    elif euler == 0:
        cyclic = True
    else:
        cyclic = two > bands * 0.4

    expected_index = np.full(count, -1.0)
    if not cyclic:
        line = []
        for k, comps in enumerate(band_comps):
            if not comps:
                continue
            line.append(pos[comps[0]].mean(axis=0))
            for c in comps:
                expected_index[c] = len(line) - 1
        line = np.array(line)
    else:
        chain_a, chain_b = [], []
        idx_a, idx_b = [], []
        start = [c for c in band_comps[0]]
        end = [c for c in band_comps[-1]]
        prev_a = prev_b = None
        for k in range(1, bands - 1):
            comps = band_comps[k]
            if not comps:
                continue
            cents = [pos[c].mean(axis=0) for c in comps[:2]]
            if len(comps) == 1:
                cents = [cents[0], cents[0]]
                comps = [comps[0], comps[0]]
            if prev_a is None:
                order = (0, 1)
            else:
                cost0 = np.linalg.norm(cents[0] - prev_a) + np.linalg.norm(cents[1] - prev_b)
                cost1 = np.linalg.norm(cents[1] - prev_a) + np.linalg.norm(cents[0] - prev_b)
                order = (0, 1) if cost0 <= cost1 else (1, 0)
            prev_a, prev_b = cents[order[0]], cents[order[1]]
            chain_a.append(prev_a); idx_a.append(comps[order[0]])
            chain_b.append(prev_b); idx_b.append(comps[order[1]])
        line = []
        groups = []
        if start:
            line.append(pos[np.concatenate(start)].mean(axis=0)); groups.append(np.concatenate(start))
        for c, g in zip(chain_a, idx_a):
            line.append(c); groups.append(g)
        if end:
            line.append(pos[np.concatenate(end)].mean(axis=0)); groups.append(np.concatenate(end))
        for c, g in zip(reversed(chain_b), reversed(idx_b)):
            line.append(c); groups.append(g)
        for i, g in enumerate(groups):
            expected_index[g] = i
        line = np.array(line)

    n = len(line)
    if n < 3:
        raise ValueError("Could not trace a centre line (part too short or branching)")
    seg = np.linalg.norm(np.diff(np.vstack([line, line[:1]]) if cyclic else line, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    expected = np.where(expected_index >= 0, np.interp(expected_index, np.arange(len(cum)), cum) / total, -1.0)
    line, expected = _refine_centerline(pos, _smooth(line, 2, cyclic), cyclic, expected, bands)
    return line, cyclic, expected


# ---------------------------------------------------------------- curve & frames

def _make_curve(name, local_points, cyclic, control_points, matrix, collection):
    pts, length = _resample(local_points, control_points, cyclic)
    data = bpy.data.curves.new(name, type='CURVE')
    data.dimensions = '3D'
    data.resolution_u = 32
    data.twist_mode = 'MINIMUM'
    data.use_radius = False
    data.use_stretch = False
    data.use_deform_bounds = False
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(len(pts) - 1)
    for bp, co in zip(spline.bezier_points, pts):
        bp.co = Vector(co)
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    obj.matrix_world = matrix.copy()
    collection.objects.link(obj)
    return obj


def _probe_frames(curve_obj, s_values, collection):
    """Deform a probe through a Curve modifier -> origin, Y, Z unit axes per s."""
    eps = 1e-3
    verts = []
    for s in s_values:
        verts += [(s, 0.0, 0.0), (s, eps, 0.0), (s, 0.0, eps)]
    mesh = bpy.data.meshes.new("_ta_unbend_probe")
    mesh.from_pydata(verts, [], [])
    probe = bpy.data.objects.new("_ta_unbend_probe", mesh)
    probe.matrix_world = curve_obj.matrix_world.copy()
    collection.objects.link(probe)
    mod = probe.modifiers.new("Follow Curve", 'CURVE')
    mod.object = curve_obj
    mod.deform_axis = 'POS_X'
    try:
        bpy.context.view_layer.update()
        ev = probe.evaluated_get(bpy.context.evaluated_depsgraph_get())
        em = ev.to_mesh()
        co = _mesh_positions(em).reshape(-1, 3, 3)
        ev.to_mesh_clear()
    finally:
        bpy.data.objects.remove(probe, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    origin = co[:, 0]
    y = co[:, 1] - origin
    z = co[:, 2] - origin
    y /= np.maximum(np.linalg.norm(y, axis=1, keepdims=True), 1e-12)
    z /= np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)
    return origin, y, z


def _curve_length(curve_obj):
    return cfp._curve_local_length(curve_obj)


def _fit_tilt(curve_obj, pos, expected, length, cyclic, collection, samples):
    """Rotate curve frames so local Y follows the part's widest cross direction."""
    spline = curve_obj.data.splines[0]
    s = np.linspace(0.0, length, samples, endpoint=not cyclic)
    origin, y_axis, _z = _probe_frames(curve_obj, s, collection)
    tangent = np.gradient(origin, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    vert_s = expected * length
    angles = np.full(samples, np.nan)
    half = length / samples
    for i in range(samples):
        if cyclic:
            dd = np.abs((vert_s - s[i] + length * 0.5) % length - length * 0.5)
        else:
            dd = np.abs(vert_s - s[i])
        sel = (expected >= 0) & (dd <= half * 1.5)
        if sel.sum() < 4:
            continue
        rel = pos[sel] - origin[i]
        rel -= np.outer(rel @ tangent[i], tangent[i])
        cov = rel.T @ rel
        w, v = np.linalg.eigh(cov)
        if w[-1] <= 1e-18 or w[-1] < w[-2] * 2.0:
            continue  # round cross-section: no preferred direction
        d = v[:, -1]
        angles[i] = math.atan2(float(np.cross(y_axis[i], d) @ tangent[i]), float(y_axis[i] @ d))
    valid = ~np.isnan(angles)
    if valid.sum() < 2:
        return 0.0
    # pi-periodic unwrap (direction sign is ambiguous)
    a = angles[valid]
    for i in range(1, len(a)):
        while a[i] - a[i - 1] > math.pi / 2:
            a[i] -= math.pi
        while a[i] - a[i - 1] < -math.pi / 2:
            a[i] += math.pi
    s_valid = s[valid]
    count = len(spline.bezier_points)
    ctrl_s = np.linspace(0.0, length, count, endpoint=not cyclic)
    tilt = np.interp(ctrl_s, s_valid, a)

    def apply(sign):
        for bp, t in zip(spline.bezier_points, tilt):
            bp.tilt = sign * float(t)
        curve_obj.data.update_tag()

    def residual():
        o2, y2, _ = _probe_frames(curve_obj, s_valid, collection)
        res = []
        for i, si in enumerate(s_valid):
            idx = int(np.argmin(np.abs(s - si)))
            dd = np.abs(vert_s - si)
            sel = (expected >= 0) & (dd <= half * 1.5)
            rel = pos[sel] - o2[i]
            rel -= np.outer(rel @ tangent[idx], tangent[idx])
            w, v = np.linalg.eigh(rel.T @ rel)
            res.append(abs(float(abs(v[:, -1] @ y2[i]))))
        return float(np.mean(res))

    apply(1.0)
    pos_score = residual()
    apply(-1.0)
    neg_score = residual()
    if pos_score >= neg_score:
        apply(1.0)
        return pos_score
    return neg_score


def _unbend_coords(curve_obj, pos, expected, length, cyclic, collection, samples):
    has_exp = expected >= 0
    exp_s = np.where(has_exp, expected * length, 0.0)
    if cyclic:
        s_lo, s_hi = 0.0, length
        count = samples * 4
        s = np.linspace(0.0, length, count, endpoint=False)
    else:
        # measure how far the part reaches past both curve ends (e.g. tassel fringe)
        eps = length * 1e-3
        ends, _y, _z = _probe_frames(curve_obj, [0.0, eps, length - eps, length], collection)
        t_start = (ends[1] - ends[0]) / max(np.linalg.norm(ends[1] - ends[0]), 1e-12)
        t_end = (ends[3] - ends[2]) / max(np.linalg.norm(ends[3] - ends[2]), 1e-12)
        past_end = (pos - ends[3]) @ t_end
        past_start = (ends[0] - pos) @ t_start
        near_end = (~has_exp) | (expected > 0.5)
        beyond_end = near_end & (past_end > 0.0)
        beyond_start = (~near_end | ~has_exp) & (past_start > 0.0)
        exp_s = np.where(beyond_end, length + past_end, exp_s)
        exp_s = np.where(beyond_start, -past_start, exp_s)
        has_exp = has_exp | beyond_end | beyond_start
        over_end = float(past_end[beyond_end].max()) if beyond_end.any() else 0.0
        over_start = float(past_start[beyond_start].max()) if beyond_start.any() else 0.0
        s_lo = -max(over_start * 1.1, length * 0.05)
        s_hi = length + max(over_end * 1.1, length * 0.05)
        count = int(samples * 4 * (s_hi - s_lo) / length)
        s = np.linspace(s_lo, s_hi, count)
    origin, y_axis, z_axis = _probe_frames(curve_obj, s, collection)
    n = len(pos)
    step = (s[1] - s[0])
    window = max(8, int(samples * 4 * 0.06))
    exp_idx = np.where(has_exp, (exp_s - s[0]) / step, 0).round().astype(np.int64)

    best = np.zeros(n, np.int64)
    chunk = 20000
    offsets = np.arange(-window, window + 1)
    for start in range(0, n, chunk):
        sl = slice(start, min(n, start + chunk))
        p = pos[sl]
        cand = exp_idx[sl, None] + offsets[None, :]
        if cyclic:
            cand %= count
        else:
            cand = np.clip(cand, 0, count - 1)
        d = np.linalg.norm(origin[cand] - p[:, None, :], axis=2)
        local = cand[np.arange(len(p)), np.argmin(d, axis=1)]
        # vertices without an expected parameter: global search
        no = ~has_exp[sl]
        if no.any():
            gd = np.linalg.norm(origin[None, :, :] - p[no][:, None, :], axis=2)
            local[no] = np.argmin(gd, axis=1)
        best[sl] = local

    # refine on neighbouring segment
    def seg_param(i0, i1, p):
        a = origin[i0]; b = origin[i1]
        ab = b - a
        t = np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
        return np.clip(t, 0.0, 1.0)

    prev = best - 1
    nxt = best + 1
    if cyclic:
        prev %= count; nxt %= count
    else:
        prev = np.clip(prev, 0, count - 1); nxt = np.clip(nxt, 0, count - 1)
    t_n = seg_param(best, nxt, pos)
    t_p = seg_param(best, prev, pos)
    pn = origin[best] + (origin[nxt] - origin[best]) * t_n[:, None]
    pp = origin[best] + (origin[prev] - origin[best]) * t_p[:, None]
    use_next = np.linalg.norm(pos - pn, axis=1) <= np.linalg.norm(pos - pp, axis=1)
    j = np.where(use_next, nxt, prev)
    t = np.where(use_next, t_n, t_p)
    o = origin[best] + (origin[j] - origin[best]) * t[:, None]
    ya = y_axis[best] + (y_axis[j] - y_axis[best]) * t[:, None]
    za = z_axis[best] + (z_axis[j] - z_axis[best]) * t[:, None]
    ya /= np.maximum(np.linalg.norm(ya, axis=1, keepdims=True), 1e-12)
    za /= np.maximum(np.linalg.norm(za, axis=1, keepdims=True), 1e-12)
    s_best = s[best]
    s_j = s[j]
    if cyclic:
        # unwrap neighbour across the seam
        s_j = np.where(np.abs(s_j - s_best) > length * 0.5, s_j + np.sign(s_best - s_j) * length, s_j)
    sx = s_best + (s_j - s_best) * t
    rel = pos - o
    out = np.column_stack([sx, np.einsum("ij,ij->i", rel, ya), np.einsum("ij,ij->i", rel, za)])
    return out


def _split_cyclic_seam(mesh, length):
    """Open a closed part in straight space: faces that wrap across the whole
    length get their own copies of the start-side vertices, moved by +length.
    On a cyclic curve x and x+length land on the same point, so the bent
    result stays closed while the straight mesh becomes a clean strip.
    Returns the source vertex index of every vertex after the split."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    src = bm.verts.layers.int.new("_ta_unbend_src")
    for v in bm.verts:
        v[src] = v.index
    half = length * 0.5

    def wraps(face):
        xs = [v.co.x for v in face.verts]
        return max(xs) - min(xs) > half

    wrap_faces = {f for f in bm.faces if wraps(f)}
    if wrap_faces:
        seam_edges = []
        for edge in bm.edges:
            if all(v.co.x < half for v in edge.verts):
                adjacent = list(edge.link_faces)
                if any(f in wrap_faces for f in adjacent) and any(f not in wrap_faces for f in adjacent):
                    seam_edges.append(edge)
        if seam_edges:
            bmesh.ops.split_edges(bm, edges=seam_edges)
        moved = set()
        for face in list(bm.faces):
            if not wraps(face):
                continue
            for v in face.verts:
                if v.co.x < half and v not in moved:
                    if all(wraps(f) for f in v.link_faces):
                        v.co.x += length
                        moved.add(v)
    bm.verts.ensure_lookup_table()
    src_index = np.array([v[src] for v in bm.verts], np.int64)
    bm.verts.layers.int.remove(src)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return src_index


# --------------------------------------------------------------------- parts

def _part_mesh(source_mesh, vert_mask, name):
    bm = bmesh.new()
    bm.from_mesh(source_mesh)
    bm.verts.ensure_lookup_table()
    drop = [v for v in bm.verts if not vert_mask[v.index]]
    bmesh.ops.delete(bm, geom=drop, context='VERTS')
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for mat in source_mesh.materials:
        mesh.materials.append(mat)
    return mesh


def _parts(mesh, split_mode, max_islands):
    count = len(mesh.vertices)
    edges = _mesh_edges(mesh)
    pid = _point_attr(mesh, "cloth_path_id", 1, np.int64)
    parts = []
    if pid is not None and split_mode in {'AUTO', 'ATTRIBUTE'}:
        for k in np.unique(pid):
            parts.append(("path_%02d" % int(k), pid == k))
    else:
        labels = _components(count, edges)
        uniq, counts = np.unique(labels, return_counts=True)
        for i, lab in enumerate(uniq[np.argsort(-counts)]):
            parts.append(("part_%02d" % i, labels == lab))
    return parts, edges


def unbend_object(context, obj, control_points=12, samples=128, fit_tilt=True,
                  split_mode='AUTO', max_islands=4, max_part_vertices=1000000,
                  generate_uv=True, hide_source=False):
    if obj.type not in {'MESH', 'CURVE'}:
        raise ValueError("Select a mesh, or a curve that generates a mesh")
    depsgraph = context.evaluated_depsgraph_get()
    source = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), depsgraph=depsgraph,
                                             preserve_all_data_layers=True)
    collection_name = f"{obj.name} · Unbend"
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        parent = obj.users_collection[0] if obj.users_collection else context.scene.collection
        parent.children.link(collection)

    report = {"created": [], "skipped": []}
    try:
        parts, all_edges = _parts(source, split_mode, max_islands)
        has_attrs = all(_point_attr(source, n, c) is not None for n, c in
                        (("cloth_path_u", 1), ("cloth_path_center", 3)))
        for part_name, mask in parts:
            nverts = int(mask.sum())
            if nverts < 6:
                report["skipped"].append((part_name, "too few vertices"))
                continue
            # keep the largest island when the part is a cloud of islands (e.g. tassel threads)
            labels = _components(len(source.vertices), all_edges, mask)
            uniq, counts = np.unique(labels[mask], return_counts=True)
            note = ""
            if len(uniq) > max_islands:
                main = uniq[np.argmax(counts)]
                mask = labels == main
                note = f"kept largest island ({int(counts.max())} of {nverts} verts, {len(uniq) - 1} islands left)"
                nverts = int(mask.sum())
            if nverts > max_part_vertices:
                report["skipped"].append((part_name, f"{nverts} verts > limit {max_part_vertices}"))
                continue
            pmesh = _part_mesh(source, mask, f"{obj.name}_{part_name}_unbend")
            try:
                pos = _mesh_positions(pmesh)
                pedges = _mesh_edges(pmesh)
                if has_attrs:
                    u = _point_attr(pmesh, "cloth_path_u", 1)
                    centers = _point_attr(pmesh, "cloth_path_center", 3)
                    cyc_attr = _point_attr(pmesh, "cloth_path_cyclic", 1, bool)
                    line, cyclic, expected = _centerline_from_attributes(
                        pos, u, centers, cyc_attr is not None and cyc_attr.any())
                    method = "attributes"
                else:
                    bands = max(12, min(samples, nverts // 8))
                    line, cyclic, expected = _centerline_from_geodesic(pos, pedges, bands, len(pmesh.polygons))
                    method = "geodesic"
                line = _smooth(line, 2, cyclic)
                curve = _make_curve(f"{obj.name}_{part_name}_curve", line, cyclic,
                                    max(3 if cyclic else 2, control_points), obj.matrix_world, collection)
                length = _curve_length(curve)
                tilt_score = None
                if fit_tilt:
                    tilt_score = _fit_tilt(curve, pos, expected, length, cyclic, collection, samples)
                straight = _unbend_coords(curve, pos, expected, length, cyclic, collection, samples)
                pmesh.vertices.foreach_set("co", straight.astype(np.float32).ravel())
                pmesh.update()
                src_index = np.arange(len(pos))
                if cyclic:
                    src_index = _split_cyclic_seam(pmesh, length)
                    straight = _mesh_positions(pmesh)
                if generate_uv and len(pmesh.uv_layers) == 0:
                    uv = pmesh.uv_layers.new(name="UVMap")
                    lv = np.zeros(len(pmesh.loops), np.int64)
                    pmesh.loops.foreach_get("vertex_index", lv)
                    span = max(float(np.ptp(straight[:, 0])), float(np.ptp(straight[:, 1])), 1e-9)
                    uvs = np.column_stack([(straight[lv, 0] - straight[:, 0].min()) / span,
                                           (straight[lv, 1] - straight[:, 1].min()) / span])
                    uv.data.foreach_set("uv", uvs.astype(np.float32).ravel())
                mobj = bpy.data.objects.new(f"{obj.name}_{part_name}_unbend", pmesh)
                mobj.matrix_world = obj.matrix_world.copy()
                collection.objects.link(mobj)
                mod = mobj.modifiers.new("Follow Curve", 'CURVE')
                mod.object = curve
                mod.deform_axis = 'POS_X'
                mobj.ta_curve_fit_source_curve = curve
                mobj[cfp._FIT_SHAPE_MARKER] = True
                mobj[cfp._FIT_SHAPE_TYPE] = 'UNBEND'
                mobj[cfp._FIT_SHAPE_CYCLIC] = bool(cyclic)
                mobj[cfp._FIT_SHAPE_LENGTH] = length
                mobj[_UNBEND_MARKER] = obj.name
                pmesh = None
                # round trip
                context.view_layer.update()
                ev = mobj.evaluated_get(context.evaluated_depsgraph_get())
                em = ev.to_mesh()
                back = _mesh_positions(em)
                ev.to_mesh_clear()
                err = np.linalg.norm(back - pos[src_index], axis=1)
                size = float(np.linalg.norm(np.ptp(pos, axis=0)))
                stats = [float(np.percentile(err, 50)), float(np.percentile(err, 95)), float(err.max())]
                mobj[_UNBEND_ERROR] = [x * 1000.0 for x in stats]
                report["created"].append({
                    "part": part_name, "mesh": mobj.name, "curve": curve.name, "method": method,
                    "cyclic": bool(cyclic), "verts": len(back), "length": length,
                    "roundtrip_p50_p95_max": stats, "size": size, "tilt_residual": tilt_score, "note": note,
                })
            finally:
                if pmesh is not None:
                    bpy.data.meshes.remove(pmesh)
    finally:
        bpy.data.meshes.remove(source)
    if hide_source and report["created"]:
        obj.hide_set(True)
    return report


# ------------------------------------------------------------------ operator

class TA_OT_unbend_mesh_to_curve(bpy.types.Operator):
    bl_idname = "object.ta_unbend_mesh_to_curve"
    bl_label = "Unbend Mesh To Curve"
    bl_description = ("Reverse a bent mesh (or a curve that generates one) into a centre curve plus a "
                      "straight mesh driven by Follow Curve; the source is left untouched")
    bl_options = {'REGISTER', 'UNDO'}

    control_points: IntProperty(name="Control Points", default=12, min=2, soft_max=64)
    samples: IntProperty(name="Samples", default=128, min=16, soft_max=1024,
                         description="Frame samples along the curve (accuracy vs speed)")
    fit_tilt: BoolProperty(name="Fit Tilt", default=True,
                           description="Rotate the curve so the straight mesh lies flat (strips/ribbons)")
    split_mode: EnumProperty(name="Parts", default='AUTO', items=(
        ('AUTO', "Auto", "cloth_path_id attribute when present, otherwise mesh islands"),
        ('ATTRIBUTE', "Path Attribute", "One part per cloth_path_id"),
        ('ISLANDS', "Islands", "One part per connected mesh island"),
    ))
    max_islands: IntProperty(name="Max Islands Per Part", default=4, min=1,
                             description="Parts with more islands keep only their largest island")
    max_part_vertices: IntProperty(name="Max Part Vertices", default=1000000, min=100)
    hide_source: BoolProperty(name="Hide Source", default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return context.mode == 'OBJECT' and obj is not None and obj.type in {'MESH', 'CURVE'}

    def execute(self, context):
        obj = context.active_object
        try:
            report = unbend_object(context, obj, self.control_points, self.samples, self.fit_tilt,
                                   self.split_mode, self.max_islands, self.max_part_vertices,
                                   True, self.hide_source)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        created = report["created"]
        if not created:
            self.report({'WARNING'}, "Nothing unbent: " + "; ".join(f"{p}: {r}" for p, r in report["skipped"]))
            return {'CANCELLED'}
        worst = max(c["roundtrip_p50_p95_max"][2] / max(c["size"], 1e-9) for c in created)
        msg = f"Unbent {len(created)} parts (worst round-trip {worst * 100:.2f}% of size)"
        if report["skipped"]:
            msg += f", skipped {len(report['skipped'])}"
        self.report({'WARNING'} if worst > 0.01 or report["skipped"] else {'INFO'}, msg)
        return {'FINISHED'}


classes = (TA_OT_unbend_mesh_to_curve,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
