"""Sparse, simultaneous topology smoothing without Blender dependencies."""

from math import fsum, isfinite


class WeightError(ValueError):
    pass


def normalize(row, locked, vertex):
    """Preserve locked values and fit unlocked values into their remaining budget."""
    fixed = {g: w for g, w in row.items() if g in locked and w > 0.0}
    fixed_sum = fsum(fixed.values())
    if fixed_sum > 1.0 + 1e-7:
        raise WeightError(f"Vertex {vertex}: locked weights exceed 1; unlock a group first")
    budget = max(0.0, 1.0 - fixed_sum)
    movable = {g: w for g, w in row.items() if g not in locked and w > 0.0}
    total = fsum(movable.values())
    if budget > 1e-7 and total <= 0.0:
        if fixed:
            raise WeightError(f"Vertex {vertex}: locked weights leave an unfillable budget")
        return {}  # No evidence of an influence: never invent a bone assignment.
    if total > 0.0 and budget > 0.0:
        fixed.update({g: w * budget / total for g, w in movable.items()})
    return fixed


def smooth_weights(rows, neighbors, selected, allowed, locked, factor=0.5,
                   iterations=5, use_outside=False):
    """Return selected rows only. Unselected rows and out-of-scope groups are immutable.

    Each iteration reads one snapshot (Jacobi); group/vertex order cannot bias the
    result. Only real edges supply neighbors. Locked groups retain original bytes.
    Entire calculation/validation completes before the caller writes any weights.
    """
    if not 0.0 <= factor <= 1.0 or not isfinite(factor):
        raise WeightError("Strength must be between 0 and 1")
    if iterations < 1:
        raise WeightError("Iterations must be at least 1")
    selected = set(selected)
    allowed = set(allowed)
    locked = set(locked) & allowed
    adjacency = {v: tuple(n for n in neighbors.get(v, ())
                          if n in rows and (use_outside or n in selected))
                 for v in selected}
    needed = selected | {n for ns in adjacency.values() for n in ns}
    source = {v: {g: w for g, w in rows[v].items() if g in allowed and w > 0.0}
              for v in needed}
    if any(not isfinite(w) or w < 0.0 or w > 1.0
           for v in needed for g, w in rows[v].items() if g in allowed):
        raise WeightError("Weights must be finite values between 0 and 1")
    current = {}
    for v, row in source.items():
        if v in selected:
            current[v] = normalize(row, locked, v)
        else:
            total = fsum(row.values())
            current[v] = {g: w / total for g, w in row.items()} if total else {}
    for _ in range(iterations):
        updates = {}
        for v in selected:
            ns = [n for n in adjacency[v] if current[n]]
            candidate = dict(current[v])
            if ns and factor > 0.0:
                mean = {}
                for n in ns:
                    for g, w in current[n].items():
                        if g not in locked:
                            mean[g] = mean.get(g, 0.0) + w / len(ns)
                candidate = {g: (1.0 - factor) * current[v].get(g, 0.0)
                             + factor * mean.get(g, 0.0)
                             for g in (current[v].keys() | mean.keys()) if g not in locked}
                candidate.update({g: w for g, w in source[v].items() if g in locked})
            updates[v] = normalize(candidate, locked, v)
        current.update(updates)
    output = {}
    unweighted = 0
    for v in selected:
        if not current[v]:
            unweighted += 1
            continue
        output[v] = {g: w for g, w in rows[v].items() if g not in allowed or g in locked}
        output[v].update({g: w for g, w in current[v].items() if g not in locked})
    return output, unweighted
