import pytest

@pytest.fixture(autouse=True)
def _offline_academic_search(monkeypatch):
    import src.research.academic.sync_search as academic_sync_search

    def _offline_search(query: str, limit: int = 4):
        return []

    monkeypatch.setattr(academic_sync_search, "search", _offline_search)
from src.pipeline.idea_to_council import IdeaToCouncilPipeline
from src.pipeline.stages import Stage
from src.hitl.plannotator_adapter import HITLAdapter
from src.evidence.artifact import EvidenceRef, Finding


class _MockResearchRunner:
    def run(self, plan):
        refs = [
            EvidenceRef(
                id=f"ref-{idx}",
                source_url=f"https://doi.org/10.1234/mock-{idx}",
                source_title=f"Mock source {idx}",
                quote=query,
                source_grade="A",
                provenance={
                    "kind": "mock",
                    "doi": f"10.1234/mock-{idx}",
                    "source": f"https://doi.org/10.1234/mock-{idx}",
                    "source_text": query,
                },
            )
            for idx, query in enumerate(plan.queries[:4], start=1)
        ]
        return [Finding(claim=ref.quote or "", support=[ref], confidence=0.8) for ref in refs]


def test_idea_to_council_pipeline_runs_with_mocks(tmp_path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PROVIDER_CHAIN", "mock")
    result = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_MockResearchRunner(),
        vault_dir=tmp_path / "vault" / "insights",
        council_log_dir=tmp_path / "council",
    ).run("How should muchanipo turn reports into debate agents?")
    assert result.state.stage is Stage.DONE
    assert result.brief.is_ready
    assert result.report.findings
    assert any(agent.name == "mirofish" for agent in result.agents)
    assert result.council.rounds
