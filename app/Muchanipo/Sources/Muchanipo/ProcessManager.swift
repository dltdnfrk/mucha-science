import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

final class ProcessManager {
    enum ManagerError: Error, Equatable {
        case processNotRunning
        case legacyActionNotAllowed
        case scientificCapabilityNotNegotiated
        case invalidCapabilityResponse
        case encodingFailed
        case unadvertisedScientificAction
        case invalidScientificEnvelope
        case killFailed(Int32)
        case terminationTimedOut
        case invalidRecoveryAcknowledgement
        case invalidRequestOrdinal
    }

    enum ProtocolMode: Equatable {
        case legacy
        case negotiating
        case scientific(capabilities: Set<String>)
    }
    struct RecoveryState: Equatable {
        let clientInstanceID: String
        fileprivate(set) var requestOrdinal: Int
        fileprivate(set) var ackOrdinal: Int
        fileprivate(set) var checkpoint: JSONValue?
        fileprivate(set) var stateHash: String?
    }

    private let encoder: JSONEncoder
    private let terminationGraceNanoseconds: UInt64
    private let killGraceNanoseconds: UInt64
    private let signal: (pid_t, Int32) -> Int32
    private var process: Process?
    private var stdinPipe: Pipe?
    private var stdoutPipe: Pipe?
    private(set) var protocolMode: ProtocolMode = .legacy
    private(set) var scientificReducer = ScientificReducer()
    private(set) var recoveryState: RecoveryState

    init(
        encoder: JSONEncoder = JSONEncoder(),
        clientInstanceID: String = "client_00000000000000000000000000000000",
        terminationGraceNanoseconds: UInt64 = 2_000_000_000,
        killGraceNanoseconds: UInt64 = 2_000_000_000,
        signal: @escaping (pid_t, Int32) -> Int32 = { kill($0, $1) }
    ) {
        precondition(ScientificEnvelope.isProtocolID(clientInstanceID))
        self.encoder = encoder
        self.recoveryState = RecoveryState(clientInstanceID: clientInstanceID, requestOrdinal: 0, ackOrdinal: 0, checkpoint: nil, stateHash: nil)
        self.terminationGraceNanoseconds = terminationGraceNanoseconds
        self.killGraceNanoseconds = killGraceNanoseconds
        self.signal = signal
    }
    static func scientificMessageID(uuid: UUID = UUID()) -> String {
        "message_\(uuid.uuidString.replacingOccurrences(of: "-", with: "").lowercased())"
    }

