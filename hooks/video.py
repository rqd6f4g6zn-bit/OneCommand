#!/usr/bin/env python3
"""OneCommand video — cut, assemble and encode web videos with ffmpeg.

Premium websites live from motion: a hero loop, product films, case-study clips.
This script turns raw footage and images into web-ready videos without an editor:

Subcommands
-----------
probe    Duration, size, fps, codecs and audio of a file (JSON with --json).
scenes   Scene cuts of a clip (ffmpeg scene detection) — where to cut.
render   Build videos from an edit plan (JSON): cut clips by time, turn images into
         Ken-Burns shots, crop/scale to one size, cross-fade in/out, then encode
         MP4 (H.264, faststart) + WebM (VP9) + poster (JPG). Muted outputs carry no
         audio track (autoplay-safe); others keep source audio or a music bed.
         Over the size budget → re-encoded at a lower quality, up to 3 times.
         Writes <out-dir>/videos.json (manifest).
check    Verify a video directory against its manifest: both formats + poster exist,
         MP4 is faststart, muted videos have no audio, sizes within budget.

Edit plan
---------
{"outputs": [{
   "name": "hero", "width": 1920, "height": 1080, "fps": 30,
   "muted": true, "max_seconds": 12, "max_kb": 4000, "fade": 0.5,
   "formats": ["mp4", "webm"], "poster": true, "audio": "assets/music.mp3",
   "clips": [
     {"src": "assets/raw/drone.mp4", "start": 12.0, "end": 16.5},
     {"src": "assets/raw/team.mov",  "start": 3.0,  "duration": 4},
     {"src": "assets/img/office.jpg", "duration": 3.5, "zoom": 1.12}
   ]}]}

Exit codes: 0 ok · 1 render/check failed · 2 usage error (bad plan, missing ffmpeg or file)
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
DEFAULTS = {"width": 1920, "height": 1080, "fps": 30, "muted": True, "fade": 0.5,
            "formats": ["mp4", "webm"], "poster": True, "max_kb": 6000}
# quality ladders: each retry steps one down when a file exceeds max_kb
MP4_CRF = [23, 26, 29, 32]
WEBM_CRF = [34, 38, 42, 46]


class PlanError(Exception):
    pass


def need_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise PlanError(f"{tool} is not installed (macOS: brew install ffmpeg · Debian/Ubuntu: apt install ffmpeg)")


def ff(args: list[str], what: str) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while {what}: {proc.stderr.strip()[-1500:]}")


# ─── probe / scenes ───────────────────────────────────────────────────────────

def probe(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PlanError(f"file not found: {path}")
    proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise PlanError(f"ffprobe cannot read {path}: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = round(int(num) / int(den), 3) if int(den) else None
    return {
        "file": str(path), "duration": float(data.get("format", {}).get("duration") or 0),
        "size_kb": round(path.stat().st_size / 1024, 1),
        "width": video.get("width") if video else None, "height": video.get("height") if video else None,
        "fps": fps, "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None, "has_audio": audio is not None,
    }


def scenes(path: Path, threshold: float) -> list[float]:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-filter:v",
                           f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                          capture_output=True, text=True)
    cuts = []
    for line in proc.stderr.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            cuts.append(round(float(line.split("pts_time:")[1].split()[0]), 3))
    return cuts


def cmd_probe(args: argparse.Namespace) -> int:
    info = probe(Path(args.file))
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"{info['file']}: {info['duration']:.2f}s · {info['width']}×{info['height']} @ {info['fps']} fps · "
              f"{info['video_codec']}" + (f" + {info['audio_codec']}" if info["has_audio"] else " · no audio")
              + f" · {info['size_kb']} KB")
    return 0


def cmd_scenes(args: argparse.Namespace) -> int:
    path = Path(args.file)
    probe(path)
    cuts = scenes(path, args.threshold)
    print(json.dumps({"file": str(path), "threshold": args.threshold, "cuts": cuts}) if args.json
          else "\n".join(f"{t:.3f}" for t in cuts) or "(no scene cuts — try a lower --threshold)")
    return 0


# ─── render ───────────────────────────────────────────────────────────────────

def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlanError(f"plan not found: {path}") from None
    except ValueError as exc:
        raise PlanError(f"plan is not valid JSON: {exc}") from None
    outputs = plan.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise PlanError("plan needs a non-empty 'outputs' list")
    names = set()
    for out in outputs:
        name = out.get("name", "")
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise PlanError(f"output name '{name}' must be a simple slug (letters, digits, - and _)")
        if name in names:
            raise PlanError(f"duplicate output name '{name}'")
        names.add(name)
        if not out.get("clips"):
            raise PlanError(f"output '{name}' has no clips")
        bad = set(out.get("formats", DEFAULTS["formats"])) - {"mp4", "webm"}
        if bad:
            raise PlanError(f"output '{name}': unsupported format(s) {', '.join(sorted(bad))} (mp4, webm)")
        for i, clip in enumerate(out["clips"]):
            if "src" not in clip:
                raise PlanError(f"output '{name}' clip {i}: 'src' is required")
            is_image = Path(clip["src"]).suffix.lower() in IMAGE_EXT
            if is_image and not clip.get("duration"):
                raise PlanError(f"output '{name}' clip {i}: an image needs 'duration'")
            if "end" in clip and "start" in clip and clip["end"] <= clip["start"]:
                raise PlanError(f"output '{name}' clip {i}: end must be after start")
    return plan


def segment(clip: dict[str, Any], root: Path, cfg: dict[str, Any], dest: Path, idx: int) -> float:
    """Normalise one clip to the output size/fps (and audio layout); return its duration."""
    src = (root / clip["src"]).resolve() if not Path(clip["src"]).is_absolute() else Path(clip["src"])
    if not src.exists():
        raise PlanError(f"clip source not found: {clip['src']}")
    w, h, fps, muted = cfg["width"], cfg["height"], cfg["fps"], cfg["muted"]
    fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps},format=yuv420p"
    is_image = src.suffix.lower() in IMAGE_EXT
    args: list[str] = []
    if is_image:
        duration = float(clip["duration"])
        frames = max(1, int(round(duration * fps)))
        zoom = float(clip.get("zoom", 1.1))
        step = (zoom - 1.0) / frames
        # Ken Burns: render large, zoom slowly towards the centre, then fit.
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='min(1+{step:.6f}*on,{zoom})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={w}x{h}:fps={fps},{fit}")
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(src)]
        if not muted:
            args += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        args += ["-vf", vf, "-frames:v", str(frames)]
    else:
        info = probe(src)
        start = float(clip.get("start", 0))
        if "end" in clip:
            duration = float(clip["end"]) - start
        else:
            duration = float(clip.get("duration", info["duration"] - start))
        if start >= info["duration"] or duration <= 0:
            raise PlanError(f"clip {clip['src']}: start {start}s is beyond its length {info['duration']:.2f}s")
        duration = min(duration, info["duration"] - start)
        args += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
        if not muted and not info["has_audio"]:
            args += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        args += ["-vf", fit]
    if muted:
        args += ["-an"]
    else:
        args += ["-map", "0:v:0", "-map", "1:a:0" if (is_image or not probe(src)["has_audio"]) else "0:a:0",
                 "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(dest)]
    ff(args, f"preparing clip {idx} ({clip['src']})")
    return duration


def encode(master: Path, out_dir: Path, cfg: dict[str, Any], duration: float, root: Path,
           level: int) -> dict[str, Path]:
    name, fade, muted = cfg["name"], float(cfg["fade"]), cfg["muted"]
    vf = []
    if fade > 0 and duration > 2 * fade:
        vf.append(f"fade=t=in:st=0:d={fade}")
        vf.append(f"fade=t=out:st={duration - fade:.3f}:d={fade}")
    filters = ["-vf", ",".join(vf)] if vf else []
    music = cfg.get("audio")
    audio_in: list[str] = []
    audio_map: list[str] = []
    if not muted and music:
        track = root / music
        if not track.exists():
            raise PlanError(f"audio track not found: {music}")
        audio_in = ["-i", str(track)]
        afade = f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade}" if fade else "anull"
        audio_map = ["-map", "0:v:0", "-map", "1:a:0", "-af", afade, "-shortest"]
    files = {}
    if "mp4" in cfg["formats"]:
        mp4 = out_dir / f"{name}.mp4"
        audio = ["-an"] if muted else ["-c:a", "aac", "-b:a", "160k"]
        ff(["-i", str(master), *audio_in, *filters, *audio_map, "-c:v", "libx264", "-preset", "slow",
            "-crf", str(MP4_CRF[level]), "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            *audio, "-t", f"{duration:.3f}", str(mp4)], f"encoding {mp4.name}")
        files["mp4"] = mp4
    if "webm" in cfg["formats"]:
        webm = out_dir / f"{name}.webm"
        audio = ["-an"] if muted else ["-c:a", "libopus", "-b:a", "128k"]
        ff(["-i", str(master), *audio_in, *filters, *audio_map, "-c:v", "libvpx-vp9", "-b:v", "0",
            "-crf", str(WEBM_CRF[level]), "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
            "-pix_fmt", "yuv420p", *audio, "-t", f"{duration:.3f}", str(webm)], f"encoding {webm.name}")
        files["webm"] = webm
    return files


def render_output(cfg: dict[str, Any], root: Path, out_dir: Path, work: Path) -> dict[str, Any]:
    cfg = {**DEFAULTS, **cfg}
    name = cfg["name"]
    segs, total = [], 0.0
    for i, clip in enumerate(cfg["clips"]):
        seg = work / f"{name}-{i:03d}.mp4"
        total += segment(clip, root, cfg, seg, i)
        segs.append(seg)
    listing = work / f"{name}-concat.txt"
    listing.write_text("".join(f"file '{s}'\n" for s in segs), encoding="utf-8")
    master = work / f"{name}-master.mp4"
    ff(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(master)], f"joining clips of {name}")
    duration = min(total, float(cfg.get("max_seconds") or total))

    max_kb = float(cfg["max_kb"])
    for level in range(len(MP4_CRF)):
        files = encode(master, out_dir, cfg, duration, root, level)
        sizes = {fmt: round(path.stat().st_size / 1024, 1) for fmt, path in files.items()}
        if all(kb <= max_kb for kb in sizes.values()):
            break
    over = {fmt: kb for fmt, kb in sizes.items() if kb > max_kb}

    poster = None
    if cfg["poster"]:
        poster = out_dir / f"{name}.jpg"
        ff(["-ss", f"{min(1.0, duration / 2):.3f}", "-i", str(master), "-frames:v", "1", "-q:v", "3", str(poster)],
           f"extracting the poster of {name}")
    return {"name": name, "duration": round(duration, 3), "width": cfg["width"], "height": cfg["height"],
            "fps": cfg["fps"], "muted": cfg["muted"], "loop": bool(cfg.get("loop", cfg["muted"])),
            "max_kb": max_kb, "quality_level": level,
            "files": {fmt: path.name for fmt, path in files.items()} | ({"poster": poster.name} if poster else {}),
            "size_kb": sizes, "over_budget": over}


def cmd_render(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    root = Path(args.root).resolve() if args.root else plan_path.parent
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    only = set(args.only or [])
    manifest_path = out_dir / "videos.json"
    try:
        manifest = {v["name"]: v for v in json.loads(manifest_path.read_text())["videos"]} if manifest_path.exists() else {}
    except (ValueError, KeyError, TypeError):
        manifest = {}
    failed = False
    with tempfile.TemporaryDirectory(prefix="oc-video-") as tmp:
        for cfg in plan["outputs"]:
            if only and cfg["name"] not in only:
                continue
            print(f"[video] ▶ {cfg['name']}: {len(cfg['clips'])} clip(s)", flush=True)
            try:
                entry = render_output(cfg, root, out_dir, Path(tmp))
            except (PlanError, RuntimeError) as exc:
                print(f"  ✗ {cfg['name']}: {exc}")
                failed = True
                continue
            manifest[entry["name"]] = entry
            sizes = ", ".join(f"{fmt} {kb:.0f} KB" for fmt, kb in entry["size_kb"].items())
            if entry["over_budget"]:
                print(f"  ✗ {entry['name']}: over the {entry['max_kb']:.0f} KB budget at the lowest quality ({sizes}) "
                      f"— shorten it or lower the resolution")
                failed = True
            else:
                print(f"  ✓ {entry['name']}: {entry['duration']:.1f}s {entry['width']}×{entry['height']} · {sizes}"
                      + (f" · poster {entry['files']['poster']}" if "poster" in entry["files"] else ""))
    manifest_path.write_text(json.dumps({"version": 1, "videos": sorted(manifest.values(), key=lambda v: v["name"])},
                                        indent=2) + "\n", encoding="utf-8")
    print(f"[video] manifest: {manifest_path}")
    return 1 if failed else 0


# ─── check ────────────────────────────────────────────────────────────────────

def mp4_faststart(path: Path) -> bool:
    """True when the moov atom comes before mdat (playback starts before the download ends)."""
    with open(path, "rb") as fh:
        offset = 0
        size_total = path.stat().st_size
        while offset < size_total:
            fh.seek(offset)
            header = fh.read(16)
            if len(header) < 8:
                return False
            size, kind = struct.unpack(">I4s", header[:8])
            if size == 1:
                size = struct.unpack(">Q", header[8:16])[0]
            elif size == 0:
                size = size_total - offset
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            offset += max(size, 8)
    return False


def cmd_check(args: argparse.Namespace) -> int:
    directory = Path(args.dir).resolve()
    manifest_path = directory / "videos.json"
    if not manifest_path.exists():
        print(f"[video] {manifest_path} not found — render the videos with `video.py render` first")
        return 1
    videos = json.loads(manifest_path.read_text(encoding="utf-8")).get("videos", [])
    problems: list[str] = []
    for v in videos:
        name, files = v["name"], v.get("files", {})
        budget = float(args.budget_kb or v.get("max_kb") or DEFAULTS["max_kb"])
        for fmt in ("mp4", "webm"):
            if fmt not in files:
                problems.append(f"{name}: no {fmt} — browsers need both (Safari: MP4, others prefer WebM)")
        if "poster" not in files:
            problems.append(f"{name}: no poster image (shown before playback and with prefers-reduced-motion)")
        for fmt, file in files.items():
            path = directory / file
            if not path.exists():
                problems.append(f"{name}: {file} is listed but missing")
                continue
            kb = path.stat().st_size / 1024
            if fmt != "poster" and kb > budget:
                problems.append(f"{name}: {file} is {kb:.0f} KB, budget {budget:.0f} KB")
            if fmt == "mp4" and not mp4_faststart(path):
                problems.append(f"{name}: {file} is not faststart (moov after mdat) — encode with -movflags +faststart")
            if fmt in ("mp4", "webm") and v.get("muted") and probe(path)["has_audio"]:
                problems.append(f"{name}: {file} has an audio track although it is muted (autoplay loops must be silent)")
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print(f"[video] {len(problems)} problem(s) in {len(videos)} video(s)")
        return 1
    print(f"[video] {len(videos)} video(s) ready for the web")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("scenes")
    p.add_argument("file")
    p.add_argument("--threshold", type=float, default=0.3, help="0–1, lower finds more cuts (default 0.3)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scenes)

    p = sub.add_parser("render")
    p.add_argument("--plan", required=True, help="edit plan JSON")
    p.add_argument("--root", help="base directory of clip sources (default: the plan's directory)")
    p.add_argument("--out-dir", default="public/videos")
    p.add_argument("--only", nargs="*", help="render only these outputs")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("check")
    p.add_argument("dir", nargs="?", default="public/videos")
    p.add_argument("--budget-kb", type=float, help="override every video's max_kb")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        need_ffmpeg()
        return args.func(args)
    except PlanError as exc:
        print(f"[video] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
