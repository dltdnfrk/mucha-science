import Foundation

enum BackendEvent: Decodable, Equatable {
    case phaseChange(phase: String, data: JSONValue?)
    case interviewQuestion(InterviewQuestion)
    case councilRoundStart(round: Int, layer: String?)
    case councilPersonaToken(persona: String, delta: String)
    case councilRoundDone(round: Int, score: Int?)
    case reportChunk(section: String?, markdown: String)
    case done(reportPath: String?)
    case error(message: String)
    case unknown(name: String, payload: JSONValue)
}

struct InterviewQuestion: Decodable, Equatable {
    let qID: String
    let text: String
    let options: [InterviewOption]

    private enum CodingKeys: String, CodingKey { case qID = "q_id", text, options }
}

struct InterviewOption: Decodable, Equatable {
    let id: String?
    let label: String?
    let text: String?
    let value: String?
}

enum JSONValue: Codable, Equatable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var objectValue: [String: JSONValue]? { if case .object(let value) = self { return value }; return nil }
    var stringValue: String? { if case .string(let value) = self { return value }; return nil }
    var integerValue: Int? {
        guard case .number(let value) = self, value.rounded() == value, value >= 0 else { return nil }
        return Int(exactly: value)
    }
}

enum ScientificProtocolCatalog {
    static let actions: Set<String> = [
        "protocol.hello", "cycle.start", "cycle.replay", "cycle.resume", "cycle.continue",
        "proposal.reject", "result.submit", "validation.adjudicate", "export.create", "export.get",
        "report.render", "cycle.abort", "cycle.ack", "responsibility.disposition.supersede",
        "responsibility.question_selection.disposition", "responsibility.safety_ethics_review.disposition",
        "responsibility.execution_accountability.disposition", "responsibility.exception_interpretation.disposition",
        "responsibility.novelty_value_judgment.disposition", "responsibility.final_accountability.disposition"
    ]
    static let events: Set<String> = [
        "cycle.started", "cycle.continued", "cycle.completed", "responsibility.disposition.recorded",
        "responsibility.disposition.superseded", "proposal.rejected", "result.recorded",
        "validation.assessment.recorded", "validation.assessment.transitioned", "export.created", "cycle.aborted"
    ]
    static let responses: Set<String> = [
        "protocol.welcome.response", "command.accepted.response", "cycle.replay.response",
        "cycle.resume.response", "export.get.response", "report.render.response", "cycle.acknowledged.response"
    ]
    static let errors: Set<String> = ["command.rejected.error", "protocol.invalid.error"]
    static let diagnostics: Set<String> = ["snapshot.repair_required"]
    static let mutations: Set<String> = [
        "cycle.start", "cycle.continue", "proposal.reject", "result.submit", "validation.adjudicate",
        "export.create", "cycle.abort", "responsibility.disposition.supersede",
        "responsibility.question_selection.disposition", "responsibility.safety_ethics_review.disposition",
        "responsibility.execution_accountability.disposition", "responsibility.exception_interpretation.disposition",
        "responsibility.novelty_value_judgment.disposition", "responsibility.final_accountability.disposition"
    ]
    static let reads: Set<String> = ["cycle.replay", "cycle.resume", "export.get", "report.render", "cycle.ack"]
}

struct ScientificEnvelope: Codable, Equatable {
    static let protocolName = "muchanipo"
    static let protocolVersion = "ai-scientist.v1"
    static let maximumSafeInteger = 9_007_199_254_740_991

    let protocolName: String
    let protocolVersion: String
    let kind: String
    let name: String
    let messageID: String
    let cycleID: String?
    let correlationID: String?
    let causationID: String?
    let sequence: Int
    let revision: Int
    let idempotencyKey: String?
    let timestamp: String
    let payload: JSONValue
    let extensions: [String: JSONValue]

    init(kind: String, name: String, messageID: String, cycleID: String? = nil, correlationID: String? = nil, causationID: String? = nil, sequence: Int = 0, revision: Int = 0, idempotencyKey: String? = nil, timestamp: String, payload: JSONValue = .object([:]), extensions: [String: JSONValue] = [:]) {
        self.protocolName = Self.protocolName; self.protocolVersion = Self.protocolVersion
        self.kind = kind; self.name = name; self.messageID = messageID; self.cycleID = cycleID
        self.correlationID = correlationID; self.causationID = causationID; self.sequence = sequence
        self.revision = revision; self.idempotencyKey = idempotencyKey; self.timestamp = timestamp
        self.payload = payload; self.extensions = extensions
    }

