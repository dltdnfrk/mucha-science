import {
  FolioSection,
  ProtocolRuler,
  ResearchMasthead,
  RuleButton,
} from "../components/ai-scientist/AiScientistPrimitives";

export function DesignSystemShowcase() {
  return (
    <div className="ms-surface" data-design-system-showcase>
      <div className="ms-sheet">
        <ResearchMasthead
          cycleLabel="Cycle 07"
          utility={<a className="ms-text-link" href="#/scientific">Open workspace</a>}
        />
        <ProtocolRuler current="Evidence" />

        <main className="ms-showcase">
          <header className="ms-showcase__intro">
            <p className="ms-kicker">Primitive showcase / 01</p>
            <h1>Instrumented research folio</h1>
            <p>
              Rules, numbering, alignment, and annotation carry the hierarchy before
              weight or type size does.
            </p>
          </header>

          <div className="ms-showcase__grid">
            <FolioSection
              kicker="Question"
              title="Ruled field"
              description="Default, focus, disabled, and error"
            >
              <div className="ms-field-stack">
                <label htmlFor="showcase-question">Scientific question</label>
                <textarea
                  id="showcase-question"
                  defaultValue="Does the intervention change the measured outcome independently of the known confounder?"
                  rows={3}
                />
                <p>Write one falsifiable question. Keep the outcome measurable.</p>
              </div>

              <div className="ms-field-stack">
                <label htmlFor="showcase-disabled">Disabled after cycle start</label>
                <input
                  disabled
                  id="showcase-disabled"
                  value="Question locked by the active cycle"
                  readOnly
                />
              </div>

              <div className="ms-field-stack is-error">
                <label htmlFor="showcase-error">Error state</label>
                <input
                  aria-describedby="showcase-error-message"
                  aria-invalid="true"
                  id="showcase-error"
                  value=""
                  readOnly
                />
                <p id="showcase-error-message" role="alert">
                  Add a measurable outcome before starting the cycle.
                </p>
              </div>
            </FolioSection>

            <FolioSection
              kicker="Evidence"
              title="Evidence row"
              description="Source, claim, method, result"
              variant="evidence"
            >
              <dl className="ms-evidence-row">
                <div><dt>Source</dt><dd>Study E-07-01</dd></div>
                <div><dt>Claim</dt><dd>Primary outcome changed</dd></div>
                <div><dt>Method</dt><dd>Randomized, blinded</dd></div>
                <div><dt>Result</dt><dd>Awaiting external result</dd></div>
              </dl>
              <div className="ms-empty-state">
                <span aria-hidden="true">∅</span>
                <p>No evidence has been added. External results stay outside this application.</p>
              </div>
            </FolioSection>

            <FolioSection
              kicker="Controls"
              title="Rule buttons"
              description="All required interaction states"
              variant="verdict"
            >
              <div className="ms-button-cluster">
                <RuleButton variant="primary">Start cycle</RuleButton>
                <RuleButton>Accept</RuleButton>
                <RuleButton variant="text">Next cycle</RuleButton>
                <RuleButton variant="destructive">Reject</RuleButton>
                <RuleButton disabled title="Evidence is required">Disabled</RuleButton>
                <RuleButton loading>Working</RuleButton>
              </div>
            </FolioSection>

            <FolioSection
              kicker="Diagnostics"
              title="Annotation and recovery"
              description="Secondary, never the visual center"
              variant="diagnostics"
            >
              <div className="ms-diagnostic-lines">
                <p><span>Revision</span><strong>0007</strong></p>
                <p><span>Recovery</span><strong>Not requested</strong></p>
                <p><span>Protocol</span><strong>ai-scientist.v1</strong></p>
              </div>
            </FolioSection>
          </div>
        </main>
      </div>
    </div>
  );
}
