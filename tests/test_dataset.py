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


# ─── images / videos (own media for generators) ───────────────────────────────

def _ffmpeg(*args: str) -> None:
    import subprocess
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture
def media(tmp_path: Path) -> Path:
    import shutil as _sh
    if not _sh.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    r = tmp_path / "media"
    for n, (label, colour) in enumerate((("rot", "red"), ("blau", "blue"))):
        (r / label).mkdir(parents=True)
        for i in range(12):  # random noise per seed: structurally different images
            _ffmpeg("-f", "lavfi", "-i", f"color=c={colour}:s=48x48", "-vf", f"noise=alls=90:all_seed={n * 100 + i}",
                    "-frames:v", "1", str(r / label / f"{i}.png"))
    (r / "rot" / "copy.png").write_bytes((r / "rot" / "0.png").read_bytes())
    return r


def test_build_image_dataset_with_labels(tmp_path, media):
    out = tmp_path / "out"
    r = ds("build", "--input", str(media), "--out", str(out), "--task", "images")
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "manifest.json").read_text())
    assert m["task"] == "images" and m["processing"]["exact_duplicates"] == 1
    assert m["labels"] == {"blau": 12, "rot": 12}
    rec = records(out / "train.jsonl")[0]
    assert {"id", "path", "sha256", "bytes", "label"} <= set(rec)
    assert "very little for a generator from scratch" in r.stdout
    assert ds("check", "--dir", str(out)).returncode == 0
    # an edited source image is detected
    (media / rec["path"]).write_bytes(b"changed")
    c = ds("check", "--dir", str(out))
    assert c.returncode == 1 and "changed since the build" in c.stdout


def test_build_video_dataset(tmp_path):
    import shutil as _sh
    if not _sh.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    raw = tmp_path / "clips"
    raw.mkdir()
    for i, src in enumerate(("testsrc2", "mandelbrot", "life", "cellauto", "rgbtestsrc", "smptebars") * 2):
        _ffmpeg("-f", "lavfi", "-i", f"{src}=size=64x64:rate=8", "-t", "1.5", "-vf", f"hue=h={i * 40}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw / f"{i:02d}-{src}.mp4"))
    out = tmp_path / "out"
    r = ds("build", "--input", str(raw), "--out", str(out), "--task", "videos", "--min-records", "5")
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "manifest.json").read_text())
    assert m["task"] == "videos" and m["records"] >= 5 and m["labels"] is None
    assert ds("check", "--dir", str(out)).returncode == 0


def test_media_without_files(tmp_path):
    (tmp_path / "empty").mkdir()
    r = ds("build", "--input", str(tmp_path / "empty"), "--out", str(tmp_path / "out"), "--task", "images")
    assert r.returncode == 2 and "no images found" in r.stderr


# ─── speech (own voice) ───────────────────────────────────────────────────────

SENTENCES = ["Guten Tag, hier ist Nordlicht Tee.", "Ihre Bestellung ist unterwegs.", "Wir rufen Sie gerne zurück.",
             "Der Versand dauert zwei Tage.", "Rücksendungen sind kostenlos.", "Einen Moment bitte, ich verbinde.",
             "Vielen Dank für Ihren Anruf.", "Grüner Tee braucht achtzig Grad.", "Unsere Teeküche hat geöffnet.",
             "Das kann ich Ihnen gern erklären.", "Schönen Abend und auf Wiederhören.", "Möchten Sie noch etwas wissen?"]


def _tone(path: Path, freq: int, seconds: float = 2.0, rate: int = 22050, af: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", *(["-af", af] if af else []),
            "-ar", str(rate), "-ac", "1", str(path))


