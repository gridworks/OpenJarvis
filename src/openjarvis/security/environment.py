"""``jarvis scan`` / Phase-1 init audit — read-only environment security checks.

All checks are macOS-first.  Linux stubs are noted with ``# TODO: Linux``
comments so they can be filled in during a follow-up pass.

Each check returns an :class:`EnvFinding`.  :func:`run_all_checks` collects
them and returns a :class:`EnvReport`.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class EnvFinding:
    """A single environment security finding."""

    check: str
    severity: Severity
    title: str
    detail: str
    remediation: str = ""


@dataclass
class EnvReport:
    """Aggregated result of all environment checks."""

    findings: List[EnvFinding] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == Severity.WARN for f in self.findings)

    def by_severity(self, severity: Severity) -> List[EnvFinding]:
        return [f for f in self.findings if f.severity == severity]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: List[str], timeout: int = 5) -> Optional[str]:
    """Run *cmd* and return stdout, or ``None`` on any error."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except Exception:
        return None


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _process_running(name: str) -> bool:
    """Return True if a process whose name contains *name* is running."""
    out = _run(["pgrep", "-x", name])
    if out is None:
        # Fall back to broader search
        out = _run(["pgrep", "-i", name]) or ""
    return bool(out.strip())


def _any_process_running(names: List[str]) -> List[str]:
    """Return which names from *names* have a running process."""
    return [n for n in names if _process_running(n)]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_filevault() -> EnvFinding:
    """Disk encryption (FileVault) status."""
    # TODO: Linux — check `lsblk --output NAME,TYPE,FSTYPE` for LUKS
    if not _is_macos():
        return EnvFinding(
            check="disk_encryption",
            severity=Severity.INFO,
            title="Disk encryption check skipped",
            detail="Automated check not yet implemented for this platform.",
        )

    out = _run(["fdesetup", "status"])
    if out is None:
        return EnvFinding(
            check="disk_encryption",
            severity=Severity.WARN,
            title="Could not determine FileVault status",
            detail="fdesetup command failed or was unavailable.",
        )

    out = out.strip()
    if "FileVault is On" in out:
        return EnvFinding(
            check="disk_encryption",
            severity=Severity.INFO,
            title="FileVault is enabled",
            detail="Disk encryption is active. Model outputs are protected at rest.",
        )

    return EnvFinding(
        check="disk_encryption",
        severity=Severity.CRITICAL,
        title="FileVault is disabled",
        detail=(
            "Your startup disk is not encrypted. If your Mac is lost or stolen, "
            "conversation logs and model outputs in ~/.openjarvis/ are readable "
            "without a password."
        ),
        remediation="Enable FileVault: System Settings → Privacy & Security → FileVault.",
    )


def check_mdm_profiles() -> EnvFinding:
    """MDM / management profile presence."""
    # TODO: Linux — check for puppet/chef/ansible managed-node indicators
    if not _is_macos():
        return EnvFinding(
            check="mdm_profiles",
            severity=Severity.INFO,
            title="MDM profile check skipped",
            detail="Automated check not yet implemented for this platform.",
        )

    out = _run(["profiles", "list"])
    if out is None:
        # profiles command not available (expected on non-managed Macs)
        return EnvFinding(
            check="mdm_profiles",
            severity=Severity.INFO,
            title="No MDM profiles detected",
            detail="The profiles command returned no output — machine appears unmanaged.",
        )

    # A managed machine will list at least one profile
    lines = [l for l in out.splitlines() if l.strip()]
    profile_lines = [l for l in lines if "attribute:" in l.lower() or "profileIdentifier" in l]

    if not lines or "There are no" in out or len(lines) <= 2:
        return EnvFinding(
            check="mdm_profiles",
            severity=Severity.INFO,
            title="No MDM profiles detected",
            detail="No management profiles are installed on this machine.",
        )

    return EnvFinding(
        check="mdm_profiles",
        severity=Severity.WARN,
        title="MDM management profile(s) detected",
        detail=(
            f"This machine has {len(profile_lines) or 'one or more'} management profile(s) "
            "installed. An employer or institution may have remote-access capabilities."
        ),
        remediation=(
            "Review installed profiles: System Settings → Privacy & Security → Profiles. "
            "If unexpected, contact your IT department."
        ),
    )