    static func scientificTimestamp(date: Date = Date()) -> String {
        let microsecondsPerSecond: Int64 = 1_000_000
        let totalMicroseconds = Int64((date.timeIntervalSince1970 * Double(microsecondsPerSecond)).rounded())
        var seconds = totalMicroseconds / microsecondsPerSecond
        var microseconds = totalMicroseconds % microsecondsPerSecond

        if microseconds < 0 {
            seconds -= 1
            microseconds += microsecondsPerSecond
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"

        return "\(formatter.string(from: Date(timeIntervalSince1970: TimeInterval(seconds)))).\(String(format: "%06lld", microseconds))Z"
    }

    var isRunning: Bool {
        process?.isRunning == true
    }

    func attach(process: Process, stdinPipe: Pipe, stdoutPipe: Pipe? = nil) {
        let isNewGeneration = self.process !== process
        self.process = process
        self.stdinPipe = stdinPipe
        self.stdoutPipe = stdoutPipe
        if isNewGeneration {
            protocolMode = .legacy
            scientificReducer = ScientificReducer()
        }
    }

    func send(_ action: BackendAction) throws {
        guard case .legacy = protocolMode else {
            throw ManagerError.legacyActionNotAllowed
        }
        try write(action)
    }

    static func scientificHello(
        messageID: String,
        timestamp: String,
        clientInstanceID: String = "client_00000000000000000000000000000000",
        cursors: [JSONValue] = []
    ) -> ScientificEnvelope {
        ScientificEnvelope(
            kind: "action",
            name: "protocol.hello",
            messageID: messageID,
            correlationID: messageID,
            idempotencyKey: messageID,
            timestamp: timestamp,
            payload: .object([
                "handshake_idempotency_key": .string(messageID),
                "client_instance_id": .string(clientInstanceID),
                "supported_versions": .array([.string(ScientificEnvelope.protocolVersion)]),
                "capabilities": .array([]),
                "projection": .string("scientific-cycle.v1"),
                "cursors": .array(cursors)
            ])
        )
    }

    func negotiateScientificCapability(
        messageID: String,
        timestamp: String
    ) throws {
        let hello = Self.scientificHello(
            messageID: messageID,
            timestamp: timestamp,
            clientInstanceID: recoveryState.clientInstanceID,
            cursors: recoveryState.checkpoint.map { [$0] } ?? []
        )
        guard hello.hasValidInvariants, hello.kind == "action" else {
            throw ManagerError.invalidScientificEnvelope
        }
        try write(hello)
        protocolMode = .negotiating
    }

    func send(_ envelope: ScientificEnvelope) throws {
        guard envelope.hasValidInvariants, envelope.kind == "action" else {
            throw ManagerError.invalidScientificEnvelope
        }
        guard case .scientific(let capabilities) = protocolMode else {
            throw ManagerError.scientificCapabilityNotNegotiated
        }
        guard capabilities.contains(envelope.name) else {
            throw ManagerError.unadvertisedScientificAction
        }
        try persistOutgoingRecoveryState(for: envelope)
        try write(envelope)
    }

    @discardableResult
    func receive(_ envelope: ScientificEnvelope) async throws -> ScientificReduction {
        guard envelope.hasValidInvariants else {
            await failScientificSession()
            throw ManagerError.invalidScientificEnvelope
        }
        if case .negotiating = protocolMode {
            guard envelope.kind == "response",
                  envelope.name == "protocol.welcome.response",
                  case .object(let payload) = envelope.payload,
                  case .string(let version)? = payload["selected_version"],
                  version == ScientificEnvelope.protocolVersion,
                  case .array(let values)? = payload["capabilities"] else {
                await failScientificSession()
                throw ManagerError.invalidCapabilityResponse
            }
            let capabilities = values.map { value -> String? in
                guard case .string(let capability) = value, !capability.isEmpty else {
                    return nil
                }
                return capability
            }
            guard !capabilities.contains(nil) else {
                await failScientificSession()
                throw ManagerError.invalidCapabilityResponse
            }
            protocolMode = .scientific(capabilities: Set(capabilities.compactMap { $0 }))
        } else if envelope.kind == "response" && envelope.name == "protocol.welcome.response" {
            await failScientificSession()
            throw ManagerError.invalidCapabilityResponse
        }
        let reduction = scientificReducer.reduce(envelope)
        if reduction != .invalid {
            persistReducerState()
        }
        return reduction
    }

    private func persistOutgoingRecoveryState(for envelope: ScientificEnvelope) throws {
        guard let payload = envelope.payload.objectValue else {
            throw ManagerError.invalidScientificEnvelope
        }
        if ["cycle.replay", "cycle.resume", "export.get", "report.render"].contains(envelope.name) {
            guard payload["client_instance_id"]?.stringValue == recoveryState.clientInstanceID,
                  let ordinal = payload["request_ordinal"]?.integerValue,
                  ordinal == recoveryState.requestOrdinal + 1 else {
                throw ManagerError.invalidRequestOrdinal
            }
            recoveryState.requestOrdinal = ordinal
        }
        if envelope.name == "cycle.ack" {
            guard payload["client_instance_id"]?.stringValue == recoveryState.clientInstanceID,
                  let ordinal = payload["ack_ordinal"]?.integerValue,
                  ordinal == recoveryState.ackOrdinal + 1,
                  payload["checkpoint"] == recoveryState.checkpoint,
                  payload["state_hash"]?.stringValue == recoveryState.stateHash else {
                throw ManagerError.invalidRecoveryAcknowledgement
            }
            // This assignment is the in-memory atomic persistence boundary before the ack is written.
            recoveryState.ackOrdinal = ordinal
        }
    }

    private func persistReducerState() {
        recoveryState.checkpoint = scientificReducer.state.checkpoint
        recoveryState.stateHash = scientificReducer.state.stateHash
    }
    private func failScientificSession() async {
        guard let process else {
            protocolMode = .legacy
            return
        }
        _ = try? await shutdown(process: process)
    }


    func shutdown(process expectedProcess: Process) async throws -> Int32? {
        guard process === expectedProcess else {
            return nil
        }

        stdinPipe?.fileHandleForWriting.closeFile()
        stdoutPipe?.fileHandleForReading.closeFile()
        if expectedProcess.isRunning {
            expectedProcess.terminate()
            if await waitForExit(expectedProcess, within: terminationGraceNanoseconds) {
                return clearShutdownProcess(expectedProcess)
            }

            let killResult = signal(expectedProcess.processIdentifier, SIGKILL)
            if killResult != 0 {
                if await waitForExit(expectedProcess, within: killGraceNanoseconds) {
                    return clearShutdownProcess(expectedProcess)
                }
                throw ManagerError.killFailed(killResult)
            }

            guard await waitForExit(expectedProcess, within: killGraceNanoseconds) else {
                throw ManagerError.terminationTimedOut
            }
        }

        return clearShutdownProcess(expectedProcess)
    }

    private func waitForExit(_ process: Process, within timeout: UInt64) async -> Bool {
        let pollInterval: UInt64 = 20_000_000
        var remaining = timeout
        while process.isRunning && remaining > 0 {
            let interval = min(pollInterval, remaining)
            try? await Task.sleep(nanoseconds: interval)
            remaining -= interval
        }
        return !process.isRunning
    }

    private func clearShutdownProcess(_ expectedProcess: Process) -> Int32? {
        guard process === expectedProcess else {
            return nil
        }
        process = nil
        stdinPipe = nil
        stdoutPipe = nil
        protocolMode = .legacy
        return expectedProcess.processIdentifier > 0 ? expectedProcess.terminationStatus : nil
    }

    private func write<T: Encodable>(_ value: T) throws {
        guard let process, process.isRunning, let stdinPipe else {
            throw ManagerError.processNotRunning
        }
        var data: Data
        do {
            data = try encoder.encode(value)
        } catch {
            throw ManagerError.encodingFailed
        }
        data.append(0x0A)
        stdinPipe.fileHandleForWriting.write(data)
    }
}
