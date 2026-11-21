"""hooks/scene3d.py — glTF inspection and the 3D scene rules of the web-3d skill."""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path

import pytest

from conftest import REPO, py, write_json

SKILL = REPO / "skills" / "web-3d" / "SKILL.md"


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(b"\x00" + b"\x00" * (width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg_header(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def glb(path: Path, *, triangles: int = 12, texture: bytes | None = None, extensions: list[str] | None = None,
        padding_kb: int = 0, instances: int = 0) -> Path:
    """A minimal valid GLB: one indexed triangle mesh, optional embedded texture and padding."""
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack(f"<{triangles * 3}H", *([0, 1, 2] * triangles))
    indices += b"\x00" * (-len(indices) % 4)
    binary = positions + indices
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
             {"buffer": 0, "byteOffset": len(positions), "byteLength": triangles * 6}]
    doc: dict = {
        "asset": {"version": "2.0"},
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                       "min": [0, 0, 0], "max": [1, 1, 0]},
                      {"bufferView": 1, "componentType": 5123, "count": triangles * 3, "type": "SCALAR"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }
    if instances:
        offs = struct.pack(f"<{instances * 3}f", *([0.0] * instances * 3))
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(offs)})
        doc["accessors"].append({"bufferView": len(views) - 1, "componentType": 5126, "count": instances, "type": "VEC3"})
        doc["nodes"][0]["extensions"] = {"EXT_mesh_gpu_instancing": {"attributes": {"TRANSLATION": len(doc["accessors"]) - 1}}}
        binary += offs
        extensions = [*(extensions or []), "EXT_mesh_gpu_instancing"]
    if texture is not None:
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(texture)})
        doc["images"] = [{"bufferView": len(views) - 1, "mimeType": "image/png", "name": "albedo"}]
        binary += texture + b"\x00" * (-len(texture) % 4)
    if padding_kb:
        binary += b"\x00" * (padding_kb * 1024)
    doc["bufferViews"] = views
    doc["buffers"] = [{"byteLength": len(binary)}]
    if extensions:
        doc["extensionsUsed"] = extensions
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    return path


def skill_block(name: str) -> str:
    """The code block that follows `// components/three/<name>` in the skill — tests use the documented code."""
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(r"```tsx\n(// components/three/" + re.escape(name) + r"\n.*?)```", text, re.S)
    assert m, f"{name} block missing in web-3d SKILL.md"
    return m.group(1)


def inspect(path: Path) -> dict:
    r = py("scene3d.py", "inspect", str(path), "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


# ─── inspect ──────────────────────────────────────────────────────────────────

def test_inspect_counts_triangles_textures_and_compression(tmp_path):
    info = inspect(glb(tmp_path / "a.glb", triangles=40, texture=png(64, 32),
                       extensions=["EXT_meshopt_compression", "EXT_texture_webp"]))
    assert info["triangles"] == 40 and info["meshes"] == 1
    assert info["textures"] == [{"index": 0, "name": "albedo", "format": "png", "width": 64, "height": 32}]
    assert info["geometry_compressed"] is True and info["texture_compression"] == ["EXT_texture_webp"]


def test_inspect_multiplies_gpu_instances(tmp_path):
    assert inspect(glb(tmp_path / "trees.glb", triangles=10, instances=50))["triangles"] == 500


def test_inspect_reads_jpeg_size_and_rejects_non_gltf(tmp_path):
    info = inspect(glb(tmp_path / "j.glb", texture=jpeg_header(4096, 2048)))
    assert (info["textures"][0]["format"], info["textures"][0]["width"], info["textures"][0]["height"]) == ("jpeg", 4096, 2048)
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"not a model at all, just text")
    r = py("scene3d.py", "inspect", str(bad))
    assert r.returncode == 2 and "magic" in r.stdout


def test_inspect_gltf_counts_external_files(tmp_path):
    (tmp_path / "m.bin").write_bytes(b"\x00" * 4096)
    write_json(tmp_path / "m.gltf", {"asset": {"version": "2.0"}, "buffers": [{"uri": "m.bin", "byteLength": 4096}]})
    assert inspect(tmp_path / "m.gltf")["kb"] >= 4
    (tmp_path / "m.bin").unlink()
    r = py("scene3d.py", "inspect", str(tmp_path / "m.gltf"))
    assert r.returncode == 2 and "m.bin" in r.stdout


# ─── check ────────────────────────────────────────────────────────────────────

