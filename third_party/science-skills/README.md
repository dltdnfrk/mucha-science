# Vendored third-party science scripts

Apache License 2.0, Copyright 2026 Google LLC — vendored from
https://github.com/google-deepmind/science-skills (unmodified scripts).

| Skill | Scripts | Used by |
|---|---|---|
| pubmed_database | `scripts/pubmed_api.py` | `src/research/academic/pubmed.py` |
| literature_search_arxiv | `scripts/search_arxiv.py` (+ download helpers) | `src/research/academic/arxiv.py` |
| literature_search_openalex | `openalex_cli.py` | `src/research/academic/openalex.py` |

Each script retains its upstream Apache 2.0 license header. Runtime
dependencies (`polite-http`, `python-dotenv`) are declared in
`pyproject.toml`; scripts run with the project virtualenv, not `uv`.

The scripts interface external data sources (PubMed/NCBI, arXiv, OpenAlex)
whose terms of use apply independently — see upstream
`SKILL_LICENSES.md` at the science-skills repository.
