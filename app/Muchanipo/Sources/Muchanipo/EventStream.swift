import Foundation

enum NDJSONFrameError: Error, Equatable {
    case frameTooLarge(limit: Int)
}

struct EventStream: AsyncSequence {
    typealias Element = BackendEvent

    private let fileHandle: FileHandle
    private let decoder: JSONDecoder
    private let maximumFrameLength: Int

    init(
        fileHandle: FileHandle,
        decoder: JSONDecoder = JSONDecoder(),
        maximumFrameLength: Int = NDJSONFrameDecoder.defaultMaximumFrameLength
    ) {
        self.fileHandle = fileHandle
        self.decoder = decoder
        self.maximumFrameLength = maximumFrameLength
    }

    init(
        pipe: Pipe,
        decoder: JSONDecoder = JSONDecoder(),
        maximumFrameLength: Int = NDJSONFrameDecoder.defaultMaximumFrameLength
    ) {
        self.init(
            fileHandle: pipe.fileHandleForReading,
            decoder: decoder,
            maximumFrameLength: maximumFrameLength
        )
    }

    func makeAsyncIterator() -> Iterator {
        Iterator(
            fileHandle: fileHandle,
            decoder: decoder,
            maximumFrameLength: maximumFrameLength
        )
    }
}

struct ScientificEventStream: AsyncSequence {
    typealias Element = ScientificEnvelope

    private let fileHandle: FileHandle
    private let decoder: JSONDecoder
    private let maximumFrameLength: Int

    init(
        fileHandle: FileHandle,
        decoder: JSONDecoder = JSONDecoder(),
        maximumFrameLength: Int = NDJSONFrameDecoder.defaultMaximumFrameLength
    ) {
        self.fileHandle = fileHandle
        self.decoder = decoder
        self.maximumFrameLength = maximumFrameLength
    }

    init(
        pipe: Pipe,
        decoder: JSONDecoder = JSONDecoder(),
        maximumFrameLength: Int = NDJSONFrameDecoder.defaultMaximumFrameLength
    ) {
        self.init(
            fileHandle: pipe.fileHandleForReading,
            decoder: decoder,
            maximumFrameLength: maximumFrameLength
        )
    }

    func makeAsyncIterator() -> Iterator {
        Iterator(
            fileHandle: fileHandle,
            decoder: decoder,
            maximumFrameLength: maximumFrameLength
        )
    }
}

extension EventStream {
    struct Iterator: AsyncIteratorProtocol {
        private var iterator: NDJSONAsyncIterator<BackendEvent>

        init(fileHandle: FileHandle, decoder: JSONDecoder, maximumFrameLength: Int) {
            iterator = NDJSONAsyncIterator(
                fileHandle: fileHandle,
                decoder: decoder,
                maximumFrameLength: maximumFrameLength
            )
        }

        mutating func next() async throws -> BackendEvent? {
            try await iterator.next()
        }
    }
}

extension ScientificEventStream {
    struct Iterator: AsyncIteratorProtocol {
        private var iterator: NDJSONAsyncIterator<ScientificEnvelope>

        init(fileHandle: FileHandle, decoder: JSONDecoder, maximumFrameLength: Int) {
            iterator = NDJSONAsyncIterator(
                fileHandle: fileHandle,
                decoder: decoder,
                maximumFrameLength: maximumFrameLength
            )
        }

        mutating func next() async throws -> ScientificEnvelope? {
            try await iterator.next()
        }
    }
}

private struct NDJSONAsyncIterator<Element: Decodable>: AsyncIteratorProtocol {
    private let fileHandle: FileHandle
    private let decoder: JSONDecoder
    private var framing: NDJSONFrameDecoder

    init(fileHandle: FileHandle, decoder: JSONDecoder, maximumFrameLength: Int) {
        self.fileHandle = fileHandle
        self.decoder = decoder
        framing = NDJSONFrameDecoder(maximumFrameLength: maximumFrameLength)
    }

