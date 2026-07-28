import type { SourceConnection } from "./sourceConnections";

const DEFAULT_SOURCE_CONNECTIONS: readonly SourceConnection[] = [
  {
    id: "openalex",
    name: "OpenAlex",
    url: "https://api.openalex.org",
    description: "공개 학술 메타데이터와 연구 성과",
    status: "disconnected",
    access: { kind: "open" },
  },
  {
    id: "crossref",
    name: "Crossref",
    url: "https://api.crossref.org",
    description: "DOI와 학술 출판물 메타데이터",
    status: "disconnected",
    access: { kind: "open" },
  },
  {
    id: "pubmed-ncbi",
    name: "PubMed/NCBI",
    url: "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    description: "생의학 문헌과 인용 메타데이터",
    status: "disconnected",
    access: { kind: "open" },
  },
  {
    id: "semantic-scholar",
    name: "Semantic Scholar",
    url: "https://api.semanticscholar.org/graph/v1",
    description: "의미 기반 학술 그래프와 인용 데이터",
    status: "disconnected",
    access: { kind: "api-key" },
  },
  {
    id: "springer-nature",
    name: "Springer Nature",
    url: "https://api.springernature.com/meta/v2/json",
    description: "출판물 메타데이터",
    status: "disconnected",
    access: { kind: "api-key" },
  },
  {
    id: "elsevier",
    name: "Elsevier",
    url: "https://api.elsevier.com/content/search/sciencedirect",
    description: "Elsevier 및 ScienceDirect 검색",
    status: "disconnected",
    access: { kind: "api-key" },
  },
  {
    id: "oasis",
    name: "OASIS",
    url: "https://www.oasis-brains.org",
    description: "공개 신경영상 연구 데이터셋",
    status: "disconnected",
    access: { kind: "custom" },
  },
];

export function getDefaultSourceConnections(): readonly SourceConnection[] {
  return DEFAULT_SOURCE_CONNECTIONS.map((source) => ({
    id: source.id,
    name: source.name,
    url: source.url,
    status: source.status,
    access: { kind: source.access.kind },
    ...(source.description === undefined ? {} : { description: source.description }),
  }));
}
