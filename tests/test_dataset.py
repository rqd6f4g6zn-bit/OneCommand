"""hooks/dataset.py — own training data: collect, clean, scrub, dedup, split, document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import py

LOREM = "Die Maschine läuft im Dreischichtbetrieb und wird jeden Montag gewartet. "


def ds(*args: str):
    return py("dataset.py", *args)


def records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    r = tmp_path / "raw"
    r.mkdir()
    for i in range(30):
        (r / f"doc{i:02d}.txt").write_text(f"Bericht {i}: {LOREM * 3} Ansprechpartner: max{i}@firma.de, Tel. +49 30 1234567{i}.")
    (r / "copy.txt").write_text((r / "doc00.txt").read_text())                    # exact duplicate
    (r / "near.txt").write_text((r / "doc01.txt").read_text().replace("Bericht 1:", "Bericht eins:"))  # near duplicate
    (r / "page.html").write_text("<html><head><style>p{}</style><script>x()</script></head><body><nav>Menü</nav>"
                                 "<h1>Wartung</h1><p>Die Anlage &amp; das Lager werden geprüft, IBAN DE89 3704 0044 0532 0130 00.</p>"
                                 "<p>" + LOREM * 2 + "</p></body></html>")
    (r / "notes.jsonl").write_text("\n".join(json.dumps({"text": f"Notiz {i}: {LOREM}"}) for i in range(5)))
    (r / "short.txt").write_text("zu kurz")
    return r


def test_build_text_corpus(tmp_path, raw):
    out = tmp_path / "out"
    r = ds("build", "--input", str(raw), "--out", str(out), "--task", "text", "--min-chars", "30")
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "manifest.json").read_text())
    p = m["processing"]
    assert p["exact_duplicates"] == 1 and p["near_duplicates"] == 1 and p["too_short_or_unlabelled"] == 1
    # scrubbed before dedup: 30 docs + the exact and the near copy
    assert p["pii_scrubbed"]["EMAIL"] == 32 and p["pii_scrubbed"]["TELEFON"] == 32 and p["pii_scrubbed"]["IBAN"] == 1
    assert m["records"] == 30 + 1 + 5  # 30 docs + html + 5 notes; the exact and the near copy are gone
    texts = " ".join(r["text"] for s in ("train", "val", "test") for r in records(out / f"{s}.jsonl"))
    assert "@firma.de" not in texts and "[EMAIL]" in texts and "[IBAN]" in texts
    assert "<p>" not in texts and "x()" not in texts and "Anlage & das Lager" in texts
    assert {s: m["outputs"][s]["records"] for s in ("val", "test")} == {"val": 4, "test": 4}
    assert "## Provenance" in (out / "DATASHEET.md").read_text()
    assert "very small corpus" in r.stdout
    assert ds("check", "--dir", str(out)).returncode == 0


def test_build_is_reproducible(tmp_path, raw):
    a, b = tmp_path / "a", tmp_path / "b"
    ds("build", "--input", str(raw), "--out", str(a))
    ds("build", "--input", str(raw), "--out", str(b))
    ma, mb = (json.loads((d / "manifest.json").read_text()) for d in (a, b))
    assert {k: v["sha256"] for k, v in ma["outputs"].items()} == {k: v["sha256"] for k, v in mb["outputs"].items()}


def test_check_detects_edits_and_leakage(tmp_path, raw):
    out = tmp_path / "out"
    ds("build", "--input", str(raw), "--out", str(out))
    test = records(out / "test.jsonl")
    with open(out / "train.jsonl", "a") as fh:
        fh.write(json.dumps({"id": "train-x", "text": test[0]["text"], "source": "x"}) + "\n")
    r = ds("check", "--dir", str(out))
    assert r.returncode == 1
    assert "train.jsonl changed since the build" in r.stdout
    assert "in both train and test" in r.stdout


def test_classification_from_folders_and_csv(tmp_path):
    raw = tmp_path / "raw"
    for label, word in (("rechnung", "Rechnung falsch"), ("technik", "Login kaputt")):
        (raw / label).mkdir(parents=True)
        for i in range(12):
            (raw / label / f"{i}.txt").write_text(f"{word} Fall {i} {'x' * i} bitte prüfen, Vorgang {i * 7}")
    (raw / "extra.csv").write_text("text,label\n" + "\n".join(f"Vertrag kündigen Nummer {i} zum Monatsende,vertrag" for i in range(3)))
    out = tmp_path / "out"
    r = ds("build", "--input", str(raw), "--out", str(out), "--task", "classification", "--near-dup", "1.0")
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "manifest.json").read_text())
    assert m["labels"] == {"rechnung": 12, "technik": 12, "vertrag": 3}
    assert "classes with fewer than 10 examples: vertrag" in r.stdout
    test_labels = {r["label"] for r in records(out / "test.jsonl")}
    assert test_labels == {"rechnung", "technik", "vertrag"}  # stratified: every class in test


def test_too_few_records_fails(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for i in range(3):
        (raw / f"{i}.txt").write_text(f"{LOREM} Nummer {i * 1000}")
    r = ds("build", "--input", str(raw), "--out", str(tmp_path / "out"), "--near-dup", "1.0")
    assert r.returncode == 1 and "need at least 10" in r.stdout


@pytest.mark.parametrize("args,message", [
    (["--split", "0.5,0.5"], "three ratios"),
    (["--input", "/does/not/exist"], "input not found"),
])
def test_usage_errors(tmp_path, raw, args, message):
    base = ["build", "--input", str(raw), "--out", str(tmp_path / "out")]
    r = ds(*(base + args))
    assert r.returncode == 2 and message in r.stderr


def test_csv_without_the_text_column(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.csv").write_text("body,label\nhallo,x\n")
    r = ds("build", "--input", str(raw), "--out", str(tmp_path / "out"))
    assert r.returncode == 2 and "no column 'text'" in r.stderr


def test_check_without_manifest(tmp_path):
    assert ds("check", "--dir", str(tmp_path)).returncode == 2
