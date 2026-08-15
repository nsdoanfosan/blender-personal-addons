# Blender Personal Add-ons

Personal Blender add-ons managed in Git and deployed to Blender with Windows
junctions.

## Packages

- `addons/ta_tools`: collection export, linked object, collection move, rename,
  alpha image silhouette mesh, and mesh utility tools. Press `Ctrl+Shift+J` in
  the 3D View to open the panel-style TA Quick Menu.
- `addons/ta_uv_tools`: UV fit, 90 degree rotation, and material border seam tools.
- `addons/align_object`: clicked-object alignment tool.
- `addons/clipboard_image_plane`: pastes a Windows clipboard image as a
  textured mesh plane at the 3D cursor. Use `Ctrl+Shift+Alt+V` in the 3D View,
  or choose `Add > Image > Paste Clipboard Image as Plane`.
- `addons/toggle_selected_edge_marks`: seam, bevel weight, and sharp toggles.
- `addons/xyz_transform_gizmo_overlay_stable`: viewport transform overlay.
- `addons/wire_bounds_selection_visibility`: hides WIRE/BOUNDS helper objects and
  reveals the active helper as WIRE when it is clicked in the Outliner.
- `addons/debug_render_pass_cycle`: cycles the active Material Preview or
  supported Rendered viewport through Unreal-style debug passes without changing
  materials. Press `B` to advance through `Combined` > `Base Color` > `Normal` >
  `Specular` > `Ambient Occlusion` > `Opacity` > `Depth` > `Position`. Press `M`
  to return immediately to `Combined`. Unreal buffer views without a Blender
  equivalent are skipped. Outside a supported shading mode, Blender's original
  B/M tools still run.
- `vendor`: third-party source snapshots. These are not deployed by the script.
- `archive`: retired source snapshots. These are not deployed by the script.

## Deploy

Run:

```powershell
.\scripts\deploy.ps1
```

The script creates junctions in Blender's `scripts/addons` directory. Editing
the repository source therefore updates the deployed add-on immediately.
