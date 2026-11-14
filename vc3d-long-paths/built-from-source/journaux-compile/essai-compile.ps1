# Long-path test with programs BUILT ON THIS PC from the villa sources (MSYS2 UCRT64, preset ci-windows-mingw),
# same commands and same data as preuves-vc3d-chemins-longs\essai.ps1 (cases a-d).
# Usage: pwsh -File essai-compile.ps1 -Phase main|branch
#   main   = build of origin/main 97fb933 as is
#   branch = same build, relinked with the manifest of the branch vc3d-windows-long-paths
param([string]$Phase)
$ErrorActionPreference = 'Continue'
$Bin = 'C:\Users\me\Dev\vesuvius\wt-vc3d\volume-cartographer\build\ci-windows-mingw\bin'
$M   = 'C:\Users\me\Dev\vesuvius\outils-vc3d\msys64'
$D   = 'C:\Users\me\Dev\vesuvius\donnees-longpath-compile'
$J   = 'C:\Users\me\Dev\vesuvius\preuves-vc3d-chemins-longs\journaux-compile'
$H   = 'https://vesuvius-challenge-open-data.s3.amazonaws.com'
$P4  = "$H/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413141734-surface-recto-2um-ps256-L0-th0.45.zarr"
$P139 = "$H/PHerc0139/representations/predictions/surfaces/20260102150214-surface-20260203205514-surface-recto-2um-ps192-L0-th0.5.zarr"
$L = 'K:'
if (Test-Path "$L\") { "ARRET : le lecteur $L existe deja"; exit 2 }
foreach ($u in "$D\Users\<name>", "$D\U") { if (Test-Path -LiteralPath $u) { cmd /c "rmdir /s /q `"\\?\$u`"" | Out-Null } }
New-Item -ItemType Directory -Force $J, "$D\Users\<name>", "$D\U", "$D\sorties-$Phase" | Out-Null
'{"mode":"seed","cache_size":500000000,"generations":2,"thread_limit":2,"min_area_cm":0}' | Set-Content "$D\params.json" -Encoding ascii
& subst $L $D
"phase=$Phase  " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "  subst: " + ((& subst) -join ' | ')
"LongPathsEnabled=" + (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled
$exe = "$Bin\vc_grow_seg_from_seed.exe"
"vc_grow_seg_from_seed.exe : " + (Get-Item $exe).Length + " bytes, written " + (Get-Item $exe).LastWriteTime.ToString('HH:mm:ss') + ", sha256=" + (Get-FileHash $exe).Hash.Substring(0, 16)
$mt = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\mt.exe' -ErrorAction SilentlyContinue | Sort-Object FullName | Select-Object -Last 1
if ($mt) {
  $man = "$D\embedded-$Phase.xml"; & $mt.FullName -nologo "-inputresource:$exe;#1" "-out:$man" | Out-Null
  "embedded manifest: longPathAware lines = " + @(Select-String -Path $man -Pattern 'longPathAware' -ErrorAction SilentlyContinue).Count
}

function Run($Nom, $Up, [string[]]$Arguments, $Timeout = 90) {
  $log = "$J\$Phase-$Nom.log"
  $psi = [Diagnostics.ProcessStartInfo]::new($exe)
  foreach ($a in $Arguments) { $psi.ArgumentList.Add($a) }
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  $psi.WorkingDirectory = $D
  $psi.Environment['USERPROFILE'] = $Up
  $psi.Environment.Remove('HOME') | Out-Null
  $psi.Environment.Remove('VC3D_CONFIG_DIR') | Out-Null
  $psi.Environment['OMP_NUM_THREADS'] = '2'
  $psi.Environment['PATH'] = "$Bin;$M\ucrt64\bin;" + $env:PATH
  $root = "$Up\.VC3D\remote_cache"
  "CMD: vc_grow_seg_from_seed " + (($Arguments | ForEach-Object { "`"$_`"" }) -join ' ') | Out-File $log -Encoding utf8
  "USERPROFILE=$Up  default root=$root (len $($root.Length))  exe=$exe" | Out-File $log -Append -Encoding utf8
  $t = Get-Date
  $p = [Diagnostics.Process]::Start($psi)
  try { $p.PriorityClass = 'BelowNormal' } catch {}
  $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  $to = ''
  if (-not $p.WaitForExit($Timeout * 1000)) { $to = " TIMEOUT_${Timeout}s_KILLED"; & taskkill /T /F /PID $p.Id | Out-Null }
  $p.WaitForExit()
  "--- stdout ---" | Out-File $log -Append -Encoding utf8; $o.Result | Out-File $log -Append -Encoding utf8
  "--- stderr ---" | Out-File $log -Append -Encoding utf8; $e.Result | Out-File $log -Append -Encoding utf8
  $d = [Math]::Round(((Get-Date) - $t).TotalSeconds, 1)
  "FIN rc=$($p.ExitCode) duree_s=$d$to" | Out-File $log -Append -Encoding utf8
  "=== $Nom rc=$($p.ExitCode) duree_s=$d$to"
  Get-Content $log | Select-String -Pattern 'error|create|saving|TIMEOUT|exception' | Select-Object -First 5 | ForEach-Object { "    " + $_.Line.Substring(0, [Math]::Min(300, $_.Line.Length)) }
}

Run 'a-p4-defaut33'   "$L\Users\<name>" @('-v', $P4,   '-t', "$L\sorties-$Phase\a", '-p', "$L\params.json", '--seed', '16346', '16346', '37892')
Run 'b-p4-defaut23'   "$L\U"           @('-v', $P4,   '-t', "$L\sorties-$Phase\b", '-p', "$L\params.json", '--seed', '16346', '16346', '37892')
Run 'c-p139-defaut33' "$L\Users\<name>" @('-v', $P139, '-t', "$L\sorties-$Phase\c", '-p', "$L\params.json", '--seed', '13255', '13255', '38476')
Run 'd-p139-defaut23' "$L\U"           @('-v', $P139, '-t', "$L\sorties-$Phase\d", '-p', "$L\params.json", '--seed', '13255', '13255', '38476')
"--- cache files with a path of 250 characters or more (as seen through $L) ---"
Get-ChildItem -LiteralPath "\\?\$D\Users\<name>\.VC3D\remote_cache" -Recurse -Force -File -ErrorAction SilentlyContinue |
  ForEach-Object { $v = $_.FullName.Replace("\\?\$D", $L); if ($v.Length -ge 250) { "len=$($v.Length) $v" } } | Select-Object -First 6
& subst $L /D
"subst after: " + ((& subst) -join ' | ')
"FIN script"
