"""Query helpers for AutoResearch.

The goal is to keep Stage 3 from becoming a vague "search the web" step.
Each query expansion states a distinct evidence intent so runners can collect
coverage across primary evidence, constraints, and counter-signals.
"""
from __future__ import annotations

from datetime import UTC, datetime
import re


_BIOMEDICAL_MARKERS = (
    "biomedical",
    "clinical",
    "medical",
    "observational",
    "randomized",
    "trial",
    "microbiome",
    "depression",
    "학술",
    "논문",
    "임상",
    "생의학",
    "관찰연구",
    "임상시험",
    "미생물",
    "우울증",
)

_BIOMEDICAL_TERMS = (
    ("장내 미생물", "gut microbiome"),
    ("마이크로바이옴", "microbiome"),
    ("우울증", "depression"),
    ("인과관계", "causal relationship"),
    ("인과", "causal"),
    ("관찰연구", "observational studies"),
    ("관찰 연구", "observational studies"),
    ("무작위 대조시험", "randomized controlled trials"),
    ("임상시험", "clinical trials"),
    ("임상 시험", "clinical trials"),
    ("체계적 문헌고찰", "systematic review"),
    ("메타분석", "meta-analysis"),
)


def is_biomedical_query(query: str) -> bool:
    normalized = " ".join((query or "").casefold().split())
    return any(marker in normalized for marker in _BIOMEDICAL_MARKERS)


def minimum_publication_year(query: str, *, current_year: int | None = None) -> int | None:
    normalized = " ".join((query or "").casefold().split())
    current_year = current_year or datetime.now(UTC).year
    explicit = re.search(
        r"(?:since|from|onward|after|published\s+(?:since|after))\s*(20\d{2})",
        normalized,
    )
    if explicit:
        year = int(explicit.group(1))
        return year + 1 if "after" in explicit.group(0) else year
    korean_explicit = re.search(r"(20\d{2})\s*년?\s*이후", normalized)
    if korean_explicit:
        return int(korean_explicit.group(1))
    recent = re.search(r"최근\s*(\d+)\s*년", normalized)
    if recent:
        return max(1900, current_year - int(recent.group(1)))
    english_recent = re.search(r"(?:last|recent)\s+(\d+|five)\s+years?", normalized)
    if english_recent:
        years = 5 if english_recent.group(1) == "five" else int(english_recent.group(1))
        return max(1900, current_year - years)
    return None


def biomedical_english_query(query: str, *, current_year: int | None = None) -> str:
    if not is_biomedical_query(query):
        return ""
    lowered = " ".join(query.casefold().split())
    terms: list[str] = []
    for source, english in _BIOMEDICAL_TERMS:
        if source in lowered and english not in terms:
            terms.append(english)
    route_focus = ""
    if "source-backed examples case studies" in lowered:
        route_focus = "randomized controlled trials"
    elif "definitions scope methods constraints" in lowered:
        route_focus = "observational studies"
    elif "counter evidence limitations failure cases" in lowered:
        route_focus = "Mendelian randomization"
    elif "official statistics peer reviewed evidence" in lowered:
        route_focus = "systematic review"
    if route_focus:
        study_design_terms = {
            "causal",
            "causal relationship",
            "clinical trials",
            "observational studies",
            "randomized controlled trials",
            "systematic review",
            "meta-analysis",
        }
        terms = [term for term in terms if term not in study_design_terms]
        terms.append(route_focus)
    if not re.search(r"[가-힣]", lowered):
        generic_suffix_tokens = {
            "backed",
            "case",
            "constraints",
            "counter",
            "definitions",
            "evidence",
            "examples",
            "failure",
            "limitations",
            "methods",
            "official",
            "peer",
            "reviewed",
            "scope",
            "source",
            "statistics",
            "studies",
        }
        terms.extend(
            token
            for token in re.findall(r"[a-z][a-z0-9-]+", lowered)
            if token not in generic_suffix_tokens
            and token not in {"the", "and", "or", "since", "from", "after"}
        )
    minimum_year = minimum_publication_year(query, current_year=current_year)
    if minimum_year is not None:
        terms.append(f"published since {minimum_year}")
    return " ".join(dict.fromkeys(terms))


def pubmed_biomedical_query(query: str, *, current_year: int | None = None) -> str:
    english = biomedical_english_query(query, current_year=current_year)
    if not english:
        return query
    clauses: list[str] = []
    if "gut microbiome" in english:
        clauses.append('("gut microbiome"[Title/Abstract] OR microbiome[MeSH Terms])')
    if "depression" in english:
        clauses.append('("depression"[Title/Abstract] OR "Depressive Disorder"[MeSH Terms])')
    study_designs: list[str] = []
    if "randomized controlled trials" in english:
        study_designs.append("randomized controlled trial[Publication Type]")
    elif "systematic review" in english:
        study_designs.append("systematic review[Publication Type]")
    elif "Mendelian randomization" in english:
        study_designs.append('"Mendelian randomization"[Title/Abstract]')
    else:
        if "causal" in english:
            study_designs.append('"causal"[Title/Abstract]')
        if "observational studies" in english:
            study_designs.append('"observational study"[Title/Abstract]')
        if "clinical trials" in english:
            study_designs.append("clinical trial[Publication Type]")
    if study_designs:
        clauses.append(f"({' OR '.join(study_designs)})")
    minimum_year = minimum_publication_year(query, current_year=current_year)
    if minimum_year is not None:
        maximum_year = current_year or datetime.now(UTC).year
        clauses.append(f"{minimum_year}:{maximum_year}[Date - Publication]")
    return " AND ".join(clauses) if clauses else english


