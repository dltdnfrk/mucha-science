mod envelope;
mod messages;
mod validation;

pub use envelope::ScientificEnvelope;
pub use messages::{BackendAction, BackendEvent, BackendMessage, BackendMode};

pub const SCIENTIFIC_PROTOCOL: &str = "muchanipo";
pub const SCIENTIFIC_PROTOCOL_VERSION: &str = "ai-scientist.v1";

const ENVELOPE_FIELDS: [&str; 14] = [
    "protocol",
    "protocol_version",
    "kind",
    "name",
    "message_id",
    "cycle_id",
    "correlation_id",
    "causation_id",
    "sequence",
    "revision",
    "idempotency_key",
    "timestamp",
    "payload",
    "extensions",
];

const V1_ACTIONS: [&str; 20] = [
    "protocol.hello",
    "cycle.start",
    "cycle.replay",
    "cycle.resume",
    "cycle.continue",
    "responsibility.question_selection.disposition",
    "responsibility.safety_ethics_review.disposition",
    "responsibility.execution_accountability.disposition",
    "responsibility.exception_interpretation.disposition",
    "responsibility.novelty_value_judgment.disposition",
    "responsibility.final_accountability.disposition",
    "responsibility.disposition.supersede",
    "proposal.reject",
    "result.submit",
    "validation.adjudicate",
    "export.create",
    "export.get",
    "report.render",
    "cycle.abort",
    "cycle.ack",
];
