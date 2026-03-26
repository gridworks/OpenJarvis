"""``jarvis scan`` — audit the local security environment on demand."""

from __future__ import annotations

import json
from dataclasses import asdict

import click
from rich.console import Console
from rich.table import Table

from openjarvis.security.environment import EnvReport, Severity, run_all_checks


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {
    Severity.INFO: "[green]\u2713[/green]",
    Severity.WARN: "[yellow]![/yellow]",
    Severity.CRITICAL: "[red]\u2717[/red]",
}

_SEVERITY_STYLES = {
    Severity.INFO: "green",
    Severity.WARN: "yellow",
    Severity.CRITICAL: "red",
}


def _render_report(report: EnvReport, console: Console) -> None:
    """Print the full scan report as a Rich table."""
    console.print()
    console.print("[bold]OpenJarvis Security Scan[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=True)
    table.add_column("", width=3, justify="center")  # icon
    table.add_column("Check")
    table.add_column("Finding")

    for finding in report.findings:
        icon = _SEVERITY_ICONS.get(finding.severity, "?")
        style = _SEVERITY_STYLES.get(finding.severity, "white")
        body = f"[{style}]{finding.title}[/{style}]\n"
        body += f"  [dim]{finding.detail}[/dim]"
        if finding.remediation:
            body += f"\n  [bold dim]Fix:[/bold dim] [dim]{finding.remediation}[/dim]"
        table.add_row(icon, finding.check, body)

    console.print(table)

    info_count = len(report.by_severity(Severity.INFO))
    warn_count = len(report.by_severity(Severity.WARN))
    crit_count = len(report.by_severity(Severity.CRITICAL))

    console.print()
    parts = [f"[green]{info_count} ok[/green]"]
    if warn_count:
        parts.append(f"[yellow]{warn_count} warning{'s' if warn_count != 1 else ''}[/yellow]")
    if crit_count:
        parts.append(f"[red]{crit_count} critical[/red]")
    console.print("  " + ", ".join(parts))
    console.print()

    if report.has_critical:
        console.print(
            "[red bold]Action required:[/red bold] address critical findings above "
            "before storing sensitive data with OpenJarvis."
        )
        console.print()
    elif report.has_warnings:
        console.print(
            "[yellow]Review warnings above[/yellow] — they may not block usage "
            "but could affect your privacy posture."
        )
        console.print()


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--json", "as_json", is_flag=True, help="Output results as JSON."
)
def scan(as_json: bool) -> None:
    """Audit the local security environment.

    Checks disk encryption, MDM profiles, cloud sync agents, open ports,
    screen recording permissions, remote access tools, and DNS configuration.
    All checks are read-only and require no elevated privileges.
    """
    report = run_all_checks()

    if as_json:
        output = [
            {
                "check": f.check,
                "severity": f.severity.value,
                "title": f.title,
                "detail": f.detail,
                "remediation": f.remediation,
            }
            for f in report.findings
        ]
        click.echo(json.dumps(output, indent=2))
        return

    console = Console()
    _render_report(report, console)
