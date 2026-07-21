import Foundation

@MainActor
final class PythonRunner {
    enum RunnerError: Error {
        case alreadyRunning
        case processNotRunning
        case scientificActionsRequired
    }

    var onEvent: ((BackendEvent) -> Void)?
    var onOutputLine: ((String) -> Void)?
    var onTermination: ((Int32) -> Void)?
    var onScientificEnvelope: ((ScientificEnvelope, ScientificReduction) -> Void)?

    private let executableURL: URL
    private let workingDirectoryURL: URL?
    private var process: Process?
    private var eventTask: Task<Void, Never>?
    private var eventTaskGeneration: Int?
    private var shutdownTask: Task<Int32?, Error>?
    private let processManager: ProcessManager
    private let scientificMessageID: () -> String
    private let scientificTimestamp: () -> String
    private var generation = 0

    init(
        executableURL: URL = URL(fileURLWithPath: "/usr/bin/env"),
        workingDirectoryURL: URL? = nil,
        encoder: JSONEncoder = JSONEncoder(),
        scientificMessageID: @escaping () -> String = { ProcessManager.scientificMessageID() },
        scientificTimestamp: @escaping () -> String = { ProcessManager.scientificTimestamp() }
    ) {
        self.executableURL = executableURL
        self.workingDirectoryURL = workingDirectoryURL
        self.scientificMessageID = scientificMessageID
        self.scientificTimestamp = scientificTimestamp
        self.processManager = ProcessManager(encoder: encoder)
    }

    var isRunning: Bool {
        process?.isRunning == true
    }

    var scientificReducer: ScientificReducer {
        processManager.scientificReducer
    }

    var scientificProtocolMode: ProcessManager.ProtocolMode {
        processManager.protocolMode
    }
    var scientificRecoveryState: ProcessManager.RecoveryState {
        processManager.recoveryState
    }

    func start(topic: String) throws {
        let stream = try startStream(topic: topic)
        guard let process else {
            throw RunnerError.processNotRunning
        }
        let generation = generation
        eventTask = Task { @MainActor [weak self, weak process] in
            do {
                for try await event in stream {
                    guard let self, let process, self.isCurrent(process, generation: generation) else {
                        return
                    }
                    self.onEvent?(event)
                    self.onOutputLine?(event.displayLine)
                }
            } catch {
                if error is CancellationError {
                    return
                }
                guard let self, let process, self.isCurrent(process, generation: generation) else {
                    return
                }
                self.onOutputLine?("[error] event decode failed: \(error.localizedDescription)")
                self.stopAfterReaderFailure(process, generation: generation)
            }
        }
        eventTaskGeneration = generation
    }

    func startScientific() throws {
        let stream = try startScientificStream()
        guard let process else {
            throw RunnerError.processNotRunning
        }
        let generation = generation
        eventTask = Task { @MainActor [weak self, weak process] in
            do {
                for try await envelope in stream {
                    guard let self, let process, self.isCurrent(process, generation: generation) else {
                        return
                    }
                    let reduction = try await self.processManager.receive(envelope)
                    guard self.isCurrent(process, generation: generation) else {
                        return
                    }
                    self.onScientificEnvelope?(envelope, reduction)
                    self.onOutputLine?("[scientific \(envelope.sequence)] \(envelope.name)")
                }
            } catch {
                if error is CancellationError {
                    return
                }
                guard let self, let process, self.isCurrent(process, generation: generation) else {
                    return
                }
                self.onOutputLine?("[error] scientific event decode failed: \(error.localizedDescription)")
                self.stopAfterReaderFailure(process, generation: generation)
            }
        }
        eventTaskGeneration = generation
    }

    func startScientificStream() throws -> ScientificEventStream {
        guard process == nil else {
            throw RunnerError.alreadyRunning
        }

        let process = Process()
        let stdoutPipe = Pipe()
        let stdinPipe = Pipe()
        let nextGeneration = generation &+ 1

        process.executableURL = executableURL
        process.arguments = [
            "python3.11", "-m", "muchanipo", "serve",
            "--topic", "scientific-cycle", "--scientific-mode"
        ]
        process.standardOutput = stdoutPipe
        process.standardInput = stdinPipe

        if let workingDirectoryURL {
            process.currentDirectoryURL = workingDirectoryURL
        }

        process.terminationHandler = { [weak self] terminatedProcess in
            let exitCode = terminatedProcess.terminationStatus
            Task { @MainActor [weak self] in
                self?.didTerminate(terminatedProcess, generation: nextGeneration, exitCode: exitCode)
            }
        }

        try process.run()

        generation = nextGeneration
        self.process = process
        processManager.attach(process: process, stdinPipe: stdinPipe, stdoutPipe: stdoutPipe)
        do {
            try processManager.negotiateScientificCapability(
                messageID: scientificMessageID(),
                timestamp: scientificTimestamp()
            )
        } catch {
            stopChild(process, generation: nextGeneration)
            throw error
        }

        return ScientificEventStream(pipe: stdoutPipe)
    }

