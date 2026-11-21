#!/usr/bin/env python3
"""OneCommand scene3d — check the 3D scenes of a website or web app.

Part of the web-3d skill · Copyright © 2026 GK DigitalStudio UG

A 3D hero, a product viewer or a configurator either feels premium or makes the page
slow, blank on old phones and dizzy for people who switched motion off. This script
measures the models and checks the code rules the `web-3d` skill sets.

Subcommands
-----------
inspect  One model (.glb or .gltf): file size, triangles, meshes, materials, textures
         with their pixel size and format, animations, extensions, geometry compression.
check    Every scene in spec.media.scenes:
         - model: exists, within max_kb, max_triangles and max_texture_px; geometry
           compressed (Draco or Meshopt) once it is over 200 KB
         - poster: exists, under 200 KB (shown while loading, without WebGL and with
           prefers-reduced-motion)
         - component: exists, handles prefers-reduced-motion, has a fallback without
           WebGL, is loaded lazily (a dynamic import() from another file, or an
           IntersectionObserver), carries an accessible name
         - credits: every model not built in code is listed in assets/CREDITS.md
         Models under public/ that no scene names are reported as warnings.

Spec section
------------
"media": {"scenes": [
  {"name": "hero", "kind": "hero", "purpose": "3D-Logo über dem Claim auf /",
   "model": "public/models/logo.glb", "poster": "public/models/logo.jpg",
   "component": "components/three/HeroScene.tsx", "source": "own",
   "max_kb": 800, "max_triangles": 60000, "max_texture_px": 2048}
]}
kind: hero · product · configurator · scroll · data · background
model: null for scenes built from code (procedural geometry) — then only poster,
component and code rules are checked. source: own · procedural · cc0 · licensed.

Exit codes: 0 ok · 1 check failed · 2 usage error (no spec section, unreadable model)
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

DEFAULTS = {"max_kb": 1500, "max_triangles": 150_000, "max_texture_px": 2048}
POSTER_MAX_KB = 200
COMPRESS_FROM_KB = 200
GEOMETRY_COMPRESSION = {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}
TEXTURE_COMPRESSION = {"KHR_texture_basisu", "EXT_texture_webp", "EXT_texture_avif"}
MODEL_EXT = {".glb", ".gltf"}
SOURCE_EXT = {".tsx", ".ts", ".jsx", ".js", ".mjs", ".vue", ".svelte", ".astro", ".php", ".html"}
SKIP_DIRS = {"node_modules", ".next", ".git", "dist", "build", ".onecommand", "out", "coverage", ".turbo", "vendor"}
KINDS = {"hero", "product", "configurator", "scroll", "data", "background"}
CODE_SOURCES = {"procedural", "own"}

REDUCED_MOTION = re.compile(r"prefers-reduced-motion|useReducedMotion|reducedMotion|reduced-motion", re.I)
WEBGL_FALLBACK = re.compile(
    r"WebGL(2)?RenderingContext|getContext\(\s*['\"](webgl2?|experimental-webgl)['\"]|isWebGL(2)?Available"
    r"|WebGL\.is|webglAvailable|hasWebGL|supportsWebGL|onContextLost|webglcontextlost|ErrorBoundary"
    r"|fallback=\{|<noscript", re.I)
ACCESSIBLE_NAME = re.compile(r"aria-label|aria-labelledby|aria-hidden|role=['\"]img['\"]|alt=", re.I)
LAZY_IN_FILE = re.compile(r"IntersectionObserver|useInView|whileInView|loading=['\"]lazy['\"]", re.I)


class ModelError(Exception):
    pass


# ─── image headers ────────────────────────────────────────────────────────────

def image_info(data: bytes) -> tuple[str, int, int]:
    """(format, width, height) from the first bytes of a PNG, JPEG, WebP, KTX2 or AVIF file."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", w, h
            i += 2 + seg_len
        return "jpeg", 0, 0
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return "webp", w, h
        if kind == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "webp", w, h
        return "webp", 0, 0
    if data[:12] == b"\xabKTX 20\xbb\r\n\x1a\n" and len(data) >= 28:
        w, h = struct.unpack("<II", data[20:28])
        return "ktx2", w, h
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        m = data.find(b"ispe")
        if m != -1 and m + 12 <= len(data):
            w, h = struct.unpack(">II", data[m + 8:m + 16])
            return "avif", w, h
        return "avif", 0, 0
    return "unknown", 0, 0


# ─── glTF reader ──────────────────────────────────────────────────────────────