    private enum CodingKeys: String, CodingKey {
        case protocolName = "protocol", protocolVersion = "protocol_version", kind, name
        case messageID = "message_id", cycleID = "cycle_id", correlationID = "correlation_id"
        case causationID = "causation_id", sequence, revision, idempotencyKey = "idempotency_key"
        case timestamp, payload, extensions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let protocolName = try c.decode(String.self, forKey: .protocolName)
        let protocolVersion = try c.decode(String.self, forKey: .protocolVersion)
        let kind = try c.decode(String.self, forKey: .kind); let name = try c.decode(String.self, forKey: .name)
        let messageID = try c.decode(String.self, forKey: .messageID)
        let cycleID = try c.decodeIfPresent(String.self, forKey: .cycleID)
        let correlationID = try c.decodeIfPresent(String.self, forKey: .correlationID)
        let causationID = try c.decodeIfPresent(String.self, forKey: .causationID)
        let sequence = try c.decode(Int.self, forKey: .sequence); let revision = try c.decode(Int.self, forKey: .revision)
        let idempotencyKey = try c.decodeIfPresent(String.self, forKey: .idempotencyKey)
        let timestamp = try c.decode(String.self, forKey: .timestamp)
        let payload = try c.decode(JSONValue.self, forKey: .payload)
        let extensions = try c.decode([String: JSONValue].self, forKey: .extensions)
        guard Self.isValid(protocolName: protocolName, protocolVersion: protocolVersion, kind: kind, name: name, messageID: messageID, cycleID: cycleID, correlationID: correlationID, causationID: causationID, sequence: sequence, revision: revision, idempotencyKey: idempotencyKey, timestamp: timestamp, payload: payload) else {
            throw DecodingError.dataCorruptedError(forKey: .protocolName, in: c, debugDescription: "Invalid scientific protocol envelope.")
        }
        self.protocolName = protocolName; self.protocolVersion = protocolVersion; self.kind = kind; self.name = name
        self.messageID = messageID; self.cycleID = cycleID; self.correlationID = correlationID; self.causationID = causationID
        self.sequence = sequence; self.revision = revision; self.idempotencyKey = idempotencyKey; self.timestamp = timestamp
        self.payload = payload; self.extensions = extensions
    }

    var hasValidCommonInvariants: Bool {
        Self.isValidCommon(protocolName: protocolName, protocolVersion: protocolVersion, messageID: messageID, cycleID: cycleID, correlationID: correlationID, causationID: causationID, sequence: sequence, revision: revision, idempotencyKey: idempotencyKey, timestamp: timestamp, payload: payload)
    }
    var hasValidInvariants: Bool {
        Self.isValid(protocolName: protocolName, protocolVersion: protocolVersion, kind: kind, name: name, messageID: messageID, cycleID: cycleID, correlationID: correlationID, causationID: causationID, sequence: sequence, revision: revision, idempotencyKey: idempotencyKey, timestamp: timestamp, payload: payload)
    }

    static func isProtocolID(_ value: String) -> Bool { value.range(of: "^[a-z][a-z0-9_]*_[0-9a-f]{32}$", options: .regularExpression) != nil }
    static func isDigest(_ value: String) -> Bool { value.range(of: "^sha256:[0-9a-f]{64}$", options: .regularExpression) != nil }

    private static func isValidCommon(protocolName: String, protocolVersion: String, messageID: String, cycleID: String?, correlationID: String?, causationID: String?, sequence: Int, revision: Int, idempotencyKey: String?, timestamp: String, payload: JSONValue) -> Bool {
        protocolName == Self.protocolName && protocolVersion == Self.protocolVersion && isProtocolID(messageID)
            && [cycleID, correlationID, causationID].allSatisfy { $0 == nil || isProtocolID($0!) }
            && sequence >= 0 && sequence <= maximumSafeInteger && revision >= 0 && revision <= maximumSafeInteger
            && (idempotencyKey == nil || !idempotencyKey!.isEmpty) && isTimestamp(timestamp) && payload.objectValue != nil
    }

