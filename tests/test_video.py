"""hooks/video.py — cut, assemble and encode web videos (needs ffmpeg)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import shutil

from conftest import py, write_json

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg not installed")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def raw(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("raw")
    # 6 s colour bars with a hard cut to red at 3 s, plus a tone
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=480x270:rate=25:duration=3", "-f", "lavfi",
           "-i", "color=c=red:size=480x270:rate=25:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
           "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-c:a", "aac", "-shortest", str(d / "clip.mp4"))
    ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=640x400", "-frames:v", "1", str(d / "photo.jpg"))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=480x270:rate=25:duration=2", "-c:v", "libx264", str(d / "silent.mp4"))
    return d


def video(*args: str, **kw):
    return py("video.py", *args, timeout=600, **kw)


def plan(tmp_path: Path, outputs: list) -> Path:
    return write_json(tmp_path / "plan.json", {"outputs": outputs})


def probe(path: Path) -> dict:
    return json.loads(video("probe", str(path), "--json").stdout)


SMALL = {"width": 320, "height": 180, "fps": 25}


def test_probe_and_scenes(raw):
    info = probe(raw / "clip.mp4")
    assert info["width"] == 480 and info["has_audio"] and 5.9 < info["duration"] < 6.2
    r = video("scenes", str(raw / "clip.mp4"), "--json")
    cuts = json.loads(r.stdout)["cuts"]
    assert any(2.8 < c < 3.2 for c in cuts), cuts


def test_render_muted_hero_from_clips_and_image(tmp_path, raw):
    p = plan(tmp_path, [{"name": "hero", **SMALL, "muted": True, "max_seconds": 5, "fade": 0.3, "clips": [
        {"src": str(raw / "clip.mp4"), "start": 0.5, "end": 2.5},
        {"src": str(raw / "photo.jpg"), "duration": 2, "zoom": 1.2},
        {"src": str(raw / "clip.mp4"), "start": 4, "duration": 3}]}])
    out = tmp_path / "out"
    r = video("render", "--plan", str(p), "--out-dir", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ("hero.mp4", "hero.webm", "hero.jpg", "videos.json"):
        assert (out / name).exists(), name
    mp4, webm = probe(out / "hero.mp4"), probe(out / "hero.webm")
    assert (mp4["width"], mp4["height"], mp4["video_codec"]) == (320, 180, "h264")
    assert webm["video_codec"] == "vp9"
    assert not mp4["has_audio"] and not webm["has_audio"]
    assert 4.8 < mp4["duration"] < 5.2  # 7 s of clips, capped at max_seconds
    entry = json.loads((out / "videos.json").read_text())["videos"][0]
    assert entry["muted"] and entry["loop"] and entry["files"]["poster"] == "hero.jpg"
    assert video("check", str(out)).returncode == 0


def test_render_with_sound_keeps_source_audio_and_fills_images_with_silence(tmp_path, raw):
    p = plan(tmp_path, [{"name": "film", **SMALL, "muted": False, "fade": 0, "clips": [
        {"src": str(raw / "clip.mp4"), "start": 0, "end": 1.5},
        {"src": str(raw / "photo.jpg"), "duration": 1},
        {"src": str(raw / "silent.mp4")}]}])
    out = tmp_path / "out"
    assert video("render", "--plan", str(p), "--out-dir", str(out)).returncode == 0
    mp4 = probe(out / "film.mp4")
    assert mp4["has_audio"] and mp4["audio_codec"] == "aac" and 4.3 < mp4["duration"] < 4.7
    assert probe(out / "film.webm")["audio_codec"] == "opus"


def test_over_budget_steps_quality_down_then_fails(tmp_path, raw):
    p = plan(tmp_path, [{"name": "big", **SMALL, "max_kb": 1, "formats": ["mp4"], "poster": False,
                         "clips": [{"src": str(raw / "clip.mp4")}]}])
    r = video("render", "--plan", str(p), "--out-dir", str(tmp_path / "out"))
    assert r.returncode == 1 and "over the 1 KB budget at the lowest quality" in r.stdout
    entry = json.loads((tmp_path / "out" / "videos.json").read_text())["videos"][0]
    assert entry["quality_level"] == 3 and entry["over_budget"]


def test_check_finds_missing_formats_audio_and_budget(tmp_path, raw):
    out = tmp_path / "out"
    p = plan(tmp_path, [{"name": "hero", **SMALL, "clips": [{"src": str(raw / "clip.mp4"), "end": 1}]}])
    assert video("render", "--plan", str(p), "--out-dir", str(out)).returncode == 0
    (out / "hero.webm").unlink()
    ffmpeg("-i", str(raw / "clip.mp4"), "-t", "1", "-c", "copy", str(tmp_path / "loud.mp4"))
    (tmp_path / "loud.mp4").replace(out / "hero.mp4")  # muted in the manifest, but has audio and no faststart
    r = video("check", str(out), "--budget-kb", "5")
    assert r.returncode == 1
    assert "hero.webm is listed but missing" in r.stdout
    assert "has an audio track although it is muted" in r.stdout
    assert "is not faststart" in r.stdout
    assert "budget 5 KB" in r.stdout


@pytest.mark.parametrize("outputs,message", [
    ([], "non-empty 'outputs'"),
    ([{"name": "a b", "clips": [{"src": "x.mp4"}]}], "simple slug"),
    ([{"name": "a", "clips": []}], "has no clips"),
    ([{"name": "a", "clips": [{"src": "x.jpg"}]}], "an image needs 'duration'"),
    ([{"name": "a", "clips": [{"src": "x.mp4", "start": 3, "end": 2}]}], "end must be after start"),
    ([{"name": "a", "formats": ["gif"], "clips": [{"src": "x.mp4"}]}], "unsupported format"),
])
def test_invalid_plans(tmp_path, outputs, message):
    r = video("render", "--plan", str(plan(tmp_path, outputs)), "--out-dir", str(tmp_path / "out"))
    assert r.returncode == 2 and message in r.stderr, r.stderr


def test_missing_source_fails_that_output_only(tmp_path, raw):
    p = plan(tmp_path, [{"name": "bad", **SMALL, "clips": [{"src": "nope.mp4"}]},
                        {"name": "good", **SMALL, "formats": ["mp4"], "clips": [{"src": str(raw / "clip.mp4"), "end": 1}]}])
    r = video("render", "--plan", str(p), "--out-dir", str(tmp_path / "out"))
    assert r.returncode == 1 and "clip source not found: nope.mp4" in r.stdout
    assert (tmp_path / "out" / "good.mp4").exists()


def test_check_without_manifest(tmp_path):
    assert video("check", str(tmp_path)).returncode == 1
