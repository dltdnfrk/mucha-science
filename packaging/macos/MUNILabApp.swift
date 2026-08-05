import AppKit
import Network

final class BundleServer {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "ai.muni.lab.bundle-server")
    private let root: URL

    init(root: URL) throws {
        self.root = root
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        listener = try NWListener(using: parameters)
    }

    func start(onReady: @escaping (URL) -> Void) {
        listener.newConnectionHandler = { [weak self] connection in
            self?.serve(connection)
        }
        listener.stateUpdateHandler = { [weak self] state in
            guard case .ready = state, let port = self?.listener.port else {
                return
            }
            DispatchQueue.main.async {
                onReady(URL(string: "http://127.0.0.1:\(port.rawValue)/#/scientific")!)
            }
        }
        listener.start(queue: queue)
    }

    private func serve(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) {
            [weak self] data, _, _, _ in
            guard let self, let data, let request = String(data: data, encoding: .utf8) else {
                connection.cancel()
                return
            }
            self.respond(to: request, through: connection)
        }
    }

    private func respond(to request: String, through connection: NWConnection) {
        let requestLine = request.split(separator: "\r\n", maxSplits: 1).first.map(String.init) ?? ""
        let parts = requestLine.split(separator: " ")
        guard parts.count >= 2, parts[0] == "GET" || parts[0] == "HEAD" else {
            send(status: "405 Method Not Allowed", data: Data(), type: "text/plain", through: connection)
            return
        }

        let rawPath = String(parts[1]).split(separator: "?", maxSplits: 1).first.map(String.init) ?? "/"
        let decodedPath = rawPath.removingPercentEncoding ?? rawPath
        let relativePath = decodedPath == "/" ? "index.html" : String(decodedPath.dropFirst())
        guard !relativePath.isEmpty, !relativePath.contains("..") else {
            send(status: "400 Bad Request", data: Data(), type: "text/plain", through: connection)
            return
        }

        let fileURL = root.appendingPathComponent(relativePath)
        guard let data = try? Data(contentsOf: fileURL) else {
            send(status: "404 Not Found", data: Data(), type: "text/plain", through: connection)
            return
        }
        let body = parts[0] == "HEAD" ? Data() : data
        send(status: "200 OK", data: body, type: mimeType(for: fileURL.pathExtension), through: connection)
    }

    private func send(
        status: String,
        data: Data,
        type: String,
        through connection: NWConnection
    ) {
        let header = """
        HTTP/1.1 \(status)\r
        Content-Type: \(type)\r
        Content-Length: \(data.count)\r
        Cache-Control: no-cache\r
        Connection: close\r
        \r

        """
        var response = Data(header.utf8)
        response.append(data)
        connection.send(content: response, isComplete: true, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func mimeType(for extensionName: String) -> String {
        switch extensionName {
        case "css": "text/css; charset=utf-8"
        case "html": "text/html; charset=utf-8"
        case "js": "text/javascript; charset=utf-8"
        case "json": "application/json; charset=utf-8"
        case "png": "image/png"
        case "svg": "image/svg+xml"
        case "webmanifest": "application/manifest+json; charset=utf-8"
        default: "application/octet-stream"
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var backendLogHandle: FileHandle?
    private var backendProcess: Process?
    private var launchURL: URL?
    private var server: BundleServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let resourceURL = Bundle.main.resourceURL else {
            NSApp.terminate(nil)
            return
        }

        do {
            try startBackend(resourceURL: resourceURL)
            let server = try BundleServer(root: resourceURL.appendingPathComponent("web"))
            self.server = server
            server.start { [weak self] url in
                self?.launchURL = url
                self?.openInDefaultBrowser()
            }
        } catch {
            NSAlert(error: error).runModal()
            NSApp.terminate(nil)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let backendProcess, backendProcess.isRunning {
            backendProcess.terminate()
            backendProcess.waitUntilExit()
        }
        try? backendLogHandle?.close()
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        openInDefaultBrowser()
        return true
    }

    private func openInDefaultBrowser() {
        guard let launchURL else {
            return
        }
        NSWorkspace.shared.open(launchURL)
    }

    private func startBackend(resourceURL: URL) throws {
        let projectRootFile = resourceURL.appendingPathComponent("project-root")
        let projectRootPath = try String(contentsOf: projectRootFile, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let projectRoot = URL(fileURLWithPath: projectRootPath, isDirectory: true)
        let python = projectRoot.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw NSError(domain: "ai.muni.lab.backend", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "MUNI lab backend Python was not found at \(python.path)",
            ])
        }

        let logs = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MUNI lab", isDirectory: true)
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appendingPathComponent("backend.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let logHandle = try FileHandle(forWritingTo: logURL)
        try logHandle.seekToEnd()

        let process = Process()
        process.executableURL = python
        process.arguments = [
            "-m",
            "src.muchanipo.web.websocket_server",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ]
        process.currentDirectoryURL = projectRoot
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        process.standardOutput = logHandle
        process.standardError = logHandle
        try process.run()

        backendLogHandle = logHandle
        backendProcess = process
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