    private static func isValid(protocolName: String, protocolVersion: String, kind: String, name: String, messageID: String, cycleID: String?, correlationID: String?, causationID: String?, sequence: Int, revision: Int, idempotencyKey: String?, timestamp: String, payload: JSONValue) -> Bool {
        guard isValidCommon(protocolName: protocolName, protocolVersion: protocolVersion, messageID: messageID, cycleID: cycleID, correlationID: correlationID, causationID: causationID, sequence: sequence, revision: revision, idempotencyKey: idempotencyKey, timestamp: timestamp, payload: payload) else { return false }
        let fields = payload.objectValue!
        switch kind {
        case "action":
            guard ScientificProtocolCatalog.actions.contains(name), correlationID == messageID, causationID == nil, sequence == 0, revision == 0 else { return false }
            if name == "protocol.hello" { return cycleID == nil && idempotencyKey != nil && isHelloPayload(fields, idempotencyKey: idempotencyKey!) }
            if name == "cycle.start" {
                return cycleID == nil && idempotencyKey != nil && fields["expected_revision"]?.integerValue == 0
            }
            guard cycleID != nil else { return false }
            if ScientificProtocolCatalog.mutations.contains(name) { return idempotencyKey != nil && fields["expected_revision"]?.integerValue != nil }
            return ScientificProtocolCatalog.reads.contains(name) && idempotencyKey == nil && isReadPayload(name, fields)
        case "event":
            return ScientificProtocolCatalog.events.contains(name)
                && cycleID != nil && correlationID != nil && causationID != nil && idempotencyKey == nil
                && isEventPayload(name, fields)
        case "response":
            return ScientificProtocolCatalog.responses.contains(name)
                && correlationID != nil && causationID != nil && idempotencyKey == nil
                && isResponsePayload(name, fields)
        case "error":
            return ScientificProtocolCatalog.errors.contains(name)
                && correlationID != nil && causationID != nil && idempotencyKey == nil
                && isErrorPayload(fields)
        case "snapshot": return name == "cycle.snapshot" && cycleID != nil && correlationID != nil && causationID != nil && idempotencyKey == nil && isSnapshotPayload(fields)
        case "diagnostic":
            return ScientificProtocolCatalog.diagnostics.contains(name)
                && cycleID != nil && idempotencyKey == nil && isDiagnosticPayload(name, fields)
        default: return false
        }
    }

