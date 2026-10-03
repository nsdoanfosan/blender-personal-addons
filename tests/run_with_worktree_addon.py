"""Run a TA Tools test against this worktree's add-on inside a normal Blender
session (user prefs loaded, never saved). Avoids --factory-startup, which on
Blender 5.2 clears the extensions wheel cache.

blender -b --python tests/run_with_worktree_addon.py -- tests/<test>.py
"""
import addon_utils
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.join(os.path.dirname(HERE), "addons")
MODULE = "ta_tools"

addon_utils.disable(MODULE, default_set=False)
for name in [n for n in sys.modules if n == MODULE or n.startswith(MODULE + ".")]:
    del sys.modules[name]
sys.path.insert(0, ADDONS)
os.environ["TA_TOOLS_ADDONS_DIR"] = ADDONS

test_path = sys.argv[sys.argv.index("--") + 1]
runpy.run_path(test_path, run_name="__main__")
