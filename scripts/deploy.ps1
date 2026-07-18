param(
    [string]$BlenderVersion = "5.1"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repoRoot "addons"
$deployRoot = Join-Path $env:APPDATA "Blender Foundation\Blender\$BlenderVersion\scripts\addons"
$packages = @(
    "ta_tools",
    "ta_uv_tools",
    "align_object",
    "toggle_selected_edge_marks",
    "xyz_transform_gizmo_overlay_stable",
    "wire_bounds_selection_visibility"
)

if (-not (Test-Path -LiteralPath $deployRoot)) {
    throw "Blender add-on directory does not exist: $deployRoot"
}

foreach ($package in $packages) {
    $source = Join-Path $sourceRoot $package
    $target = Join-Path $deployRoot $package

    if (-not (Test-Path -LiteralPath $source)) {
        throw "Package source does not exist: $source"
    }

    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target
        if ($item.LinkType -eq "Junction" -and $item.Target -eq $source) {
            Write-Host "Already linked: $package"
            continue
        }

        throw "Deployment target already exists: $target"
    }

    New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    Write-Host "Linked: $package"
}