    private static func isHelloPayload(_ fields: [String: JSONValue], idempotencyKey: String) -> Bool {
        guard Set(fields.keys) == ["handshake_idempotency_key", "client_instance_id", "supported_versions", "capabilities", "projection", "cursors"], fields["handshake_idempotency_key"]?.stringValue == idempotencyKey, let client = fields["client_instance_id"]?.stringValue, isProtocolID(client), case .array(let versions)? = fields["supported_versions"], versions.contains(.string(protocolVersion)), case .array(let capabilities)? = fields["capabilities"], capabilities.allSatisfy({ $0.stringValue != nil }), fields["projection"]?.stringValue != nil, case .array(let cursors)? = fields["cursors"] else { return false }
        return cursors.allSatisfy { cursor in validCursor(cursor.objectValue) }
    }
    private static func isReadPayload(_ name: String, _ fields: [String: JSONValue]) -> Bool {
        switch name {
        case "cycle.replay": return fields["client_instance_id"]?.stringValue.map(isProtocolID) == true && fields["request_ordinal"]?.integerValue != nil && validCursor(fields["cursor"]?.objectValue) && fields["max_events"]?.integerValue != nil
        case "cycle.resume": return fields["client_instance_id"]?.stringValue.map(isProtocolID) == true && fields["request_ordinal"]?.integerValue != nil && validCursor(fields["cursor"]?.objectValue) && fields["projection"]?.stringValue != nil
        case "export.get", "report.render": return fields["client_instance_id"]?.stringValue.map(isProtocolID) == true && fields["request_ordinal"]?.integerValue != nil
        case "cycle.ack": return fields["client_instance_id"]?.stringValue.map(isProtocolID) == true && fields["ack_ordinal"]?.integerValue != nil && validCheckpoint(fields["checkpoint"]?.objectValue) && fields["state_hash"]?.stringValue.map(isDigest) == true
        default: return false
        }
    }
    private static func isEventPayload(_ name: String, _ fields: [String: JSONValue]) -> Bool {
        let common = Set(["created_records", "superseded_record_ids", "derived_current_refs"])
        let required: Set<String>
        switch name {
        case "cycle.started": required = Set(["normalized_question", "contract_version", "created_records"])
        case "cycle.continued": required = common.union(["operation"])
        case "cycle.completed": required = Set(["report_body_id", "report_body_hash", "final_accountability_disposition_id", "responsibility_statuses"])
        case "responsibility.disposition.recorded": required = Set(["responsibility", "requirement_id", "disposition_id", "created_records", "derived_current_refs"])
        case "responsibility.disposition.superseded": required = common.union(["responsibility", "old_requirement_id", "new_requirement_id", "superseded_disposition_id", "replacement_disposition_id"])
        case "proposal.rejected": required = common.union(["proposal_id", "proposal_hash", "rejection_record_id", "recoverable"])
        case "result.recorded": required = common.union(["proposal_id", "proposal_hash", "result_id", "result_hash", "external_stage_id", "supersedes_result_id"])
        case "validation.assessment.recorded": required = common.union(["assessment_id", "claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids", "validation_policy_id", "validation_policy_version", "validation_policy_reference", "claim_support_changes"])
        case "validation.assessment.transitioned": required = common.union(["assessment_id", "transition_id", "from_state", "to_state", "claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids", "validation_policy_id", "validation_policy_version", "validation_policy_reference", "claim_support_changes"])
        case "export.created": required = Set(["export_id", "manifest_hash", "archive_blob_id", "archive_hash", "byte_length", "created_records"])
        case "cycle.aborted": required = Set(["actor", "reason", "final_observation", "aborted_at"])
        default: return false
        }
        return Set(fields.keys) == required
    }
    private static func isResponsePayload(_ name: String, _ fields: [String: JSONValue]) -> Bool {
        guard fields["request_message_id"]?.stringValue.map(isProtocolID) == true else { return false }
        switch name {
        case "protocol.welcome.response":
            return Set(fields.keys) == ["request_message_id", "selected_version", "connection_id", "server_instance_id", "capabilities", "operation_modes", "accepted_cursors"]
                && fields["selected_version"] == .string(protocolVersion)
                && fields["connection_id"]?.stringValue.map(isProtocolID) == true
                && fields["server_instance_id"]?.stringValue.map(isProtocolID) == true
                && {
                    if case .array(let capabilities)? = fields["capabilities"] {
                        return capabilities.allSatisfy { $0.stringValue != nil }
                    }
                    return false
                }()
                && {
                    if case .array(let modes)? = fields["operation_modes"] {
                        return !modes.isEmpty && modes.allSatisfy {
                            $0 == .string("normal") || $0 == .string("read_only")
                        }
                    }
                    return false
                }()
                && {
                    if case .array(let cursors)? = fields["accepted_cursors"] {
                        return cursors.allSatisfy { validCursor($0.objectValue) }
                    }
                    return false
                }()
        case "command.accepted.response":
            return Set(fields.keys) == ["request_message_id", "command_name", "cycle_id", "sequence", "revision", "result"]
                && fields["command_name"]?.stringValue != nil && fields["result"]?.objectValue != nil
                && fields["sequence"]?.integerValue != nil && fields["revision"]?.integerValue != nil
        case "cycle.resume.response":
            return Set(fields.keys) == ["request_message_id", "cycle_id", "snapshot", "events", "to_cursor", "current_revision"]
                && fields["snapshot"]?.objectValue != nil && fields["events"] != nil && validCursor(fields["to_cursor"]?.objectValue) && fields["current_revision"]?.integerValue != nil
        case "cycle.replay.response":
            return Set(fields.keys) == ["request_message_id", "cycle_id", "from_cursor", "to_cursor", "events", "has_more"]
                && validCursor(fields["from_cursor"]?.objectValue) && validCursor(fields["to_cursor"]?.objectValue) && fields["events"] != nil && {
                    if case .bool = fields["has_more"] { return true }
                    return false
                }()
        case "export.get.response":
            return Set(fields.keys) == ["request_message_id", "export_id", "manifest", "archive_hash", "byte_length", "archive_base64"]
        case "report.render.response":
            return Set(fields.keys) == ["request_message_id", "cycle_id", "at_revision", "format", "body_utf8_or_json", "body_hash", "status_overlay"]
        case "cycle.acknowledged.response":
            return Set(fields.keys) == ["request_message_id", "checkpoint", "state_hash", "accepted"]
                && validCheckpoint(fields["checkpoint"]?.objectValue) && fields["state_hash"]?.stringValue.map(isDigest) == true && fields["accepted"] == .bool(true)
        default: return false
        }
    }
    private static func isErrorPayload(_ fields: [String: JSONValue]) -> Bool {
        Set(fields.keys) == ["stable_code", "message", "details", "retryability", "outcome"]
            && fields["stable_code"]?.stringValue != nil && fields["message"]?.stringValue != nil
            && fields["details"]?.objectValue != nil && fields["retryability"]?.objectValue == nil && fields["outcome"]?.stringValue != nil
    }
    private static func isDiagnosticPayload(_ name: String, _ fields: [String: JSONValue]) -> Bool {
        name == "snapshot.repair_required"
            && Set(fields.keys) == ["cycle_id", "committed_sequence", "reason"]
            && fields["cycle_id"]?.stringValue.map(isProtocolID) == true
            && fields["committed_sequence"]?.integerValue != nil && fields["reason"]?.stringValue != nil
    }
    private static func isSnapshotPayload(_ fields: [String: JSONValue]) -> Bool {
        fields["request_message_id"]?.stringValue.map(isProtocolID) == true && ["initial", "cursor_mismatch", "recovery"].contains(fields["reason"]?.stringValue ?? "") && validCheckpoint(fields["checkpoint"]?.objectValue) && fields["state_hash"]?.stringValue.map(isDigest) == true && fields["state"]?.objectValue != nil
    }
    static func validCursor(_ value: [String: JSONValue]?) -> Bool { guard let value else { return false }; return Set(value.keys) == ["cycle_id", "sequence", "event_hash"] && value["cycle_id"]?.stringValue.map(isProtocolID) == true && value["sequence"]?.integerValue != nil && value["event_hash"]?.stringValue.map(isDigest) == true }
    static func validCheckpoint(_ value: [String: JSONValue]?) -> Bool { validCursor(value) }

