"""hooks/call-sim.py — scripted test calls against a phone / voice assistant."""

from __future__ import annotations

import io
import json
import shutil
import threading
import wave
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import py, write_json

GREETING = "Willkommen bei Servicehafen. Sie sprechen mit unserem digitalen Assistenten, einer KI."


def wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


class Assistant(BaseHTTPRequestHandler):
    """A tiny rule-based assistant with the /api/voice/simulate contract."""
    greeting = GREETING
    slow_ms = 0
    long_reply = False
    smalltalk_fallback = False
    complaint_fallback = False
    memory = True
    sessions: dict = {}
    tts = "elevenlabs"          # X-Voice-Provider; "503" = no provider configured
    letters_per_s = 13.0

    def log_message(self, *args):
        pass

    def speak(self, text: str):
        if self.tts == "503":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error":"no TTS provider configured"}')
            return
        letters = sum(ch.isalnum() for ch in text)
        data = wav(letters / self.letters_per_s)
        self.send_response(200)
        self.send_header("content-type", "audio/wav")
        self.send_header("x-voice-provider", self.tts)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/api/voice/tts":
            return self.speak(body["text"])
        text = body["text"].lower()
        last = self.sessions.setdefault(body["session_id"], {})
        if self.slow_ms:
            time.sleep(self.slow_ms / 1000)
        if not text:
            out = {"reply": self.greeting, "intent": "greeting"}
        elif any(w in text for w in ("hallo", "moment")) and "mensch" not in text:
            out = {"reply": "Wie bitte? Das habe ich leider nicht verstanden." if self.smalltalk_fallback
                   else "Hallo! Wie kann ich Ihnen helfen?", "intent": None if self.smalltalk_fallback else "smalltalk"}
        elif "falsch geliefert" in text:
            out = ({"reply": "Wie bitte? Das habe ich leider nicht verstanden.", "intent": None} if self.complaint_fallback
                   else {"reply": "Das tut mir leid. Ich lege ein Ticket an, ein Kollege meldet sich heute.",
                         "intent": "complaint", "action": {"type": "create_ticket"}})
        elif "wann kommt" in text:
            order = last.get("order") if self.memory else None
            out = ({"reply": f"Ihre Bestellung {order} kommt am Mittwoch.", "intent": "order_status"} if order
                   else {"reply": "Gern. Wie lautet Ihre Bestellnummer?", "intent": "order_status"})
        elif "geöffnet" in text:
            reply = "Wir sind Montag bis Freitag von 8 bis 18 Uhr für Sie da."
            out = {"reply": reply * (20 if self.long_reply else 1), "intent": "opening_hours"}
        elif "bestellung" in text:
            last["order"] = "4711"
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
    Assistant.smalltalk_fallback, Assistant.tts, Assistant.letters_per_s = False, "elevenlabs", 13.0
    Assistant.complaint_fallback, Assistant.memory, Assistant.sessions = False, True, {}


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
    assert "6/6 calls passed" in r.stdout and "Small talk (built-in)" in r.stdout
    assert "Complaint (built-in)" in r.stdout and "Follow-up question (built-in)" in r.stdout
    report = json.loads((p / ".onecommand" / "calls" / "report.json").read_text())
    assert report["passed"] and report["turns"] == 10 and report["latency_ms_p95"] is not None
    assert report["audio"] is None
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


def test_smalltalk_answered_with_not_understood_fails(tmp_path, server):
    Assistant.smalltalk_fallback = True
    r = sim("run", "--project-dir", str(project(tmp_path)), "--base-url", server)
    assert r.returncode == 1
    assert "answers small talk with 'not understood'" in r.stdout and "'Hallo?'" in r.stdout


def test_smalltalk_probe_can_be_switched_off(tmp_path, server):
    Assistant.smalltalk_fallback = True
    r = sim("run", "--project-dir", str(project(tmp_path, smalltalk=[])), "--base-url", server)
    assert r.returncode == 0 and "5/5 calls passed" in r.stdout


