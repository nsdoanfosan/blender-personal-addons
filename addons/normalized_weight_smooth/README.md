# Selected All Weights Smooth

Handy Weight Edit companion for Blender 4.2+ (verified in 5.2.2 LTS).
Installed from this package through the Blender 5.2 `scripts/addons` junction.
No changes to Handy's original source or its Shift+E key binding.

Select mesh vertices in Edit Mode and press **Ctrl+Shift+E**, or use **Smooth All
Selected Weights** at the bottom of Handy Weight Edit's panel (currently Skinning).
The tool follows Handy's tab customization; if Handy is disabled it has its own
Skinning panel. **F9** changes Strength, Iterations, group scope and boundary sampling
for the last operation; **Ctrl+Z** undoes the complete operation.
Panel settings are defaults for subsequent shortcut invocations.

## Handy active vertex group label

With Handy's **Vertex Weight Toggle** enabled, the active mesh's vertex group
name appears at the **bottom left of the 3D viewport**, even when the N panel
is closed. It also shows the mesh name and `[Locked]` for a locked group.
Switching, renaming or deleting a group updates the label automatically;
no active group is reported explicitly. Turning Handy's toggle off hides it.
Blender's Show Overlays toggle also hides the label.

**Show Active Group in Viewport** and **Group Label Position** are available
below the existing smoothing tools and in this companion's preferences.
Choose **Top Right** to move it below the navigation gizmo. Names wrap in narrow
viewports, and placement avoids the open toolbar/sidebar. This display only
reads the group: it does not change weights, selection, modes or saved UI.

- Default: Strength 0.5, 5 iterations, selection neighbors only.
- All weight influences are averaged together using mesh edges, then normalized
  on every iteration. Group/vertex processing order cannot bias the result.
- Only selected, visible vertices of the active mesh are written. Selection,
  active group, mesh positions, shape keys, active mode and viewport are preserved.
- `Use Outside Neighbors` reads a fixed one-edge halo for boundary blending; no
  unselected vertices are modified, and proximity across disconnected layers
  never supplies neighbors.
- Bone Weights (Auto) includes deform bones of vertex-group-enabled Armature
  modifiers. Mask, cloth pin and other non-bone groups remain untouched. Without
  an armature it includes all groups. `All Vertex Groups` explicitly includes
  masks too. The sum of **the chosen group domain** is 1; independent masks do
  not belong to a skin-weight normalization sum.
- Group locks are respected. Impossible locked budgets cancel before any write.
  Vertices with no influence evidence in the selected topology are skipped and
  reported. Bone influences may spread within the selection (this is smoothing),
  but never change weights outside it. No influence-count limit or pruning.
- Weight Paint requires vertex or face selection masking. Shared mesh data and
  linked meshes are rejected to prevent editing another object's weights.

Tests use disposable generated meshes; no production `.blend` is saved.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --factory-startup --background --python 'C:\Users\PARK\Documents\GitHub\blender-personal-addons\tests\test_normalized_weight_smooth_blender.py'
```
