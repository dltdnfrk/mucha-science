from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, IO

from .contracts import CLI_JSON_CONTRACTS_V1, JSON_SCHEMA_VERSION
from .paths import repo_root


def json_contracts_report() -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for command, contract in CLI_JSON_CONTRACTS_V1.items():
        contracts[command] = {
            "schema_version": contract["schema_version"],
            "description": contract["description"],
            "required_top_level_keys": list(contract["required_top_level_keys"]),
            "compatibility": contract["compatibility"],
        }
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "muchanipo contracts",
        "contracts": contracts,
    }


def render_json_contracts(*, stdout: IO[str] | None = None) -> dict[str, Any]:
    out = stdout or sys.stdout
    report = json_contracts_report()
    out.write("\nCLI JSON contracts\n------------------\n")
    for command, contract in report["contracts"].items():
        keys = ", ".join(contract["required_top_level_keys"])
        out.write(f"{command} --json\n")
        out.write(f"  schema_version: {contract['schema_version']}\n")
        out.write(f"  required keys: {keys}\n")
        out.write(f"  compatibility: {contract['compatibility']}\n")
    out.write("\n")
    out.flush()
    return report


def references_report() -> dict[str, Any]:
    from src.pipeline.reference_inventory import reference_readiness_report

    return reference_readiness_report(repo_root=repo_root())


def render_references(
    *,
    stdout: IO[str] | None = None,
    report_loader: Callable[[], dict[str, Any]] = references_report,
) -> dict[str, Any]:
    out = stdout or sys.stdout
    report = report_loader()
    out.write("\nReference runtime readiness\n---------------------------\n")
    for stage in report["stages"]:
        out.write(
            f"{stage['step']}. {stage['name']}: "
            f"{stage['ready_count']}/{stage['reference_count']} ready, "
            f"{stage['product_standard_covered_count']}/{stage['reference_count']} product-standard covered, "
            f"{stage['implemented_count']}/{stage['reference_count']} runtime-backed"
        )
        if stage["license_blocked_count"]:
            out.write(f", {stage['license_blocked_count']} license boundary")
        if stage["gap_count"]:
            out.write(f", {stage['gap_count']} gap(s)")
        out.write("\n")
    if report["license_warnings"]:
        out.write("\nLicense warnings\n")
        for item in report["license_warnings"]:
            out.write(f"- {item['name']}: {item['warning']}\n")
    if report["gaps"]:
        out.write("\nKnown gaps\n")
        for item in report["gaps"]:
            out.write(f"- {item['name']}: {item['gap']}\n")
    out.write("\n")
    out.flush()
    return report


def guard_report(*, strict: bool = False, include_untracked: bool = True) -> dict[str, Any]:
    from src.governance.autoresearch_guard import run_product_guard

    return run_product_guard(
        repo_root=repo_root(),
        strict=strict,
        include_untracked=include_untracked,
    )


def render_guard(*, stdout: IO[str] | None = None, strict: bool = False) -> dict[str, Any]:
    from src.governance.autoresearch_guard import render_product_guard

    report = guard_report(strict=strict)
    render_product_guard(report, stdout=stdout)
    return report
