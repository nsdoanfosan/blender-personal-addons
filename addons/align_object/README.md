# Align Object

Press **Alt+A**, then click a target object. Change axes, target reference,
rotation and percent in **F9 / Adjust Last Operation**.

With Blender's **Affect Only Origins** enabled (PARK's **Ctrl+Shift+Alt+Q**),
the tool aligns only the selected origins. Geometry, mesh/curve shape keys
and child objects stay in place. The source reference is always Pivot;
the target can still be Minimum, Center, Pivot, Maximum or Cursor.
Apply Rotation aligns the origin axes without rotating the source geometry.
The invocation's mode is retained when adjusting the last operation.

Shared geometry is made single-user on the changed object so linked copies
are unaffected. Origin mode supports editable meshes, legacy curves/surfaces,
lattices, armatures and empties. Unsupported objects, read-only linked data
and zero-scale transforms cancel before alignment. Origin-dependent modifiers
and constraints retain Blender's usual origin-change behavior.

With Affect Only Origins off, normal object alignment is unchanged.
**Alt+Shift+A** in multi-object Edit Mode still aligns selected faces.

Validation (no saved files or user preferences):

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --factory-startup --background --python-exit-code 1 --python .\tests\test_align_object_origins.py
```
