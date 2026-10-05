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
