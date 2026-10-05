#!/usr/bin/env python3
"""OneCommand call simulator — test calls against a phone/voice support assistant.

A phone assistant is only done when real conversations work: it greets with the AI
disclosure, understands what callers want, answers briefly and correctly from the
company's knowledge, triggers the right action, hands over to a human when it should
— and answers fast enough for a phone line.

The assistant exposes a text endpoint next to its telephony webhooks (spec "voice"):

  POST <endpoint>  {"session_id": "...", "text": "...", "caller": "+4930123456"}
  → {"reply": "...", "intent": "...", "handover": false, "end_call": false, "action": {"type": "..."}}

An empty "text" starts the call (greeting). Scenarios live in <scenarios>/*.json:

  {"name": "Bestellstatus", "caller": "+4930111222",
   "turns": [
     {"say": "Wo ist meine Bestellung 4711?",
      "expect": {"intent": "order_status", "reply_contains": ["4711", "unterwegs"],
                 "action": "lookup_order", "max_ms": 1500}},
     {"say": "Ich möchte mit einem Menschen sprechen", "expect": {"handover": true}}
   ]}

expect: intent · reply_contains (all) · reply_contains_any · reply_not_contains · action (type) ·
        handover · end_call · max_ms · max_chars (default spec voice.max_reply_chars, 300)

Every call additionally checks the greeting: it must contain one of voice.disclosure
("KI", "digitaler Assistent" …) — callers must know they talk to an AI.

Subcommands
-----------
validate   check spec "voice" and the scenario files
run        start the production server (or use --base-url) and play every scenario

Exit codes: 0 ok · 1 failures · 2 usage error · 3 not applicable (no "voice" in the spec)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

EXPECT_KEYS = {"intent", "reply_contains", "reply_contains_any", "reply_not_contains", "action", "handover",
               "end_call", "max_ms", "max_chars"}
DEFAULT_DISCLOSURE = ["KI", "künstliche Intelligenz", "digitaler Assistent", "digitale Assistentin", "virtueller Assistent", "AI"]


def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"[call-sim] {what} not found: {path}") from None
    except ValueError as exc:
        raise SystemExit(f"[call-sim] {what} is not valid JSON ({path}): {exc}") from None


def voice_cfg(spec: dict[str, Any]) -> dict[str, Any] | None:
    v = spec.get("voice")
    return v if isinstance(v, dict) else None


def load_scenarios(project: Path, v: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    folder = project / v.get("scenarios", "voice/scenarios")
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        return [], [f"no scenarios in {folder.relative_to(project) if folder.is_relative_to(project) else folder} "
                    f"— write one JSON file per call (see call-sim.py --help)"]
    scenarios = []
    for f in files:
        try:
            sc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{f.name}: invalid JSON: {exc}")
            continue
        sc["_file"] = f.name
        if not sc.get("name") or not isinstance(sc.get("turns"), list) or not sc["turns"]:
            errors.append(f"{f.name}: needs 'name' and a non-empty 'turns' list")
            continue
        for i, turn in enumerate(sc["turns"]):
            if not isinstance(turn, dict) or not str(turn.get("say", "")).strip():
                errors.append(f"{f.name} turn {i + 1}: 'say' is required")
                continue
            unknown = set(turn.get("expect", {})) - EXPECT_KEYS
            if unknown:
                errors.append(f"{f.name} turn {i + 1}: unknown expect key(s) {', '.join(sorted(unknown))}")
            if not turn.get("expect"):
                errors.append(f"{f.name} turn {i + 1}: 'expect' is empty — every turn checks something")
        scenarios.append(sc)
    return scenarios, errors


def validate(spec: dict[str, Any], project: Path) -> list[str]:
    v = voice_cfg(spec)
    if v is None:
        return []
    errors = []
    if not str(v.get("endpoint", "")).startswith("/"):
        errors.append("voice.endpoint must be a path like /api/voice/simulate")
    scenarios, problems = load_scenarios(project, v)
    errors += problems
    intents = set(v.get("intents") or [])
    covered = {t.get("expect", {}).get("intent") for s in scenarios for t in s["turns"]} - {None}
    if intents and intents - covered:
        errors.append(f"intents without a test call: {', '.join(sorted(intents - covered))}")
    if scenarios and not any(t.get("expect", {}).get("handover") for s in scenarios for t in s["turns"]):
        errors.append("no scenario tests the handover to a human")
    return errors


# ─── run ──────────────────────────────────────────────────────────────────────

def post(url: str, body: dict[str, Any], timeout: int) -> tuple[int, Any, float]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local or given URL
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc), (time.monotonic() - start) * 1000
    ms = (time.monotonic() - start) * 1000
    try:
        return status, json.loads(raw), ms
    except ValueError:
        return status, raw, ms


def check_turn(resp: Any, ms: float, expect: dict[str, Any], defaults: dict[str, Any]) -> list[str]:
    if not isinstance(resp, dict) or not isinstance(resp.get("reply"), str):
        return [f"response is not {{\"reply\": …}}: {str(resp)[:200]}"]
    fails = []
    reply = resp["reply"]
    low = reply.lower()
    if "intent" in expect and resp.get("intent") != expect["intent"]:
        fails.append(f"intent '{resp.get('intent')}', expected '{expect['intent']}'")
    for word in expect.get("reply_contains", []):
        if word.lower() not in low:
            fails.append(f"reply lacks '{word}'")
    any_of = expect.get("reply_contains_any")
    if any_of and not any(w.lower() in low for w in any_of):
        fails.append(f"reply contains none of {any_of}")
    for word in expect.get("reply_not_contains", []):
        if word.lower() in low:
            fails.append(f"reply must not contain '{word}'")
    if "action" in expect:
        got = (resp.get("action") or {}).get("type") if isinstance(resp.get("action"), dict) else resp.get("action")
        if got != expect["action"]:
            fails.append(f"action '{got}', expected '{expect['action']}'")
    for flag in ("handover", "end_call"):
        if flag in expect and bool(resp.get(flag)) != bool(expect[flag]):
            fails.append(f"{flag} is {bool(resp.get(flag))}, expected {bool(expect[flag])}")
    max_ms = expect.get("max_ms", defaults["max_ms"])
    if max_ms and ms > max_ms:
        fails.append(f"answered in {ms:.0f} ms, budget {max_ms} ms")
    max_chars = expect.get("max_chars", defaults["max_chars"])
    if max_chars and len(reply) > max_chars:
        fails.append(f"reply has {len(reply)} characters, max {max_chars} — callers cannot listen to long texts")
    return fails


def play(base: str, v: dict[str, Any], sc: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    url = base.rstrip("/") + v["endpoint"]
    session = f"sim-{uuid.uuid4().hex[:10]}"
    caller = sc.get("caller", "+4930000000")
    record: dict[str, Any] = {"name": sc["name"], "file": sc["_file"], "session": session, "turns": [], "failures": []}
    status, resp, ms = post(url, {"session_id": session, "text": "", "caller": caller}, defaults["timeout"])
    greeting = resp.get("reply", "") if isinstance(resp, dict) else ""
    record["greeting"] = {"reply": greeting, "ms": round(ms)}
    if status != 200:
        record["failures"].append(f"call start: HTTP {status}: {str(resp)[:200]}")
        return record
    disclosure = v.get("disclosure") or DEFAULT_DISCLOSURE
    if not any(w.lower() in greeting.lower() for w in disclosure):
        record["failures"].append(f"greeting does not say it is an AI (none of {disclosure}): '{greeting[:160]}'")
    for i, turn in enumerate(sc["turns"], 1):
        status, resp, ms = post(url, {"session_id": session, "text": turn["say"], "caller": caller}, defaults["timeout"])
        fails = [f"HTTP {status}: {str(resp)[:200]}"] if status != 200 else check_turn(resp, ms, turn["expect"], defaults)
        record["turns"].append({"say": turn["say"], "reply": resp.get("reply") if isinstance(resp, dict) else None,
                                "intent": resp.get("intent") if isinstance(resp, dict) else None,
                                "ms": round(ms), "failures": fails})
        record["failures"] += [f"turn {i} ('{turn['say'][:40]}'): {f}" for f in fails]
        if status != 200:
            break
    return record


def ui_tour_module():
    spec = importlib.util.spec_from_file_location("oc_ui_tour", Path(__file__).with_name("ui-tour.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_validate(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec = load_json(project / args.spec if not os.path.isabs(args.spec) else Path(args.spec), "spec")
    if voice_cfg(spec) is None:
        print("[call-sim] spec has no voice section — not applicable")
        return 3
    errors = validate(spec, project)
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        return 1
    scenarios, _ = load_scenarios(project, spec["voice"])
    print(f"[call-sim] valid — {len(scenarios)} scenario(s), {sum(len(s['turns']) for s in scenarios)} turns")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec = load_json(project / args.spec if not os.path.isabs(args.spec) else Path(args.spec), "spec")
    v = voice_cfg(spec)
    if v is None:
        print("[call-sim] spec has no voice section — not applicable")
        return 3
    errors = validate(spec, project)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    scenarios, _ = load_scenarios(project, v)
    defaults = {"max_ms": v.get("max_ms", 2000), "max_chars": v.get("max_reply_chars", 300), "timeout": args.timeout}
    out = Path(args.out).resolve() if args.out else project / ".onecommand" / "calls"
    out.mkdir(parents=True, exist_ok=True)

    server = None
    base = args.base_url
    try:
        if not base:
            tour = ui_tour_module()
            server = tour.Server(project, tour.free_port(args.port), out / "server.log",
                                 {"ONECOMMAND_E2E": "1"} if v.get("test_mode", True) else {})
            print(f"[call-sim] ▶ production server on port {server.port}", flush=True)
            problem = server.start(args.start_timeout)
            if problem:
                print(f"  ✗ {problem}")
                return 1
            base = server.base_url
        results = []
        for sc in scenarios:
            rec = play(base, v, sc, defaults)
            results.append(rec)
            mark = "✓" if not rec["failures"] else "✗"
            slowest = max([t["ms"] for t in rec["turns"]] + [rec["greeting"]["ms"]])
            print(f"  {mark} {rec['name']} — {len(rec['turns'])} turn(s), slowest {slowest} ms")
            for f in rec["failures"]:
                print(f"      ✗ {f}")
    finally:
        if server:
            server.stop()

    failed = [r for r in results if r["failures"]]
    latencies = sorted(t["ms"] for r in results for t in r["turns"])
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    report = {"version": 1, "passed": not failed, "scenarios": len(results), "failed": len(failed),
              "turns": len(latencies), "latency_ms_p95": p95, "results": results}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [f"# Test calls — {spec.get('project_name', 'assistant')}", "",
          f"{len(results) - len(failed)}/{len(results)} calls passed · {len(latencies)} turns · p95 latency {p95} ms", ""]
    for r in results:
        md += [f"## {'✅' if not r['failures'] else '❌'} {r['name']}", "", f"**Assistant:** {r['greeting']['reply']}", ""]
        for t in r["turns"]:
            md += [f"**Caller:** {t['say']}  ", f"**Assistant** ({t['intent']}, {t['ms']} ms): {t['reply']}", ""]
            md += [f"- ✗ {f}" for f in t["failures"]]
        md += [f"- ✗ {f}" for f in r["failures"] if not f.startswith("turn ")] + [""]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[call-sim] {len(results) - len(failed)}/{len(results)} calls passed, p95 {p95} ms — {out / 'report.md'}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("validate", cmd_validate), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        p.add_argument("--spec", default=".onecommand-spec.json")
        if name == "run":
            p.add_argument("--base-url", help="use a running assistant instead of starting `npm run start`")
            p.add_argument("--out", help="default <project>/.onecommand/calls")
            p.add_argument("--port", type=int, default=3230)
            p.add_argument("--start-timeout", type=int, default=120)
            p.add_argument("--timeout", type=int, default=30, help="seconds per request")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
