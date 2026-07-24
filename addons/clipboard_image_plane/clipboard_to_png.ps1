param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Save-ClipboardImageAsPng {
    param(
        [Parameter(Mandatory = $true)]
        [System.Drawing.Image]$Image,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $bitmap = New-Object System.Drawing.Bitmap $Image

    try {
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $bitmap.Dispose()
    }
}

if ([System.Windows.Forms.Clipboard]::ContainsImage()) {
    $clipboardImage = [System.Windows.Forms.Clipboard]::GetImage()

    try {
        Save-ClipboardImageAsPng -Image $clipboardImage -Path $OutputPath
    }
    finally {
        $clipboardImage.Dispose()
    }

    exit 0
}

if ([System.Windows.Forms.Clipboard]::ContainsFileDropList()) {
    $supportedExtensions = @(
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp"
    )

    $imagePath = [System.Windows.Forms.Clipboard]::GetFileDropList() |
        Where-Object {
            $supportedExtensions -contains (
                [System.IO.Path]::GetExtension($_).ToLowerInvariant()
            )
        } |
        Select-Object -First 1

    if ($imagePath) {
        $fileImage = [System.Drawing.Image]::FromFile($imagePath)

        try {
            Save-ClipboardImageAsPng -Image $fileImage -Path $OutputPath
        }
        finally {
            $fileImage.Dispose()
        }

        exit 0
    }
}

[Console]::Error.WriteLine("Clipboard does not contain an image.")
exit 2
