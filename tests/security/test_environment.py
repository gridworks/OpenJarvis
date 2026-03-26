"""Tests for openjarvis.security.environment — environment security checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.security.environment import (
    EnvFinding,
    EnvReport,
    Severity,
    check_cloud_sync,
    check_dns,
    check_filevault,
    check_mdm_profiles,
    check_open_ports,
    check_remote_access,
    check_screen_recording,
    run_all_checks,
)


# ---------------------------------------------------------------------------
# EnvReport helpers
# ---------------------------------------------------------------------------


class TestEnvReport:
    def test_has_critical(self) -> None:
        report = EnvReport(findings=[
            EnvFinding("a", Severity.CRITICAL, "t", "d"),
            EnvFinding("b", Severity.INFO, "t", "d"),
        ])
        assert report.has_critical is True

    def test_has_no_critical(self) -> None:
        report = EnvReport(findings=[
            EnvFinding("a", Severity.WARN, "t", "d"),
        ])
        assert report.has_critical is False

    def test_has_warnings(self) -> None:
        report = EnvReport(findings=[
            EnvFinding("a", Severity.WARN, "t", "d"),
        ])
        assert report.has_warnings is True

    def test_by_severity(self) -> None:
        report = EnvReport(findings=[
            EnvFinding("a", Severity.INFO, "t", "d"),
            EnvFinding("b", Severity.WARN, "t", "d"),
            EnvFinding("c", Severity.CRITICAL, "t", "d"),
        ])
        assert len(report.by_severity(Severity.INFO)) == 1
        assert len(report.by_severity(Severity.WARN)) == 1
        assert len(report.by_severity(Severity.CRITICAL)) == 1


# ---------------------------------------------------------------------------
# check_filevault
# ---------------------------------------------------------------------------


class TestCheckFilevault:
    def test_filevault_on(self) -> None:
        with patch("openjarvis.security.environment._run", return_value="FileVault is On.\n"):
            result = check_filevault()
        assert result.severity == Severity.INFO
        assert "enabled" in result.title.lower()

    def test_filevault_off(self) -> None:
        with patch("openjarvis.security.environment._run", return_value="FileVault is Off.\n"):
            result = check_filevault()
        assert result.severity == Severity.CRITICAL
        assert "disabled" in result.title.lower()
        assert result.remediation != ""

    def test_filevault_command_fails(self) -> None:
        with patch("openjarvis.security.environment._run", return_value=None):
            result = check_filevault()
        assert result.severity == Severity.WARN

    def test_filevault_skipped_on_linux(self) -> None:
        with patch("openjarvis.security.environment._is_macos", return_value=False):
            result = check_filevault()
        assert result.severity == Severity.INFO
        assert "skipped" in result.title.lower()


# ---------------------------------------------------------------------------
# check_mdm_profiles
# ---------------------------------------------------------------------------


class TestCheckMdmProfiles:
    def test_no_profiles(self) -> None:
        with patch("openjarvis.security.environment._run", return_value="There are no configuration profiles installed\n"):
            result = check_mdm_profiles()
        assert result.severity == Severity.INFO

    def test_profiles_present(self) -> None:
        fake_output = (
            "There are 2 user configuration profiles installed for 'testuser':\n"
            "profileIdentifier: com.example.mdm\n"
            "  attribute: PayloadType: com.apple.mdm\n"
            "profileIdentifier: com.example.vpn\n"
            "  attribute: PayloadType: com.apple.vpn\n"
        )
        with patch("openjarvis.security.environment._run", return_value=fake_output):
            result = check_mdm_profiles()
        assert result.severity == Severity.WARN
        assert result.remediation != ""

    def test_profiles_command_unavailable(self) -> None:
        with patch("openjarvis.security.environment._run", return_value=None):
            result = check_mdm_profiles()
        assert result.severity == Severity.INFO

    def test_skipped_on_linux(self) -> None:
        with patch("openjarvis.security.environment._is_macos", return_value=False):
            result = check_mdm_profiles()
        assert result.severity == Severity.INFO
        assert "skipped" in result.title.lower()


# ---------------------------------------------------------------------------
# check_cloud_sync
# ---------------------------------------------------------------------------


class TestCheckCloudSync:
    def test_no_sync_running(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=[]):
            result = check_cloud_sync()
        assert result.severity == Severity.INFO
        assert "no cloud" in result.title.lower()

    def test_icloud_running(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=["bird"]):
            result = check_cloud_sync()
        assert result.severity == Severity.WARN
        assert "iCloud" in result.title

    def test_dropbox_running(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=["Dropbox"]):
            result = check_cloud_sync()
        assert result.severity == Severity.WARN
        assert result.remediation != ""

    def test_multiple_sync_tools(self) -> None:
        with patch(
            "openjarvis.security.environment._any_process_running",
            return_value=["bird", "Dropbox"],
        ):
            result = check_cloud_sync()
        assert result.severity == Severity.WARN
        assert "iCloud" in result.title
        assert "Dropbox" in result.title


# ---------------------------------------------------------------------------
# check_open_ports
# ---------------------------------------------------------------------------

_LSOF_HEADER = "COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
_LSOF_OLLAMA = "ollama    123  user  10u  IPv4  123     0t0  TCP *:11434 (LISTEN)\n"
_LSOF_SSHD   = "sshd      99   root  3u   IPv4  99      0t0  TCP *:22 (LISTEN)\n"
_LSOF_CUSTOM = "myapp     200  user  5u   IPv4  200     0t0  TCP *:9999 (LISTEN)\n"


class TestCheckOpenPorts:
    def test_only_known_ports(self) -> None:
        with patch("openjarvis.security.environment._run", return_value=_LSOF_HEADER + _LSOF_OLLAMA):
            result = check_open_ports()
        assert result.severity == Severity.INFO
        assert "no unexpected" in result.title.lower()

    def test_unexpected_port_reported(self) -> None:
        with patch(
            "openjarvis.security.environment._run",
            return_value=_LSOF_HEADER + _LSOF_SSHD + _LSOF_CUSTOM,
        ):
            result = check_open_ports()
        assert result.severity == Severity.INFO
        assert "unexpected" in result.title.lower()
        assert "9999" in result.detail or "sshd" in result.detail or "myapp" in result.detail

    def test_lsof_fails(self) -> None:
        with patch("openjarvis.security.environment._run", return_value=None):
            result = check_open_ports()
        assert result.severity == Severity.INFO
        assert "could not" in result.title.lower()


# ---------------------------------------------------------------------------
# check_screen_recording
# ---------------------------------------------------------------------------


class TestCheckScreenRecording:
    def test_no_apps_granted(self) -> None:
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment.Path.exists", return_value=True),
            patch("openjarvis.security.environment._run", return_value=""),
        ):
            result = check_screen_recording()
        assert result.severity == Severity.INFO
        assert "no apps" in result.title.lower()

    def test_apps_with_permission(self) -> None:
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment.Path.exists", return_value=True),
            patch("openjarvis.security.environment._run", return_value="com.example.recorder\ncom.zoom.us\n"),
        ):
            result = check_screen_recording()
        assert result.severity == Severity.WARN
        assert "2" in result.title
        assert result.remediation != ""

    def test_tcc_db_missing(self) -> None:
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment.Path.exists", return_value=False),
        ):
            result = check_screen_recording()
        assert result.severity == Severity.INFO

    def test_skipped_on_linux(self) -> None:
        with patch("openjarvis.security.environment._is_macos", return_value=False):
            result = check_screen_recording()
        assert result.severity == Severity.INFO
        assert "skipped" in result.title.lower()


# ---------------------------------------------------------------------------
# check_remote_access
# ---------------------------------------------------------------------------


class TestCheckRemoteAccess:
    def test_nothing_running(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=[]):
            result = check_remote_access()
        assert result.severity == Severity.INFO
        assert "no remote" in result.title.lower()

    def test_teamviewer_running(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=["TeamViewer"]):
            result = check_remote_access()
        assert result.severity == Severity.WARN
        assert "TeamViewer" in result.title
        assert result.remediation != ""

    def test_vpn_only_is_info(self) -> None:
        with patch("openjarvis.security.environment._any_process_running", return_value=["tailscaled"]):
            result = check_remote_access()
        assert result.severity == Severity.INFO

    def test_vpn_plus_remote_desktop_is_warn(self) -> None:
        with patch(
            "openjarvis.security.environment._any_process_running",
            return_value=["tailscaled", "AnyDesk"],
        ):
            result = check_remote_access()
        assert result.severity == Severity.WARN


# ---------------------------------------------------------------------------
# check_dns
# ---------------------------------------------------------------------------


class TestCheckDns:
    def test_plain_google_dns(self) -> None:
        fake_scutil = "nameserver[0] : 8.8.8.8\nnameserver[1] : 8.8.4.4\n"
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment._run", return_value=fake_scutil),
        ):
            result = check_dns()
        assert result.severity == Severity.INFO
        assert "8.8.8.8" in result.title

    def test_private_dns(self) -> None:
        fake_scutil = "nameserver[0] : 192.168.1.1\n"
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment._run", return_value=fake_scutil),
        ):
            result = check_dns()
        assert result.severity == Severity.INFO
        assert "local" in result.title.lower() or "private" in result.title.lower()

    def test_doh_detected(self) -> None:
        fake_scutil = "dns-over-https resolver active\n"
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment._run", return_value=fake_scutil),
        ):
            result = check_dns()
        assert result.severity == Severity.INFO
        assert "encrypted" in result.title.lower()

    def test_scutil_fails(self) -> None:
        with (
            patch("openjarvis.security.environment._is_macos", return_value=True),
            patch("openjarvis.security.environment._run", return_value=None),
        ):
            result = check_dns()
        assert result.severity == Severity.INFO

    def test_skipped_on_linux(self) -> None:
        with patch("openjarvis.security.environment._is_macos", return_value=False):
            result = check_dns()
        assert result.severity == Severity.INFO
        assert "skipped" in result.title.lower()


# ---------------------------------------------------------------------------
# run_all_checks
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    def test_returns_seven_findings(self) -> None:
        report = run_all_checks()
        assert len(report.findings) == 7

    def test_all_findings_have_required_fields(self) -> None:
        report = run_all_checks()
        for finding in report.findings:
            assert finding.check
            assert finding.title
            assert finding.detail
            assert finding.severity in list(Severity)

    def test_check_exception_is_caught(self) -> None:
        """A failing check should not propagate — it becomes an INFO finding."""
        def boom():
            raise RuntimeError("simulated failure")

        import openjarvis.security.environment as env_mod
        original = env_mod.check_filevault
        env_mod.check_filevault = boom
        try:
            report = run_all_checks()
        finally:
            env_mod.check_filevault = original

        # All 7 checks should still be present (the failed one as a caught finding)
        assert len(report.findings) == 7
