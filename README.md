# Blender Personal Add-ons

Personal Blender add-ons managed in Git and deployed to Blender with Windows
junctions.

## Packages

- `addons/ta_tools`: collection export, linked object, collection move, rename,
  alpha image silhouette mesh, and mesh utility tools. Curve Fit Shape can
  optionally generate an arc-length chain rig with smooth rope weights; the
  option is off by default. An independent **Add End Bone** checkbox (also off
  by default) adds a connected `rope_end` bone at the hanging end and blends
  the rope tip into it for payload attachment. Cyclic source splines generate
  truly closed fitted topology with a wrapped UV seam and cyclic-safe segment
  rebuilding. Press `Ctrl+Shift+J` in the 3D View to open the panel-style TA
  Quick Menu. Press `F4` over a 3D View to show or hide the wire overlay while
  keeping the current viewport shading mode.
- `addons/ta_uv_tools`: UV fit, 90 degree rotation, and material border seam tools.
- `addons/align_object`: clicked-object alignment tool.
- `addons/toggle_selected_edge_marks`: seam, bevel weight, and sharp toggles.
- `addons/xyz_transform_gizmo_overlay_stable`: viewport transform overlay.
- `addons/wire_bounds_selection_visibility`: hides WIRE/BOUNDS helper objects and
  reveals the active helper as WIRE when it is clicked in the Outliner.
- `vendor`: third-party source snapshots. These are not deployed by the script.
- `archive`: retired source snapshots. These are not deployed by the script.

## Deploy

Run:

```powershell
.\scripts\deploy.ps1
```

The script creates junctions in Blender's `scripts/addons` directory. Editing
the repository source therefore updates the deployed add-on immediately.

## TA Tools

`addons/ta_tools` is a collection of independent Blender utilities registered
as one add-on. Most panels are in the 3D Viewport sidebar under the **TA** tab.
Two utilities intentionally live elsewhere:

- **Linked Data Info**: 3D Viewport sidebar > **Item**;
- **Quick Collection Move**: Properties editor > **Object Properties**.

### Install TA Tools on Another Machine

1. Zip the `addons/ta_tools` folder.
2. In Blender, open **Edit > Preferences > Add-ons > Install from Disk**.
3. Select the zip and enable **TA Tools**.

Blender 4.0 or newer is required.

### Collection FBX Exporter

Exports each direct child of the active collection to a separate FBX file.

1. In the Outliner, make the parent collection active.
2. Open **N > TA > Collection FBX Exporter**.
3. Choose an output folder. If blank, the default is `exported_fbx` beside the
   `.blend` file.
4. Press **Export Child Collections to FBX**.

For every direct child collection, the tool recursively gathers visible
objects, exports mesh objects only, and names the file after that child
collection. Its FBX settings use `-Y` forward, `Z` up, no unit scaling, and no
space transform.

The operation changes the current object selection while it works.

### Alpha Mesh

Creates a silhouette mesh from the alpha channel of the image connected
upstream of a material's Principled BSDF **Base Color**.

1. Select a mesh plane whose material uses a Base Color image.
2. Open **N > TA > Alpha Mesh**.
3. Press **Alpha Mesh From Base Color**.
4. Adjust the operator options in Blender's last-operation panel:
   - **Alpha Threshold** chooses solid pixels;
   - **Max Sample Dimension** limits tracing cost;
   - **Simplify** and **Smooth Passes** clean the outline;
   - **Minimum Area** removes small islands;
   - **Extrusion** adds a Solidify modifier;
   - **Copy Material** reuses the source material;
   - **Hide Source Plane** hides the original plane.

The generated object is named `<source>_alpha_mesh`, uses the source transform,
and becomes active. Traced holes are currently ignored; the result is built
from outer n-gon islands.

### Curve Fit Plane

Builds a subdivided strip matching a curve's evaluated length and adds a Curve
modifier.

1. In Object Mode, select a Curve object.
2. Open **N > TA > Curve Fit Plane**.
3. Set **Width**, **Segments**, and **Deform Axis**.
4. Press **Create Curve Fit Plane**.

