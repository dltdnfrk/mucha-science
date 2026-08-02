import { useEffect, useState } from "react";
import {
  collectMuniStudy,
  createMuniHandoff,
  createMuniStudy,
  getMuniCandidates,
  listMuniStudies,
  reviewMuniCandidate,
  runMuniDiagnostic,
  runMuniScreening,
  type MuniCandidateItem,
  type MuniCandidateSet,
  type MuniCollectionJob,
  type MuniHandoff,
  type MuniReview,
  type MuniStudy as Study,
} from "../api/client";

const SCREENING_PURPOSES = [
  "contained-lab reagent",
  "molecular-diagnostic reagent",
  "fungicide/control agent",
  "crop coating agent",
  "other environmental control agent",
];

type BusyAction = "create" | "collection" | "diagnostic" | "screening" | "review" | "handoff";

export default function MuniStudy() {
  const [crop, setCrop] = useState("");
  const [pathogen, setPathogen] = useState("");
  const [purpose, setPurpose] = useState("contained-lab reagent");
  const [screeningPurpose, setScreeningPurpose] = useState(SCREENING_PURPOSES[0]);
  const [studies, setStudies] = useState<Study[]>([]);
  const [study, setStudy] = useState<Study>();
  const [jobs, setJobs] = useState<MuniCollectionJob[]>([]);
  const [candidateSets, setCandidateSets] = useState<MuniCandidateSet[]>([]);
  const [reviewer, setReviewer] = useState("local-researcher");
  const [note, setNote] = useState("Reviewed in the unified local shell.");
  const [decision, setDecision] = useState<MuniReview["decision"]>("APPROVED");
  const [reviews, setReviews] = useState<Record<string, MuniReview>>({});
  const [handoffs, setHandoffs] = useState<Record<string, MuniHandoff>>({});
  const [busy, setBusy] = useState<BusyAction>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    void listMuniStudies().then(setStudies).catch((cause: unknown) => setError(message(cause)));
  }, []);

  async function perform(action: BusyAction, operation: () => Promise<void>) {
    setBusy(action);
    setError(undefined);
    try {
      await operation();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(undefined);
    }
  }

  async function refreshCandidates(studyId = study?.study_id) {
    if (studyId) setCandidateSets(await getMuniCandidates(studyId));
  }

  function selectStudy(selected: Study) {
    setStudy(selected);
    setJobs([]);
    setCandidateSets([]);
    setReviews({});
    setHandoffs({});
    void refreshCandidates(selected.study_id).catch((cause: unknown) => setError(message(cause)));
  }

  return (
    <div className="muni-page">
      <header className="muni-hero">
        <p className="atlas-label">MUNI simulator / DRY-LAB STUDY</p>
        <h1>Target-led discovery, with an explicit review gate.</h1>
        <p>Enter the crop and pathogen exactly as your team names them. Targets are free text and are not matched against a registry.</p>
      </header>

      {error && <div className="muni-alert" role="alert">{error}</div>}

      <section className="muni-panel">
        <div className="muni-section-heading"><span>01</span><div><h2>Study definition</h2><p>Describe the target and intended screening profile.</p></div></div>
        <form className="muni-form" onSubmit={(event) => {
          event.preventDefault();
          void perform("create", async () => {
            const created = await createMuniStudy({ target_crop: crop, target_pathogen: pathogen, purpose });
            setStudies((current) => [...current.filter((item) => item.study_id !== created.study_id), created]);
            selectStudy(created);
          });
        }}>
          <label>Target crop<input required maxLength={256} value={crop} onChange={(event) => setCrop(event.target.value)} placeholder="cropA" /></label>
          <label>Target pathogen<input required maxLength={256} value={pathogen} onChange={(event) => setPathogen(event.target.value)} placeholder="pathogenX" /></label>
          <label className="muni-form-wide">Study purpose<input required maxLength={1024} value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="contained-lab reagent" /></label>
          <button className="muni-primary" disabled={busy === "create"}>{busy === "create" ? "Creating…" : "Create study"}</button>
        </form>
        {studies.length > 0 && <div className="muni-study-list" aria-label="Saved studies">{studies.map((item) => <button key={item.study_id} className={item.study_id === study?.study_id ? "active" : ""} onClick={() => selectStudy(item)}><strong>{item.target_crop}</strong><span>{item.target_pathogen}</span></button>)}</div>}
      </section>

      {study && <>
        <section className="muni-panel">
          <div className="muni-section-heading"><span>02</span><div><h2>Collection jobs</h2><p>Adapters run independently; policy-gated sources remain visible as skipped.</p></div></div>
          <button className="muni-secondary" disabled={busy === "collection"} onClick={() => void perform("collection", async () => {
            setJobs([{ job_id: "pending", study_ref: study.study_id, source_ref: "registered adapters", status: "RUNNING", started_at: new Date().toISOString(), finished_at: null, result_ref: null, reason: null }]);
            setJobs((await collectMuniStudy(study.study_id)).jobs);
          })}>{busy === "collection" ? "Collecting…" : "Run collection"}</button>
          <JobTable jobs={jobs} />
        </section>

        <section className="muni-panel">
          <div className="muni-section-heading"><span>03</span><div><h2>Independent workflows</h2><p>Run either workflow on its own. No action starts both.</p></div></div>
          <div className="muni-workflows">
            <article><p className="atlas-label">DIAGNOSTIC</p><h3>Diagnostic discovery</h3><p>Rank diagnostic candidates from collected evidence.</p><button className="muni-primary" disabled={busy === "diagnostic"} onClick={() => void perform("diagnostic", async () => { await runMuniDiagnostic(study.study_id); await refreshCandidates(); })}>{busy === "diagnostic" ? "Running…" : "Run diagnostic"}</button></article>
            <article><p className="atlas-label">SCREENING</p><h3>Compound screening</h3><p>Choose the application purpose at run time; platform safety constraints are automatic.</p><label>Screening purpose<select value={screeningPurpose} onChange={(event) => setScreeningPurpose(event.target.value)}>{SCREENING_PURPOSES.map((item) => <option key={item}>{item}</option>)}</select></label><button className="muni-primary" disabled={busy === "screening"} onClick={() => void perform("screening", async () => { await runMuniScreening(study.study_id, screeningPurpose); await refreshCandidates(); })}>{busy === "screening" ? "Running…" : "Run screening"}</button></article>
          </div>
        </section>

        <section className="muni-panel">
          <div className="muni-section-heading"><span>04</span><div><h2>Candidates and review</h2><p>Ranked, excluded, and abstained decisions remain separate and reviewable.</p></div></div>
          {candidateSets.length === 0 ? <p className="muni-empty">Run a workflow to produce candidates.</p> : candidateSets.map((set) => <CandidateSetCard key={set.set_id} candidateSet={set} review={reviews[set.set_id]} handoff={reviews[set.set_id] ? handoffs[reviews[set.set_id].review_id] : undefined} reviewer={reviewer} note={note} decision={decision} busy={busy} onReviewer={setReviewer} onNote={setNote} onDecision={setDecision} onReview={() => void perform("review", async () => { const review = await reviewMuniCandidate(set.set_id, { reviewer, decision, note }); setReviews((current) => ({ ...current, [set.set_id]: review })); })} onHandoff={(reviewId) => void perform("handoff", async () => { const handoff = await createMuniHandoff(reviewId); setHandoffs((current) => ({ ...current, [reviewId]: handoff })); })} />)}
        </section>
      </>}
    </div>
  );
}

