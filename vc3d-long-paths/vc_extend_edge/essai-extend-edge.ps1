# vc_extend_edge long-path test (same command as vc3d-zip d2), default cache root of length 50.
# -Exe vc_extend_edge_orig (unmodified copy of the official exe) or vc_extend_edge (manifest + longPathAware)
param([string]$Phase, [string]$Exe, [int]$Timeout = 60)
$ErrorActionPreference = 'Continue'
$P   = "C:\Users\me\Dev\vesuvius\preuves-vc3d-chemins-longs"
$D   = "C:\Users\me\Dev\vesuvius\donnees-longpath"
$Bin = "$D\bin"; $J = "$P\journaux"; $L = 'L:'
$Pred = "https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0800/representations/predictions/surfaces/20250521135224-surface-20260413222639-surface-m7-L0-th0.2.zarr"
$UpRel = "Users\jean-christophe.dupont"
if (Test-Path -LiteralPath "$D\$UpRel") { Remove-Item -LiteralPath "$D\$UpRel" -Recurse -Force }
New-Item -ItemType Directory -Force "$D\$UpRel", "$D\sorties-ee-$Phase" | Out-Null
& subst $L $D
"phase=$Phase exe=$Exe sha256=" + (Get-FileHash "$Bin\$Exe.exe").Hash
$Up = "$L\$UpRel"; $root = "$Up\.VC3D\remote_cache"
$args2 = @('-i', "$L\seg0800\tifxyz_original", '-o', "$L\sorties-ee-$Phase\0800 etendu", '-n', $Pred, '--sides', 'right', '--cells', '5', '--rounds', '1', '--threads', '2', '--normal-step', '2', '--walk-mode', 'streamline', '--integrator', 'rk4', '--report', "$L\sorties-ee-$Phase\rapport.json", '--overwrite')
$log = "$J\$Phase-extend-edge.log"
$psi = [Diagnostics.ProcessStartInfo]::new("$Bin\$Exe.exe")
foreach ($a in $args2) { $psi.ArgumentList.Add($a) }
$psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
$psi.WorkingDirectory = $D
$psi.Environment['USERPROFILE'] = $Up
$psi.Environment.Remove('HOME') | Out-Null
$psi.Environment.Remove('VC3D_CONFIG_DIR') | Out-Null
$psi.Environment['OMP_NUM_THREADS'] = '2'
"CMD: $Exe " + (($args2 | % { "`"$_`"" }) -join ' ') | Out-File $log -Encoding utf8
"USERPROFILE=$Up  default root=$root (len $($root.Length))" | Out-File $log -Append -Encoding utf8
$t = Get-Date; $pk = 0
$p = [Diagnostics.Process]::Start($psi)
try { $p.PriorityClass = 'BelowNormal' } catch {}
$o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
$to = ''
while (-not $p.WaitForExit(1000)) {
  try { $p.Refresh(); if ($p.WorkingSet64 -gt $pk) { $pk = $p.WorkingSet64 } } catch {}
  if ($pk -gt 950MB) { $to = ' KILLED_MEM>950MB'; break }
  if (((Get-Date) - $t).TotalSeconds -gt $Timeout) { $to = " TIMEOUT_${Timeout}s_KILLED"; break }
}
if ($to) { "$to" | Out-File $log -Append; & taskkill /T /F /PID $p.Id | Out-Null }
$p.WaitForExit()
"--- stdout ---" | Out-File $log -Append -Encoding utf8; $o.Result | Out-File $log -Append -Encoding utf8
"--- stderr ---" | Out-File $log -Append -Encoding utf8; $e.Result | Out-File $log -Append -Encoding utf8
$d = [Math]::Round(((Get-Date) - $t).TotalSeconds, 1)
"FIN rc=$($p.ExitCode) duree_s=$d pic_Mo=$([int]($pk/1MB))$to" | Out-File $log -Append -Encoding utf8
"root=$root (len $($root.Length))"
"=== extend-edge rc=$($p.ExitCode) duree_s=$d pic_Mo=$([int]($pk/1MB))$to"
Get-Content $log | Select-String -Pattern 'error|create|added|vertices|TIMEOUT|exception' | Select-Object -First 6 | % { "    " + $_.Line }
"--- fichiers du cache, 5 plus longs (via $L) ---"
Get-ChildItem -LiteralPath "$D\$UpRel\.VC3D\remote_cache" -Recurse -Force -File -ErrorAction SilentlyContinue | % { $v = $_.FullName.Replace($D, $L); "len=$($v.Length) $v" } | Sort-Object { [int]($_ -replace '^len=(\d+).*', '$1') } -Descending | Select-Object -First 5
& subst $L /D
"subst apres: " + ((& subst) -join ' | ')
"FIN script"
