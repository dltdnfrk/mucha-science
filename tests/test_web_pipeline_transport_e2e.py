from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
import signal
import subprocess
from threading import Thread

from websockets.sync.client import connect


REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_EXECUTABLE = REPO_ROOT / "bin" / "muchanipo-web"
WEB_PROTOCOL = "mucha-science.web.v1"
RUN_ID = "run_00000000000000000000000000000001"


def read_line(process: subprocess.Popen[str], timeout: float = 5) -> str:
    stdout = process.stdout
    assert stdout is not None
    lines: Queue[str] = Queue(maxsize=1)
    reader = Thread(target=lambda: lines.put(stdout.readline()), daemon=True)
    reader.start()
    return lines.get(timeout=timeout)


def stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=2)


def receive_until(
    client: object,
    terminal_event: str,
    *,
    limit: int = 80,
) -> list[dict[str, object]]:
    received: list[dict[str, object]] = []
    for _ in range(limit):
        message = client.recv(timeout=5)  # type: ignore[attr-defined]
        event = json.loads(message)
        received.append(event)
        if event.get("event") == terminal_event:
            return received
    raise AssertionError(f"event {terminal_event!r} was not received")


def test_browser_transport_runs_pipeline_streams_events_and_replays(
    tmp_path: Path,
) -> None:
    # Given a browser-facing web server and an offline pipeline
    home = tmp_path / "home"
    home.mkdir()
    process = subprocess.Popen(
        [
            str(WEB_EXECUTABLE),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--scientific-home",
            str(home),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        readiness = json.loads(read_line(process))
        with connect(readiness["url"], origin="http://127.0.0.1:1420") as command:
            command.send(json.dumps({
                "protocol": WEB_PROTOCOL,
                "type": "run.start",
                "run_id": RUN_ID,
                "topic": "브라우저 연구 실행 검증",
                "pipeline": "stub",
                "depth": "shallow",
                "environment": {"MUCHANIPO_OFFLINE": "1"},
            }))
            started = json.loads(command.recv(timeout=5))

        # When a browser subscribes, answers the inline interview, and waits
        with connect(readiness["url"], origin="http://127.0.0.1:1420") as stream:
            stream.send(json.dumps({
                "protocol": WEB_PROTOCOL,
                "type": "run.subscribe",
                "run_id": RUN_ID,
                "after_sequence": -1,
            }))
            before_answer = receive_until(stream, "interview_question")

            with connect(readiness["url"], origin="http://127.0.0.1:1420") as action:
                action.send(json.dumps({
                    "protocol": WEB_PROTOCOL,
                    "type": "run.action",
                    "run_id": RUN_ID,
                    "generation": 1,
                    "action": {
                        "action": "interview_answer",
                        "q_id": "Q1",
                        "answer": "브라우저에서 실제 보고서를 만든다",
                    },
                }))
                action_response = json.loads(action.recv(timeout=5))

            after_answer = receive_until(stream, "done")

        # Then the stream is real pipeline output and a fresh browser can replay it
        events = [*before_answer, *after_answer]
        assert started["type"] == "run.started"
        assert started["receipt"]["app_run_id"] == RUN_ID
        assert started["receipt"]["generation"] == 1
        assert action_response == {
            "protocol": WEB_PROTOCOL,
            "type": "run.action.accepted",
            "run_id": RUN_ID,
            "generation": 1,
        }
        assert [event["sequence"] for event in events] == list(range(len(events)))
        assert all(event["app_run_id"] == RUN_ID for event in events)
        assert all(event["generation"] == 1 for event in events)
        assert any(event["event"] == "report_chunk" for event in events)

        replay_cursor = events[-3]["sequence"]
        with connect(readiness["url"], origin="http://127.0.0.1:1420") as replay:
            replay.send(json.dumps({
                "protocol": WEB_PROTOCOL,
                "type": "run.subscribe",
                "run_id": RUN_ID,
                "after_sequence": replay_cursor,
            }))
            replayed = receive_until(replay, "done")
        assert [event["sequence"] for event in replayed] == [
            event["sequence"]
            for event in events
            if event["sequence"] > replay_cursor
        ]
    finally:
        _, stderr = stop_process(process)

    assert process.returncode == 130, stderr