def test_twiml_say_and_robotic_engines_fail_validation(tmp_path):
    p = project(tmp_path)
    route = p / "app" / "api" / "voice" / "dtmf" / "route.ts"
    route.parent.mkdir(parents=True)
    route.write_text('const xml = `<Response><Say language="de-DE">${reply}</Say></Response>`;\n')
    (p / "lib").mkdir()
    (p / "lib" / "tts.py").write_text('subprocess.run(["espeak-ng", "-v", "de", text])\n# espeak would be robotic\n')
    r = sim("validate", "--project-dir", str(p))
    assert r.returncode == 1
    assert "app/api/voice/dtmf/route.ts:1: TwiML <Say>" in r.stdout
    assert "lib/tts.py:1: robotic speech engine" in r.stdout and "tts.py:2" not in r.stdout


def test_turn_that_checks_only_length_is_rejected(tmp_path):
    sc = {"hallo": {"name": "Hallo", "turns": [{"say": "Hallo", "expect": {"max_chars": 300}}]}, **SCENARIOS}
    r = sim("validate", "--project-dir", str(project(tmp_path, sc, intents=[])))
    assert r.returncode == 1 and "hallo.json turn 1: checks only length/latency" in r.stdout


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_voice_samples_are_saved_for_listening(tmp_path, server):
    p = project(tmp_path, tts_endpoint="/api/voice/tts")
    r = sim("run", "--project-dir", str(p), "--base-url", server)
    assert r.returncode == 0, r.stdout
    assert "voice: " in r.stdout and "(elevenlabs" in r.stdout
    audio = json.loads((p / ".onecommand" / "calls" / "report.json").read_text())["audio"]
    assert audio["status"] == "ok" and len(audio["files"]) == 11     # greeting + 10 replies
    assert (p / ".onecommand" / "calls" / "audio" / "greeting.wav").exists()
    assert all(12 <= a["letters_per_s"] <= 14 for a in audio["files"])
    md = (p / ".onecommand" / "calls" / "report.md").read_text()
    assert "## 🔊 Voice samples" in md and "(audio/greeting.wav)" in md


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_rushed_speech_fails(tmp_path, server):
    Assistant.letters_per_s = 60
    r = sim("run", "--project-dir", str(project(tmp_path, tts_endpoint="/api/voice/tts")), "--base-url", server)
    assert r.returncode == 1 and "letters/s — speech is too fast" in r.stdout


@pytest.mark.parametrize("provider,code,message", [
    ("503", 0, "no voice provider configured"),
    ("fake", 0, "no voice provider configured"),
    ("espeak-ng", 1, "is a robotic engine"),
])
def test_voice_provider_states(tmp_path, server, provider, code, message):
    Assistant.tts = provider
    r = sim("run", "--project-dir", str(project(tmp_path, tts_endpoint="/api/voice/tts")), "--base-url", server)
    assert r.returncode == code and message in r.stdout


def test_complaint_answered_with_not_understood_fails(tmp_path, server):
    Assistant.complaint_fallback = True
    r = sim("run", "--project-dir", str(project(tmp_path)), "--base-url", server)
    assert r.returncode == 1 and "answers a complaint with 'not understood'" in r.stdout


def test_followup_without_memory_fails(tmp_path, server):
    Assistant.memory = False
    r = sim("run", "--project-dir", str(project(tmp_path)), "--base-url", server)
    assert r.returncode == 1
    assert "asks again for the number the caller already gave (4711)" in r.stdout


def test_followup_probe_needs_a_scenario_with_a_number(tmp_path, server):
    sc = {k: v for k, v in SCENARIOS.items() if k != "bestellung"}
    r = sim("run", "--project-dir", str(project(tmp_path, sc, intents=[])), "--base-url", server)
    assert r.returncode == 0 and "⚠ no follow-up probe" in r.stdout
    custom = {**sc, "termin": {"name": "Termin", "turns": [
        {"say": "Mein Termin 2024 ist wann?", "expect": {"intent": "appointment"}}]}}
    r = sim("run", "--project-dir", str(project(tmp_path, custom, intents=[],
                                                followup={"after_intent": "appointment", "then": ["Und wann kommt es?"]})),
            "--base-url", server)
    assert "Follow-up question (built-in)" in r.stdout
