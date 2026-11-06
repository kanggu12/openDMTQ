# Opens the OpenDMTQ game port to the local network, or to anywhere with -Internet (when exposed).
# Run elevated; `./opendmtq firewall` does that.
#
# WSL2 in mirrored networking shares the Windows address, and the WSL VM's Hyper-V firewall merges
# ordinary host rules, so one host rule is enough. -Profile Any because home connections are often
# classified Public, where a Domain,Private rule silently never applies.
# A test from this PC proves nothing (loopback skips the firewall); only another device does.
param(
    # Port the server publishes (LISTEN_PORT; 80 unless exposed on another port).
    [int]$Port = 80,
    # Accept connections from anywhere (exposed to the internet), not only the local subnet.
    [switch]$Internet,
    # Remove the rule instead of creating it.
    [switch]$Remove,
    # The port this server used until now, whose rule goes.
    [int]$Replaces = 0
)

$ErrorActionPreference = 'Stop'

# One fixed display name so re-runs replace the rule instead of stacking copies.
$name = "OpenDMTQ (TCP $Port)"

# This server's rules only: another copy on this PC has its own port and its own rule, which must stay. This also
# implements -Remove.
foreach ($old in @($Port, $Replaces)) {
    if ($old) { Get-NetFirewallRule -DisplayName "OpenDMTQ (TCP $old)" -EA SilentlyContinue | Remove-NetFirewallRule }
}
if ($Remove) {
    Write-Host "removed: $name"
    exit 0
}

# Inbound TCP: from the local subnet only, or from anywhere when exposed to the internet.
$remote = if ($Internet) { 'Any' } else { 'LocalSubnet' }
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port `
    -RemoteAddress $remote -Action Allow -Profile Any | Out-Null
Write-Host "created: $name (from $remote)"