def load_gltf(path: Path) -> tuple[dict[str, Any], bytes | None, int]:
    """(json, binary chunk, total bytes on disk incl. external buffers and images)."""
    if not path.is_file():
        raise ModelError(f"{path} not found")
    raw = path.read_bytes()
    total = len(raw)
    if path.suffix.lower() == ".glb" or raw[:4] == b"glTF":
        if len(raw) < 20 or raw[:4] != b"glTF":
            raise ModelError(f"{path.name}: not a binary glTF (magic bytes missing)")
        version, length = struct.unpack("<II", raw[4:12])
        if version != 2:
            raise ModelError(f"{path.name}: glTF version {version}, only 2.0 is supported")
        if length > len(raw):
            raise ModelError(f"{path.name}: truncated ({len(raw)} of {length} bytes)")
        offset, doc, binary = 12, None, None
        while offset + 8 <= length:
            chunk_len, chunk_type = struct.unpack("<II", raw[offset:offset + 8])
            body = raw[offset + 8:offset + 8 + chunk_len]
            if chunk_type == 0x4E4F534A:
                doc = json.loads(body.decode("utf-8").rstrip(" \x00"))
            elif chunk_type == 0x004E4942:
                binary = body
            offset += 8 + chunk_len
        if doc is None:
            raise ModelError(f"{path.name}: no JSON chunk")
    else:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ModelError(f"{path.name}: not valid glTF JSON ({exc})") from None
        binary = None
    for item in (doc.get("buffers") or []) + (doc.get("images") or []):
        uri = item.get("uri")
        if uri and not uri.startswith("data:"):
            ext = path.parent / uri
            if not ext.is_file():
                raise ModelError(f"{path.name}: referenced file {uri} is missing")
            total += ext.stat().st_size
    return doc, binary, total


def buffer_bytes(doc: dict[str, Any], binary: bytes | None, base: Path, index: int) -> bytes:
    buf = (doc.get("buffers") or [])[index]
    uri = buf.get("uri")
    if uri is None:
        return binary or b""
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    return (base / uri).read_bytes()


def image_bytes(doc: dict[str, Any], binary: bytes | None, base: Path, image: dict[str, Any]) -> bytes:
    if "bufferView" in image:
        view = doc["bufferViews"][image["bufferView"]]
        data = buffer_bytes(doc, binary, base, view.get("buffer", 0))
        start = view.get("byteOffset", 0)
        return data[start:start + view["byteLength"]]
    uri = image.get("uri", "")
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    target = base / uri
    return target.read_bytes()[:65536] if target.is_file() else b""


def triangles_of(doc: dict[str, Any], prim: dict[str, Any]) -> int:
    accessors = doc.get("accessors") or []
    mode = prim.get("mode", 4)
    if "indices" in prim:
        count = accessors[prim["indices"]].get("count", 0)
    elif "POSITION" in prim.get("attributes", {}):
        count = accessors[prim["attributes"]["POSITION"]].get("count", 0)
    else:
        return 0
    if mode == 4:
        return count // 3
    if mode in (5, 6):
        return max(0, count - 2)
    return 0  # points and lines draw no triangles


def inspect_model(path: Path) -> dict[str, Any]:
    doc, binary, total = load_gltf(path)
    base = path.parent
    used = set(doc.get("extensionsUsed") or [])
    meshes = doc.get("meshes") or []
    tris = sum(triangles_of(doc, p) for m in meshes for p in m.get("primitives", []))
    # instancing: a mesh drawn by n nodes costs n times its triangles
    per_mesh = [sum(triangles_of(doc, p) for p in m.get("primitives", [])) for m in meshes]
    drawn = 0
    for node in doc.get("nodes") or []:
        if "mesh" in node:
            copies = 1
            inst = (node.get("extensions") or {}).get("EXT_mesh_gpu_instancing")
            if inst and "TRANSLATION" in inst.get("attributes", {}):
                copies = doc["accessors"][inst["attributes"]["TRANSLATION"]].get("count", 1)
            elif inst and inst.get("attributes"):
                first = next(iter(inst["attributes"].values()))
                copies = doc["accessors"][first].get("count", 1)
            drawn += per_mesh[node["mesh"]] * copies
    textures = []
    for i, image in enumerate(doc.get("images") or []):
        fmt, w, h = image_info(image_bytes(doc, binary, base, image))
        textures.append({"index": i, "name": image.get("name") or image.get("uri") or f"image{i}",
                         "format": fmt, "width": w, "height": h})
    return {
        "file": str(path),
        "kb": round(total / 1024, 1),
        "triangles": max(tris, drawn),
        "meshes": len(meshes),
        "materials": len(doc.get("materials") or []),
        "textures": textures,
        "animations": len(doc.get("animations") or []),
        "extensions": sorted(used),
        "geometry_compressed": bool(used & GEOMETRY_COMPRESSION),
        "texture_compression": sorted(used & TEXTURE_COMPRESSION),
    }


