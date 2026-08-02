# MUNI Research Handoff

> **DRY-LAB SIMULATION RESULTS ONLY - AWAITING WET-LAB VALIDATION; NO LABORATORY OUTCOME IS ESTABLISHED.**

## Study

- Target crop: `cropA`
- Target pathogen: `pathogenX`
- Purpose: synthetic dry-lab prioritization

## Researcher review

- Reviewer: synthetic-researcher-nipo-handoff
- Decision: APPROVED
- Note: Reviewed for downstream wet-lab planning.

## Candidate set

- Kind: `DIAGNOSTIC_DISCOVERY`
- Count: 1

### Candidate 1: `diagnostic-f4ddda76b5d853e22c4d537b`

- Score (ppm): 262904
- Disposition: RANKED
- Rationale and uncertainty:

```json
{
  "rationale": {
    "gate_result_ids": [],
    "objective_evaluations": [
      {
        "gate_result_ids": [],
        "objective_term_id": "detectability",
        "prediction_lineage_ref": null,
        "status": "SCORED",
        "utility_ppm": 394130
      },
      {
        "gate_result_ids": [],
        "objective_term_id": "non_target_avoidance",
        "prediction_lineage_ref": null,
        "status": "SCORED",
        "utility_ppm": 131677
      }
    ],
    "per_objective_utility_ppm": {
      "detectability": 394130,
      "non_target_avoidance": 131677
    },
    "reasons": []
  },
  "uncertainty": {
    "abstention_reasons": [],
    "required_next_evidence": []
  }
}
```

## Collected-data provenance

```json
{
  "collected_data": [
    {
      "digest": "sha256:6fd5a3493c56f81a4dfb0d063d990d35018fec4c03cdec636b10f034c4966c46",
      "job_ref": "muni_collection_job_c397b5828e00fd33c1e83ae8e2ebb819",
      "source_record_ref": "synthetic-record-cropA-pathogenX",
      "source_ref": "synthetic-source-cropA-pathogenX"
    }
  ]
}
```

## Execution lineage

```json
{
  "collection_adapters": [
    {
      "adapter_identity": "synthetic-source-cropA-pathogenX",
      "job_ref": "muni_collection_job_c397b5828e00fd33c1e83ae8e2ebb819"
    }
  ],
  "workflow": {
    "parameters": {
      "query_revision_ids": [
        "query_revision_4e24ea16450563d66401c76ca6ca3962"
      ]
    },
    "run": {
      "finished_at": "2026-08-02T10:54:33.885792Z",
      "kind": "DIAGNOSTIC_DISCOVERY",
      "run_id": "muni_workflow_run_266b20b25407322b2197de7f5f5a5840",
      "started_at": "2026-08-02T10:54:33.884204Z",
      "status": "SUCCEEDED",
      "study_ref": "muni_study_ffb20d2a1d4ee8ecc3e57e37ec78251a"
    },
    "tool_identity": "muni.diagnostic-discovery"
  }
}
```

> **DRY-LAB SIMULATION RESULTS ONLY - AWAITING WET-LAB VALIDATION; NO LABORATORY OUTCOME IS ESTABLISHED.**
