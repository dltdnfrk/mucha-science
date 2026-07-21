import { useState } from "react";
import type { ScientificState } from "../lib/scientificReducer";
import type { ScientificActionName } from "../lib/types";
import type { ScientificEnvelope } from "../lib/tauri";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./ui/card";

const STAGES = [
  ["L", "Scope"],
  ["H", "Hypothesis"],
  ["P", "Plan"],
  ["X", "External result"],
  ["A", "Assessment"],
  ["W", "Write / export"],
] as const;

const RESPONSIBILITY_GATES = [
  "Question and scope are reviewed by the operator.",
  "Hypothesis claims remain attributable to the operator.",
  "Experiment instructions are handed off outside this application.",
  "External results are supplied and accountable to a human source.",
  "Validation and adjudication remain human decisions.",
  "Export is a review package, not an institutional approval.",
] as const;

const VALIDATION_DIMENSIONS = [
  "empirical",
  "methodological",
  "reproducibility",
  "ethical",
] as const;

interface ScientificCycleViewProps {
  state: ScientificState;
  responses: readonly ScientificEnvelope[];
  errors: readonly ScientificEnvelope[];
  actionError?: string;
  startUnavailableReason?: string;
  resetUnavailableReason?: string;
  recoveryUnavailableReason?: string;
  abortUnavailableReason?: string;
  exportUnavailableReason?: string;
  onStart: () => void;
  onReset: () => void;
  onRecover: () => void;
  onAbort: () => void;
  onExport: () => void;
  workflowActions: readonly ScientificActionName[];
  workflowUnavailableReason?: string;
  onWorkflowAction: (name: ScientificActionName, payload: Record<string, unknown>) => void;
}

