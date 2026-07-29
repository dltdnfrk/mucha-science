# Research quality benchmark

## Scope and reproducibility contract

This package provides a small deterministic baseline for testing research
retrieval and evidence evaluation. The versioned gold fixture is
`tests/fixtures/research_quality_benchmark.v1.json`; its `schema_version` must
change when the fixture meaning or expected values change. Tests use no network,
clock, randomness, model, or API key.

The runtime integration point is `WebResearchRunner._gather` in
`src/research/runner.py`. Each enabled backend's filtered return order is treated
as that backend's ranking. Rankings are fused before `per_query_cap` is applied.
Raw provider scores remain available for source grading, while `canonical_id`,
`rrf_score`, and ordered `rrf_contributions` (`provider`, `rank`) are recorded in
evidence provenance for audit.

## Retrieval and deduplication

Reciprocal Rank Fusion uses the fixed constant `k = 60`:

`RRF(d) = sum(1 / (60 + rank(provider, d)))`.

DOIs are stripped of common resolver prefixes, trimmed, and case-folded.
Deduplication uses this normalized DOI first. If no DOI is present, a normalized
stable paper ID is used. Duplicate occurrences within one provider contribute
only their first rank. Output ordering is deterministic by fused score
descending, best source priority, then paper ID. Source priority is the order of
provider rankings supplied by the runtime.

The retrieval API reports:

- `recall_at_k`: unique relevant documents retrieved in the first `k`, divided
  by the number of judged relevant documents.
- `mean_reciprocal_rank`: mean inverse rank of the first relevant result across
  aligned query runs.
- `ndcg_at_k`: exponential graded gain (`2^relevance - 1`) with logarithmic
  discount, normalized by the ideal ranking.

The fixture pins Recall@5, Recall@10, MRR, and nDCG@10 values independently of
the implementation. These measurements describe a judged pool; unjudged
documents are treated as non-relevant.

## Claim/evidence and evidence spans

The labels are `SUPPORTS`, `REFUTES`, and `INSUFFICIENT_EVIDENCE`. The baseline
requires substantial lexical overlap and shared entity-like tokens. It only
returns `REFUTES` for explicit negation mismatch or opposing increase/decrease
direction with a shared numeric value. Ambiguity markers cause abstention.

This is an English-pattern, conservative lexical baseline. It is **not semantic
entailment**, cannot establish scientific truth, and is not adequate for Korean
claims. In particular, it does not resolve coreference, units, populations,
study design, causal qualification, paraphrases outside its small direction
lexicon, or contradictions without explicit numeric/negation cues. Production
decisions require domain-aware adjudication or a separately validated
multilingual entailment system; uncertain cases must remain
`INSUFFICIENT_EVIDENCE`.

Evidence-span F1 lowercases and tokenizes both spans, then computes multiset
token precision/recall. Two empty spans score 1, one empty span scores 0, and
repeated tokens receive multiplicity-aware partial credit. This is a boundary
metric, not a factuality metric.

## Calibration and selective prediction

`brier_score` is the mean binary squared probability error. ECE uses
equal-width bins over `[0, 1]`, includes probability 1 in the final bin, and
weights each non-empty bin's absolute confidence/accuracy gap by its sample
fraction. ECE is sensitive to bin count and sample size and should always be
reported with both.

`risk_coverage_curve` sorts examples by confidence descending with original
input order as the tie-break. Every prefix reports coverage and empirical error
risk. It measures the quality/coverage trade-off; it does not choose an
operational threshold.

## Known limitations

- The fixture is deliberately small and synthetic. It is a regression gold
  fixture, not evidence of external validity or model quality.
- DOI normalization does not query registries or infer missing DOIs. Incorrect
  provider metadata can still merge or split records incorrectly.
- Stable-ID fallback only deduplicates providers that expose the same canonical
  ID; title-only near duplicates are not merged.
- RRF ignores score magnitudes and assumes each provider supplies a meaningful
  rank order. Source priority affects exact ties.
- Recall and nDCG are bounded by judgment completeness. Calibration estimates
  need substantially larger held-out samples before scientific interpretation.
- Claim labels and span F1 evaluate local text behavior only. They do not verify
  source integrity, publication status, statistical validity, or claim
  generalizability.

## Primary references

- Cormack, G. V., Clarke, C. L. A., & Büttcher, S. (2009).
  *Reciprocal rank fusion outperforms Condorcet and individual rank learning
  methods*. SIGIR 2009. DOI:
  [10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114).
- Järvelin, K., & Kekäläinen, J. (2002). *Cumulated gain-based evaluation of IR
  techniques*. ACM Transactions on Information Systems, 20(4), 422–446. DOI:
  [10.1145/582415.582418](https://doi.org/10.1145/582415.582418).
- Brier, G. W. (1950). *Verification of forecasts expressed in terms of
  probability*. Monthly Weather Review, 78(1), 1–3. DOI:
  [10.1175/1520-0493(1950)078<0001:VOFEIT>2.0.CO;2](https://doi.org/10.1175/1520-0493%281950%29078%3C0001%3AVOFEIT%3E2.0.CO%3B2).
- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017).
  [*On calibration of modern neural networks*](https://proceedings.mlr.press/v70/guo17a.html).
  ICML 2017, PMLR 70, 1321–1330.
- El-Yaniv, R., & Wiener, Y. (2010).
  [*On the foundations of noise-free selective classification*](https://jmlr.org/papers/v11/el-yaniv10a.html).
  JMLR, 11(53), 1605–1641.
- Thorne, J., Vlachos, A., Christodoulopoulos, C., & Mittal, A. (2018).
  [*FEVER: a large-scale dataset for Fact Extraction and VERification*](https://aclanthology.org/N18-1074/).
  DOI: [10.18653/v1/N18-1074](https://doi.org/10.18653/v1/N18-1074).
- Wadden, D., et al. (2020).
  [*Fact or Fiction: Verifying Scientific Claims*](https://aclanthology.org/2020.emnlp-main.609/).
  DOI:
  [10.18653/v1/2020.emnlp-main.609](https://doi.org/10.18653/v1/2020.emnlp-main.609).
- Gao, T., Yen, H., Yu, J., & Chen, D. (2023).
  [*Enabling Large Language Models to Generate Text with Citations*](https://aclanthology.org/2023.emnlp-main.398/).
  DOI:
  [10.18653/v1/2023.emnlp-main.398](https://doi.org/10.18653/v1/2023.emnlp-main.398).