def sources(root: Path, *entries: dict) -> None:
    (root / "sources.json").write_text(json.dumps({"sources": list(entries)}, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def speech(tmp_path: Path) -> Path:
    import shutil as _sh
    if not (_sh.which("ffmpeg") and _sh.which("ffprobe")):
        pytest.skip("ffmpeg not installed")
    r = tmp_path / "voice"
    for i, text in enumerate(SENTENCES):
        _tone(r / "wavs" / f"c{i:02d}.wav", 200 + 25 * i)
    lines = [f"c{i:02d}|{t}" for i, t in enumerate(SENTENCES)]
    _tone(r / "wavs" / "digits.wav", 520)
    lines.append("digits|Wir haben bis 18 Uhr geöffnet.")
    _tone(r / "wavs" / "mismatch.wav", 540)
    lines.append("mismatch|" + "Dieser Text ist viel zu lang für zwei Sekunden Aufnahme und gehört zu einem anderen Clip. " * 2)
    _tone(r / "wavs" / "clipped.wav", 560, af="volume=30")
    lines.append("clipped|Das ist zu laut aufgenommen.")
    _tone(r / "wavs" / "quiet.wav", 580, af="volume=0.001")
    lines.append("quiet|Das ist viel zu leise aufgenommen.")
    _tone(r / "wavs" / "padded.wav", 600, af="apad=pad_dur=2")
    lines.append("padded|Hier fehlt der Schnitt am Ende.")
    _tone(r / "wavs" / "long.wav", 620, seconds=25)
    lines.append("long|Ein sehr langer Absatz.")
    _tone(r / "wavs" / "notext.wav", 640)
    import shutil as _sh2
    _sh2.copy(r / "wavs" / "c00.wav", r / "wavs" / "c00-copy.wav")  # stray copy without a transcript
    _sh2.copy(r / "wavs" / "c01.wav", r / "wavs" / "zz-dup.wav")    # exact duplicate with a transcript
    lines.append("zz-dup|Ihre Bestellung ist unterwegs.")
    (r / "metadata.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (r / "consent").mkdir()
    (r / "consent" / "einwilligung.txt").write_text("Einwilligung der Sprecherin", encoding="utf-8")
    sources(r, {"path": ".", "name": "Eigene Aufnahmen", "license": "own", "consent": "consent/einwilligung.txt"})
    _tone(r / "phone.wav", 660, rate=8000)                       # sidecar transcript, telephone quality
    (r / "phone.txt").write_text("Aufnahme vom Telefon.", encoding="utf-8")
    return r


def test_build_speech_dataset(tmp_path, speech):
    out = tmp_path / "out"
    r = ds("build", "--input", str(speech), "--out", str(out), "--task", "speech")
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "manifest.json").read_text())
    assert m["task"] == "speech" and m["records"] == 13, r.stdout  # 12 sentences + the clip with digits
    assert m["processing"]["exact_duplicates"] == 1
    reasons = {x["path"]: x["reason"] for x in m["processing"]["rejected"]}
    assert "letters per second" in reasons["wavs/mismatch.wav"]
    assert "clipped" in reasons["wavs/clipped.wav"]
    assert "too quiet" in reasons["wavs/quiet.wav"]
    assert "silence" in reasons["wavs/padded.wav"]
    assert "too long" in reasons["wavs/long.wav"]
    assert reasons["wavs/notext.wav"] == reasons["wavs/c00-copy.wav"] == "no transcript"
    assert "sample rate 8000" in reasons["phone.wav"]
    assert m["processing"]["transcripts_with_digits"] == 1 and "digits" in r.stdout
    assert m["seconds"] == pytest.approx(26, abs=0.5) and m["speakers"] == {"default": m["hours"]}
    assert [x["ready"] for x in m["readiness"]] == [False, False, False, False]
    recs = [json.loads(l) for name in ("train", "val", "test") for l in (out / f"{name}.jsonl").read_text().splitlines()]
    assert {x["sample_rate"] for x in recs} == {22050} and all(x["text"] and x["seconds"] for x in recs)
    sheet = (out / "DATASHEET.md").read_text()
    assert "Voice readiness" in sheet and "Consent" in sheet and "| Eigene Aufnahmen | own | 13 |" in sheet
    assert m["commercial_use"] is True and m["sources"][0]["clips"] == 13
    assert not (out / "ATTRIBUTION.md").exists()
    assert "train a TTS model from scratch" in r.stdout


def test_speech_check_and_min_hours(tmp_path, speech):
    out = tmp_path / "out"
    r = ds("build", "--input", str(speech), "--out", str(out), "--task", "speech", "--min-hours", "0.5")
    assert r.returncode == 1 and "need at least 0.5 h" in r.stdout
    assert ds("check", "--dir", str(out)).returncode == 0
    _tone(speech / "wavs" / "c03.wav", 999)
    r = ds("check", "--dir", str(out))
    assert r.returncode == 1 and "c03.wav" in r.stdout and "changed since the build" in r.stdout


def test_speech_without_recordings(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "notes.txt").write_text("kein Audio")
    r = ds("build", "--input", str(tmp_path / "raw"), "--out", str(tmp_path / "out"), "--task", "speech")
    assert r.returncode == 2 and ("no recordings" in r.stderr or "ffmpeg" in r.stderr)


def _speech_build(root: Path, out: Path, *extra: str):
    return ds("build", "--input", str(root), "--out", str(out), "--task", "speech", *extra)


def test_speech_needs_sources(tmp_path, speech):
    (speech / "sources.json").unlink()
    r = _speech_build(speech, tmp_path / "out")
    assert r.returncode == 2 and "sources.json is missing" in r.stderr


@pytest.mark.parametrize("entry,message", [
    ({"path": ".", "name": "Stimmen von YouTube", "license": "CC0-1.0", "url": "https://www.youtube.com/watch?v=x"},
     "content from youtube.com"),
    ({"path": ".", "name": "Songs", "license": "CC0-1.0", "url": "https://open.spotify.com/track/1"}, "content from spotify.com"),
    ({"path": ".", "name": "Korpus", "license": "CC-BY-NC-4.0"}, "forbids commercial use"),
    ({"path": ".", "name": "Korpus", "license": "CC-BY-ND-4.0"}, "forbids commercial use"),
    ({"path": ".", "name": "Korpus", "license": "proprietary"}, "not on the allow-list"),
    ({"path": ".", "name": "Korpus"}, "no licence recorded"),
    ({"path": ".", "name": "Sprecherin", "license": "own"}, "written consent"),
    ({"path": ".", "name": "Sprecherin", "license": "own", "consent": "fehlt.pdf"}, "fehlt.pdf"),
])
def test_speech_rejects_unlicensed_sources(tmp_path, speech, entry, message):
    sources(speech, entry)
    r = _speech_build(speech, tmp_path / "out")
    assert r.returncode == 2 and message in r.stdout and "source problem" in r.stderr


def test_speech_noncommercial_only_for_research(tmp_path, speech):
    sources(speech, {"path": ".", "name": "Forschungskorpus", "license": "CC-BY-NC-4.0"})
    out = tmp_path / "out"
    r = _speech_build(speech, out, "--allow-noncommercial")
    assert r.returncode == 0 and "research only" in r.stdout
    m = json.loads((out / "manifest.json").read_text())
    assert m["commercial_use"] is False
    assert "Commercial use: **no — research only**" in (out / "DATASHEET.md").read_text()


def test_speech_corpus_plus_own_voice(tmp_path):
    import shutil as _sh
    if not (_sh.which("ffmpeg") and _sh.which("ffprobe")):
        pytest.skip("ffmpeg not installed")
    r = tmp_path / "voice"
    meta = {"cv": [], "sprecherin": [], "fremd": []}
    for i, text in enumerate(SENTENCES):
        folder = ("cv/spk1", "cv/spk2", "sprecherin", "fremd")[i % 4]
        _tone(r / folder / f"c{i:02d}.wav", 200 + 25 * i)
        (r / folder / f"c{i:02d}.txt").write_text(text, encoding="utf-8")
    (r / "einwilligung.pdf").write_bytes(b"%PDF signed")
    sources(r, {"path": "cv", "name": "Multilingual LibriSpeech (de)", "license": "CC-BY-4.0",
                "url": "https://www.openslr.org/94/"},
            {"path": "sprecherin", "name": "Eigene Sprecherin", "license": "own", "consent": "einwilligung.pdf",
             "speaker": "markenstimme"})
    out = tmp_path / "out"
    res = _speech_build(r, out, "--min-records", "5")
    assert res.returncode == 0, res.stdout + res.stderr
    m = json.loads((out / "manifest.json").read_text())
    assert set(m["speakers"]) == {"cv/spk1", "cv/spk2", "markenstimme"} and m["records"] == 9
    assert {x["path"] for x in m["processing"]["rejected"]} == {f"fremd/c{i:02d}.wav" for i in (3, 7, 11)}
    assert all(x["reason"] == "no source/licence recorded in sources.json" for x in m["processing"]["rejected"])
    assert {x["name"]: x["clips"] for x in m["sources"]} == {"Multilingual LibriSpeech (de)": 6, "Eigene Sprecherin": 3}
    attribution = (out / "ATTRIBUTION.md").read_text()
    assert "Multilingual LibriSpeech (de) — CC-BY-4.0 — https://www.openslr.org/94/" in attribution
    assert "Eigene Sprecherin" not in attribution