export function ScientificCycleView({
  state,
  responses,
  errors,
  actionError,
  startUnavailableReason,
  resetUnavailableReason,
  recoveryUnavailableReason,
  abortUnavailableReason,
  exportUnavailableReason,
  onStart,
  onReset,
  onRecover,
  onAbort,
  onExport,
  workflowActions,
  workflowUnavailableReason,
  onWorkflowAction,
}: ScientificCycleViewProps) {
  const [selectedAction, setSelectedAction] = useState<ScientificActionName>("cycle.continue");
  const [actionPayload, setActionPayload] = useState("{}");
  const activeStage = state.stage;
  const validation = state.validation.at(-1);
  const outcome = state.outcome;
  const submitWorkflowAction = () => {
    try {
      const parsed: unknown = JSON.parse(actionPayload);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        return;
      }
      onWorkflowAction(selectedAction, parsed as Record<string, unknown>);
    } catch {
      // Invalid JSON is deliberately not sent to the authoritative server.
    }
  };
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Scientific cycle (beta)</CardTitle>
          <CardDescription>
            Server sequence {state.sequence} · revision {state.revision}. Creator authority is
            asserted and unverified; this is not institutional approval.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div aria-label="Scientific cycle stage timeline" className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            {STAGES.map(([code, label]) => (
              <div
                key={code}
                className={`rounded-md border p-3 text-center text-sm ${
                  activeStage === code ? "border-primary bg-accent" : "border-input"
                }`}
              >
                <div className="font-semibold">{code}</div>
                <div className="text-muted-foreground">{label}</div>
              </div>
            ))}
          </div>
        </CardContent>
        <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
          <span>Current gate: {state.current_gate ?? "not reported"}</span>
          <span>Disposition: {state.disposition ?? "not reported"}</span>
          <span>Automation mode: {state.automation_mode ?? "not reported"}</span>
          <span>Current references: {Object.keys(state.current_refs).length || "not reported"}</span>
        </CardContent>
        <CardFooter className="flex flex-wrap justify-end gap-2">
          <Button
            onClick={onStart}
            disabled={Boolean(startUnavailableReason)}
            title={startUnavailableReason}
          >
            {startUnavailableReason ? "Start cycle (unavailable)" : "Start cycle"}
          </Button>
          <Button
            variant="outline"
            onClick={onReset}
            disabled={Boolean(resetUnavailableReason)}
            title={resetUnavailableReason}
          >
            {resetUnavailableReason ? "New cycle (unavailable)" : "New cycle"}
          </Button>
          <Button
            variant="outline"
            onClick={onRecover}
            disabled={Boolean(recoveryUnavailableReason)}
            title={recoveryUnavailableReason}
          >
            {recoveryUnavailableReason ? "Replay / resume (unavailable)" : "Replay / resume"}
          </Button>
          <Button
            variant="destructive"
            onClick={onAbort}
            disabled={Boolean(abortUnavailableReason)}
            title={abortUnavailableReason}
          >
            {abortUnavailableReason ? "Abort (unavailable)" : "Abort"}
          </Button>
          <Button
            variant="outline"
            onClick={onExport}
            disabled={Boolean(exportUnavailableReason)}
            title={exportUnavailableReason}
          >
            {exportUnavailableReason ? "Export package (unavailable)" : "Export package"}
          </Button>
        </CardFooter>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Responsibility gates</CardTitle>
            <CardDescription>All six gates require human accountability.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="space-y-3 text-sm">
              {RESPONSIBILITY_GATES.map((gate, index) => (
                <li key={gate} className="flex gap-3">
                  <span className="font-semibold">{index + 1}.</span>
                  <span>{gate}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Orthogonal validation</CardTitle>
            <CardDescription>
              V-level is separate from confidence and outcome. Validation states are server-reported.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {VALIDATION_DIMENSIONS.map((dimension) => (
              <div key={dimension} className="flex justify-between border-b border-input pb-2">
                <span className="capitalize">{dimension}</span>
                <span>{validation?.[dimension] ?? "not reported"}</span>
              </div>
            ))}
            <div className="flex justify-between border-b border-input pb-2">
              <span>V-level</span>
              <span>{state.v_level ?? "not reported"}</span>
            </div>
            <div className="flex justify-between border-b border-input pb-2">
              <span>Confidence</span>
              <span>{state.confidence ?? "not reported"}</span>
            </div>
            <div className="flex justify-between">
              <span>Outcome</span>
              <span>{outcome ?? "not reported"}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Authoritative workflow action</CardTitle>
          <CardDescription>
            Select an advertised action and provide its exact server-contract JSON. The server owns
            lifecycle legality, gates, current references, and revision checks.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <select
            aria-label="Scientific workflow action"
            className="w-full rounded-md border border-input bg-background p-2 text-sm"
            value={selectedAction}
            onChange={(event) => setSelectedAction(event.target.value as ScientificActionName)}
          >
            {workflowActions.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <textarea
            aria-label="Scientific workflow action payload"
            className="min-h-32 w-full rounded-md border border-input bg-background p-2 font-mono text-xs"
            value={actionPayload}
            onChange={(event) => setActionPayload(event.target.value)}
          />
          <Button
            onClick={submitWorkflowAction}
            disabled={Boolean(workflowUnavailableReason) || workflowActions.length === 0}
            title={workflowUnavailableReason}
          >
            Submit server-validated action
          </Button>
          <p className="text-xs text-muted-foreground">
            Physical execution is external-only. Submitted results must reference already staged IDs;
            this client cannot verify authority, results, or physical work.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>External-result boundary</CardTitle>
          <CardDescription>
            This client generates hypotheses and packages work for external experiments. It does not
            execute physical work, control instruments, or verify external results on its own.
          </CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Diagnostics and recovery</CardTitle>
          <CardDescription>
            {state.recovery
              ? `Replay needed: ${state.recovery.kind} from ${
                  state.recovery.kind === "replay"
                    ? `sequence ${state.recovery.after_sequence}`
                    : `revision ${state.recovery.at_revision}`
                }.`
              : "No reducer recovery request."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {state.diagnostics.length === 0 ? (
            <p>No reducer diagnostics.</p>
          ) : (
            <ul className="space-y-2">
              {state.diagnostics.map((diagnostic, index) => (
                <li key={`${diagnostic.message_id}-${diagnostic.kind}-${index}`}>
                  {diagnostic.kind}: {diagnostic.detail}
                </li>
              ))}
            </ul>
          )}
          {actionError && <p className="text-destructive">{actionError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Raw protocol limitations</CardTitle>
          <CardDescription>
            Responses and errors are retained without lifecycle inference. Unknown server events remain
            available to the reducer as raw protocol data.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>{state.unsupported_events.length} unsupported event(s) retained.</p>
          <p>{responses.length} raw response(s) and {errors.length} raw error(s) retained.</p>
          <details>
            <summary className="cursor-pointer">Show raw messages</summary>
            <pre className="mt-3 overflow-auto rounded-md border border-input p-3 text-xs">
              {JSON.stringify({ responses, errors }, null, 2)}
            </pre>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}