The new mesh is aligned to the curve's world transform, receives a full-length
UV map, and becomes the active object. The Curve modifier remains editable.
Enable **Generate Chain Rig** to create evenly spaced `rope_###` deform bones
and smooth longitudinal weights. Enable **Add End Bone** when the hanging end
needs its own `rope_end` transform for a payload; both options default to off.

### Vertex Group & Color

Initializes selected mesh objects for a simple group-and-color workflow.

1. In Object Mode, select the target mesh objects.
2. Open **N > TA > Vertex Group & Color**.
3. Press **Setup Group & Color**.

Warning: this is a destructive reset. For every selected mesh it:

- deletes **all existing vertex groups**;
- creates one empty group named `Group`;
- deletes **all existing color attributes**;
- creates a `FLOAT_COLOR`, `POINT`-domain attribute named `Color`;
- fills the new color attribute with white.

Use **Vertex Data Tools** instead when existing groups or color attributes must
be preserved.

### Connect Edge

Subdivides selected edges and leaves the newly created edges selected.

1. Enter Mesh Edit Mode.
2. Select one or more edges.
3. Open **N > TA > Connect Edge**.
4. Set **Cuts** from 1 to 10 and press **Connect Edge**.

This uses Blender's edge subdivision without grid fill. Despite the historical
name, it does not run a separate loop-connection solver.

### Linked Data Info

Shows which visible View Layer objects share the active object's underlying
data block.

1. Select an object.
2. Open **N > Item > Linked Data Info**.
3. Review the data-block name, user count, and shared-object list.
4. Click an object name to select and activate it.

This is an inspection and selection tool. It does not make data single-user or
create linked duplicates.

### Quick Collection Move

Moves or links selected objects through a searchable scene-collection tree.

1. Switch to Object Mode and select the objects.
2. Open **Object Properties > Quick Collection Move**.
3. Use **Search** or **Current Only** to filter the list.
4. Use:
   - **Move** to link to the target and unlink from every other collection;
   - **Link** to add another collection membership;
   - the `X` beside a current collection to unlink from it.

The tool refuses to remove an object's final collection link. A target
collection excluded in the active View Layer is made available before moving or
linking.

### Rename Utilities

There are two separate renaming tools.

**Scene Object Renamer** is in **N > Rename Tools**:

1. Optionally enable **Only Mesh Objects**.
2. Press **Rename All Scene Objects**.
3. Objects are renamed from their containing collection:
   `CollectionName_01`, `CollectionName_02`, and so on.

The `Export` collection and its descendants are excluded from traversal.
Objects linked to multiple included collections are renamed only once, based on
the first traversed collection.

**Rename Object(s)** is available through Blender's operator search (`F3`).
With one selected object it performs a simple rename. With multiple objects it
can apply a base name, prefix, suffix, character removal, numbering, and
find/replace.

## TA Tools Developer Map

Registration is centralized in `addons/ta_tools/__init__.py`. Each feature is a
separate module:

```text
addons/ta_tools/
|-- __init__.py                        # bl_info and module registration order
|-- export_collections.py              # child-collection FBX export
|-- alpha_image_to_mesh.py             # image-alpha contour tracing
|-- curve_fit_plane.py                 # curve-length strip generator
|-- linked_object.py                   # shared datablock inspector
|-- move_collection.py                 # move/link/unlink collection UI
|-- rename_objects.py                  # selection-based rename dialog
|-- scene_collection_object_renamer.py # collection-driven scene rename
|-- ta_tool.py                         # destructive group/color reset + edge cut
`-- viewport_wire_overlay.py           # F4 wire overlay toggle
```

When adding a module, import it in `__init__.py` and add it to `modules`.
Registration runs in listed order and unregistration runs in reverse.

The utilities do not share a common settings object. Scene properties are owned
and registered by the module that uses them. Keep that separation when
modifying one tool so unrelated tools can continue to register independently.
