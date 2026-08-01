"""Curated external data sources for Mucha Science domain packs.

Ported from ontologylab@ad9444c ("Add Ensembl and ChEMBL") with the port
explicitly limited to the chemistry resource (ChEMBL) plus the shared
scaffolding. Two invariants are preserved verbatim from the origin:

1. Field-qualified exact lookup only. ChEMBL is queried with
   ``pref_name__iexact``; the similarity-ranked endpoints are never used,
   because a near miss attaches a page of true facts to the wrong thing.
2. A miss is returned, never the closest record.

Mucha-specific addition: the data-source policy gate. The revised product
spec (docs/PRODUCT_SPEC.md, 데이터 소스 정책) defers ChEMBL until its
required fields and redistribution/commercial rights are confirmed, so
every lookup passes through :func:`activation_verdict` — a deferred source
is inert until an ALLOWED license decision is recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote_plus

CHEMBL_API_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
CHEMBL_RESOURCE = "chembl"

MAX_FACT_CHARS = 400

_SOURCE_POLICY: dict[str, str] = {
    "ncbi_amrfinderplus": "REQUIRED",
    "ncbi_refseq_genbank": "REQUIRED",
    "uniprot": "REQUIRED",
    "card_rgi": "LICENSE_GATED",
    CHEMBL_RESOURCE: "DEFERRED",
    "brenda": "DEFERRED",
    "pubchem": "DEFERRED",
    "zinc": "DEFERRED",
}


class ResourceError(Exception):
    pass


class SourcePolicyError(Exception):
    pass


@dataclass(frozen=True)
class ActivationVerdict:
    source: str
    policy: str
    active: bool
    note: str


@dataclass(frozen=True)
class ResourceMatch:
    resource: str
    external_id: str
    record_url: str
    matched_name: str
    facts: dict[str, Any] = field(default_factory=dict)


def activation_verdict(source: str, *, license_decision: str) -> ActivationVerdict:
    policy = _SOURCE_POLICY.get(source, "DEFERRED")
    if license_decision == "ALLOWED":
        return ActivationVerdict(source, policy, True, f"license ALLOWED on record; policy {policy}")
    if policy == "REQUIRED":
        return ActivationVerdict(source, policy, True, f"required source; decision {license_decision} recorded")
    raise SourcePolicyError(
        f"source {source!r} is {policy} under the data-source policy and "
        f"license decision is {license_decision}; activation refused"
    )


def _clip(text: Any) -> str:
    return " ".join(str(text or "").split())[:MAX_FACT_CHARS]


def build_chembl_url(name: str) -> str:
    return f"{CHEMBL_API_URL}?pref_name__iexact={quote_plus(name)}&limit=1"


def parse_chembl(json_text: str, name: str) -> ResourceMatch | None:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ResourceError(f"chembl returned unparseable JSON: {exc}") from exc
    molecules = payload.get("molecules") or []
    if not molecules:
        return None
    item = molecules[0]
    chembl_id = _clip(item.get("molecule_chembl_id"))
    pref = _clip(item.get("pref_name"))
    if not chembl_id or pref.upper() != name.strip().upper():
        return None
    props = item.get("molecule_properties") or {}
    return ResourceMatch(
        resource=CHEMBL_RESOURCE,
        external_id=chembl_id,
        record_url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
        matched_name=pref,
        facts={
            "chembl_id": chembl_id,
            "molecule_type": _clip(item.get("molecule_type")),
            "max_phase": _clip(item.get("max_phase")),
            "formula": _clip(props.get("full_molformula")),
        },
    )


def fetch_chembl(
    name: str,
    *,
    http_get: Callable[[str], str],
    license_decision: str,
) -> ResourceMatch | None:
    activation_verdict(CHEMBL_RESOURCE, license_decision=license_decision)
    return parse_chembl(http_get(build_chembl_url(name)), name)