def check_cloud_sync() -> EnvFinding:
    """Cloud sync agents that may upload ~/.openjarvis/ data."""
    # TODO: Linux — check for rclone, Nextcloud, Dropbox on Linux
    _SYNC_PROCESSES = [
        "bird",          # iCloud Drive daemon
        "Dropbox",
        "Google Drive",
        "OneDrive",
        "Box",
        "Maestral",      # open-source Dropbox client
    ]
    _SYNC_LABELS = {
        "bird": "iCloud Drive",
        "Dropbox": "Dropbox",
        "Google Drive": "Google Drive",
        "OneDrive": "Microsoft OneDrive",
        "Box": "Box",
        "Maestral": "Maestral (Dropbox)",
    }

    running = _any_process_running(_SYNC_PROCESSES)
    if not running:
        return EnvFinding(
            check="cloud_sync",
            severity=Severity.INFO,
            title="No cloud sync agents detected",
            detail="No known cloud sync processes are running.",
        )

    labels = [_SYNC_LABELS.get(p, p) for p in running]

    # Check whether any sync root overlaps with ~/.openjarvis
    openjarvis_dir = Path.home() / ".openjarvis"
    overlap_warning = ""
    if "bird" in running:
        # iCloud Drive syncs ~/Library/Mobile Documents and can sync Desktop/Documents
        icloud_root = Path.home() / "Library" / "Mobile Documents"
        if icloud_root.exists():
            overlap_warning = (
                " iCloud Drive is active — ensure ~/.openjarvis/ is not inside "
                "an iCloud-synced folder (Desktop or Documents if iCloud Desktop & "
                "Documents is enabled)."
            )

    return EnvFinding(
        check="cloud_sync",
        severity=Severity.WARN,
        title=f"Cloud sync running: {', '.join(labels)}",
        detail=(
            f"The following sync agents are active: {', '.join(labels)}. "
            f"If ~/.openjarvis/ or any parent folder is inside a synced directory, "
            f"conversation logs and memory files may be uploaded to the cloud."
            f"{overlap_warning}"
        ),
        remediation=(
            "Verify that ~/.openjarvis/ is excluded from sync. "
            "For iCloud, check System Settings → Apple ID → iCloud → iCloud Drive."
        ),
    )