    func startStream(topic: String) throws -> EventStream {
        guard process == nil else {
            throw RunnerError.alreadyRunning
        }

        let process = Process()
        let stdoutPipe = Pipe()
        let stdinPipe = Pipe()
        let nextGeneration = generation &+ 1

        process.executableURL = executableURL
        process.arguments = ["python3", "-m", "muchanipo", "serve", "--topic", topic]
        process.standardOutput = stdoutPipe
        process.standardInput = stdinPipe

        if let workingDirectoryURL {
            process.currentDirectoryURL = workingDirectoryURL
        }

        process.terminationHandler = { [weak self] terminatedProcess in
            let exitCode = terminatedProcess.terminationStatus
            Task { @MainActor [weak self] in
                self?.didTerminate(terminatedProcess, generation: nextGeneration, exitCode: exitCode)
            }
        }

        try process.run()

        generation = nextGeneration
        self.process = process
        processManager.attach(process: process, stdinPipe: stdinPipe, stdoutPipe: stdoutPipe)

        return EventStream(pipe: stdoutPipe)
    }

    func send(_ action: BackendAction) throws {
        guard case .legacy = processManager.protocolMode else {
            throw RunnerError.scientificActionsRequired
        }
        try processManager.send(action)
    }

    func send(_ envelope: ScientificEnvelope) throws {
        try processManager.send(envelope)
    }

    func stop() {
        guard let process else {
            return
        }
        stopChild(process, generation: generation)
    }

    func stopAndWait() async throws {
        guard let process else {
            return
        }
        _ = try await shutdownChild(process, generation: generation)
    }

    func restart(topic: String) async throws -> EventStream {
        try await stopAndWait()
        return try startStream(topic: topic)
    }

    private func stopChild(_ expectedProcess: Process, generation: Int) {
        Task { @MainActor [weak self, weak expectedProcess] in
            guard let self, let expectedProcess else {
                return
            }
            do {
                _ = try await self.shutdownChild(expectedProcess, generation: generation)
            } catch {
                self.onOutputLine?("[error] process shutdown failed: \(error.localizedDescription)")
            }
        }
    }
    private func stopAfterReaderFailure(_ expectedProcess: Process, generation: Int) {
        Task { @MainActor [weak self, weak expectedProcess] in
            guard let self, let expectedProcess else {
                return
            }
            do {
                _ = try await self.shutdownChild(expectedProcess, generation: generation)
            } catch {
                self.onOutputLine?("[error] process shutdown failed: \(error.localizedDescription)")
            }
        }
    }


    private func shutdownChild(_ expectedProcess: Process, generation: Int) async throws -> Int32? {
        guard isCurrent(expectedProcess, generation: generation) else {
            return nil
        }

        let task: Task<Int32?, Error>
        if let shutdownTask {
            task = shutdownTask
        } else {
            let shutdownTask = Task<Int32?, Error> { @MainActor [weak self, weak expectedProcess] in
                guard let self, let expectedProcess else {
                    return nil
                }
                await self.cancelAndWaitForEventTask(generation: generation)
                guard self.isCurrent(expectedProcess, generation: generation) else {
                    return nil
                }
                return try await self.processManager.shutdown(process: expectedProcess)
            }
            self.shutdownTask = shutdownTask
            task = shutdownTask
        }

        do {
            let exitCode = try await task.value
            guard isCurrent(expectedProcess, generation: generation) else {
                return exitCode
            }
            process = nil
            shutdownTask = nil
            onTermination?(exitCode ?? expectedProcess.terminationStatus)
            return exitCode
        } catch {
            guard isCurrent(expectedProcess, generation: generation) else {
                throw error
            }
            shutdownTask = nil
            throw error
        }
    }
    private func cancelAndWaitForEventTask(generation: Int) async {
        guard eventTaskGeneration == generation, let eventTask else {
            return
        }
        eventTask.cancel()
        await eventTask.value
        guard eventTaskGeneration == generation else {
            return
        }
        self.eventTask = nil
        eventTaskGeneration = nil
    }

    private func didTerminate(_ expectedProcess: Process, generation: Int, exitCode _: Int32) {
        guard isCurrent(expectedProcess, generation: generation) else {
            return
        }
        if shutdownTask == nil {
            stopChild(expectedProcess, generation: generation)
        }
    }

    private func isCurrent(_ expectedProcess: Process, generation: Int) -> Bool {
        self.generation == generation && process === expectedProcess
    }
}

private extension BackendEvent {
    var displayLine: String {
        switch self {
        case .phaseChange(let phase, _):
            return "[phase] \(phase)"
        case .interviewQuestion(let question):
            return "[question] \(question.text)"
        case .councilRoundStart(let round, let layer):
            return "[round \(round)] start \(layer ?? "")"
        case .councilPersonaToken(let persona, let delta):
            return "[\(persona)] \(delta)"
        case .councilRoundDone(let round, let score):
            if let score {
                return "[round \(round)] done score=\(score)"
            }
            return "[round \(round)] done"
        case .reportChunk(let section, let markdown):
            return "[report \(section ?? "chunk")] \(markdown)"
        case .done(let reportPath):
            return "[done] \(reportPath ?? "")"
        case .error(let message):
            return "[error] \(message)"
        case .unknown(let name, _):
            return "[unsupported] \(name)"
        }
    }
}