function JobTable({ jobs }: { jobs: MuniCollectionJob[] }) {
  if (jobs.length === 0) return <p className="muni-empty">Collection has not started.</p>;
  return <div className="muni-table-wrap"><table className="muni-table"><thead><tr><th>Source</th><th>Status</th><th>Result / reason</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id}><td>{job.source_ref}</td><td><Status value={job.status} /></td><td>{job.reason || job.result_ref || "—"}</td></tr>)}</tbody></table></div>;
}

function CandidateSetCard(props: {
  candidateSet: MuniCandidateSet; review?: MuniReview; handoff?: MuniHandoff; reviewer: string; note: string;
  decision: MuniReview["decision"]; busy?: BusyAction; onReviewer: (value: string) => void; onNote: (value: string) => void;
  onDecision: (value: MuniReview["decision"]) => void; onReview: () => void; onHandoff: (reviewId: string) => void;
}) {
  const { candidateSet: set, review, handoff } = props;
  const rows = [["RANKED", set.ranked], ["EXCLUDED", set.excluded], ["ABSTAINED", set.abstained]] as const;
  return <article className="muni-candidate-set"><header><div><p className="atlas-label">{set.kind.replaceAll("_", " ")}</p><h3>{set.set_id}</h3></div><span>{set.ranked.length + set.excluded.length + set.abstained.length} decisions</span></header>
    <div className="muni-table-wrap"><table className="muni-table"><thead><tr><th>Candidate</th><th>Disposition</th><th>Rank</th><th>Score</th><th>Reason</th></tr></thead><tbody>{rows.flatMap(([disposition, items]) => items.map((item, index) => <CandidateRow key={`${disposition}-${item.candidate_id || index}`} item={item} fallbackDisposition={disposition} />))}</tbody></table></div>
    <div className="muni-review"><label>Reviewer<input value={props.reviewer} onChange={(event) => props.onReviewer(event.target.value)} /></label><label>Decision<select value={props.decision} onChange={(event) => props.onDecision(event.target.value as MuniReview["decision"])}><option value="APPROVED">Approved</option><option value="NEEDS_MORE">Needs more</option><option value="REJECTED">Rejected</option></select></label><label className="muni-review-note">Review note<input value={props.note} onChange={(event) => props.onNote(event.target.value)} /></label><button className="muni-secondary" disabled={props.busy === "review"} onClick={props.onReview}>Record review</button>{review && <button className="muni-primary" disabled={review.decision !== "APPROVED" || props.busy === "handoff"} title={review.decision !== "APPROVED" ? "Only approved reviews can be handed off" : undefined} onClick={() => props.onHandoff(review.review_id)}>Create handoff</button>}</div>
    {review && <p className="muni-record">Review: <strong>{review.decision}</strong> · {review.review_id}</p>}{handoff && <div className="muni-handoff"><strong>Handoff created</strong><p>{handoff.disclaimer}</p><ul>{handoff.artifact_paths.map((path) => <li key={path}>{path}</li>)}</ul></div>}
  </article>;
}

function CandidateRow({ item, fallbackDisposition }: { item: MuniCandidateItem; fallbackDisposition: string }) {
  return <tr><td>{item.candidate_id || "unnamed"}</td><td><Status value={item.disposition || fallbackDisposition} /></td><td>{item.rank ?? "—"}</td><td>{item.composite_score_ppm?.toLocaleString() ?? "—"}</td><td>{item.reasons?.join("; ") || "—"}</td></tr>;
}

function Status({ value }: { value: string }) {
  return <span className={`muni-status muni-status--${value.toLowerCase()}`}>{value}</span>;
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : "The MUNI request failed.";
}
