import Foundation

struct ScientificAssessmentFields: Equatable {
    let modelConfidence: JSONValue?
    let evidenceQuality: JSONValue?
    let validationLevel: JSONValue?
    let resultOutcome: JSONValue?
    let support: JSONValue?

    init(payload: JSONValue) { self.init(fields: Self.fields(in: payload)) }
    private init(fields: [String: JSONValue]) { modelConfidence = fields["model_confidence"]; evidenceQuality = fields["evidence_quality"]; validationLevel = fields["validation_level"]; resultOutcome = fields["result_outcome"]; support = fields["support"] }
    func merged(with payload: JSONValue) -> ScientificAssessmentFields { let patch = Self.fields(in: payload); return ScientificAssessmentFields(fields: ["model_confidence": patch["model_confidence"] ?? modelConfidence, "evidence_quality": patch["evidence_quality"] ?? evidenceQuality, "validation_level": patch["validation_level"] ?? validationLevel, "result_outcome": patch["result_outcome"] ?? resultOutcome, "support": patch["support"] ?? support].compactMapValues { $0 }) }
    private static func fields(in payload: JSONValue) -> [String: JSONValue] { guard let object = payload.objectValue else { return [:] }; return object["assessment"]?.objectValue ?? object }
}

struct ScientificState: Equatable {
    fileprivate(set) var cycleID: String?
    fileprivate(set) var lastSequence: Int?
    fileprivate(set) var revision: Int?
    fileprivate(set) var replayNeeded = false
    fileprivate(set) var snapshot: JSONValue?
    fileprivate(set) var stateHash: String?
    fileprivate(set) var checkpoint: JSONValue?
    fileprivate(set) var latestEnvelope: ScientificEnvelope?
    fileprivate(set) var assessmentFields: ScientificAssessmentFields?
    fileprivate(set) var unverifiedAuthorityLabels: [String] = []
    fileprivate(set) var automationMode: JSONValue?
    fileprivate(set) var gates: JSONValue?
    fileprivate(set) var reportStatusOverlay: JSONValue?
    fileprivate(set) var exportState: JSONValue?
    fileprivate(set) var receivedMessageIDs: Set<String> = []
}

enum ScientificReduction: Equatable { case applied, duplicate, invalid, gap(expected: Int, received: Int), stale(last: Int, received: Int), staleRevision(last: Int, received: Int), crossCycle(expected: String, received: String?), snapshotReplaced }

struct ScientificReducer {
    private(set) var state = ScientificState()
    private var replayUntilSequence: Int?

    @discardableResult mutating func reduce(_ envelope: ScientificEnvelope) -> ScientificReduction {
        guard envelope.hasValidInvariants else { return .invalid }
        guard !state.receivedMessageIDs.contains(envelope.messageID) else { return .duplicate }
        if let cycleID = state.cycleID, cycleID != envelope.cycleID { return .crossCycle(expected: cycleID, received: envelope.cycleID) }
        if envelope.kind != "snapshot", let last = state.lastSequence, envelope.sequence <= last { return .stale(last: last, received: envelope.sequence) }
        if envelope.kind != "snapshot", let revision = state.revision, envelope.revision < revision { return .staleRevision(last: revision, received: envelope.revision) }
        if envelope.kind == "snapshot" {
            guard let fields = envelope.payload.objectValue, let checkpoint = fields["checkpoint"], let stateHash = fields["state_hash"], let snapshotState = fields["state"] else { return .invalid }
            state = ScientificState(cycleID: envelope.cycleID, lastSequence: envelope.sequence, revision: envelope.revision, replayNeeded: false, snapshot: snapshotState, stateHash: stateHash.stringValue, checkpoint: checkpoint, latestEnvelope: envelope, assessmentFields: ScientificAssessmentFields(payload: snapshotState), unverifiedAuthorityLabels: authorityLabels(in: snapshotState), automationMode: snapshotState.objectValue?["automation_mode"], gates: snapshotState.objectValue?["gates"], reportStatusOverlay: snapshotState.objectValue?["status_overlay"] ?? snapshotState.objectValue?["report_status_overlay"], exportState: snapshotState.objectValue?["export_state"], receivedMessageIDs: state.receivedMessageIDs.union([envelope.messageID]))
            replayUntilSequence = nil
            return .snapshotReplaced
        }
        if let last = state.lastSequence, envelope.sequence > last + 1 { replayUntilSequence = max(replayUntilSequence ?? envelope.sequence, envelope.sequence); state.replayNeeded = true; return .gap(expected: last + 1, received: envelope.sequence) }
        state.cycleID = envelope.cycleID ?? state.cycleID; state.lastSequence = envelope.sequence; state.revision = max(state.revision ?? envelope.revision, envelope.revision); state.latestEnvelope = envelope
        if envelope.sequence >= (replayUntilSequence ?? envelope.sequence) { replayUntilSequence = nil; state.replayNeeded = false } else { state.replayNeeded = true }
        applyExplicitProjection(envelope.payload)
        if hasAssessmentFields(in: envelope.payload) { state.assessmentFields = state.assessmentFields?.merged(with: envelope.payload) ?? ScientificAssessmentFields(payload: envelope.payload) }
        let labels = authorityLabels(in: envelope.payload); if !labels.isEmpty { state.unverifiedAuthorityLabels = labels }
        state.receivedMessageIDs.insert(envelope.messageID)
        return .applied
    }

    private mutating func applyExplicitProjection(_ payload: JSONValue) {
        guard let fields = payload.objectValue else { return }
        // These are server projections; no event name is treated as a lifecycle transition.
        if let value = fields["automation_mode"] { state.automationMode = value }
        if let value = fields["gates"] { state.gates = value }
        if let value = fields["status_overlay"] ?? fields["report_status_overlay"] { state.reportStatusOverlay = value }
        if let value = fields["export_state"] { state.exportState = value }
        if let value = fields["event_hash"]?.stringValue { state.checkpoint = .object(["cycle_id": state.cycleID.map(JSONValue.string) ?? .null, "sequence": state.lastSequence.map { .number(Double($0)) } ?? .null, "event_hash": .string(value)]) }
    }
    private func authorityLabels(in value: JSONValue) -> [String] { switch value { case .object(let object): return (object["verification_status"]?.stringValue.flatMap { ["operator_asserted_unverified", "external_reference_unverified"].contains($0) ? [$0] : [] } ?? []) + object.values.flatMap(authorityLabels(in:)); case .array(let values): return values.flatMap(authorityLabels(in:)); default: return [] } }
    private func hasAssessmentFields(in payload: JSONValue) -> Bool { let fields = payload.objectValue?["assessment"]?.objectValue ?? payload.objectValue ?? [:]; return ["model_confidence", "evidence_quality", "validation_level", "result_outcome", "support"].contains { fields[$0] != nil } }
}