    private static func isTimestamp(_ value: String) -> Bool {
        guard value.range(of: "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$", options: .regularExpression) != nil else { return false }
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) != nil
    }
}

extension BackendEvent {
    private enum CodingKeys: String, CodingKey { case event, phase, data, round, layer, persona, delta, score, section, markdown, reportPath = "report_path", message, protocolName = "protocol", protocolVersion = "protocol_version", kind, name, messageID = "message_id" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard let name = try c.decodeIfPresent(String.self, forKey: .event) else { _ = try ScientificEnvelope(from: decoder); throw DecodingError.dataCorruptedError(forKey: .event, in: c, debugDescription: "Scientific envelopes cannot be decoded as legacy events.") }
        guard !c.contains(.protocolName), !c.contains(.protocolVersion), !c.contains(.kind), !c.contains(.name), !c.contains(.messageID) else { throw DecodingError.dataCorruptedError(forKey: .event, in: c, debugDescription: "Scientific envelopes cannot be decoded as legacy events.") }
        switch name {
        case "phase_change": self = .phaseChange(phase: try c.decode(String.self, forKey: .phase), data: try c.decodeIfPresent(JSONValue.self, forKey: .data))
        case "interview_question": self = .interviewQuestion(try c.decode(InterviewQuestion.self, forKey: .data))
        case "council_round_start": self = .councilRoundStart(round: try c.decode(Int.self, forKey: .round), layer: try c.decodeIfPresent(String.self, forKey: .layer))
        case "council_persona_token": self = .councilPersonaToken(persona: try c.decode(String.self, forKey: .persona), delta: try c.decode(String.self, forKey: .delta))
        case "council_round_done": self = .councilRoundDone(round: try c.decode(Int.self, forKey: .round), score: try c.decodeIfPresent(Int.self, forKey: .score))
        case "report_chunk": self = .reportChunk(section: try c.decodeIfPresent(String.self, forKey: .section), markdown: try c.decode(String.self, forKey: .markdown))
        case "done": self = .done(reportPath: try c.decodeIfPresent(String.self, forKey: .reportPath))
        case "error": self = .error(message: try c.decode(String.self, forKey: .message))
        default: self = .unknown(name: name, payload: try JSONValue(from: decoder))
        }
    }
}
