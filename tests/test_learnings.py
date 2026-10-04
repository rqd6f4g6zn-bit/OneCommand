"""hooks/learnings.py — shared Claude/Codex memory and rule promotion."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import py


def L(mem: Path, *args: str):
    return py("learnings.py", "--memory-dir", str(mem), *args)


def record(mem: Path, error: str, fix: str = "npm i x", desc: str = "x missing", agent: str = "claude"):
    return L(mem, "record", "--error", error, "--fix", fix, "--description", desc, "--agent", agent)


def data(mem: Path) -> dict:
    return json.loads((mem / "cross_learnings.json").read_text())


def test_record_creates_and_reinforces_case_insensitively(tmp_path):
    mem = tmp_path / "mem"
    assert record(mem, "Cannot find module 'bcryptjs'").returncode == 0
    assert record(mem, "cannot find   module 'bcryptjs'", agent="codex").returncode == 0
    items = data(mem)["learnings"]
    assert len(items) == 1
    assert items[0]["confirmations"] == 2
    assert items[0]["confirmed_by"] == ["claude", "codex"]


def test_alternative_fix_is_kept(tmp_path):
    mem = tmp_path / "mem"
    record(mem, "E1", fix="npm i a")
    record(mem, "E1", fix="pnpm add a")
    assert data(mem)["learnings"][0]["alternative_fixes"] == ["pnpm add a"]


def test_evolve_promotes_at_threshold_and_keeps_earlier_rules(tmp_path):
    mem = tmp_path / "mem"
    for _ in range(3):
        record(mem, "Error A", desc="rule A")
    out = L(mem, "evolve")
    assert out.returncode == 0 and "1 learning(s) promoted" in out.stdout
    for _ in range(3):
        record(mem, "Error B", desc="rule B")
    L(mem, "evolve")
    rules = (mem / "evolved_rules.md").read_text()
    # Promoting B must not drop A (the pre-v1.4.1 code replaced the whole section).
    assert "rule A" in rules and "rule B" in rules
    assert all(l["applied_to_skill"] for l in data(mem)["learnings"])


def test_evolve_below_threshold_promotes_nothing(tmp_path):
    mem = tmp_path / "mem"
    record(mem, "Error A")
    out = L(mem, "evolve")
    assert "nothing to promote" in out.stdout
    assert not (mem / "evolved_rules.md").exists()


def test_read_filters_by_stack(tmp_path):
    mem = tmp_path / "mem"
    L(mem, "record", "--error", "E1", "--fix", "f", "--description", "prisma thing", "--stack", "Next.js + Prisma")
    L(mem, "record", "--error", "E2", "--fix", "f", "--description", "django thing", "--stack", "Django")
    out = L(mem, "read", "--stack", "prisma")
    assert "prisma thing" in out.stdout and "django thing" not in out.stdout


def test_corrupt_file_is_not_touched_by_reads_and_moved_aside_by_writes(tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "cross_learnings.json").write_text("{broken")
    assert L(mem, "stats").returncode == 1
    assert (mem / "cross_learnings.json").read_text() == "{broken"
    assert record(mem, "E1").returncode == 0
    assert any(p.name.startswith("cross_learnings.json.corrupt-") for p in mem.iterdir())
    assert len(data(mem)["learnings"]) == 1


def test_invalid_category_is_a_usage_error(tmp_path):
    out = L(tmp_path / "mem", "record", "--error", "e", "--fix", "f", "--description", "d", "--category", "nope")
    assert out.returncode == 2
