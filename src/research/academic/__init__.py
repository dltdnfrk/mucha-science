"""Academic research API backends (DeepMind science-skills CLI-backed)."""
from __future__ import annotations

from .arxiv import get_citations as arxiv_get_citations
from .arxiv import get_paper as arxiv_get_paper
from .arxiv import search as arxiv_search
from .biorxiv import get_citations as biorxiv_get_citations
from .biorxiv import get_paper as biorxiv_get_paper
from .biorxiv import search as biorxiv_search
from .core import CoreClient
from .crossref import CrossRefClient
from .europepmc import get_citations as europepmc_get_citations
from .europepmc import get_paper as europepmc_get_paper
from .europepmc import search as europepmc_search
from .openalex import get_citations as openalex_get_citations
from .openalex import get_paper as openalex_get_paper
from .openalex import search as openalex_search
from .pubmed import get_citations as pubmed_get_citations
from .pubmed import get_paper as pubmed_get_paper
from .pubmed import search as pubmed_search
from .semantic_scholar import SemanticScholarClient
from .unpaywall import UnpaywallClient

__all__ = [
    "CoreClient",
    "CrossRefClient",
    "SemanticScholarClient",
    "UnpaywallClient",
    "arxiv_get_citations",
    "arxiv_get_paper",
    "arxiv_search",
    "biorxiv_get_citations",
    "biorxiv_get_paper",
    "biorxiv_search",
    "europepmc_get_citations",
    "europepmc_get_paper",
    "europepmc_search",
    "openalex_get_citations",
    "openalex_get_paper",
    "openalex_search",
    "pubmed_get_citations",
    "pubmed_get_paper",
    "pubmed_search",
]
