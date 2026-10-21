"""Topology based, simultaneous color smoothing. No Blender dependency."""

import numpy as np


class ColorSmoothError(ValueError):
    pass


VIEW_CHANNELS = ('RGB', 'R', 'G', 'B')


def isolate_rgb(colors, channel):
    """Opaque, primary-color channel view; never a grayscale replacement."""
    source = np.asarray(colors, dtype=float)
    output = np.zeros(source.shape, dtype=float)
    output[:, 3] = 1.0
    if channel == 'RGB':
        output[:, :3] = source[:, :3]
    else:
        index = {'R': 0, 'G': 1, 'B': 2}[channel]
        output[:, index] = source[:, index]
    return output


def edit_colors(colors, vertices, writable, *, channels=(0, 1, 2),
                action='GRADIENT', delta=0.1, value=0.0, source_vertex=None):
    """Handy-style fill/gradient edits; preserve every other sample/channel."""
    values = np.asarray(colors, dtype=float)
    vertices = np.asarray(vertices, dtype=int)
    targets = np.flatnonzero(writable)
    if not len(targets):
        raise ColorSmoothError("Select visible vertices or faces first")
    if not np.all(np.isfinite(values[targets])):
        raise ColorSmoothError("The selection contains non-finite colors")
    output = values.copy()
    if action == 'GRADIENT':
        result = values[targets][:, channels] + delta
    elif action in {'FILL_DELTA', 'COPY'}:
        anchor = int(vertices[targets].min()) if source_vertex is None else source_vertex
        samples = targets[vertices[targets] == anchor]
        if not len(samples):
            raise ColorSmoothError("Select an active vertex to copy from")
        base = values[samples][:, channels].mean(axis=0)
        result = base + (delta if action == 'FILL_DELTA' else 0.0)
    elif action == 'SET':
        result = np.broadcast_to(value, (4,))[list(channels)]
    else:
        raise ColorSmoothError("Unknown color edit operation")
    output[np.ix_(targets, channels)] = np.clip(result, 0.0, 1.0)
    return output


def srgb_to_linear(rgb):
    return np.where(rgb <= 0.04045, rgb / 12.92,
                    np.maximum((rgb + 0.055) / 1.055, 0.0) ** 2.4)


def linear_to_srgb(rgb):
    return np.where(rgb <= 0.0031308, rgb * 12.92,
                    1.055 * np.maximum(rgb, 0.0) ** (1.0 / 2.4) - 0.055)


def smooth_colors(colors, vertices, edges, writable, readable, *,
                  factor=0.5, iterations=1, channels=(0, 1, 2),
                  use_outside=True):
    """Diffuse each channel along edges; update only writable color samples.

    POINT has one sample per vertex. CORNER samples retain their own values and
    blend gradually towards neighboring vertex averages, without converting the
    attribute domain. Unselected/hidden samples are never written.
    """
    values = np.asarray(colors, dtype=np.float64).copy()
    vertices = np.asarray(vertices, dtype=np.int64)
    edges = np.asarray(edges, dtype=np.int64).reshape((-1, 2))
    writable = np.asarray(writable, dtype=bool)
    readable = np.asarray(readable, dtype=bool)
    channels = tuple(channels)
    count = len(values)
    if (values.shape != (count, 4) or vertices.shape != (count,)
            or writable.shape != (count,) or readable.shape != (count,)):
        raise ColorSmoothError("Invalid color sample layout")
    if not (0.0 <= factor <= 1.0) or not (1 <= iterations <= 100):
        raise ColorSmoothError("Invalid strength or iteration count")
    if not channels or any(c not in range(4) for c in channels):
        raise ColorSmoothError("Choose valid color channels")
    if np.any(vertices < 0) or np.any(edges < 0):
        raise ColorSmoothError("Invalid vertex index")
    writable &= readable
    if not np.any(writable):
        raise ColorSmoothError("Select visible vertices or faces first")
    if not np.all(np.isfinite(values[readable])):
        raise ColorSmoothError("The active attribute contains non-finite colors")
    if factor == 0.0 or not len(edges):
        return values
    nverts = int(max(vertices.max(initial=-1), edges.max(initial=-1))) + 1
    sources = readable if use_outside else readable & writable
    counts = np.bincount(vertices[sources], minlength=nverts)
    # Exclude self edges and duplicates; an edge has the same influence regardless
    # of how many polygons share it. No proximity search or topology mutation.
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    edges = edges[edges[:, 0] != edges[:, 1]]
    directed = np.concatenate((edges, edges[:, ::-1]))
    dst, src = directed[:, 0], directed[:, 1]
    valid = counts[src] > 0
    dst, src = dst[valid], src[valid]
    degree = np.bincount(dst, minlength=nverts)
    targets = np.flatnonzero(writable & (degree[vertices] > 0))
    if not len(targets):
        return values
    for _ in range(iterations):
        # All channels read the previous complete pass (Jacobi iteration).
        for channel in channels:
            sums = np.bincount(vertices[sources], weights=values[sources, channel],
                               minlength=nverts)
            means = np.divide(sums, counts, out=np.zeros(nverts), where=counts > 0)
            neighbor_sums = np.bincount(dst, weights=means[src], minlength=nverts)
            averages = neighbor_sums[vertices[targets]] / degree[vertices[targets]]
            values[targets, channel] += factor * (averages - values[targets, channel])
    return values
