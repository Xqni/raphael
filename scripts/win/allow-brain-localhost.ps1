# OPTIONAL — narrow Hyper-V firewall rule for the Raphael Brain port.
#
# *** USER-run, AS ADMIN (elevated PowerShell). Agents NEVER run this ***
# *** (AGENT_RULES §12: no elevated commands by agents; documented,   ***
# *** not forced).                                                     ***
#
# WHAT IT DOES: creates ONE inbound Hyper-V firewall rule scoped to the WSL
# VM creator and TCP port 8765 (the Brain's port) — re-enabling Windows ->
# WSL localhost forwarding for that port only.
#
# WHY: on this machine the Hyper-V firewall blocks WSL's built-in localhost
# relay (verified 2026-10-05: win -> 127.0.0.1:8765 = refused while
# win -> <vm-ip>:8765 connects), so the supervisor runs a user-space relay
# (Windows 127.0.0.1 splice -> VM NAT address -> Brain loopback). With this
# rule the NATIVE path works and the relay can be switched off, leaving a
# pure end-to-end 127.0.0.1 chain (see scripts/NETWORK-SECURITY.md).
#
# WHY NOT THE BLANKET FIX: the usual advice
#   Set-NetFirewallHyperVVMSetting -Name '{...}' -DefaultInboundAction Allow
# opens ALL inbound traffic to the WSL VM — rejected by the network-security
# requirement. This rule allows exactly one port for one VM creator.
#
# VERIFY AFTER RUNNING (no admin needed):
#   1. stop the relay:  set  paths.brain_relay: false  in config.yaml
#      (and restart the supervisor), or run without the supervisor.
#   2. curl.exe http://127.0.0.1:8765/health
#        -> 200 {"status":"ok"} or 401 = WORKING (loopback end-to-end)
#        -> connection refused     = revert (see ROLLBACK)
#   3. the WSL helper leg can then stay off: paths.brain_relay_helper: false
#
# ROLLBACK:
#   Remove-NetFirewallHyperVRule -Name 'Raphael-Brain-8765'
#   (and set paths.brain_relay: true again)

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

# WSL VM creator id (Microsoft docs: Get-NetFirewallHyperVVMCreator ->
# FriendlyName 'WSL'). Do NOT change without re-checking.
$WslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
$RuleName = 'Raphael-Brain-8765'

$existing = Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq $RuleName }
if ($existing) {
    Write-Host "Rule '$RuleName' already exists:"
    $existing | Format-List Name, DisplayName, Direction, Action, Protocol, LocalPorts, VMCreatorId
    exit 0
}

New-NetFirewallHyperVRule `
    -Name $RuleName `
    -DisplayName 'Raphael Brain localhost forward (TCP 8765, WSL only)' `
    -Description 'Narrow alternative to blanket DefaultInboundAction Allow: allows inbound TCP 8765 to the WSL VM only, so Windows localhost forwarding reaches the loopback-bound Brain.' `
    -VMCreatorId $WslCreatorId `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPorts 8765 `
    -Action Allow | Out-Null

Write-Host "Created rule '$RuleName' (Inbound, TCP, LocalPort 8765, WSL VM only)."
Get-NetFirewallHyperVRule -Name $RuleName |
    Format-List Name, DisplayName, Direction, Action, Protocol, LocalPorts, VMCreatorId, Enabled
Write-Host "Next: set paths.brain_relay: false in config.yaml, restart the supervisor,"
Write-Host "then: curl.exe http://127.0.0.1:8765/health   (expect 200/401, not refused)"
