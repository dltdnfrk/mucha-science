import XCTest
import CryptoKit
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif
@testable import Muchanipo

final class ProtocolFixturesTests: XCTestCase {
    func testUnknownLegacyEventPreservesNameAndPayload() throws {
        let data = Data("""
        {"event":"future.scientific.event","payload":{"nested":[1,true]},"version":2}
        """.utf8)

        let event = try JSONDecoder().decode(BackendEvent.self, from: data)

        XCTAssertEqual(
            event,
            .unknown(
                name: "future.scientific.event",
                payload: .object([
                    "event": .string("future.scientific.event"),
                    "payload": .object(["nested": .array([.number(1), .bool(true)])]),
                    "version": .number(2)
                ])
            )
        )
    }
    func testGeneratedProtocolCorpusMatchesManifestAndPreservesFrameBytes() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("../../../../config/protocol/ai-scientist.v1", isDirectory: true)
            .standardizedFileURL
        let manifestData = try Data(contentsOf: root.appendingPathComponent("manifest.json"))
        let manifest = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: manifestData) as? [String: Any]
        )
        let files = try XCTUnwrap(manifest["files"] as? [[String: Any]])

        for entry in files {
            let path = try XCTUnwrap(entry["path"] as? String)
            let expectedLength = try XCTUnwrap(entry["length"] as? Int)
            let expectedHash = try XCTUnwrap(entry["sha256"] as? String)
            let contents = try Data(contentsOf: root.appendingPathComponent(path))
            XCTAssertEqual(contents.count, expectedLength, path)
            XCTAssertEqual(String(sha256(contents).dropFirst("sha256:".count)), expectedHash, path)
        }

        let byteCorpus = try String(
            contentsOf: root.appendingPathComponent("bytes/corpus.jsonl"),
            encoding: .utf8
        )
        for line in byteCorpus.split(separator: "\n", omittingEmptySubsequences: true) {
            let vector = try XCTUnwrap(
                try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
            )
            guard let event = vector["event_line_utf8_base64"] as? String,
                  let marker = vector["marker_line_utf8_base64"] as? String,
                  let expected = vector["combined_bytes_sha256"] as? String else {
                continue
            }
            let eventBytes = try XCTUnwrap(Data(base64Encoded: event))
            let markerBytes = try XCTUnwrap(Data(base64Encoded: marker))
            XCTAssertEqual(eventBytes.last, 0x0A)
            XCTAssertEqual(markerBytes.last, 0x0A)
            XCTAssertEqual(sha256(eventBytes + markerBytes), expected)
        }
    }
    func testScientificEnvelopeCannotDowngradeToLegacyUnknownEvent() {
        let data = Data("""
        {"protocol":"muchanipo","protocol_version":"ai-scientist.v1","kind":"event","name":"future.event","message_id":"message_0123456789abcdef0123456789abcdef","cycle_id":null,"correlation_id":null,"causation_id":null,"sequence":2,"revision":1,"idempotency_key":null,"timestamp":"2026-07-19T00:00:00.000000Z","payload":{"future":true},"extensions":{}}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder().decode(BackendEvent.self, from: data))
    }
    func testScientificHelloUsesStrictProtocolWireValues() throws {
        let uuid = try XCTUnwrap(UUID(uuidString: "01234567-89ab-cdef-0123-456789abcdef"))
        let messageID = ProcessManager.scientificMessageID(uuid: uuid)
        let timestamp = ProcessManager.scientificTimestamp(date: Date(timeIntervalSince1970: 1_784_419_200.123456))
        let hello = ProcessManager.scientificHello(
            messageID: messageID,
            timestamp: timestamp
        )
        let encoded = try JSONEncoder().encode(hello)
        let decoded = try JSONDecoder().decode(ScientificEnvelope.self, from: encoded)

        XCTAssertEqual(messageID, "message_0123456789abcdef0123456789abcdef")
        XCTAssertEqual(timestamp, "2026-07-19T00:00:00.123456Z")
        XCTAssertTrue(matchesPythonWireRegex(messageID, pattern: "^[a-z][a-z0-9_]*_[0-9a-f]{32}$"))
        XCTAssertTrue(matchesPythonWireRegex(timestamp, pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$"))
        XCTAssertEqual(decoded.protocolName, "muchanipo")
        XCTAssertEqual(decoded.protocolVersion, "ai-scientist.v1")
        XCTAssertEqual(decoded.kind, "action")
        XCTAssertEqual(decoded.name, "protocol.hello")
        XCTAssertEqual(decoded.messageID, messageID)
        XCTAssertEqual(decoded.timestamp, timestamp)
        XCTAssertEqual(decoded.payload, .object([
            "handshake_idempotency_key": .string(messageID),
            "client_instance_id": .string("client_00000000000000000000000000000000"),
            "supported_versions": .array([.string("ai-scientist.v1")]),
            "capabilities": .array([]),
            "projection": .string("scientific-cycle.v1"),
            "cursors": .array([])
        ]))
    }

    func testScientificWritesFailClosedBeforeWelcome() {
        let manager = ProcessManager()
        let messageID = "action_0123456789abcdef0123456789abcdef"
        let action = ScientificEnvelope(
            kind: "action",
            name: "cycle.start",
            messageID: messageID,
            correlationID: messageID,
            idempotencyKey: "idempotency_0123456789abcdef0123456789abcdef",
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object(["expected_revision": .number(0)])
        )

        XCTAssertThrowsError(try manager.send(action)) { error in
            XCTAssertEqual(
                error as? ProcessManager.ManagerError,
                .scientificCapabilityNotNegotiated
            )
        }
    }
    func testProcessManagerLegacyActionsRequireLegacyProtocolMode() async throws {
        let process = Process()
        let stdinPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["cat"]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        try process.run()
        defer {
            if process.isRunning {
                process.terminate()
            }
        }

        let manager = ProcessManager()
        manager.attach(process: process, stdinPipe: stdinPipe)
        try manager.send(.abort)

        try manager.negotiateScientificCapability(
            messageID: "hello_0123456789abcdef0123456789abcdef",
            timestamp: "2026-07-19T00:00:00.000000Z"
        )
        XCTAssertThrowsError(try manager.send(.abort)) {
            XCTAssertEqual($0 as? ProcessManager.ManagerError, .legacyActionNotAllowed)
        }

        let welcome = welcome(requestMessageID: "hello_0123456789abcdef0123456789abcdef")
        _ = try await manager.receive(welcome)
        XCTAssertThrowsError(try manager.send(.abort)) {
            XCTAssertEqual($0 as? ProcessManager.ManagerError, .legacyActionNotAllowed)
        }
    }


    func testProcessManagerPreservesFullScientificEnvelopeForReducer() async throws {
        let manager = ProcessManager()
        let envelope = envelope(messageID: "message_7", sequence: 7, revision: 4)

        let reduction = try await manager.receive(envelope)
        XCTAssertEqual(reduction, .applied)
        XCTAssertEqual(manager.scientificReducer.state.latestEnvelope, envelope)
        XCTAssertEqual(manager.scientificReducer.state.unverifiedAuthorityLabels, [])
    }


    func testScientificReducerPersistsUntilNewGenerationAttach() async throws {
        let manager = ProcessManager()
        let firstProcess = Process()
        let firstInput = Pipe()
        manager.attach(process: firstProcess, stdinPipe: firstInput)
        let event = envelope(messageID: "message_1", sequence: 1, revision: 1)

        _ = try await manager.receive(event)
        manager.attach(process: firstProcess, stdinPipe: firstInput)
        XCTAssertEqual(manager.scientificReducer.state.latestEnvelope, event)

        manager.attach(process: Process(), stdinPipe: Pipe())
        XCTAssertNil(manager.scientificReducer.state.latestEnvelope)
    }
    func testReducerDeduplicatesAndRequestsReplayForGaps() {
        var reducer = ScientificReducer()
        let first = envelope(messageID: "message_1", sequence: 1, revision: 3)
        let gap = envelope(messageID: "message_3", sequence: 3, revision: 5)

        XCTAssertEqual(reducer.reduce(first), .applied)
        XCTAssertEqual(reducer.reduce(first), .duplicate)
        XCTAssertEqual(reducer.reduce(gap), .gap(expected: 2, received: 3))
        XCTAssertTrue(reducer.state.replayNeeded)
        XCTAssertEqual(reducer.state.lastSequence, 1)
        XCTAssertEqual(reducer.state.revision, 3)
    }
    func testReducerReplaysGapAfterMissingEnvelopeArrives() {
        var reducer = ScientificReducer()
        let first = envelope(messageID: "message_1", sequence: 1, revision: 1)
        let third = envelope(messageID: "message_3", sequence: 3, revision: 3)
        let second = envelope(messageID: "message_2", sequence: 2, revision: 2)

        XCTAssertEqual(reducer.reduce(first), .applied)
        XCTAssertEqual(reducer.reduce(third), .gap(expected: 2, received: 3))
        XCTAssertEqual(reducer.reduce(second), .applied)
        XCTAssertTrue(reducer.state.replayNeeded)
        XCTAssertEqual(reducer.reduce(third), .applied)
        XCTAssertEqual(reducer.state.lastSequence, 3)
        XCTAssertFalse(reducer.state.replayNeeded)
    }

    func testReducerRetainsIndependentAssessmentAndAuthorityFields() {
        var reducer = ScientificReducer()
        let cycleID = protocolID("cycle_123")
        let snapshot = ScientificEnvelope(
            kind: "snapshot",
            name: "cycle.snapshot",
            messageID: protocolID("snapshot_assessment"),
            cycleID: cycleID,
            correlationID: protocolID("request_assessment"),
            causationID: protocolID("request_assessment"),
            sequence: 1,
            revision: 1,
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "request_message_id": .string(protocolID("request_assessment")),
                "reason": .string("recovery"),
                "checkpoint": checkpoint(cycleID: cycleID, sequence: 1),
                "state_hash": .string(digest("a")),
                "state": .object([
                    "assessment": .object(["model_confidence": .number(0.9), "evidence_quality": .string("high")]),
                    "verification_status": .string("operator_asserted_unverified")
                ])
            ])
        )

        XCTAssertEqual(reducer.reduce(snapshot), .snapshotReplaced)
        XCTAssertEqual(reducer.reduce(envelope(messageID: "message_2", sequence: 2, revision: 2)), .applied)
        XCTAssertEqual(reducer.state.assessmentFields?.modelConfidence, .number(0.9))
        XCTAssertEqual(reducer.state.assessmentFields?.evidenceQuality, .string("high"))
        XCTAssertEqual(reducer.state.unverifiedAuthorityLabels, ["operator_asserted_unverified"])
    }

    func testLegacyEventsRemainCompatible() throws {
        let data = Data("""
        {"event":"phase_change","phase":"council","data":{"round":2}}
        """.utf8)

        XCTAssertEqual(
            try JSONDecoder().decode(BackendEvent.self, from: data),
            .phaseChange(phase: "council", data: .object(["round": .number(2)]))
        )
    }
    func testWelcomeTransitionsScientificNegotiation() async throws {
        let process = Process()
        let stdinPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["cat"]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        try process.run()
        defer {
            if process.isRunning {
                process.terminate()
            }
        }

        let manager = ProcessManager()
        manager.attach(process: process, stdinPipe: stdinPipe)
        try manager.negotiateScientificCapability(
            messageID: "hello_0123456789abcdef0123456789abcdef",
            timestamp: "2026-07-19T00:00:00.000000Z"
        )

        let welcome = welcome(requestMessageID: "hello_0123456789abcdef0123456789abcdef")

        let welcomeReduction = try await manager.receive(welcome)
        XCTAssertEqual(welcomeReduction, .applied)
        XCTAssertEqual(
            manager.protocolMode,
            .scientific(capabilities: ["cycle.start"])
        )
        let unadvertised = ScientificEnvelope(
            kind: "action",
            name: "cycle.abort",
            messageID: "abort_0123456789abcdef0123456789abcdef",
            cycleID: protocolID("cycle_123"),
            correlationID: "abort_0123456789abcdef0123456789abcdef",
            idempotencyKey: "abort-key",
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object(["expected_revision": .number(1)])
        )
        XCTAssertThrowsError(try manager.send(unadvertised)) {
            XCTAssertEqual($0 as? ProcessManager.ManagerError, .unadvertisedScientificAction)
        }
        let malformedActions = [
            ScientificEnvelope(kind: "response", name: "cycle.start", messageID: "response_0123456789abcdef0123456789abcdef", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "", messageID: "emptyname_0123456789abcdef0123456789abcdef", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_1", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", cycleID: "cycle_1", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", correlationID: "correlation_1", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", causationID: "causation_1", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", sequence: -1, timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", revision: 9_007_199_254_740_992, timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", idempotencyKey: "", timestamp: "2026-07-19T00:00:00.000000Z"),
            ScientificEnvelope(kind: "action", name: "cycle.start", messageID: "message_0123456789abcdef0123456789abcdef", timestamp: "2026-07-19T00:00:00Z")
        ]
        for action in malformedActions {
            XCTAssertThrowsError(try manager.send(action)) {
                XCTAssertEqual($0 as? ProcessManager.ManagerError, .invalidScientificEnvelope)
            }
        }
    }
    func testScientificEnvelopeRejectsInvalidCommonFields() {
        let valid = """
        {"protocol":"muchanipo","protocol_version":"ai-scientist.v1","kind":"event","name":"cycle.continued","message_id":"message_0123456789abcdef0123456789abcdef","cycle_id":null,"correlation_id":null,"causation_id":null,"sequence":1,"revision":1,"idempotency_key":null,"timestamp":"2026-07-19T00:00:00.000000Z","payload":{},"extensions":{}}
        """
        let invalidFrames = [
            valid.replacingOccurrences(of: "\"muchanipo\"", with: "\"other\"", options: [], range: valid.range(of: "\"muchanipo\"")),
            valid.replacingOccurrences(of: "\"ai-scientist.v1\"", with: "\"ai-scientist.v2\""),
            valid.replacingOccurrences(of: "\"message_0123456789abcdef0123456789abcdef\"", with: "\"message_1\""),
            valid.replacingOccurrences(of: "\"2026-07-19T00:00:00.000000Z\"", with: "\"2026-07-19T00:00:00Z\""),
            valid.replacingOccurrences(of: "\"sequence\":1", with: "\"sequence\":-1"),
            valid.replacingOccurrences(of: "\"revision\":1", with: "\"revision\":9007199254740992")
        ]

        for frame in invalidFrames {
            XCTAssertThrowsError(try JSONDecoder().decode(ScientificEnvelope.self, from: Data(frame.utf8)))
        }
    }

    @MainActor
    func testCallbackStartAPIsDoNotExposeStreams() {
        let runner = PythonRunner()
        let start = runner.start(topic:)
        let startScientific = runner.startScientific
        _ = start
        _ = startScientific
    }
    func testLegacyStreamAcceptsFrameAtItsLimit() async throws {
        let frame = Data(#"{"event":"done","report_path":null}"#.utf8)
        let pipe = Pipe()
        pipe.fileHandleForWriting.write(frame + Data([0x0A]))
        pipe.fileHandleForWriting.closeFile()

        var iterator = EventStream(
            pipe: pipe,
            maximumFrameLength: frame.count
        ).makeAsyncIterator()
        let event = try await iterator.next()
        XCTAssertEqual(event, .done(reportPath: nil))
    }

    func testScientificStreamAcceptsFrameAtItsLimit() async throws {
        let expected = envelope(
            messageID: "message_0123456789abcdef0123456789abcdef",
            sequence: 1,
            revision: 1
        )
        let frame = try JSONEncoder().encode(expected)
        let pipe = Pipe()
        let writer = Task.detached {
            pipe.fileHandleForWriting.write(frame + Data([0x0A]))
            pipe.fileHandleForWriting.closeFile()
        }

        var iterator = ScientificEventStream(
            pipe: pipe,
            maximumFrameLength: frame.count
        ).makeAsyncIterator()
        let event = try await iterator.next()
        XCTAssertEqual(event, expected)
        await writer.value
    }

    func testLegacyAndScientificStreamsRejectOverLimitFrames() async {
        let limit = 8
        let oversizedFrame = Data(repeating: 0x20, count: limit + 1)

        let legacyPipe = Pipe()
        legacyPipe.fileHandleForWriting.write(oversizedFrame + Data([0x0A]))
        legacyPipe.fileHandleForWriting.closeFile()
        var legacyIterator = EventStream(
            pipe: legacyPipe,
            maximumFrameLength: limit
        ).makeAsyncIterator()

        do {
            _ = try await legacyIterator.next()
            XCTFail("Expected oversized legacy frame to fail.")
        } catch {
            XCTAssertEqual(error as? NDJSONFrameError, .frameTooLarge(limit: limit))
        }

        let scientificPipe = Pipe()
        scientificPipe.fileHandleForWriting.write(oversizedFrame + Data([0x0A]))
        scientificPipe.fileHandleForWriting.closeFile()
        var scientificIterator = ScientificEventStream(
            pipe: scientificPipe,
            maximumFrameLength: limit
        ).makeAsyncIterator()

        do {
            _ = try await scientificIterator.next()
            XCTFail("Expected oversized scientific frame to fail.")
        } catch {
            XCTAssertEqual(error as? NDJSONFrameError, .frameTooLarge(limit: limit))
        }
    }

    @MainActor
    func testRunnerReapsCurrentGenerationBeforeRestartAndDeliversTerminationOnMainActor() async throws {
        let runner = PythonRunner(executableURL: URL(fileURLWithPath: "/usr/bin/true"))
        let terminated = expectation(description: "first generation terminated")
        var callbackWasOnMainActor = false
        var terminationCount = 0
        var restartedFromTerminationCallback = false
        runner.onTermination = { _ in
            callbackWasOnMainActor = Thread.isMainThread
            terminationCount += 1
            if terminationCount == 1 {
                do {
                    _ = try runner.startStream(topic: "ignored")
                    restartedFromTerminationCallback = true
                } catch {
                    XCTFail("Termination callback must own the completed restart: \(error)")
                }
                terminated.fulfill()
            }
        }

        _ = try runner.startStream(topic: "ignored")
        XCTAssertThrowsError(try runner.startStream(topic: "ignored")) {
            XCTAssertEqual($0 as? PythonRunner.RunnerError, .alreadyRunning)
        }

        await fulfillment(of: [terminated], timeout: 2)
        XCTAssertTrue(callbackWasOnMainActor)
        XCTAssertTrue(restartedFromTerminationCallback)
        runner.stop()
    }
    @MainActor
    func testRestartAwaitsShutdownBeforeStartingReplacement() async throws {
        let runner = PythonRunner(executableURL: URL(fileURLWithPath: "/usr/bin/yes"))

        _ = try runner.startStream(topic: "ignored")
        _ = try await runner.restart(topic: "ignored")

        XCTAssertThrowsError(try runner.startStream(topic: "ignored")) {
            XCTAssertEqual($0 as? PythonRunner.RunnerError, .alreadyRunning)
        }
        try await runner.stopAndWait()
    }
    @MainActor
    func testReaderErrorTeardownJoinsBeforeRestart() async throws {
        let runner = PythonRunner(executableURL: URL(fileURLWithPath: "/bin/echo"))
        let restarted = expectation(description: "replacement started after reader failure")
        var hasRestarted = false

        runner.onOutputLine = { line in
            guard line.contains("event decode failed"), !hasRestarted else {
                return
            }
            hasRestarted = true
            Task { @MainActor in
                do {
                    _ = try await runner.restart(topic: "ignored")
                    restarted.fulfill()
                } catch {
                    XCTFail("Reader failure cleanup must permit restart: \(error)")
                }
            }
        }

        try runner.start(topic: "ignored")
        await fulfillment(of: [restarted], timeout: 2)
        try await runner.stopAndWait()
    }

    func testShutdownRetainsStubbornChildWhenKillFails() async throws {
        let process = Process()
        let stdinPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", "trap '' TERM; while :; do sleep 1; done"]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        try process.run()
        try await Task.sleep(nanoseconds: 20_000_000)

        let manager = ProcessManager(
            terminationGraceNanoseconds: 1_000_000,
            killGraceNanoseconds: 1_000_000,
            signal: { _, _ in -1 }
        )
        manager.attach(process: process, stdinPipe: stdinPipe)

        do {
            _ = try await manager.shutdown(process: process)
            XCTFail("A child that survives a failed kill must remain owned.")
        } catch {
            XCTAssertEqual(error as? ProcessManager.ManagerError, .killFailed(-1))
        }
        XCTAssertTrue(manager.isRunning)

        _ = kill(process.processIdentifier, SIGKILL)
        process.waitUntilExit()
    }

    func testCancelledNDJSONIterationDoesNotDecodeBufferedOrBlockedReads() async {
        let bufferedPipe = Pipe()
        bufferedPipe.fileHandleForWriting.write(Data(#"{"event":"done"}"#.utf8) + Data([0x0A]))
        let bufferedRead = Task {
            var iterator = EventStream(pipe: bufferedPipe).makeAsyncIterator()
            return try await iterator.next()
        }
        bufferedRead.cancel()

        do {
            _ = try await bufferedRead.value
            XCTFail("Cancelled buffered reads must not decode.")
        } catch is CancellationError {
        } catch {
            XCTFail("Expected cancellation, got \(error)")
        }

        let blockedPipe = Pipe()
        let blockedRead = Task {
            var iterator = EventStream(pipe: blockedPipe).makeAsyncIterator()
            return try await iterator.next()
        }
        try? await Task.sleep(nanoseconds: 10_000_000)
        blockedRead.cancel()

        do {
            _ = try await blockedRead.value
            XCTFail("Cancelled blocked reads must not continue waiting.")
        } catch is CancellationError {
        } catch {
            XCTFail("Expected cancellation, got \(error)")
        }
    }

    func testMalformedWelcomeResetsAttachedChild() async throws {
        let process = Process()
        let stdinPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["cat"]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        try process.run()

        let manager = ProcessManager()
        manager.attach(process: process, stdinPipe: stdinPipe)
        try manager.negotiateScientificCapability(
            messageID: "hello_0123456789abcdef0123456789abcdef",
            timestamp: "2026-07-19T00:00:00.000000Z"
        )
        let malformed = ScientificEnvelope(
            kind: "response",
            name: "protocol.welcome.response",
            messageID: protocolID("welcome_1"),
            correlationID: "hello_0123456789abcdef0123456789abcdef",
            causationID: "hello_0123456789abcdef0123456789abcdef",
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "request_message_id": .string("hello_0123456789abcdef0123456789abcdef"),
                "selected_version": .string("ai-scientist.v1"),
                "connection_id": .string(protocolID("connection")),
                "server_instance_id": .string(protocolID("server")),
                "capabilities": .array([.number(1)]),
                "operation_modes": .object([:]),
                "accepted_cursors": .array([])
            ])
        )

        do {
            _ = try await manager.receive(malformed)
            XCTFail("malformed welcome must be rejected")
        } catch {
            XCTAssertEqual(error as? ProcessManager.ManagerError, .invalidScientificEnvelope)
        }
        XCTAssertFalse(manager.isRunning)
        XCTAssertEqual(manager.protocolMode, .legacy)
    }

    func testReducerQuarantinesInvalidOrderWithoutReplacingDerivedState() {
        var reducer = ScientificReducer()
        let assessed = envelope(messageID: "message_1", sequence: 1, revision: 1)
        let unrelated = envelope(messageID: "message_2", sequence: 2, revision: 2)
        let stale = envelope(messageID: "message_stale", sequence: 1, revision: 1)
        let gap = envelope(messageID: "message_gap", sequence: 4, revision: 4)
        let crossCycle = ScientificEnvelope(
            kind: "event",
            name: "cycle.continued",
            messageID: protocolID("message_cross"),
            cycleID: protocolID("cycle_456"),
            correlationID: protocolID("correlation"),
            causationID: protocolID("cause"),
            sequence: 3,
            revision: 3,
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "operation": .string("landscape.complete"),
                "created_records": .array([]),
                "superseded_record_ids": .array([]),
                "derived_current_refs": .object([:])
            ])
        )

        XCTAssertEqual(reducer.reduce(assessed), .applied)
        XCTAssertEqual(reducer.reduce(unrelated), .applied)
        XCTAssertNil(reducer.state.assessmentFields)
        XCTAssertEqual(reducer.reduce(stale), .stale(last: 2, received: 1))
        XCTAssertEqual(reducer.reduce(gap), .gap(expected: 3, received: 4))
        XCTAssertEqual(reducer.reduce(crossCycle), .crossCycle(expected: protocolID("cycle_123"), received: protocolID("cycle_456")))
        XCTAssertEqual(reducer.state.lastSequence, 2)
        XCTAssertNil(reducer.state.assessmentFields)
    }

    func testScientificCatalogAndSnapshotRecoveryRemainClosed() {
        XCTAssertEqual(
            ScientificProtocolCatalog.actions.count,
            20
        )
        XCTAssertEqual(ScientificProtocolCatalog.events.count, 11)
        XCTAssertEqual(ScientificProtocolCatalog.responses.count, 7)

        let snapshot = ScientificEnvelope(
            kind: "snapshot",
            name: "cycle.snapshot",
            messageID: protocolID("snapshot"),
            cycleID: protocolID("cycle"),
            correlationID: protocolID("request"),
            causationID: protocolID("request"),
            sequence: 4,
            revision: 4,
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "request_message_id": .string(protocolID("request")),
                "reason": .string("recovery"),
                "checkpoint": .object([
                    "cycle_id": .string(protocolID("cycle")),
                    "sequence": .number(4),
                    "event_hash": .string("sha256:" + String(repeating: "a", count: 64))
                ]),
                "state_hash": .string("sha256:" + String(repeating: "b", count: 64)),
                "state": .object([
                    "automation_mode": .string("automated"),
                    "gates": .object(["final_accountability": .string("pending")]),
                    "status_overlay": .object(["label": .string("pending")]),
                    "export_state": .object(["status": .string("none")])
                ])
            ])
        )
        var reducer = ScientificReducer()
        XCTAssertEqual(reducer.reduce(snapshot), .snapshotReplaced)
        XCTAssertEqual(reducer.state.automationMode, .string("automated"))
        XCTAssertEqual(reducer.state.reportStatusOverlay, .object(["label": .string("pending")]))
        XCTAssertEqual(reducer.state.exportState, .object(["status": .string("none")]))
    }

    func testMalformedCheckpointAndUnadvertisedActionFailClosed() {
        let malformed = ScientificEnvelope(
            kind: "snapshot",
            name: "cycle.snapshot",
            messageID: protocolID("snapshot_bad"),
            cycleID: protocolID("cycle"),
            correlationID: protocolID("request"),
            causationID: protocolID("request"),
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([:])
        )
        XCTAssertFalse(malformed.hasValidInvariants)
        XCTAssertThrowsError(try ProcessManager().send(malformed))
    }
    private func envelope(messageID: String, sequence: Int, revision: Int) -> ScientificEnvelope {
        ScientificEnvelope(
            kind: "event",
            name: "cycle.continued",
            messageID: protocolID(messageID),
            cycleID: protocolID("cycle_123"),
            correlationID: protocolID("correlation"),
            causationID: protocolID("cause"),
            sequence: sequence,
            revision: revision,
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "operation": .string("landscape.complete"),
                "created_records": .array([]),
                "superseded_record_ids": .array([]),
                "derived_current_refs": .object([:])
            ])
        )
    }
    private func welcome(requestMessageID: String) -> ScientificEnvelope {
        ScientificEnvelope(
            kind: "response",
            name: "protocol.welcome.response",
            messageID: protocolID("welcome"),
            correlationID: requestMessageID,
            causationID: requestMessageID,
            timestamp: "2026-07-19T00:00:00.000000Z",
            payload: .object([
                "request_message_id": .string(requestMessageID),
                "selected_version": .string("ai-scientist.v1"),
                "connection_id": .string(protocolID("connection")),
                "server_instance_id": .string(protocolID("server")),
                "capabilities": .array([.string("cycle.start")]),
                "operation_modes": .array([.string("normal")]),
                "accepted_cursors": .array([])
            ])
        )
    }
    private func checkpoint(cycleID: String, sequence: Int) -> JSONValue {
        .object([
            "cycle_id": .string(cycleID),
            "sequence": .number(Double(sequence)),
            "event_hash": .string(digest("b"))
        ])
    }
    private func digest(_ character: Character) -> String {
        "sha256:" + String(repeating: String(character), count: 64)
    }
    private func sha256(_ data: Data) -> String {
        "sha256:" + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func protocolID(_ value: String) -> String {
        let components = value.split(separator: "_", maxSplits: 1)
        let prefix = components.first.map(String.init) ?? "message"
        let hexadecimal = value.utf8.map { String(format: "%02x", $0) }.joined()
        let padded = hexadecimal + String(repeating: "0", count: 32)
        return "\(prefix)_\(padded.prefix(32))"
    }
    private func matchesPythonWireRegex(_ value: String, pattern: String) -> Bool {
        value.range(of: pattern, options: .regularExpression) != nil
    }
}