def check_open_ports() -> EnvFinding:
    """Unexpected listening TCP services."""
    # TODO: Linux — same lsof command works on Linux
    _EXPECTED_PORTS = {
        # Common local inference engine ports — not suspicious
        11434,  # Ollama
        8080,   # llama.cpp / MLX
        8000,   # vLLM
        30000,  # SGLang
        1234,   # LM Studio
        52415,  # Exo
        18181,  # Nexa
    }

    out = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=10)
    if out is None:
        return EnvFinding(
            check="open_ports",
            severity=Severity.INFO,
            title="Could not enumerate open ports",
            detail="lsof command failed or permission denied.",
        )

    unexpected: List[str] = []
    for line in out.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 9:
            continue
        addr = parts[8]  # e.g. "*:22" or "127.0.0.1:5000"
        try:
            port = int(addr.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if port not in _EXPECTED_PORTS:
            proc = parts[0]
            unexpected.append(f"{proc} on :{port}")

    # Deduplicate (lsof can show multiple file descriptors per process)
    seen: set[str] = set()
    unique_unexpected: List[str] = []
    for entry in unexpected:
        if entry not in seen:
            seen.add(entry)
            unique_unexpected.append(entry)

    if not unique_unexpected:
        return EnvFinding(
            check="open_ports",
            severity=Severity.INFO,
            title="No unexpected listening ports detected",
            detail="Only known inference engine ports are open (or none at all).",
        )

    sample = unique_unexpected[:8]
    more = len(unique_unexpected) - len(sample)
    detail = "Unexpected listening services: " + ", ".join(sample)
    if more:
        detail += f" (+{more} more)"

    return EnvFinding(
        check="open_ports",
        severity=Severity.INFO,
        title=f"{len(unique_unexpected)} unexpected listening port(s)",
        detail=detail,
        remediation="Review with: lsof -nP -iTCP -sTCP:LISTEN",
    )


def check_screen_recording() -> EnvFinding:
    """Apps with Screen Recording permission (TCC database)."""
    # TODO: Linux — no TCC equivalent; could check /proc for X11 grabs
    if not _is_macos():
        return EnvFinding(
            check="screen_recording",
            severity=Severity.INFO,
            title="Screen recording check skipped",
            detail="Automated check not yet implemented for this platform.",
        )

    tcc_db = Path.home() / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db"
    if not tcc_db.exists():
        return EnvFinding(
            check="screen_recording",
            severity=Severity.INFO,
            title="Screen recording: TCC database not found",
            detail="Could not locate TCC.db — check may require Full Disk Access.",
        )

    # Read screencapture service entries that are allowed
    out = _run([
        "sqlite3", str(tcc_db),
        "SELECT client FROM access WHERE service='kTCCServiceScreenCapture' AND auth_value=2;",
    ])
    if out is None:
        return EnvFinding(
            check="screen_recording",
            severity=Severity.INFO,
            title="Screen recording: could not query TCC database",
            detail=(
                "sqlite3 returned an error. Grant Full Disk Access to Terminal "
                "or run as root to inspect screen recording permissions."
            ),
        )

    apps = [line.strip() for line in out.splitlines() if line.strip()]
    if not apps:
        return EnvFinding(
            check="screen_recording",
            severity=Severity.INFO,
            title="No apps with Screen Recording permission",
            detail="No applications have been granted screen recording access.",
        )

    return EnvFinding(
        check="screen_recording",
        severity=Severity.WARN,
        title=f"{len(apps)} app(s) have Screen Recording permission",
        detail=f"Apps: {', '.join(apps[:10])}" + (f" (+{len(apps)-10} more)" if len(apps) > 10 else ""),
        remediation="Review: System Settings → Privacy & Security → Screen Recording.",
    )


def check_remote_access() -> EnvFinding:
    """Remote access tools that could expose the machine."""
    # TODO: Linux — check for xrdp, x11vnc, rustdesk, nomachine
    _REMOTE_TOOLS = {
        "TeamViewer": "TeamViewer",
        "AnyDesk": "AnyDesk",
        "Screensharing": "macOS Screen Sharing (ARD)",
        "ARDAgent": "Apple Remote Desktop",
        "Vine Server": "Vine VNC Server",
        "ngrok": "ngrok tunnel",
        "tailscaled": "Tailscale VPN",
        "ZeroTier": "ZeroTier VPN",
    }

    running = _any_process_running(list(_REMOTE_TOOLS.keys()))
    if not running:
        return EnvFinding(
            check="remote_access",
            severity=Severity.INFO,
            title="No remote access tools detected",
            detail="No known remote access or tunneling processes are running.",
        )

    labels = [_REMOTE_TOOLS.get(p, p) for p in running]

    # Distinguish VPNs (lower risk) from remote desktop tools (higher risk)
    vpn_tools = {"tailscaled", "ZeroTier"}
    remote_desktop = [p for p in running if p not in vpn_tools]
    vpns = [p for p in running if p in vpn_tools]

    if remote_desktop:
        severity = Severity.WARN
        detail = (
            f"Remote desktop / access tools running: {', '.join(_REMOTE_TOOLS.get(p, p) for p in remote_desktop)}. "
            "These tools can give a third party live access to your screen and files."
        )
        if vpns:
            detail += f" VPN tools also active: {', '.join(_REMOTE_TOOLS.get(p, p) for p in vpns)}."
    else:
        severity = Severity.INFO
        detail = (
            f"VPN tools running: {', '.join(labels)}. "
            "These route traffic through a private network but do not grant screen access."
        )

    return EnvFinding(
        check="remote_access",
        severity=severity,
        title=f"Remote access tools active: {', '.join(labels)}",
        detail=detail,
        remediation=(
            "If unexpected, quit or disable these tools. "
            "For Screen Sharing: System Settings → General → Sharing."
        ) if remote_desktop else "",
    )


def check_dns() -> EnvFinding:
    """DNS configuration — plain DNS exposes query metadata."""
    # TODO: Linux — parse /etc/resolv.conf and check for DoH/DoT config
    if not _is_macos():
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title="DNS check skipped",
            detail="Automated check not yet implemented for this platform.",
        )

    out = _run(["scutil", "--dns"])
    if out is None:
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title="Could not determine DNS configuration",
            detail="scutil command failed.",
        )

    # Heuristic: DoH/DoT resolvers tend to use well-known IPs or show "encrypted"
    # Plain indicators: 8.8.8.8, 1.1.1.1, ISP-assigned (192.168.x.x, 10.x.x.x)
    _PLAIN_DNS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9"}
    _DOH_INDICATORS = ["dns-over-https", "dns-over-tls", "encrypted", "doh", "dot"]

    has_doh = any(ind in out.lower() for ind in _DOH_INDICATORS)
    if has_doh:
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title="Encrypted DNS detected",
            detail="DNS-over-HTTPS or DNS-over-TLS appears to be active.",
        )

    # Extract nameserver IPs
    nameservers: List[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("nameserver["):
            parts = line.split(":", 1)
            if len(parts) == 2:
                nameservers.append(parts[1].strip())

    if not nameservers:
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title="DNS configuration unclear",
            detail="Could not parse nameserver entries from scutil output.",
        )

    plain = [ns for ns in nameservers if ns in _PLAIN_DNS]
    private = [
        ns for ns in nameservers
        if ns.startswith("192.168.") or ns.startswith("10.") or ns.startswith("172.")
    ]

    if plain:
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title=f"Plain DNS in use: {', '.join(plain)}",
            detail=(
                "Your DNS queries may be visible to your ISP or resolver. "
                "Model-related searches (if any) could be logged."
            ),
            remediation=(
                "Consider enabling encrypted DNS: System Settings → "
                "Wi-Fi / Network → DNS, or use a DoH-capable resolver."
            ),
        )

    if private:
        return EnvFinding(
            check="dns",
            severity=Severity.INFO,
            title=f"Local/private DNS: {', '.join(private)}",
            detail="Queries route to a local or private resolver — likely a home router or VPN.",
        )

    return EnvFinding(
        check="dns",
        severity=Severity.INFO,
        title=f"DNS resolvers: {', '.join(nameservers[:3])}",
        detail="DNS configuration detected; encryption status is unclear.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_all_checks() -> EnvReport:
    """Run all environment security checks and return an :class:`EnvReport`."""
    report = EnvReport()
    for check_fn in [
        check_filevault,
        check_mdm_profiles,
        check_cloud_sync,
        check_open_ports,
        check_screen_recording,
        check_remote_access,
        check_dns,
    ]:
        try:
            report.findings.append(check_fn())
        except Exception as exc:
            report.findings.append(
                EnvFinding(
                    check=check_fn.__name__,
                    severity=Severity.INFO,
                    title=f"Check failed: {check_fn.__name__}",
                    detail=str(exc),
                )
            )
    return report


__all__ = [
    "EnvFinding",
    "EnvReport",
    "Severity",
    "run_all_checks",
    "check_filevault",
    "check_mdm_profiles",
    "check_cloud_sync",
    "check_open_ports",
    "check_screen_recording",
    "check_remote_access",
    "check_dns",
]