def project_with_documented_scene(root: Path, **scene) -> Path:
    """A project built exactly like the skill's wrapper + hero example, plus one product model."""
    three = root / "components" / "three"
    three.mkdir(parents=True)
    (three / "Scene3D.tsx").write_text(skill_block("Scene3D.tsx"), encoding="utf-8")
    (three / "HeroScene.tsx").write_text(skill_block("HeroScene.tsx"), encoding="utf-8")
    (three / "HeroSceneSlot.tsx").write_text(skill_block("HeroSceneSlot.tsx"), encoding="utf-8")
    (root / "public" / "scenes").mkdir(parents=True)
    (root / "public" / "scenes" / "hero.jpg").write_bytes(jpeg_header(1600, 900))
    glb(root / "public" / "models" / "chair.glb", triangles=200, texture=png(256, 256))
    (root / "public" / "models" / "chair.jpg").write_bytes(jpeg_header(800, 800))
    (three / "ChairViewer.tsx").write_text(
        "'use client'\nimport '@google/model-viewer'\n"
        "export default function ChairViewer({ reduced }: { reduced: boolean }) {\n"
        "  const still = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches\n"
        "  return <model-viewer src=\"/models/chair.glb\" poster=\"/models/chair.jpg\" alt=\"Sessel Lina\" "
        "loading=\"lazy\" camera-controls auto-rotate={!still || undefined} />\n}\n"
        "// model-viewer shows its poster when WebGL is missing: fallback={<img src=\"/models/chair.jpg\" />}\n",
        encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "CREDITS.md").write_text("- chair.glb — Poly Haven, CC0\n", encoding="utf-8")
    scenes = [
        {"name": "hero", "kind": "hero", "model": None, "source": "procedural",
         "poster": "public/scenes/hero.jpg", "component": "components/three/HeroScene.tsx", "max_kb": 600},
        {"name": "chair", "kind": "product", "model": "public/models/chair.glb", "source": "cc0",
         "poster": "public/models/chair.jpg", "component": "components/three/ChairViewer.tsx", **scene},
    ]
    write_json(root / ".onecommand-spec.json", {"build_targets": ["web"], "media": {"scenes": scenes}})
    return root


def check(project: Path):
    return py("scene3d.py", "check", "--project-dir", str(project))


def test_the_documented_pattern_passes(tmp_path):
    project = project_with_documented_scene(tmp_path)
    r = check(project)
    assert r.returncode == 0, r.stdout
    report = json.loads((project / ".onecommand" / "scene3d.json").read_text())
    assert report["scenes"][1]["model"]["triangles"] == 200 and report["problems"] == []


def test_budgets_compression_and_textures_fail(tmp_path):
    project = project_with_documented_scene(tmp_path, max_kb=100, max_triangles=100, max_texture_px=128)
    glb(project / "public" / "models" / "chair.glb", triangles=200, texture=png(256, 256), padding_kb=300)
    r = check(project)
    assert r.returncode == 1
    for needle in ("budget 100 KB", "budget 100", "without geometry compression", "limit 128 px"):
        assert needle in r.stdout, needle


def test_missing_poster_credits_and_unknown_kind_fail(tmp_path):
    project = project_with_documented_scene(tmp_path)
    spec = json.loads((project / ".onecommand-spec.json").read_text())
    spec["media"]["scenes"][1]["kind"] = "spinny"
    spec["media"]["scenes"][0]["poster"] = "public/scenes/missing.jpg"
    write_json(project / ".onecommand-spec.json", spec)
    (project / "assets" / "CREDITS.md").write_text("nothing here\n")
    r = check(project)
    assert r.returncode == 1
    assert "kind 'spinny'" in r.stdout and "missing.jpg is missing" in r.stdout and "CREDITS.md" in r.stdout


def test_heavy_poster_fails(tmp_path):
    project = project_with_documented_scene(tmp_path)
    (project / "public" / "scenes" / "hero.jpg").write_bytes(jpeg_header(1600, 900) + b"\x00" * 250_000)
    r = check(project)
    assert r.returncode == 1 and "LCP image" in r.stdout


def test_component_without_the_rules_fails(tmp_path):
    project = project_with_documented_scene(tmp_path)
    (project / "components" / "three" / "ChairViewer.tsx").write_text(
        "import { Canvas } from '@react-three/fiber'\n"
        "export default function ChairViewer() { return <Canvas><mesh /></Canvas> }\n", encoding="utf-8")
    r = check(project)
    assert r.returncode == 1
    for needle in ("prefers-reduced-motion", "without WebGL", "chair.jpg is not used", "not loaded lazily",
                   "accessible name"):
        assert needle in r.stdout, needle


def test_configurator_needs_html_controls(tmp_path):
    project = project_with_documented_scene(tmp_path)
    spec = json.loads((project / ".onecommand-spec.json").read_text())
    spec["media"]["scenes"][1]["kind"] = "configurator"
    write_json(project / ".onecommand-spec.json", spec)
    r = check(project)
    assert r.returncode == 1 and "configurator without HTML controls" in r.stdout
    viewer = project / "components" / "three" / "ChairViewer.tsx"
    viewer.write_text(viewer.read_text() + "// <fieldset><input type=\"radio\" name=\"farbe\" /></fieldset>\n")
    assert check(project).returncode == 0


def test_unreferenced_models_warn_and_missing_section_is_usage_error(tmp_path):
    project = project_with_documented_scene(tmp_path)
    glb(project / "public" / "models" / "old.glb")
    r = check(project)
    assert r.returncode == 0 and "old.glb is shipped but no scene" in r.stdout
    write_json(project / ".onecommand-spec.json", {"build_targets": ["web"]})
    assert check(project).returncode == 2


@pytest.mark.parametrize("needle", ['preset="', "gstatic.com", "scene3d.py\" check", "CREDITS.md", "aria-live"])
def test_skill_states_the_rules_the_checker_and_tour_enforce(needle):
    text = SKILL.read_text(encoding="utf-8")
    assert needle in text