# ─── project helpers ──────────────────────────────────────────────────────────

def source_files(project: Path) -> list[Path]:
    files = []
    for p in project.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(project).parts):
            continue
        if p.is_file() and p.suffix.lower() in SOURCE_EXT:
            files.append(p)
    return files


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def lazy_importers(files: list[Path], component: Path) -> list[Path]:
    """Files that load the component with a dynamic import (next/dynamic, React.lazy, import())."""
    stem = re.escape(component.stem)
    pattern = re.compile(r"import\(\s*['\"][^'\"]*\b" + stem + r"(\.\w+)?['\"]\s*\)")
    return [f for f in files if f != component and pattern.search(read_text(f))]


IMPORT_FROM = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")


def local_imports(project: Path, path: Path) -> list[Path]:
    """Project files a source file imports (relative paths and the @/ alias), resolved to existing files."""
    found = []
    for spec in IMPORT_FROM.findall(read_text(path)):
        if spec.startswith("@/"):
            base = project / spec[2:]
        elif spec.startswith("."):
            base = (path.parent / spec).resolve()
        else:
            continue
        candidates = [base] + [base.with_name(base.name + ext) for ext in SOURCE_EXT] + \
                     [base / f"index{ext}" for ext in (".tsx", ".ts", ".jsx", ".js")]
        hit = next((c for c in candidates if c.is_file()), None)
        if hit:
            found.append(hit)
    return found


