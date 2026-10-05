"""hooks/call-sim.py — scripted test calls against a phone / voice assistant."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import py, write_json

GREETING = "Willkommen bei Servicehafen. Sie sprechen mit unserem digitalen Assistenten, einer KI."


class Assistant(BaseHTTPRequestHandler):
    """A tiny rule-based assistant with the /api/voice/simulate contract."""
    greeting = GREETING
    slow_ms = 0
    long_reply = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        text = body["text"].lower()
        if self.slow_ms:
            time.sleep(self.slow_ms / 1000)
        if not text:
            out = {"reply": self.greeting, "intent": "greeting"}
        elif "geöffnet" in text:
            reply = "Wir sind Montag bis Freitag von 8 bis 18 Uhr für Sie da."
            out = {"reply": reply * (20 if self.long_reply else 1), "intent": "opening_hours"}
        elif "bestellung" in text:
            out = {"reply": "Ihre Bestellung 4711 ist unterwegs.", "intent": "order_status", "action": {"type": "lookup_order"}}
        elif "mensch" in text:
            out = {"reply": "Ich verbinde Sie mit einem Kollegen.", "intent": "handover", "handover": True}
        else:
            out = {"reply": "Danke für Ihren Anruf, auf Wiederhören.", "intent": "goodbye", "end_call": True}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Assistant)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    Assistant.greeting, Assistant.slow_ms, Assistant.long_reply = GREETING, 0, False


SCENARIOS = {
    "oeffnungszeiten": {"name": "Öffnungszeiten", "turns": [
        {"say": "Wann habt ihr geöffnet?", "expect": {"intent": "opening_hours", "reply_contains": ["8", "18"]}},
        {"say": "Danke, tschüss", "expect": {"intent": "goodbye", "end_call": True}}]},
    "bestellung": {"name": "Bestellstatus", "caller": "+4930111222", "turns": [
        {"say": "Wo ist meine Bestellung 4711?", "expect": {"intent": "order_status", "action": "lookup_order",
                                                            "reply_contains": ["4711"], "reply_not_contains": ["storniert"]}}]},
    "mensch": {"name": "Übergabe", "turns": [
        {"say": "Ich will einen Menschen sprechen", "expect": {"handover": True, "intent": "handover"}}]},
}


def project(tmp_path: Path, scenarios: dict = SCENARIOS, **voice) -> Path:
    cfg = {"endpoint": "/api/voice/simulate", "scenarios": "voice/scenarios", "max_ms": 1500,
           "intents": ["opening_hours", "order_status", "handover", "goodbye"], **voice}
    write_json(tmp_path / ".onecommand-spec.json", {"project_name": "Servicehafen", "voice": cfg})
    for name, sc in scenarios.items():
        write_json(tmp_path / "voice" / "scenarios" / f"{name}.json", sc)
    return tmp_path


def sim(*args: str):
    return py("call-sim.py", *args, timeout=120)


def test_all_calls_pass(tmp_path, server):
    p = project(tmp_path)
    assert sim("validate", "--project-dir", str(p)).returncode == 0
    r = sim("run", "--project-dir", str(p), "--base-url", server)
    assert r.returncode == 0, r.stdout
    assert "3/3 calls passed" in r.stdout
    report = json.loads((p / ".onecommand" / "calls" / "report.json").read_text())
    assert report["passed"] and report["turns"] == 4 and report["latency_ms_p95"] is not None
    md = (p / ".onecommand" / "calls" / "report.md").read_text()
    assert "**Caller:** Wo ist meine Bestellung 4711?" in md and "digitalen Assistenten" in md


def test_greeting_without_ai_disclosure_fails(tmp_path, server):
    Assistant.greeting = "Willkommen bei Servicehafen, wie kann ich helfen?"
    r = sim("run", "--project-dir", str(project(tmp_path)), "--base-url", server)
    assert r.returncode == 1 and "greeting does not say it is an AI" in r.stdout


def test_wrong_expectations_are_reported_per_turn(tmp_path, server):
    sc = {"x": {"name": "Falsch", "turns": [
        {"say": "Wann habt ihr geöffnet?", "expect": {"intent": "order_status", "reply_contains": ["Samstag"],
                                                      "reply_not_contains": ["18 Uhr"]}},
        {"say": "Ich will einen Menschen", "expect": {"handover": False}}]}, "mensch": SCENARIOS["mensch"]}
    p = project(tmp_path, sc, intents=[])
    r = sim("run", "--project-dir", str(p), "--base-url", server)
    assert r.returncode == 1
    assert "intent 'opening_hours', expected 'order_status'" in r.stdout
    assert "reply lacks 'Samstag'" in r.stdout and "must not contain '18 Uhr'" in r.stdout
    assert "handover is True, expected False" in r.stdout


def test_long_and_slow_replies_fail(tmp_path, server):
    Assistant.long_reply, Assistant.slow_ms = True, 300
    p = project(tmp_path, max_ms=200)
    r = sim("run", "--project-dir", str(p), "--base-url", server)
    assert r.returncode == 1
    assert "callers cannot listen to long texts" in r.stdout and "budget 200 ms" in r.stdout


def test_validate_requires_handover_and_every_intent(tmp_path):
    sc = {"a": SCENARIOS["oeffnungszeiten"]}
    r = sim("validate", "--project-dir", str(project(tmp_path, sc)))
    assert r.returncode == 1
    assert "intents without a test call: handover, order_status" in r.stdout
    assert "no scenario tests the handover" in r.stdout


@pytest.mark.parametrize("scenario,message", [
    ({"name": "x", "turns": []}, "needs 'name' and a non-empty 'turns'"),
    ({"name": "x", "turns": [{"say": "Hallo"}]}, "'expect' is empty"),
    ({"name": "x", "turns": [{"say": "Hallo", "expect": {"mood": "happy"}}]}, "unknown expect key(s) mood"),
])
def test_invalid_scenarios(tmp_path, scenario, message):
    p = project(tmp_path, {"bad": scenario, **SCENARIOS}, intents=[])
    r = sim("validate", "--project-dir", str(p))
    assert r.returncode == 1 and message in r.stdout


def test_unreachable_assistant(tmp_path):
    r = sim("run", "--project-dir", str(project(tmp_path)), "--base-url", "http://127.0.0.1:9", "--timeout", "2")
    assert r.returncode == 1 and "call start: HTTP 0" in r.stdout


def test_no_voice_section_is_not_applicable(tmp_path):
    write_json(tmp_path / ".onecommand-spec.json", {"project_name": "web"})
    assert sim("run", "--project-dir", str(tmp_path)).returncode == 3
