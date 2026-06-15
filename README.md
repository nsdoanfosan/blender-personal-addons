# Blender Personal Add-ons

Personal Blender add-ons managed in Git and deployed to Blender with Windows
junctions.

## Packages

- `addons/ta_tools`: collection export, linked object, collection move, rename,
  alpha image silhouette mesh, and mesh utility tools.
- `addons/ta_uv_tools`: UV fit and 90 degree rotation tools.
- `addons/align_object`: clicked-object alignment tool.
- `addons/toggle_selected_edge_marks`: seam, bevel weight, and sharp toggles.
- `addons/xyz_transform_gizmo_overlay_stable`: viewport transform overlay.
- `vendor`: third-party source snapshots. These are not deployed by the script.
- `archive`: retired source snapshots. These are not deployed by the script.

## Deploy

Run:

```powershell
.\scripts\deploy.ps1
```

The script creates junctions in Blender's `scripts/addons` directory. Editing
the repository source therefore updates the deployed add-on immediately.
