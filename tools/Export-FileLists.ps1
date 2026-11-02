# Export-FileLists.ps1
# Drop this whole "tools" folder into a project directory. The script scans the
# PARENT directory (recursively) for proteomics files of interest and writes one
# .txt per file category into <tools>\_filelists. Nothing outside the tools
# folder is created or modified.
#
# Each .txt is grouped by folder:
#   <folder path>
#   <blank line>
#   file names, one per line
#   <two blank lines, then the next folder>
#
# Run by double-clicking Export-FileLists.bat

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location -LiteralPath $root

# ---- Categories of interest -----------------------------------------------
# Matched by extension (lowercase)
$extensionMap = [ordered]@{
    'raw'    = 'RAW_files'        # Thermo/Waters vendor raw
    'wiff'   = 'RAW_files'        # AB Sciex
    'mzml'   = 'PEAK_files'
    'mzxml'  = 'PEAK_files'
    'mgf'    = 'PEAK_files'
    'fasta'  = 'FASTA_files'
    'mzid'   = 'RESULT_files'     # mzIdentML (Complete submissions)
    'mztab'  = 'RESULT_files'     # mzTab (Complete submissions)
    'sdrf'   = 'SDRF_files'
}
# Matched by exact file name (MaxQuant output tables, parameters, etc.)
$nameMap = [ordered]@{
    'proteinGroups.txt'   = 'MaxQuant_RESULT_files'
    'peptides.txt'        = 'MaxQuant_RESULT_files'
    'evidence.txt'        = 'MaxQuant_RESULT_files'
    'msms.txt'            = 'MaxQuant_RESULT_files'
    'sites.txt'           = 'MaxQuant_RESULT_files'
    'allPeptides.txt'     = 'MaxQuant_RESULT_files'
    'modificationSpecificPeptides.txt' = 'MaxQuant_RESULT_files'
    'mqpar.xml'           = 'MaxQuant_design_files'   # -> OTHER in PRIDE
    'parameters.txt'      = 'MaxQuant_design_files'
    'summary.txt'         = 'MaxQuant_design_files'
    'mqpar.txt'           = 'MaxQuant_design_files'
}
# Bruker .d acquisitions are folders, not files; handled separately below.

# ---- Scan (skipping the tools folder itself) ---------------------------------
$toolsPrefix = $here.TrimEnd('\') + '\'
function Test-InTools($path) {
    return $path.StartsWith($toolsPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

$timer = [System.Diagnostics.Stopwatch]::StartNew()
function Get-Elapsed { '{0:hh\:mm\:ss}' -f $timer.Elapsed }

Write-Host "Scanning $root"
Write-Host "(large or network folders can take a while; matches are listed as they are found)"
Write-Host ""

$entries = New-Object System.Collections.Generic.List[object]
$scanned = 0
Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if (Test-InTools $_.FullName) { return }
    $scanned++
    if ($scanned % 5000 -eq 0) {
        Write-Host ("  ... {0} items scanned, {1} matches so far ({2})" -f $scanned, $entries.Count, (Get-Elapsed))
    }
    $cat = $null
    if ($_.PSIsContainer) {
        if ($_.Extension -ieq '.d') { $cat = 'RAW_files'; $dir = $_.Parent.FullName }
    } elseif ($_.Name -notlike '~$*') {
        $ext = $_.Extension.ToLower().TrimStart('.')
        $name = $_.Name.ToLower()
        if ($nameMap.Contains($name))          { $cat = $nameMap[$name] }
        elseif ($extensionMap.Contains($ext)) { $cat = $extensionMap[$ext] }
        $dir = $_.DirectoryName
    }
    if ($cat) {
        $entries.Add([pscustomobject]@{ Category = $cat; Name = $_.Name; Dir = $dir })
        Write-Host ("  [{0}] {1}" -f $entries.Count, $_.FullName.Substring($root.TrimEnd('\').Length + 1))
    }
}

Write-Host ""
Write-Host ("Scan finished: {0} items scanned, {1} files of interest found in {2}" -f $scanned, $entries.Count, (Get-Elapsed))
Write-Host ""

if ($entries.Count -eq 0) {
    Write-Host "No files of interest found under: $root"
    Read-Host 'Press Enter to close'
    exit
}

# ---- Write one .txt per category, grouped by folder ---------------------------
$outDir = Join-Path $here '_filelists'
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
# Remove lists from earlier runs so no stale categories are left behind
Get-ChildItem -LiteralPath $outDir -File |
    Where-Object { $_.Name -like '*_files.txt' -or $_.Name -like '*_files.tsv' } |
    Remove-Item

foreach ($cat in ($entries | Group-Object Category | Sort-Object Name)) {
    $txtPath = Join-Path $outDir ($cat.Name + '.txt')
    $lines = New-Object System.Collections.Generic.List[string]
    $first = $true
    $folders = $cat.Group | Group-Object Dir | Sort-Object Name
    foreach ($folder in $folders) {
        if (-not $first) { $lines.Add(''); $lines.Add('') }
        $first = $false
        $lines.Add($folder.Name)
        $lines.Add('')
        foreach ($f in ($folder.Group | Sort-Object Name)) { $lines.Add($f.Name) }
    }
    Set-Content -LiteralPath $txtPath -Value $lines -Encoding UTF8
    Write-Host ("{0}: {1} file(s) in {2} folder(s) -> {3}" -f $cat.Name, $cat.Count, @($folders).Count, (Split-Path -Leaf $txtPath))
}

Write-Host ""
Write-Host ("Done in {0}. Lists written to: {1}" -f (Get-Elapsed), $outDir)
Read-Host 'Press Enter to close'