    mutating func next() async throws -> Element? {
        while true {
            try Task.checkCancellation()

            if let frame = try framing.popFrame() {
                try Task.checkCancellation()
                if frame.isEmpty {
                    continue
                }
                return try decoder.decode(Element.self, from: frame)
            }

            if framing.isEOF {
                return nil
            }

            let chunk = try await fileHandle.nextChunk()
            try Task.checkCancellation()
            if chunk.isEmpty {
                framing.finish()
            } else {
                try framing.append(chunk)
            }
        }
    }
}

private struct NDJSONFrameDecoder {
    static let defaultMaximumFrameLength = 1_048_576

    private let maximumFrameLength: Int
    private var buffer = Data()
    private(set) var isEOF = false

    init(maximumFrameLength: Int) {
        self.maximumFrameLength = maximumFrameLength
    }

    mutating func append(_ chunk: Data) throws {
        buffer.append(chunk)

        var frameStart = buffer.startIndex
        while let newline = buffer[frameStart...].firstIndex(of: 0x0A) {
            var frameEnd = newline
            if frameEnd > frameStart, buffer[buffer.index(before: frameEnd)] == 0x0D {
                frameEnd = buffer.index(before: frameEnd)
            }
            try validateLength(buffer.distance(from: frameStart, to: frameEnd))
            frameStart = buffer.index(after: newline)
        }
        var trailingEnd = buffer.endIndex
        if trailingEnd > frameStart, buffer[buffer.index(before: trailingEnd)] == 0x0D {
            trailingEnd = buffer.index(before: trailingEnd)
        }
        try validateLength(buffer.distance(from: frameStart, to: trailingEnd))
    }

    mutating func finish() {
        isEOF = true
    }

    mutating func popFrame() throws -> Data? {
        if let newline = buffer.firstIndex(of: 0x0A) {
            var frame = Data(buffer[..<newline])
            buffer.removeSubrange(...newline)
            if frame.last == 0x0D {
                frame.removeLast()
            }
            try validate(frame)
            return frame
        }

        guard isEOF else {
            if buffer.count > maximumFrameLength {
                throw NDJSONFrameError.frameTooLarge(limit: maximumFrameLength)
            }
            return nil
        }

        guard !buffer.isEmpty else {
            return nil
        }

        let frame = buffer
        buffer.removeAll()
        try validate(frame)
        return frame
    }

    private func validate(_ frame: Data) throws {
        try validateLength(frame.count)
    }

    private func validateLength(_ length: Int) throws {
        guard length <= maximumFrameLength else {
            throw NDJSONFrameError.frameTooLarge(limit: maximumFrameLength)
        }
    }
}

private extension FileHandle {
    func nextChunk() async throws -> Data {
        let read = FileHandleRead(fileHandle: self)
        return try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await read.value()
        }, onCancel: {
            read.cancel()
        })
    }
}

private final class FileHandleRead {
    private let fileHandle: FileHandle
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Data, Error>?
    private var source: DispatchSourceRead?
    private var completed = false

    init(fileHandle: FileHandle) {
        self.fileHandle = fileHandle
    }

    func value() async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            guard !completed else {
                lock.unlock()
                continuation.resume(throwing: CancellationError())
                return
            }
            self.continuation = continuation
            let source = DispatchSource.makeReadSource(
                fileDescriptor: fileHandle.fileDescriptor,
                queue: DispatchQueue.global(qos: .userInitiated)
            )
            self.source = source
            source.setEventHandler { [weak self] in
                self?.readReady()
            }
            lock.unlock()
            source.resume()
        }
    }

    func cancel() {
        complete(.failure(CancellationError()))
    }

    private func readReady() {
        do {
            let data = try fileHandle.read(upToCount: 64 * 1024) ?? Data()
            complete(.success(data))
        } catch {
            complete(.failure(error))
        }
    }

    private func complete(_ result: Result<Data, Error>) {
        lock.lock()
        guard !completed else {
            lock.unlock()
            return
        }
        completed = true
        let continuation = self.continuation
        self.continuation = nil
        let source = self.source
        self.source = nil
        lock.unlock()

        source?.cancel()
        continuation?.resume(with: result)
    }
}