def model_issues(name: str, info: dict[str, Any], scene: dict[str, Any]) -> list[str]:
    issues = []
    max_kb = float(scene.get("max_kb") or DEFAULTS["max_kb"])
    max_tris = int(scene.get("max_triangles") or DEFAULTS["max_triangles"])
    max_px = int(scene.get("max_texture_px") or DEFAULTS["max_texture_px"])
    if info["kb"] > max_kb:
        issues.append(f"{name}: model is {info['kb']:.0f} KB, budget {max_kb:.0f} KB — "
                      "compress (gltf-transform optimize) or simplify")
    if info["triangles"] > max_tris:
        issues.append(f"{name}: {info['triangles']:,} triangles, budget {max_tris:,} — "
                      "decimate (gltf-transform simplify) or bake detail into normal maps")
    if info["kb"] > COMPRESS_FROM_KB and not info["geometry_compressed"]:
        issues.append(f"{name}: {info['kb']:.0f} KB without geometry compression — "
                      "run gltf-transform with --compress draco or meshopt")
    for t in info["textures"]:
        if max(t["width"], t["height"]) > max_px:
            issues.append(f"{name}: texture {t['name']} is {t['width']}×{t['height']} px, limit {max_px} px "
                          "— resize (gltf-transform resize) before shipping")
        if t["format"] == "unknown":
            issues.append(f"{name}: texture {t['name']} has an unknown format — use JPEG, PNG, WebP or KTX2")
    return issues


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        info = inspect_model(Path(args.file))
    except ModelError as exc:
        print(f"[scene3d] {exc}")
        return 2
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    print(f"{info['file']}: {info['kb']} KB · {info['triangles']:,} triangles · {info['meshes']} meshes · "
          f"{info['materials']} materials · {info['animations']} animations")
    print(f"  geometry compression: {'yes' if info['geometry_compressed'] else 'no'}"
          f" · texture compression: {', '.join(info['texture_compression']) or 'none'}")
    for t in info["textures"]:
        print(f"  texture {t['name']}: {t['format']} {t['width']}×{t['height']}")
    if info["extensions"]:
        print(f"  extensions: {', '.join(info['extensions'])}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec_path = Path(args.spec) if Path(args.spec).is_absolute() else project / args.spec
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[scene3d] {spec_path} not found")
        return 2
    except ValueError as exc:
        print(f"[scene3d] {spec_path} is not valid JSON: {exc}")
        return 2
    scenes = (spec.get("media") or {}).get("scenes")
    if not scenes:
        print("[scene3d] spec has no media.scenes — nothing to check")
        return 2
    if not isinstance(scenes, list):
        print("[scene3d] media.scenes must be a list")
        return 2

    files = source_files(project)
    credits_path = project / "assets" / "CREDITS.md"
    credits = read_text(credits_path) if credits_path.is_file() else ""
    problems: list[str] = []
    warnings: list[str] = []
    named_models: set[Path] = set()
    report = []

    for i, scene in enumerate(scenes):
        name = str(scene.get("name") or f"scene{i + 1}")
        entry: dict[str, Any] = {"name": name}
        kind = scene.get("kind")
        if kind not in KINDS:
            problems.append(f"{name}: kind {kind!r} — use one of {', '.join(sorted(KINDS))}")

        model = scene.get("model")
        source = str(scene.get("source") or ("procedural" if not model else "")).lower()
        if model:
            mpath = (project / model).resolve()
            named_models.add(mpath)
            try:
                info = inspect_model(mpath)
            except ModelError as exc:
                problems.append(f"{name}: {exc}")
            else:
                entry["model"] = info
                problems.extend(model_issues(name, info, scene))
            if source not in CODE_SOURCES and Path(model).name not in credits:
                problems.append(f"{name}: {Path(model).name} is not listed in assets/CREDITS.md "
                                "(source, author, license) — every third-party model needs one")
            if not source:
                warnings.append(f"{name}: no 'source' — set own, procedural, cc0 or licensed")

        poster = scene.get("poster")
        if not poster:
            problems.append(f"{name}: no poster — a still image is needed while loading, without WebGL and "
                            "with prefers-reduced-motion")
        else:
            ppath = project / poster
            if not ppath.is_file():
                problems.append(f"{name}: poster {poster} is missing")
            elif ppath.stat().st_size / 1024 > POSTER_MAX_KB:
                problems.append(f"{name}: poster is {ppath.stat().st_size / 1024:.0f} KB, limit {POSTER_MAX_KB} KB "
                                "(it is the LCP image)")

        component = scene.get("component")
        if not component:
            problems.append(f"{name}: no component — name the file that renders the scene")
        else:
            cpath = project / component
            if not cpath.is_file():
                problems.append(f"{name}: component {component} is missing")
            else:
                text = read_text(cpath)
                importers = lazy_importers(files, cpath)
                # the rules may live in the scene, in the file that loads it or in the wrapper that file uses
                related = {cpath.resolve()}
                for f in importers:
                    related.add(f.resolve())
                    related.update(x.resolve() for x in local_imports(project, f))
                context = "".join(read_text(f) for f in sorted(related))
                if not REDUCED_MOTION.search(context):
                    problems.append(f"{name}: {component} ignores prefers-reduced-motion — stop auto-rotation, "
                                    "scroll animation and camera moves, show the poster or a still frame")
                if not WEBGL_FALLBACK.search(context):
                    problems.append(f"{name}: {component} has no fallback without WebGL — catch a failed context "
                                    "(error boundary or WebGL check) and show the poster")
                if poster and Path(poster).name not in context:
                    problems.append(f"{name}: the poster {Path(poster).name} is not used by {component} or the "
                                    "file that loads it")
                lazy = bool(importers) or bool(LAZY_IN_FILE.search(text))
                if not lazy:
                    problems.append(f"{name}: {component} is not loaded lazily — a dynamic import() (Scene3D, next/dynamic, "
                                    "React.lazy) or an IntersectionObserver keeps three.js out of the first load")
                if not ACCESSIBLE_NAME.search(context):
                    problems.append(f"{name}: the canvas has no accessible name — aria-label for a meaningful "
                                    "scene, aria-hidden for decoration")
                if kind == "configurator" and not re.search(r"<button|<input|<select|role=['\"](radio|button)", context):
                    problems.append(f"{name}: configurator without HTML controls — every option must be a "
                                    "button, radio or select, not only a click on the mesh")
        report.append(entry)

    public = project / "public"
    if public.is_dir():
        for p in public.rglob("*"):
            if p.suffix.lower() in MODEL_EXT and p.resolve() not in named_models:
                warnings.append(f"{p.relative_to(project)} is shipped but no scene in media.scenes names it")

    out = project / ".onecommand" / "scene3d.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"scenes": report, "problems": problems, "warnings": warnings}, indent=2),
                   encoding="utf-8")
    for w in warnings:
        print(f"  ! {w}")
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print(f"[scene3d] {len(problems)} problem(s) in {len(scenes)} scene(s)")
        return 1
    print(f"[scene3d] {len(scenes)} scene(s) ready for the web")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="size, triangles, textures and compression of one model")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("check", help="check every scene in spec.media.scenes")
    p.add_argument("--project-dir", default=".")
    p.add_argument("--spec", default=".onecommand-spec.json")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
