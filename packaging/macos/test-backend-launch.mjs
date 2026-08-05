import { execFileSync } from "node:child_process";
import { closeSync, mkdirSync, openSync, readFileSync, statSync, watch } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const appExecutable = join(
  homedir(),
  "Applications",
  "MUNI lab.app",
  "Contents",
  "MacOS",
  "MUNILab",
);
const logDirectory = join(homedir(), "Library", "Logs", "MUNI lab");
const logPath = join(logDirectory, "backend.log");
const keepAppRunning = process.env.KEEP_APP_RUNNING === "1";

mkdirSync(logDirectory, { recursive: true });
closeSync(openSync(logPath, "a"));
const initialLogSize = (() => {
  try {
    return statSync(logPath).size;
  } catch {
    return 0;
  }
})();

try {
  execFileSync("osascript", ["-e", 'tell application id "ai.muni.lab" to quit']);
} catch {
  // The app may not be running before the test.
}

let settled = false;
const finish = (error) => {
  if (settled) return;
  settled = true;
  clearTimeout(timeout);
  watcher.close();
  if (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
};

const verifyProtocol = () => {
  const socket = new WebSocket("ws://127.0.0.1:8765/api/pipeline");
  socket.onerror = () => finish(new Error("backend WebSocket connection failed"));
  socket.onopen = () => {
    socket.send(JSON.stringify({
      protocol: "mucha-science.web.v1",
      type: "runtime.status",
    }));
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(String(event.data));
    if (message.protocol === "mucha-science.web.v1" && message.type === "runtime.status") {
      console.log("installed app backend ready");
      if (keepAppRunning) {
        socket.close();
        finish();
        return;
      }
      socket.onclose = () => {
        console.log("installed app backend stopped");
        finish();
      };
      execFileSync("osascript", ["-e", 'tell application id "ai.muni.lab" to quit']);
    }
  };
};

const inspectLog = () => {
  try {
    const log = readFileSync(logPath, "utf8");
    if (log.length <= initialLogSize) return;
    const appended = log.slice(initialLogSize);
    if (appended.includes('"event":"muchanipo_web.ready"')) {
      verifyProtocol();
    }
  } catch {
    // The log file is created by the app after launch.
  }
};

const watcher = watch(logPath, inspectLog);
const timeout = setTimeout(
  () => finish(new Error("installed app did not start backend within 15 seconds")),
  15_000,
);

execFileSync("open", ["-a", "MUNI lab"]);
inspectLog();