def expand_query(
    query: str,
    *,
    context: str = "",
    quality_bar: str = "",
    max_queries: int = 5,
) -> list[str]:
    query = query.strip()
    if not query:
        return []

    # Keep query expansion topic-anchored and domain-neutral. Muchanipo is a
    # general-purpose research tool: Korean topics should not be rewritten into
    # hardcoded vertical presets such as AgTech, diagnostics, pricing, or a
    # standalone "Korea" bridge query. Search backends may still receive the
    # original Korean topic plus generic evidence intents.
    candidates = [
        query,
        f"{query} official statistics peer reviewed evidence",
        f"{query} definitions scope methods constraints",
        f"{query} source-backed examples case studies",
        f"{query} counter evidence limitations failure cases",
    ]
    if context.strip():
        candidates.append(f"{query} {context.strip()} source evidence")
    if quality_bar.strip():
        candidates.append(f"{query} {quality_bar.strip()} source quality")

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= max(1, max_queries):
            break
    return out


def translated_topic_queries(query: str) -> list[str]:
    """Add topic-anchored bridge queries without injecting a vertical preset.

    Muchanipo is a general-purpose research tool. The planner may add generic
    source-channel probes (official statistics, adoption, limitations, methods),
    but domain specialization must come from the user's topic, interview answers,
    or targeting map — not from keyword-triggered AgTech/diagnostics/etc. presets.
    """
    query = " ".join(query.split())
    if not query:
        return []
    biomedical_query = biomedical_english_query(query)
    if biomedical_query:
        return [biomedical_query]
    lowered = query.casefold()

    # Suppress product-market source-channel probes for financial-asset market
    # questions, but do not treat every "forecast/예측" as an asset-market query:
    # product adoption forecasts still need government/statistics/WTP evidence.
    financial_asset_market_intent = any(
        marker in query or marker in lowered
        for marker in (
            "주식",
            "증권",
            "암호화폐",
            "가상자산",
            "선물",
            "옵션",
            "채권",
            "외환",
            "stock market",
            "financial market",
            "equity market",
            "crypto market",
            "cryptocurrency",
            "bitcoin",
            "bond market",
            "forex",
            "fx market",
            "futures",
            "options market",
            "derivatives",
            "commodity market",
        )
    )
    source_channel_intent = (not financial_asset_market_intent) and any(
        marker in query or marker in lowered
        for marker in (
            "시장성",
            "가격",
            "채택",
            "도입",
            "구매",
            "지불의사",
            "규제",
            "유통",
            "통계",
            "market",
            "pricing",
            "adoption",
            "willingness to pay",
            "regulatory adoption",
            "distribution channel",
        )
    )
    if not source_channel_intent:
        return []

    # Use the topic itself as the bridge base. Do not translate selected tokens
    # into a hardcoded domain lexicon here; the deep interview/targeting map is
    # responsible for adding domain-specific search language when needed.
    base = query
    queries = [base]
    local_query = _local_language_source_channel_query(query)
    if local_query:
        queries.append(local_query)
    queries.extend(
        [
            f"{base} government statistics willingness to pay adoption market adoption pricing government statistics market adoption pricing willingness to pay",
            f"{base} empirical evidence methods validation limitations",
            f"{base} distribution channel regulatory adoption case studies",
        ]
    )
    if _scientific_validation_intent(query):
        queries.append(f"{base} peer reviewed assay field validation sensitivity specificity")
    return queries


def _scientific_validation_intent(query: str) -> bool:
    lowered = " ".join(query.casefold().split())
    return any(
        marker in lowered
        for marker in (
            "diagnostic",
            "diagnostics",
            "molecular",
            "assay",
            "field validation",
            "detection kit",
            "진단",
            "검출",
            "분자",
        )
    )


def _local_language_source_channel_query(query: str) -> str:
    """Build a concise local-language source-channel query when possible.

    Market/adoption evidence often lives in local government/statistics pages,
    while long translated technical queries can return no web hits. Keep this
    procedural and domain-neutral: retain local topic nouns, drop scientific
    method terms that would force a diagnostic evidence gate, and add generic
    channel/facet words.
    """

    import re

    if not re.search(r"[가-힣]", query):
        return ""
    terms = re.findall(r"[가-힣A-Za-z0-9]+", query)
    excluded = {
        "source",
        "backed",
        "deep",
        "research",
        "council",
        "persona",
        "검증",
    }
    kept: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in excluded or term in excluded:
            continue
        if term.isdigit() or re.fullmatch(r"\d+[a-z]?", key):
            continue
        if term not in kept:
            kept.append(term)
    if not kept:
        return ""
    suffix = ["공식", "통계", "가격", "도입", "유통", "규제"]
    return " ".join(kept[:6] + suffix)
