# Handy Vertex Color Edit

Independent Blender color editing with Handy Weight Edit style controls.
Edits the active **Color Attribute**. Handy Weight Edit and Vertex Data Tools
are not dependencies.

## Automatic activation

Open **N > Color > Handy Vertex Color Edit**. The **Attribute View** button
toggles **Solid > Color > Attribute**. Blender's normal viewport controls also
work: shortcuts activate automatically in that specific Attribute viewport.
Weight-overlay viewports, Material/Rendered view and other areas keep their
existing shortcuts. The active mesh must have an active Color Attribute.

**Edit Mode:** select vertices or faces. **Vertex Paint:** enable vertex or face
selection masking before editing. **Object Mode:** channel preview/cycling only.

## Channels

**Shift+Alt+Right Click** cycles **All → R → G → B → All**. Panel buttons select
the channel directly. The displayed channel is also the editing target.

- **All:** native RGB Attribute display; edit RGB independently, preserve alpha.
- **R:** black-to-red display; edit red only.
- **G:** black-to-green display; edit green only.
- **B:** black-to-blue display; edit blue only.

Single channels use their primary color, **not grayscale**. The GPU overlay
reads the evaluated surface, including armature deformation. It does not replace
colors, create preview attributes or change materials. Edit-mode edges and vertex
markers remain visible. The preview applies to the active mesh.

## Controls

| Shortcut | Action |
| --- | --- |
| **Shift+E** | Smooth displayed channels; default strength 0.5 × 1 pass |
| **Shift+Wheel Up/Down** | Fill selection from first selected vertex ± main increment |
| **Shift+Alt+Wheel Up/Down** | Add/subtract main increment from each selected color |
| **Shift+Ctrl+Wheel Up/Down** | Add/subtract micro increment from each selected color |
| **Shift+Ctrl+Alt+Wheel Up/Down** | Fill selection from first selected vertex ± micro increment |
| **Shift+Ctrl+Right Click** | Copy the last selected active vertex to the selection |
| **Shift+Alt+Right Click** | Cycle All → R → G → B |
| **F9** | Adjust the last data operation |
| **Ctrl+Z** | Undo a data operation |

There is **no Ctrl+Shift+E binding**. Original weight shortcuts and settings are
unchanged. Mode-specific color keymaps take precedence in Attribute view, even
if Handy's weight toggle remains on.

Main increment defaults to **0.1**, micro to **0.01**. Fill references the
lowest-index selected vertex, matching Handy's fill concept. Gradient adds to
each value, preserving differences. CORNER references average the vertex's
selected visible corners. Copy requires a vertex selected last in Edit Mode.
The panel also provides 0 / 0.2 / 0.4 / 0.6 / 0.8 / 1 presets.
Increment/fill/copy clamp to 0–1. Untouched channels remain unchanged.

## Smoothing and preservation

- Simultaneous averaging along actual mesh edges; nearby disconnected shells
  do not bleed together. There is no weight normalization.
- **Use Outside Neighbors** reads visible unselected neighbors by default,
  never writing them. Disable it to use only neighbors inside the selection.
- Keep POINT/CORNER and BYTE_COLOR/FLOAT_COLOR. CORNER values blend individually
  towards neighboring vertex averages; connected color seams can soften.
- Smooth in scene-linear space. BYTE_COLOR's native sRGB storage is converted
  consistently for Edit Mode and Vertex Paint. FLOAT_COLOR HDR is not clamped.
- Preserve alpha by default, other attributes, hidden/unselected samples,
  weights, topology, shape keys, selection and mode. Advanced F9 smoothing
  also offers explicit RGBA or Alpha targets.
- Shared mesh data and multi-object Edit Mode are rejected.
- Disabling the add-on removes its preview handlers and GPU resources.

## Installation and source

The module directory is **`addons/vertex_color_smooth`**; the visible add-on name
is **Handy Vertex Color Edit**. This keeps one installed add-on while replacing
the earlier smoothing-only version and its Vertex Data Tools panel attachment.
Place the package in Blender's `scripts/addons`, or use a directory junction,
then enable **Handy Vertex Color Edit**.

Validated in **Blender 5.2.2 LTS**. Blender 4.2+ is the API baseline; other
versions have not been tested on this workstation.

## Validation

17 tests cover color types/domains, masks, hidden/unselected preservation,
channel isolation, fill/gradient/copy, viewport gates, keymaps, weights and shapes:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --factory-startup --background --python 'C:\Users\PARK\Documents\GitHub\blender-personal-addons\tests\test_vertex_color_smooth.py'
```

In an existing GUI Blender, `tests/test_vertex_color_smooth_gpu.py` provides
`run()`: render an in-memory triangle and verify All/R/G/B pixels, including
zero values in the two undisplayed channels. The test does not change production
mesh data, UI settings, `.blend` files or user preferences.
