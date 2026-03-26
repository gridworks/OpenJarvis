"""Tests for ``jarvis scan`` CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.security.environment import EnvFinding, EnvReport, Severity


def _make_report(*findings: EnvFinding) -> EnvReport:
    return EnvReport(findings=list(findings))


def _clean_report() -> EnvReport:
    return _make_report(
        EnvFinding("disk_encryption", Severity.INFO, "FileVault is enabled", "All good."),
        EnvFinding("mdm_profiles", Severity.INFO, "No MDM profiles detected", "Clean."),
        EnvFinding("cloud_sync", Severity.INFO, "No cloud sync agents detected", "Clean."),
        EnvFinding("open_ports", Severity.INFO, "No unexpected ports", "Clean."),
        EnvFinding("screen_recording", Severity.INFO, "No apps with permission", "Clean."),
        EnvFinding("remote_access", Severity.INFO, "No remote access tools", "Clean."),
        EnvFinding("dns", Severity.INFO, "Private DNS", "Clean."),
    )


class TestScanHelp:
    def test_scan_help(self) -> None:
        result = CliRunner().invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0
        assert "security" in result.output.lower() or "audit" in result.output.lower()


class TestScanRuns:
    def test_scan_clean(self) -> None:
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=_clean_report()):
            result = CliRunner().invoke(cli, ["scan"])
        assert result.exit_code == 0
        assert "Security Scan" in result.output or "ok" in result.output.lower()

    def test_scan_with_critical(self) -> None:
        report = _make_report(
            EnvFinding(
                "disk_encryption", Severity.CRITICAL,
                "FileVault is disabled", "Disk unencrypted.",
                remediation="Enable FileVault.",
            ),
        )
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=report):
            result = CliRunner().invoke(cli, ["scan"])
        assert result.exit_code == 0
        assert "FileVault is disabled" in result.output

    def test_scan_with_warning(self) -> None:
        report = _make_report(
            EnvFinding(
                "cloud_sync", Severity.WARN,
                "Cloud sync running: iCloud Drive", "iCloud is active.",
                remediation="Check iCloud settings.",
            ),
        )
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=report):
            result = CliRunner().invoke(cli, ["scan"])
        assert result.exit_code == 0
        assert "iCloud Drive" in result.output


class TestScanJsonOutput:
    def test_json_flag_produces_valid_json(self) -> None:
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=_clean_report()):
            result = CliRunner().invoke(cli, ["scan", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 7

    def test_json_entries_have_required_fields(self) -> None:
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=_clean_report()):
            result = CliRunner().invoke(cli, ["scan", "--json"])
        data = json.loads(result.output)
        for entry in data:
            assert "check" in entry
            assert "severity" in entry
            assert "title" in entry
            assert "detail" in entry
            assert "remediation" in entry

    def test_json_severity_values_are_strings(self) -> None:
        with patch("openjarvis.cli.scan_cmd.run_all_checks", return_value=_clean_report()):
            result = CliRunner().invoke(cli, ["scan", "--json"])
        data = json.loads(result.output)
        for entry in data:
            assert entry["severity"] in ("info", "warn", "critical")


class TestScanRegistered:
    def test_scan_is_top_level_command(self) -> None:
        assert "scan" in cli.commands
