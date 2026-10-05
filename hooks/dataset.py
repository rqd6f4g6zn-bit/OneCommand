#!/usr/bin/env python3
"""OneCommand dataset builder — the user's own data, ready to train a model from scratch.

A model trained from zero is only as good and as lawful as its data. This turns raw
files into a clean, documented, reproducible dataset:

  collect   .txt .md .html .htm .jsonl .json .csv files (and folders per label)
  clean     Unicode NFC, control characters, whitespace, minimum length
  scrub     personal data → [EMAIL] [TELEFON] [IBAN] [URL-MIT-TOKEN] (default on)
  dedup     exact duplicates and near duplicates (MinHash over word 5-grams)
  split     train / val / test by document (stratified per label for classification),
            no document in two splits
  record    manifest.json (input + output SHA-256, counts, labels, size estimate) and
            DATASHEET.md (provenance, processing, statistics, open questions)

Images and videos (--task images | videos — for image / video generators trained from scratch):
  collect   .png .jpg .jpeg .webp .bmp / .mp4 .mov .webm .mkv .avi (one folder per label optional)
  dedup     exact (SHA-256) and visually near-identical files (8×8 average hash via ffmpeg, if installed)
  split     by file, stratified per label; records reference the files with their hashes
  The training project decodes and resizes them itself.

Speech (--task speech — recordings of one voice for a text-to-speech model / voice clone):
  collect   .wav .flac .mp3 .m4a .ogg with the spoken text: metadata.csv (LJSpeech "clip|text" or a header
            with file,text) or a sidecar clip.txt; one sub-folder per speaker optional
  check     per clip via ffmpeg: transcript present, 1–20 s, sample rate ≥ --min-sample-rate (22.05 kHz;
            telephone recordings cannot teach a voice), no clipping, not too quiet, ≤ 1 s silence at the
            ends, speaking rate plausible for the transcript (catches swapped or truncated texts)
  report    hours per speaker and which voice path the data supports (clone ≥ 0.5 h, fine-tune ≥ 1 h,
            production fine-tune ≥ 3 h, from scratch ≥ 24 h); rejected clips with the reason

Subcommands
-----------
build   --input data/raw --out data/processed --task text|classification|images|videos|speech
check   --dir data/processed   files unchanged since build, splits disjoint, no test text in train
stats   --dir data/processed   print the manifest summary

Exit codes: 0 ok · 1 check failed / dataset too small · 2 usage error
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

TEXT_EXT = {".txt", ".md", ".markdown", ".rst"}
HTML_EXT = {".html", ".htm"}
TABLE_EXT = {".csv", ".tsv", ".jsonl", ".json"}
PII = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")),
    ("URL-MIT-TOKEN", re.compile(r"https?://\S*?(?:token|key|secret|password|sig)=\S+", re.I)),
    ("TELEFON", re.compile(r"(?<![\w/])(?:\+\d{1,3}[\s/-]?|\b0)\(?\d{2,5}\)?[\s/-]?\d{3,}(?:[\s-]?\d{2,})*\b")),
]
SPLIT_NAMES = ("train", "val", "test")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
MEDIA_TASKS = {"images": IMAGE_EXT, "videos": VIDEO_EXT}
AUDIO_EXT = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}
FILE_TASKS = {"images", "videos", "speech"}  # records reference files by path + hash
# hours of clean single-speaker audio each way of getting an own voice needs
VOICE_READINESS = [(0.5, "voice clone at a provider (e.g. ElevenLabs Professional Voice Clone)"),
                   (1.0, "fine-tune an open, commercially licensed TTS model (usable)"),
                   (3.0, "fine-tune for production quality"),
                   (24.0, "train a TTS model from scratch (below this it sounds robotic)")]


class DataError(Exception):
    pass


# ─── collect ──────────────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</li>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def read_rows(path: Path, text_field: str, label_field: str | None) -> Iterator[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in (".csv", ".tsv"):
        reader = csv.DictReader(io.StringIO(raw), delimiter="\t" if path.suffix == ".tsv" else ",")
        if not reader.fieldnames or text_field not in reader.fieldnames:
            raise DataError(f"{path}: no column '{text_field}' (columns: {', '.join(reader.fieldnames or [])})")
        for i, row in enumerate(reader):
            yield {"text": row.get(text_field) or "", "label": row.get(label_field) if label_field else None,
                   "source": f"{path.name}:{i + 2}"}
    else:
        items = json.loads(raw) if path.suffix == ".json" else [json.loads(l) for l in raw.splitlines() if l.strip()]
        if isinstance(items, dict):
            items = items.get("data") or items.get("items") or [items]
        for i, item in enumerate(items):
            if not isinstance(item, dict) or text_field not in item:
                raise DataError(f"{path}: record {i + 1} has no field '{text_field}'")
            yield {"text": str(item[text_field]), "label": item.get(label_field) if label_field else None,
                   "source": f"{path.name}:{i + 1}"}


def collect(root: Path, task: str, text_field: str, label_field: str) -> tuple[list[dict[str, Any]], list[Path]]:
    if not root.exists():
        raise DataError(f"input not found: {root}")
    files = sorted(p for p in (root.rglob("*") if root.is_dir() else [root]) if p.is_file() and not p.name.startswith("."))
    docs: list[dict[str, Any]] = []
    used: list[Path] = []
    for path in files:
        ext = path.suffix.lower()
        # classification from folders: data/raw/<label>/<file>.txt
        folder_label = path.parent.name if task == "classification" and path.parent != root else None
        if ext in TEXT_EXT or ext in HTML_EXT:
            text = path.read_text(encoding="utf-8", errors="replace")
            if ext in HTML_EXT:
                text = strip_html(text)
            if task == "classification" and not folder_label:
                continue  # loose text files carry no label
            docs.append({"text": text, "label": folder_label, "source": str(path.relative_to(root if root.is_dir() else root.parent))})
            used.append(path)
        elif ext in TABLE_EXT:
            rows = list(read_rows(path, text_field, label_field if task == "classification" else None))
            for r in rows:
                if task == "classification" and r["label"] in (None, ""):
                    r["label"] = folder_label
            docs.extend(rows)
            used.append(path)
    return docs, used


# ─── clean / scrub / dedup ────────────────────────────────────────────────────

def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def scrub(text: str, counts: Counter) -> str:
    for name, pattern in PII:
        text, n = pattern.subn(f"[{name}]", text)
        counts[name] += n
    return text


def shingles(text: str, n: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def minhash(sh: set[str], perms: int = 64) -> tuple[int, ...]:
    return tuple(min(int.from_bytes(hashlib.blake2b(f"{p}:{s}".encode(), digest_size=8).digest(), "big") for s in sh)
                 for p in range(perms))


def dedup(docs: list[dict[str, Any]], near: float) -> tuple[list[dict[str, Any]], int, int]:
    seen: set[str] = set()
    exact_drop = 0
    kept = []
    for d in docs:
        key = hashlib.sha256(re.sub(r"\W+", " ", d["text"].lower()).strip().encode()).hexdigest()
        if key in seen:
            exact_drop += 1
            continue
        seen.add(key)
        kept.append(d)
    if near >= 1.0:
        return kept, exact_drop, 0
    bands, rows = 16, 4
    buckets: dict[tuple[int, tuple[int, ...]], int] = {}
    sigs: list[tuple[int, ...]] = []
    result = []
    near_drop = 0
    for d in kept:
        sig = minhash(shingles(d["text"]))
        dup = False
        candidates = {buckets[(b, sig[b * rows:(b + 1) * rows])] for b in range(bands)
                      if (b, sig[b * rows:(b + 1) * rows]) in buckets}
        for c in candidates:
            if sum(a == b for a, b in zip(sig, sigs[c])) / len(sig) >= near:
                dup = True
                break
        if dup:
            near_drop += 1
            continue
        idx = len(sigs)
        sigs.append(sig)
        for b in range(bands):
            buckets.setdefault((b, sig[b * rows:(b + 1) * rows]), idx)
        result.append(d)
    return result, exact_drop, near_drop


# ─── split / write ────────────────────────────────────────────────────────────

def split(docs: list[dict[str, Any]], ratios: tuple[float, float, float], seed: int,
          stratify: bool) -> dict[str, list[dict[str, Any]]]:
    rnd = random.Random(seed)
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for d in docs:
        groups[d["label"] if stratify else None].append(d)
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in SPLIT_NAMES}
    for key in sorted(groups, key=str):
        items = groups[key]
        rnd.shuffle(items)
        n = len(items)
        n_val = max(1 if n >= 3 else 0, round(n * ratios[1]))
        n_test = max(1 if n >= 3 else 0, round(n * ratios[2]))
        out["val"] += items[:n_val]
        out["test"] += items[n_val:n_val + n_test]
        out["train"] += items[n_val + n_test:]
    for k in SPLIT_NAMES:
        rnd.shuffle(out[k])
    return out


def text_key(text: str) -> str:
    return hashlib.sha256(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()


# ─── images / videos ──────────────────────────────────────────────────────────

def average_hash(path: Path, video: bool) -> int | None:
    """8×8 grayscale average hash of an image (or a video's first second) via ffmpeg; None without ffmpeg."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        return None
    args = ["ffmpeg", "-v", "error"] + (["-ss", "0.5"] if video else []) + ["-i", str(path), "-frames:v", "1",
            "-vf", "scale=8:8:flags=area,format=gray", "-f", "rawvideo", "-"]
    try:
        raw = subprocess.run(args, capture_output=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(raw) != 64:
        return None
    mean = sum(raw) / 64
    return sum(1 << i for i, b in enumerate(raw) if b > mean)


def build_media(args: argparse.Namespace, root: Path, out: Path, ratios: tuple[float, float, float]) -> int:
    exts = MEDIA_TASKS[args.task]
    if not root.is_dir():
        raise DataError(f"input folder not found: {root}")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("."))
    seen: dict[str, Path] = {}
    hashes: list[tuple[int, Path]] = []
    items, exact_drop, near_drop, unhashed = [], 0, 0, 0
    for path in files:
        digest = sha256(path)
        if digest in seen:
            exact_drop += 1
            continue
        seen[digest] = path
        ahash = average_hash(path, args.task == "videos") if args.near_dup < 1.0 else None
        if ahash is None:
            unhashed += 1
        elif any(bin(ahash ^ h).count("1") <= args.media_near_bits for h, _ in hashes):
            near_drop += 1
            continue
        else:
            hashes.append((ahash, path))
        label = path.parent.name if path.parent != root else None
        items.append({"text": "", "path": str(path.relative_to(root)), "sha256": digest,
                      "bytes": path.stat().st_size, "label": label, "source": str(path.relative_to(root))})
    if not items:
        raise DataError(f"no {args.task} found in {root} ({', '.join(sorted(exts))})")
    labelled = all(i["label"] for i in items)
    parts = split(items, ratios, args.seed, labelled)
    out.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name in SPLIT_NAMES:
        path = out / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for i, d in enumerate(parts[name]):
                rec = {"id": f"{name}-{i:06d}", "path": d["path"], "sha256": d["sha256"], "bytes": d["bytes"]}
                if labelled:
                    rec["label"] = d["label"]
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        outputs[name] = {"file": path.name, "sha256": sha256(path), "records": len(parts[name]),
                         "bytes": sum(d["bytes"] for d in parts[name])}
    labels = Counter(i["label"] for i in items) if labelled else None
    manifest = {
        "version": 1, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task, "seed": args.seed, "split": dict(zip(SPLIT_NAMES, ratios)),
        "input": {"root": str(root), "files": [{"path": i["path"], "sha256": i["sha256"], "bytes": i["bytes"]}
                                               for i in items]},
        "processing": {"records_in": len(files), "too_short_or_unlabelled": 0, "exact_duplicates": exact_drop,
                       "near_duplicates": near_drop, "near_dup_threshold": f"average hash ≤ {args.media_near_bits} bits",
                       "not_hashed": unhashed, "pii_scrubbed": "not applicable (media)", "min_chars": None},
        "outputs": outputs, "records": len(items), "chars": 0, "approx_tokens": 0,
        "bytes": sum(i["bytes"] for i in items), "labels": dict(sorted(labels.items())) if labels else None,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_datasheet(out, manifest)
    if unhashed and args.near_dup < 1.0:
        print(f"  ⚠ {unhashed} file(s) without a perceptual hash (ffmpeg missing or unreadable) — only exact duplicates removed")
    if len(items) < 500:
        print(f"  ⚠ {len(items)} {args.task} is very little for a generator from scratch (aim for thousands; small sets are "
              f"memorised — fine for a style model of your own material, not for variety)")
    print(f"[dataset] {len(items)} {args.task} ({manifest['bytes'] / 1e6:.1f} MB) → "
          + ", ".join(f"{k} {v['records']}" for k, v in outputs.items())
          + f" · removed: {exact_drop} exact + {near_drop} near duplicates")
    if len(items) < args.min_records:
        print(f"  ✗ only {len(items)} files, need at least {args.min_records}")
        return 1
    return 0


# ─── speech ───────────────────────────────────────────────────────────────────

def read_transcripts(root: Path) -> dict[Path, str]:
    """metadata.csv files (LJSpeech `clip|text[|normalised]` or a header with file,text) → {audio path: text}."""
    texts: dict[Path, str] = {}
    for meta in sorted(root.rglob("metadata.csv")):
        raw = meta.read_text(encoding="utf-8", errors="replace")
        lines = [l for l in raw.splitlines() if l.strip()]
        if not lines:
            continue
        if "|" in lines[0]:
            rows = [[c.strip() for c in l.split("|")] for l in lines]
        else:
            reader = csv.DictReader(io.StringIO(raw))
            fields = {f.lower(): f for f in reader.fieldnames or []}
            fcol = next((fields[k] for k in ("file", "audio", "path", "filename", "clip") if k in fields), None)
            tcol = next((fields[k] for k in ("text", "transcript", "sentence", "normalized_text") if k in fields), None)
            if not fcol or not tcol:
                raise DataError(f"{meta}: needs columns file and text (or LJSpeech lines 'clip|text')")
            rows = [[r.get(fcol) or "", r.get(tcol) or ""] for r in reader]
        for row in rows:
            if len(row) < 2 or not row[0]:
                continue
            name = row[0]
            text = next((c for c in reversed(row[1:]) if c), "")
            candidates = [meta.parent / name] + [meta.parent / f"{name}{e}" for e in sorted(AUDIO_EXT)] \
                + [meta.parent / "wavs" / f"{name}{e}" for e in sorted(AUDIO_EXT)]
            hit = next((c for c in candidates if c.is_file()), None)
            if hit:
                texts[hit.resolve()] = text
    return texts


def analyse_audio(path: Path) -> dict[str, Any]:
    """Duration, sample rate, loudness, clipping and edge silence of one clip via ffprobe/ffmpeg."""
    import subprocess
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                            "stream=sample_rate,channels:format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=60)
    try:
        info = json.loads(probe.stdout or "{}")
        stream = info["streams"][0]
        seconds = float(info["format"]["duration"])
    except (ValueError, KeyError, IndexError):
        return {"error": "not a readable audio file"}
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                          "silencedetect=n=-45dB:d=0.25,volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=300)
    log = run.stderr
    def last(pattern: str) -> float | None:
        found = re.findall(pattern, log)
        return float(found[-1]) if found else None
    n_samples = last(r"n_samples: (\d+)") or 0
    clipped = last(r"histogram_0db: (\d+)") or 0
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    lead = ends[0] if starts and starts[0] <= 0.05 and ends else 0.0
    trail = seconds - starts[-1] if starts and (len(ends) < len(starts) or ends[-1] >= seconds - 0.05) else 0.0
    return {"seconds": seconds, "sample_rate": int(stream.get("sample_rate", 0)), "channels": stream.get("channels"),
            "mean_db": last(r"mean_volume: (-?[\d.]+) dB"), "max_db": last(r"max_volume: (-?[\d.]+) dB"),
            "clipped": int(clipped), "n_samples": int(n_samples), "lead_silence": round(lead, 2),
            "trail_silence": round(max(trail, 0.0), 2)}


def judge_clip(a: dict[str, Any], text: str, args: argparse.Namespace) -> str | None:
    """Reason the clip is unusable for voice training, or None."""
    if "error" in a:
        return a["error"]
    if not text.strip():
        return "no transcript"
    if a["seconds"] < 1.0:
        return f"too short ({a['seconds']:.1f} s)"
    if a["seconds"] > args.max_clip_seconds:
        return f"too long ({a['seconds']:.0f} s, max {args.max_clip_seconds}) — cut into sentences"
    if a["sample_rate"] < args.min_sample_rate:
        return f"sample rate {a['sample_rate']} Hz below {args.min_sample_rate} (phone-quality audio cannot teach a voice)"
    if a["clipped"] > max(10, a["n_samples"] * 1e-4):
        return f"clipped ({a['clipped']} samples at full scale) — record with more headroom"
    if a["mean_db"] is not None and a["mean_db"] < -40:
        return f"too quiet (mean {a['mean_db']} dB)"
    if max(a["lead_silence"], a["trail_silence"]) > 1.0:
        return f"{max(a['lead_silence'], a['trail_silence']):.1f} s silence at the start/end — trim the clip"
    letters = len(re.sub(r"[^\w]", "", text))
    rate = letters / max(a["seconds"] - a["lead_silence"] - a["trail_silence"], 0.1)
    if not 5 <= rate <= 25:
        return f"{rate:.0f} letters per second does not fit speech — transcript belongs to another clip or is cut off"
    return None


def build_speech(args: argparse.Namespace, root: Path, out: Path, ratios: tuple[float, float, float]) -> int:
    import shutil
    if not root.is_dir():
        raise DataError(f"input folder not found: {root}")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise DataError("--task speech needs ffmpeg and ffprobe (apt install ffmpeg / brew install ffmpeg)")
    texts = read_transcripts(root)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT and not p.name.startswith("."))
    if not files:
        raise DataError(f"no recordings found in {root} ({', '.join(sorted(AUDIO_EXT))})")
    seen: set[str] = set()
    items, rejected, exact_drop = [], [], 0
    digits = 0
    for path in files:
        digest = sha256(path)
        if digest in seen:  # only accepted clips count, so a stray copy cannot push out the transcribed original
            exact_drop += 1
            continue
        text = texts.get(path.resolve())
        if text is None:
            for ext in (".txt", ".lab"):
                side = path.with_suffix(ext)
                if side.is_file():
                    text = side.read_text(encoding="utf-8", errors="replace")
                    break
        text = clean(text or "").replace("\n", " ")
        a = analyse_audio(path)
        rel = path.relative_to(root)
        reason = judge_clip(a, text, args)
        if reason:
            rejected.append({"path": str(rel), "reason": reason})
            continue
        seen.add(digest)
        if re.search(r"\d", text):
            digits += 1
        speaker = rel.parts[0] if len(rel.parts) > 1 and rel.parts[0] != "wavs" else "default"
        items.append({"text": text, "path": str(rel), "sha256": digest, "bytes": path.stat().st_size,
                      "label": None, "speaker": speaker, "seconds": round(a["seconds"], 3),
                      "sample_rate": a["sample_rate"], "source": str(rel)})
    if not items:
        for r in rejected[:10]:
            print(f"  ✗ {r['path']}: {r['reason']}")
        raise DataError(f"no usable recordings in {root} — all {len(rejected)} clip(s) rejected")
    parts = split(items, ratios, args.seed, False)
    out.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name in SPLIT_NAMES:
        path = out / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for i, d in enumerate(parts[name]):
                fh.write(json.dumps({"id": f"{name}-{i:06d}", "path": d["path"], "text": d["text"],
                                     "speaker": d["speaker"], "seconds": d["seconds"], "sample_rate": d["sample_rate"],
                                     "sha256": d["sha256"], "bytes": d["bytes"]}, ensure_ascii=False) + "\n")
        outputs[name] = {"file": path.name, "sha256": sha256(path), "records": len(parts[name]),
                         "seconds": round(sum(d["seconds"] for d in parts[name]), 1)}
    seconds = sum(d["seconds"] for d in items)
    hours = seconds / 3600
    speakers = Counter()
    for d in items:
        speakers[d["speaker"]] += d["seconds"]
    main_hours = max(speakers.values()) / 3600
    readiness = [{"hours": h, "path": what, "ready": main_hours >= h} for h, what in VOICE_READINESS]
    categories = ("no transcript", "too short", "too long", "sample rate", "clipped", "too quiet", "silence",
                  "letters per second", "not a readable audio file")
    reasons = Counter(next((c for c in categories if c in r["reason"]), "other") for r in rejected)
    manifest = {
        "version": 1, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": "speech", "seed": args.seed, "split": dict(zip(SPLIT_NAMES, ratios)),
        "input": {"root": str(root), "files": [{"path": i["path"], "sha256": i["sha256"], "bytes": i["bytes"]}
                                               for i in items]},
        "processing": {"records_in": len(files), "too_short_or_unlabelled": len(rejected), "exact_duplicates": exact_drop,
                       "near_duplicates": 0, "near_dup_threshold": "not applicable (speech)",
                       "pii_scrubbed": "not applicable (scripted recordings — never record real customer calls)",
                       "min_chars": None, "rejected": rejected, "rejected_by_reason": dict(reasons),
                       "transcripts_with_digits": digits},
        "outputs": outputs, "records": len(items), "chars": sum(len(d["text"]) for d in items), "approx_tokens": 0,
        "bytes": sum(i["bytes"] for i in items), "labels": None, "seconds": round(seconds, 1),
        "hours": round(hours, 3), "speakers": {k: round(v / 3600, 3) for k, v in sorted(speakers.items())},
        "sample_rates": dict(Counter(str(d["sample_rate"]) for d in items)), "readiness": readiness,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_datasheet(out, manifest)
    for r in rejected[:20]:
        print(f"  ✗ {r['path']}: {r['reason']}")
    if len(rejected) > 20:
        print(f"  … {len(rejected) - 20} more rejected clip(s) in manifest.json")
    if digits:
        print(f"  ⚠ {digits} transcript(s) contain digits — write numbers the way they are spoken ('vierzehn Uhr')")
    if len(speakers) > 1:
        print(f"  ⚠ {len(speakers)} speakers — a voice is trained per speaker; hours below count the largest one")
    print(f"[dataset] {len(items)} clips, {hours:.2f} h usable ({len(rejected)} rejected, {exact_drop} duplicates) → "
          + ", ".join(f"{k} {v['records']}" for k, v in outputs.items()))
    for r in readiness:
        print(f"  {'✓' if r['ready'] else '·'} {r['hours']:>4} h  {r['path']}")
    if len(items) < args.min_records:
        print(f"  ✗ only {len(items)} usable clips, need at least {args.min_records}")
        return 1
    if main_hours < args.min_hours:
        print(f"  ✗ {main_hours:.2f} h of one voice, need at least {args.min_hours} h for the chosen voice path")
        return 1
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    root, out = Path(args.input).resolve(), Path(args.out).resolve()
    ratios = tuple(float(x) for x in args.split.split(","))
    if len(ratios) != 3 or abs(sum(ratios) - 1) > 1e-6 or min(ratios) < 0:
        raise DataError("--split needs three ratios that add up to 1, e.g. 0.8,0.1,0.1")
    if args.task in MEDIA_TASKS:
        return build_media(args, root, out, ratios)
    if args.task == "speech":
        return build_speech(args, root, out, ratios)
    docs, used = collect(root, args.task, args.text_field, args.label_field)
    total_in = len(docs)
    pii: Counter = Counter()
    cleaned = []
    too_short = 0
    for d in docs:
        text = clean(d["text"])
        if not args.no_pii_scrub:
            text = scrub(text, pii)
        if len(text) < args.min_chars:
            too_short += 1
            continue
        label = d.get("label")
        if args.task == "classification":
            if label in (None, ""):
                too_short += 1
                continue
            label = str(label).strip()
        cleaned.append({**d, "text": text, "label": label})
    kept, exact_drop, near_drop = dedup(cleaned, args.near_dup)
    if not kept:
        raise DataError("no usable documents left after cleaning — check --input, --text-field and --min-chars")
    parts = split(kept, ratios, args.seed, args.task == "classification")
    out.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name in SPLIT_NAMES:
        path = out / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for i, d in enumerate(parts[name]):
                rec = {"id": f"{name}-{i:06d}", "text": d["text"], "source": d["source"]}
                if args.task == "classification":
                    rec["label"] = d["label"]
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        outputs[name] = {"file": path.name, "sha256": sha256(path), "records": len(parts[name]),
                         "chars": sum(len(d["text"]) for d in parts[name])}
    labels = Counter(d["label"] for d in kept) if args.task == "classification" else None
    chars = sum(len(d["text"]) for d in kept)
    manifest = {
        "version": 1, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task, "seed": args.seed, "split": dict(zip(SPLIT_NAMES, ratios)),
        "input": {"root": str(root), "files": [{"path": str(p.relative_to(root) if root.is_dir() else p.name),
                                                "sha256": sha256(p), "bytes": p.stat().st_size} for p in used]},
        "processing": {"records_in": total_in, "too_short_or_unlabelled": too_short, "exact_duplicates": exact_drop,
                       "near_duplicates": near_drop, "near_dup_threshold": args.near_dup,
                       "pii_scrubbed": dict(pii) if not args.no_pii_scrub else "disabled", "min_chars": args.min_chars},
        "outputs": outputs, "records": len(kept), "chars": chars, "approx_tokens": chars // 4,
        "labels": dict(sorted(labels.items())) if labels else None,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_datasheet(out, manifest)

    warnings = []
    if labels:
        small = [l for l, n in labels.items() if n < 10]
        if small:
            warnings.append(f"classes with fewer than 10 examples: {', '.join(small)} — collect more or merge classes")
        if max(labels.values()) > 10 * min(labels.values()):
            warnings.append("class imbalance above 10:1 — use class weights or collect more of the small classes")
    if args.task == "text" and chars < 1_000_000:
        warnings.append(f"{chars:,} characters is a very small corpus for a language model from scratch "
                        f"(aim for 10M+ characters; small models still learn style and vocabulary)")
    for w in warnings:
        print(f"  ⚠ {w}")
    print(f"[dataset] {len(kept)} records ({chars:,} chars, ~{chars // 4:,} tokens) → "
          + ", ".join(f"{k} {v['records']}" for k, v in outputs.items())
          + f" · removed: {too_short} short/unlabelled, {exact_drop} exact + {near_drop} near duplicates"
          + (f" · PII scrubbed: {sum(pii.values())}" if not args.no_pii_scrub else ""))
    if len(kept) < args.min_records:
        print(f"  ✗ only {len(kept)} records, need at least {args.min_records}")
        return 1
    return 0


def write_datasheet(out: Path, m: dict[str, Any]) -> None:
    p = m["processing"]
    lines = [
        "# Datasheet", "",
        f"Built {m['created_at']} by `hooks/dataset.py` (seed {m['seed']}). Regenerate with the same input to reproduce.", "",
        "## Provenance", "",
        "| File | Bytes | SHA-256 |", "|---|---|---|",
        *[f"| {f['path']} | {f['bytes']} | `{f['sha256'][:16]}…` |" for f in m["input"]["files"]], "",
        "Owner, license / right to use, and how the data was collected: **to be completed by the project owner.**", "",
        "## Processing", "",
        f"- Records in: {p['records_in']}; removed as too short or unlabelled: {p['too_short_or_unlabelled']}",
        f"- Exact duplicates removed: {p['exact_duplicates']}; near duplicates (≥ {p['near_dup_threshold']}): {p['near_duplicates']}",
        f"- Personal data replaced: {p['pii_scrubbed']}",
        "", "## Result", "",
        *([f"- {m['records']} clips, {m['hours']:.2f} h of speech, speakers (h): {m['speakers']}, "
           f"sample rates: {m['sample_rates']}"] if m["task"] == "speech" else
          [f"- {m['records']} files, {m.get('bytes', 0) / 1e6:.1f} MB"] if m["task"] in MEDIA_TASKS else
          [f"- {m['records']} records, {m['chars']:,} characters (~{m['approx_tokens']:,} tokens)"]),
        *[f"- {k}: {v['records']} records" + (f", {v['chars']:,} chars" if "chars" in v else "") for k, v in m["outputs"].items()],
    ]
    if m.get("readiness"):
        lines += ["", "## Voice readiness", "", "| Needs | Path | Ready |", "|---|---|---|",
                  *[f"| {r['hours']} h | {r['path']} | {'yes' if r['ready'] else 'no'} |" for r in m["readiness"]],
                  "", "Consent: written consent of the speaker to train and use this voice: **to be attached by the owner.**"]
    if m.get("labels"):
        lines += ["", "## Labels", "", "| Label | Records |", "|---|---|", *[f"| {k} | {v} |" for k, v in m["labels"].items()]]
    lines += ["", "## Known limitations", "", "- To be completed: gaps, biases, languages, time range of the data."]
    (out / "DATASHEET.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── check / stats ────────────────────────────────────────────────────────────

def load_manifest(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if not path.exists():
        raise DataError(f"{path} not found — build the dataset with `dataset.py build` first")
    return json.loads(path.read_text(encoding="utf-8"))


def check_dataset(directory: Path) -> list[str]:
    m = load_manifest(directory)
    problems = []
    keys: dict[str, set[str]] = {}
    ids: dict[str, set[str]] = {}
    for name, info in m["outputs"].items():
        path = directory / info["file"]
        if not path.exists():
            problems.append(f"{info['file']} is missing")
            continue
        if sha256(path) != info["sha256"]:
            problems.append(f"{info['file']} changed since the build (hash differs) — rebuild instead of editing splits")
        recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if m["task"] in FILE_TASKS:
            media_root = Path(m["input"]["root"])
            for r in recs:
                f = media_root / r["path"]
                if not f.exists():
                    problems.append(f"{r['path']} ({name}) is missing")
                elif f.stat().st_size != r["bytes"] or sha256(f) != r["sha256"]:
                    problems.append(f"{r['path']} ({name}) changed since the build")
            keys[name] = {r["sha256"] for r in recs}
            ids[name] = {r["id"] for r in recs}
            continue
        keys[name] = {text_key(r["text"]) for r in recs}
        ids[name] = {r["id"] for r in recs}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        if a in keys and b in keys:
            overlap = keys[a] & keys[b]
            if overlap:
                problems.append(f"{len(overlap)} text(s) in both {a} and {b} — test results would be inflated")
            if ids[a] & ids[b]:
                problems.append(f"record ids shared by {a} and {b}")
    if m["outputs"].get("test", {}).get("records", 0) == 0:
        problems.append("test split is empty — too little data for an honest evaluation")
    return problems


def cmd_check(args: argparse.Namespace) -> int:
    problems = check_dataset(Path(args.dir).resolve())
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print(f"[dataset] {len(problems)} problem(s)")
        return 1
    m = load_manifest(Path(args.dir).resolve())
    print(f"[dataset] ok — {m['records']} records, splits disjoint, files unchanged since {m['created_at']}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    m = load_manifest(Path(args.dir).resolve())
    keys = ("task", "records", "hours", "speakers", "readiness") if m["task"] == "speech" else \
        ("task", "records", "chars", "approx_tokens", "labels", "processing")
    print(json.dumps({k: m.get(k) for k in keys},
                     indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--input", default="data/raw")
    p.add_argument("--out", default="data/processed")
    p.add_argument("--task", choices=("text", "classification", "images", "videos", "speech"), default="text")
    p.add_argument("--text-field", default="text")
    p.add_argument("--label-field", default="label")
    p.add_argument("--split", default="0.8,0.1,0.1")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--min-chars", type=int, default=20)
    p.add_argument("--min-records", type=int, default=10)
    p.add_argument("--near-dup", type=float, default=0.9, help="MinHash similarity treated as duplicate (1.0 = off)")
    p.add_argument("--no-pii-scrub", action="store_true", help="keep e-mails, phone numbers and IBANs (only with consent)")
    p.add_argument("--media-near-bits", type=int, default=4,
                   help="images/videos: average-hash distance treated as duplicate (default 4 of 64 bits)")
    p.add_argument("--min-sample-rate", type=int, default=22050, help="speech: minimum sample rate in Hz")
    p.add_argument("--max-clip-seconds", type=float, default=20, help="speech: longest usable clip")
    p.add_argument("--min-hours", type=float, default=0, help="speech: fail below this many hours of one voice")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("check")
    p.add_argument("--dir", default="data/processed")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("stats")
    p.add_argument("--dir", default="data/processed")
    p.set_defaults(func=cmd_stats)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DataError as exc:
        print(f"[dataset] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
