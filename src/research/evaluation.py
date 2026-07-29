"""Deterministic retrieval and evidence-quality evaluation primitives."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import AbstractSet, Final


RRF_K: Final = 60
_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*|[가-힣]+")
_ENTITY_RE: Final = re.compile(r"\b(?:[A-Z][A-Za-z0-9-]*|\d+(?:\.\d+)?)\b")
_NUMBER_RE: Final = re.compile(r"\b\d+(?:\.\d+)?\b")
_AMBIGUITY: Final = frozenset(
    {"ambiguous", "associated", "association", "unclear", "mixed", "may", "might"}
)
_STOPWORDS: Final = frozenset(
    {"a", "an", "and", "by", "for", "in", "is", "of", "on", "the", "to", "versus", "with"}
)
_NEGATION_RE: Final = re.compile(r"\b(?:did not|does not|no|not|never|without)\b")
_DIRECTION_DOWN: Final = "__direction_down__"
_DIRECTION_UP: Final = "__direction_up__"
_DIRECTION_TOKENS: Final = frozenset({_DIRECTION_DOWN, _DIRECTION_UP})
_KOREAN_PARTICLES: Final = (
    "에게서",
    "으로",
    "에서",
    "까지",
    "부터",
    "처럼",
    "보다",
    "에게",
    "한테",
    "께서",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "에",
    "의",
    "도",
    "만",
    "로",
)


@dataclass(frozen=True, slots=True)
class EvaluationInputError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RankedPaper:
    paper_id: str
    doi: str | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRanking:
    provider: str
    papers: tuple[RankedPaper, ...]


@dataclass(frozen=True, slots=True)
class RankContribution:
    provider: str
    rank: int


@dataclass(frozen=True, slots=True)
class FusedPaper:
    canonical_id: str
    paper_id: str
    doi: str | None
    title: str | None
    score: float
    source_priority: int
    contributions: tuple[RankContribution, ...]


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    confidence_threshold: float
    coverage: float
    risk: float


@unique
class ClaimLabel(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def normalize_doi(value: str | None) -> str | None:
    """Return a lowercase DOI without common resolver prefixes."""
    if value is None:
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    normalized = normalized.rstrip(" .;,")
    return normalized or None


def _canonical_id(paper: RankedPaper) -> str:
    doi = normalize_doi(paper.doi)
    if doi is not None:
        return f"doi:{doi}"
    stable_id = " ".join(paper.paper_id.strip().casefold().split()).rstrip("/")
    return f"id:{stable_id}"


def reciprocal_rank_fusion(rankings: Sequence[ProviderRanking]) -> tuple[FusedPaper, ...]:
    """Fuse provider rankings with fixed RRF k=60 and deterministic ties."""
    scores: dict[str, float] = {}
    priorities: dict[str, int] = {}
    representatives: dict[str, RankedPaper] = {}
    contributions: dict[str, list[RankContribution]] = {}
    for priority, ranking in enumerate(rankings):
        seen: set[str] = set()
        for rank, paper in enumerate(ranking.papers, start=1):
            canonical_id = _canonical_id(paper)
            if canonical_id in seen:
                continue
            seen.add(canonical_id)
            scores[canonical_id] = scores.get(canonical_id, 0.0) + 1.0 / (RRF_K + rank)
            contributions.setdefault(canonical_id, []).append(
                RankContribution(provider=ranking.provider, rank=rank)
            )
            if canonical_id not in representatives:
                representatives[canonical_id] = paper
                priorities[canonical_id] = priority
    fused = (
        FusedPaper(
            canonical_id=canonical_id,
            paper_id=representatives[canonical_id].paper_id,
            doi=normalize_doi(representatives[canonical_id].doi),
            title=representatives[canonical_id].title,
            score=score,
            source_priority=priorities[canonical_id],
            contributions=tuple(contributions[canonical_id]),
        )
        for canonical_id, score in scores.items()
    )
    return tuple(
        sorted(
            fused,
            key=lambda paper: (
                -paper.score,
                paper.source_priority,
                paper.paper_id.casefold(),
                paper.paper_id,
            ),
        )
    )


def recall_at_k(run: Sequence[str], relevant: AbstractSet[str], k: int) -> float:
    if k <= 0:
        raise EvaluationInputError("k must be positive")
    if not relevant:
        return 0.0
    return len(set(run[:k]) & relevant) / len(relevant)


def mean_reciprocal_rank(
    runs: Sequence[Sequence[str]],
    relevant_per_query: Sequence[AbstractSet[str]],
) -> float:
    if not runs or len(runs) != len(relevant_per_query):
        raise EvaluationInputError("runs and relevance must be non-empty and aligned")
    reciprocal_ranks = (
        next((1.0 / rank for rank, paper_id in enumerate(run, start=1) if paper_id in relevant), 0.0)
        for run, relevant in zip(runs, relevant_per_query, strict=True)
    )
    return sum(reciprocal_ranks) / len(runs)


def ndcg_at_k(run: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    if k <= 0:
        raise EvaluationInputError("k must be positive")
    gains = [relevance.get(paper_id, 0) for paper_id in run[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    dcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    idcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _tokens(text: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_token in _TOKEN_RE.findall(text):
        token = raw_token.casefold()
        direction = _direction_token(token)
        if direction is not None:
            normalized.append(direction)
            continue
        if re.fullmatch(r"[가-힣]+", token):
            token = _strip_korean_particle(token)
        if token:
            normalized.append(token)
    return tuple(normalized)


def _direction_token(token: str) -> str | None:
    if re.fullmatch(
        r"(?:decreas\w*|lower\w*|reduc\w*|drop\w*|fall(?:s|ing|en)?|fell)",
        token,
    ):
        return _DIRECTION_DOWN
    if re.fullmatch(
        r"(?:increas\w*|higher|rais\w*|rise|rises|rising|risen|grow\w*|rose)",
        token,
    ):
        return _DIRECTION_UP
    if any(stem in token for stem in ("낮추", "낮춘", "낮췄", "감소", "줄이", "줄었", "저하")):
        return _DIRECTION_DOWN
    if any(stem in token for stem in ("높이", "높인", "높였", "증가", "상승", "늘리", "늘었")):
        return _DIRECTION_UP
    return None


def _strip_korean_particle(token: str) -> str:
    for particle in _KOREAN_PARTICLES:
        if token.endswith(particle) and len(token) > len(particle):
            return token[: -len(particle)]
    return token


def classify_claim_evidence(claim: str, evidence: str) -> ClaimLabel:
    """Label only clear lexical support or explicit directional contradiction."""
    claim_tokens = frozenset(token for token in _tokens(claim) if token not in _STOPWORDS)
    evidence_tokens = frozenset(token for token in _tokens(evidence) if token not in _STOPWORDS)
    if not claim_tokens or not evidence_tokens:
        return ClaimLabel.INSUFFICIENT_EVIDENCE
    claim_core = claim_tokens - _DIRECTION_TOKENS
    evidence_core = evidence_tokens - _DIRECTION_TOKENS
    overlap = len(claim_core & evidence_core) / len(claim_core) if claim_core else 0.0
    claim_entities = frozenset(_ENTITY_RE.findall(claim))
    evidence_entities = frozenset(_ENTITY_RE.findall(evidence))
    entity_overlap = not claim_entities or bool(claim_entities & evidence_entities)
    if overlap < 0.6 or not entity_overlap or _AMBIGUITY & evidence_tokens:
        return ClaimLabel.INSUFFICIENT_EVIDENCE
    claim_down = _DIRECTION_DOWN in claim_tokens
    claim_up = _DIRECTION_UP in claim_tokens
    evidence_down = _DIRECTION_DOWN in evidence_tokens
    evidence_up = _DIRECTION_UP in evidence_tokens
    opposed = (claim_down and evidence_up) or (claim_up and evidence_down)
    if opposed or bool(_NEGATION_RE.search(claim.casefold())) != bool(
        _NEGATION_RE.search(evidence.casefold())
    ):
        return ClaimLabel.REFUTES
    if (claim_down and not evidence_down) or (claim_up and not evidence_up):
        return ClaimLabel.INSUFFICIENT_EVIDENCE
    claim_numbers = set(_NUMBER_RE.findall(claim))
    if claim_numbers and not claim_numbers <= set(_NUMBER_RE.findall(evidence)):
        return ClaimLabel.INSUFFICIENT_EVIDENCE
    return ClaimLabel.SUPPORTS


def evidence_span_f1(predicted: str, gold: str) -> float:
    predicted_tokens, gold_tokens = _tokens(predicted), _tokens(gold)
    if not predicted_tokens and not gold_tokens:
        return 1.0
    if not predicted_tokens or not gold_tokens:
        return 0.0
    overlap = sum((Counter(predicted_tokens) & Counter(gold_tokens)).values())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(predicted_tokens), overlap / len(gold_tokens)
    return 2.0 * precision * recall / (precision + recall)


def _validated_predictions(
    probabilities: Sequence[float],
    outcomes: Sequence[bool],
) -> tuple[tuple[float, bool], ...]:
    if not probabilities or len(probabilities) != len(outcomes):
        raise EvaluationInputError("probabilities and outcomes must be non-empty and aligned")
    if any(probability < 0.0 or probability > 1.0 for probability in probabilities):
        raise EvaluationInputError("probabilities must be within [0, 1]")
    return tuple(zip(probabilities, outcomes, strict=True))


def brier_score(probabilities: Sequence[float], outcomes: Sequence[bool]) -> float:
    pairs = _validated_predictions(probabilities, outcomes)
    return sum((probability - float(outcome)) ** 2 for probability, outcome in pairs) / len(pairs)


def expected_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[bool],
    bins: int,
) -> float:
    if bins <= 0:
        raise EvaluationInputError("bins must be positive")
    pairs = _validated_predictions(probabilities, outcomes)
    grouped: list[list[tuple[float, bool]]] = [[] for _index in range(bins)]
    for probability, outcome in pairs:
        grouped[min(int(probability * bins), bins - 1)].append((probability, outcome))
    return sum(
        len(group) / len(pairs)
        * abs(
            sum(probability for probability, _outcome in group) / len(group)
            - sum(float(outcome) for _probability, outcome in group) / len(group)
        )
        for group in grouped
        if group
    )


def risk_coverage_curve(
    confidences: Sequence[float],
    correct: Sequence[bool],
) -> tuple[RiskCoveragePoint, ...]:
    pairs = _validated_predictions(confidences, correct)
    ordered = sorted(enumerate(pairs), key=lambda row: (-row[1][0], row[0]))
    errors = 0
    points: list[RiskCoveragePoint] = []
    for covered, (_index, (confidence, is_correct)) in enumerate(ordered, start=1):
        errors += int(not is_correct)
        points.append(
            RiskCoveragePoint(
                confidence_threshold=confidence,
                coverage=covered / len(ordered),
                risk=errors / covered,
            )
        )
    return tuple(points)
