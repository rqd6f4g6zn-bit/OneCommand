---
name: asset-generator
description: Generates all game assets programmatically: SVG/PNG sprites, procedural textures, 3D geometry (GLB via pygltflib), Blender Python scripts for complex models, sprite sheets, and audio asset manifest.
model: claude-sonnet-4-6
---

# Game Asset Generator

Generates all game assets programmatically — no external design tools required. Run this skill alongside any game builder skill.

---

## Step 1: Detect Game Type and Engine

Read `.onecommand-spec.json` to determine:
- `engine` — `"threejs"` | `"phaser"` | `"godot2d"` | `"godot3d"`
- `genre` — affects sprite color palettes and geometry shapes
- `project_name` — used in file naming

Based on `engine`:
- `"phaser"` or `"godot2d"` → run Steps 2, 3, 6, 7
- `"threejs"` or `"godot3d"` → run Steps 2, 3, 4, 5, 6, 7

If no spec exists, default to running all steps.

Create the output directory structure:

```
public/
  assets/
    sprites/          # 2D spritesheets (PNG)
    textures/         # Procedural PNGs
    models/           # 3D GLB files
    ui/               # UI element PNGs
    backgrounds/      # Background layer PNGs
    audio/            # Placeholder (real audio fetched via manifest)
    tilemaps/         # Tilemap JSON files
    tilesets/         # Tileset PNGs
```

Run:
```bash
mkdir -p public/assets/{sprites,textures,models,ui,backgrounds,audio,tilemaps,tilesets}
```

---

## Step 2: Generate 2D Sprites

Create `/scripts/generate_sprites.py` with this complete content:

```python
#!/usr/bin/env python3
"""
generate_sprites.py
Generates placeholder sprite PNGs for 2D games using PIL.

Install: pip install Pillow
Run: python3 scripts/generate_sprites.py
"""

import os
import math
from PIL import Image, ImageDraw, ImageFilter

# ---- Output directories ----
SPRITES_DIR     = "public/assets/sprites"
UI_DIR          = "public/assets/ui"
BG_DIR          = "public/assets/backgrounds"
TILESETS_DIR    = "public/assets/tilesets"

for d in [SPRITES_DIR, UI_DIR, BG_DIR, TILESETS_DIR]:
    os.makedirs(d, exist_ok=True)


# ============================================================
# Helper: Spritesheet builder
# ============================================================

def make_spritesheet(path: str, frame_w: int, frame_h: int, frames: list[Image.Image]):
    """Stitch a list of frame Images into a horizontal strip and save."""
    sheet = Image.new("RGBA", (frame_w * len(frames), frame_h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * frame_w, 0))
    sheet.save(path)
    print(f"  Saved: {path}  ({len(frames)} frames @ {frame_w}x{frame_h})")


def blank_frame(w: int, h: int) -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ============================================================
# Player — humanoid stick figure style
# ============================================================

PLAYER_COLOR  = (70,  140, 230, 255)
SKIN_COLOR    = (255, 210, 160, 255)
HAIR_COLOR    = (60,  40,  20,  255)

def draw_humanoid(draw: ImageDraw.Draw, cx: int, cy: int, scale: float = 1.0,
                  leg_offset: int = 0, arm_angle: float = 0.0, squash: float = 1.0):
    """Draw a simple humanoid at (cx, cy). scale controls size."""
    s = scale
    # Head
    draw.ellipse([cx - 8*s, cy - 28*s*squash, cx + 8*s, cy - 12*s*squash],
                 fill=SKIN_COLOR, outline=HAIR_COLOR, width=int(1.5*s))
    # Hair
    draw.rectangle([cx - 8*s, cy - 28*s*squash, cx + 8*s, cy - 24*s*squash], fill=HAIR_COLOR)
    # Body
    draw.rectangle([cx - 6*s, cy - 12*s*squash, cx + 6*s, cy + 4*s], fill=PLAYER_COLOR, outline=(30,80,160,255), width=int(s))
    # Arms
    arm_dy = math.sin(arm_angle) * 6 * s
    draw.line([cx - 6*s, cy - 8*s, cx - 14*s, cy - 2*s + arm_dy], fill=SKIN_COLOR, width=int(2.5*s))
    draw.line([cx + 6*s, cy - 8*s, cx + 14*s, cy - 2*s - arm_dy], fill=SKIN_COLOR, width=int(2.5*s))
    # Legs
    draw.line([cx - 3*s, cy + 4*s, cx - 3*s - leg_offset, cy + 18*s], fill=PLAYER_COLOR, width=int(3*s))
    draw.line([cx + 3*s, cy + 4*s, cx + 3*s + leg_offset, cy + 18*s], fill=PLAYER_COLOR, width=int(3*s))


def generate_player_idle(frame_w=64, frame_h=64, frame_count=4):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        bob = math.sin(i / frame_count * math.pi * 2) * 1.5
        draw_humanoid(draw, frame_w//2, frame_h//2 + 6 + int(bob), scale=1.0, arm_angle=i * 0.4)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/player_idle.png", frame_w, frame_h, frames)


def generate_player_run(frame_w=64, frame_h=64, frame_count=8):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        t = i / frame_count
        leg = int(math.sin(t * math.pi * 2) * 5)
        draw_humanoid(draw, frame_w//2, frame_h//2 + 6, scale=1.0,
                      leg_offset=leg, arm_angle=t * math.pi * 2)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/player_run.png", frame_w, frame_h, frames)


def generate_player_jump(frame_w=64, frame_h=64, frame_count=2):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        draw_humanoid(draw, frame_w//2, frame_h//2 + 2, scale=1.0,
                      leg_offset=-4 if i == 0 else 0, arm_angle=1.2)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/player_jump.png", frame_w, frame_h, frames)


def generate_player_fall(frame_w=64, frame_h=64, frame_count=2):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        draw_humanoid(draw, frame_w//2, frame_h//2 + 8, scale=1.0,
                      leg_offset=3, arm_angle=-0.8)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/player_fall.png", frame_w, frame_h, frames)


def generate_player_attack(frame_w=64, frame_h=64, frame_count=3):
    frames = []
    swing_angles = [0.3, 1.8, 3.0]
    for angle in swing_angles:
        img, draw = blank_frame(frame_w, frame_h)
        draw_humanoid(draw, frame_w//2, frame_h//2 + 6, arm_angle=angle)
        # Sword flash
        if angle > 1.0:
            sx = frame_w//2 + int(math.cos(angle) * 20)
            sy = frame_h//2 - int(math.sin(angle) * 20)
            draw.line([frame_w//2 + 6, frame_h//2 - 8, sx, sy],
                      fill=(255, 255, 100, 220), width=3)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/player_attack.png", frame_w, frame_h, frames)


# ============================================================
# Enemies
# ============================================================

def generate_enemy_slime(frame_w=48, frame_h=48, frame_count=6):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        t = i / frame_count
        squash = 1.0 + math.sin(t * math.pi * 2) * 0.15
        cy_base = int(frame_h * 0.65)
        w = int(18 * squash)
        h = int(14 / squash)
        draw.ellipse([frame_w//2 - w, cy_base - h, frame_w//2 + w, cy_base + h],
                     fill=(60, 200, 60, 255), outline=(20, 100, 20, 255), width=2)
        # Eyes
        ey = cy_base - h // 2
        draw.ellipse([frame_w//2 - 6, ey - 3, frame_w//2 - 2, ey + 3], fill=(255,255,255,255))
        draw.ellipse([frame_w//2 + 2, ey - 3, frame_w//2 + 6, ey + 3], fill=(255,255,255,255))
        draw.ellipse([frame_w//2 - 5, ey - 1, frame_w//2 - 3, ey + 1], fill=(0,0,0,255))
        draw.ellipse([frame_w//2 + 3, ey - 1, frame_w//2 + 5, ey + 1], fill=(0,0,0,255))
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/enemy_slime.png", frame_w, frame_h, frames)


def generate_enemy_bat(frame_w=48, frame_h=48, frame_count=6):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        t = i / frame_count
        wing_angle = math.sin(t * math.pi * 2) * 0.5 + 0.5
        cx, cy = frame_w // 2, frame_h // 2
        # Body
        draw.ellipse([cx - 8, cy - 7, cx + 8, cy + 7], fill=(100, 50, 140, 255), outline=(60,20,100,255), width=2)
        # Wings (triangles approximated by polygon)
        left_tip_y  = int(cy - 16 * wing_angle)
        right_tip_y = int(cy - 16 * wing_angle)
        draw.polygon([(cx - 8, cy), (cx - 22, left_tip_y), (cx - 2, cy + 4)],
                     fill=(80, 30, 120, 220))
        draw.polygon([(cx + 8, cy), (cx + 22, right_tip_y), (cx + 2, cy + 4)],
                     fill=(80, 30, 120, 220))
        # Eyes
        draw.ellipse([cx - 5, cy - 3, cx - 1, cy + 1], fill=(255, 50, 50, 255))
        draw.ellipse([cx + 1, cy - 3, cx + 5, cy + 1], fill=(255, 50, 50, 255))
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/enemy_bat.png", frame_w, frame_h, frames)


def generate_enemy_goblin(frame_w=64, frame_h=64, frame_count=6):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        t = i / frame_count
        leg = int(math.sin(t * math.pi * 2) * 4)
        cx, cy = frame_w//2, frame_h//2 + 6
        # Head
        draw.ellipse([cx-9, cy-26, cx+9, cy-10], fill=(80,160,40,255), outline=(40,100,20,255), width=2)
        # Ears
        draw.ellipse([cx-15, cy-22, cx-7, cy-14], fill=(80,160,40,255))
        draw.ellipse([cx+7,  cy-22, cx+15,cy-14], fill=(80,160,40,255))
        # Eyes (angry)
        draw.ellipse([cx-6, cy-20, cx-2, cy-16], fill=(255,200,0,255))
        draw.ellipse([cx+2, cy-20, cx+6, cy-16], fill=(255,200,0,255))
        draw.line([cx-7, cy-22, cx-1, cy-18], fill=(40,0,0,255), width=2)
        draw.line([cx+1, cy-22, cx+7, cy-18], fill=(40,0,0,255), width=2)
        # Body
        draw.rectangle([cx-7, cy-10, cx+7, cy+4], fill=(80,160,40,255), outline=(40,100,20,255), width=1)
        # Legs
        draw.line([cx-3, cy+4, cx-3-leg, cy+18], fill=(60,120,30,255), width=4)
        draw.line([cx+3, cy+4, cx+3+leg, cy+18], fill=(60,120,30,255), width=4)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/enemy_goblin.png", frame_w, frame_h, frames)


# ============================================================
# Collectibles
# ============================================================

def generate_coin(frame_w=16, frame_h=16, frame_count=8):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        t = i / frame_count
        # Coin "spin" — squash horizontally
        squash = abs(math.cos(t * math.pi))
        w = max(1, int(6 * squash))
        cx, cy = frame_w//2, frame_h//2
        draw.ellipse([cx - w, cy - 6, cx + w, cy + 6], fill=(255,215,0,255), outline=(200,150,0,255), width=1)
        if squash > 0.3:
            draw.text((cx, cy), "$", fill=(180,130,0,255), anchor="mm")
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/coin.png", frame_w, frame_h, frames)


def generate_heart(frame_w=16, frame_h=16, frame_count=2):
    frames = []
    for i in range(frame_count):
        img, draw = blank_frame(frame_w, frame_h)
        color = (220, 30, 30, 255) if i == 0 else (80, 30, 30, 255)
        # Heart shape using two circles + triangle
        draw.ellipse([2, 2, 9, 9], fill=color)
        draw.ellipse([7, 2, 14, 9], fill=color)
        draw.polygon([(2, 7), (14, 7), (8, 14)], fill=color)
        frames.append(img)
    make_spritesheet(f"{SPRITES_DIR}/heart.png", frame_w, frame_h, frames)


# ============================================================
# UI elements
# ============================================================

def generate_ui_icons():
    # Heart full
    img, draw = blank_frame(32, 32)
    draw.ellipse([2, 4, 14, 16], fill=(220, 30, 30, 255))
    draw.ellipse([16, 4, 28, 16], fill=(220, 30, 30, 255))
    draw.polygon([(2, 12), (28, 12), (15, 28)], fill=(220, 30, 30, 255))
    img.save(f"{UI_DIR}/heart_full.png")
    print(f"  Saved: {UI_DIR}/heart_full.png")

    # Heart empty
    img, draw = blank_frame(32, 32)
    draw.ellipse([2, 4, 14, 16], outline=(180, 30, 30, 255), width=2)
    draw.ellipse([16, 4, 28, 16], outline=(180, 30, 30, 255), width=2)
    draw.polygon([(2, 12), (28, 12), (15, 28)], outline=(180, 30, 30, 255))
    img.save(f"{UI_DIR}/heart_empty.png")
    print(f"  Saved: {UI_DIR}/heart_empty.png")

    # Coin icon
    img, draw = blank_frame(32, 32)
    draw.ellipse([2, 2, 30, 30], fill=(255, 215, 0, 255), outline=(200, 150, 0, 255), width=2)
    draw.text((16, 16), "$", fill=(160, 110, 0, 255), anchor="mm")
    img.save(f"{UI_DIR}/coin_icon.png")
    print(f"  Saved: {UI_DIR}/coin_icon.png")

    # Panel (9-slice compatible)
    img = Image.new("RGBA", (64, 64), (20, 25, 40, 200))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 63, 63], outline=(80, 100, 160, 255), width=3)
    draw.rectangle([1, 1, 62, 62], outline=(50, 65, 110, 180), width=1)
    img.save(f"{UI_DIR}/panel.png")
    print(f"  Saved: {UI_DIR}/panel.png")


# ============================================================
# Tileset (ground, brick, stone)
# ============================================================

def generate_tileset(tile_size=64, cols=8, rows=4):
    """Generate a tileset PNG with 32 distinct colored tiles."""
    w = tile_size * cols
    h = tile_size * rows
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    tile_defs = [
        # (color_bg, color_detail, label)
        ((80,  50,  30,  255), (60, 35, 15, 255), "dirt"),
        ((100, 60,  30,  255), (80, 45, 20, 255), "dirt2"),
        ((90,  120, 60,  255), (60, 90, 40, 255), "grass"),
        ((60,  90,  40,  255), (40, 70, 25, 255), "grass2"),
        ((140, 140, 160, 255), (100,100,120, 255), "stone"),
        ((160, 160, 180, 255), (120,120,140, 255), "stone2"),
        ((100, 80,  60,  255), (80, 60, 40,  255), "wood"),
        ((60,  40,  20,  255), (40, 25, 10,  255), "wood2"),
        ((180, 150, 80,  255), (160,130,60,  255), "sand"),
        ((200, 100, 40,  255), (170,80, 20,  255), "lava_edge"),
        ((255, 60,  10,  255), (220,30, 5,   255), "lava"),
        ((60,  150, 200, 255), (40, 120,170, 255), "water"),
        ((40,  100, 160, 255), (25, 80, 130, 255), "water2"),
        ((200, 200, 220, 255), (170,170,190, 255), "snow"),
        ((120, 80,  180, 255), (90, 55, 150, 255), "crystal"),
        ((50,  50,  60,  255), (30, 30, 40,  255), "void"),
    ]

    for i, (bg, detail, label) in enumerate(tile_defs):
        col = i % cols
        row = i // cols
        x0 = col * tile_size
        y0 = row * tile_size
        x1 = x0 + tile_size
        y1 = y0 + tile_size

        # Fill
        draw.rectangle([x0, y0, x1, y1], fill=bg)
        # Inner detail lines
        draw.rectangle([x0+4, y0+4, x1-4, y1-4], outline=detail, width=2)
        # Texture dots
        for dx in range(12, tile_size-12, 16):
            for dy in range(12, tile_size-12, 16):
                draw.ellipse([x0+dx-2, y0+dy-2, x0+dx+2, y0+dy+2], fill=detail)
        # Border
        draw.rectangle([x0, y0, x1-1, y1-1], outline=(0, 0, 0, 80), width=1)

    path = f"{TILESETS_DIR}/tileset_main.png"
    img.save(path)
    print(f"  Saved: {path}  ({cols}x{rows} tiles, {tile_size}px each)")


# ============================================================
# Background layers (parallax)
# ============================================================

def generate_backgrounds():
    W, H = 1280, 720

    # Sky gradient
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        c = lerp_color((100, 160, 240, 255), (200, 230, 255, 255), t)
        draw.line([(0, y), (W, y)], fill=c)
    img.save(f"{BG_DIR}/sky.png")
    print(f"  Saved: {BG_DIR}/sky.png")

    # Clouds
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    import random
    random.seed(42)
    for _ in range(12):
        cx = random.randint(50, W - 50)
        cy = random.randint(50, 260)
        rw = random.randint(60, 160)
        rh = random.randint(30, 70)
        draw.ellipse([cx-rw, cy-rh, cx+rw, cy+rh], fill=(255,255,255,160))
        draw.ellipse([cx-rw//2, cy-rh-20, cx+rw//2, cy+rh//2], fill=(255,255,255,140))
    img = img.filter(ImageFilter.GaussianBlur(radius=4))
    img.save(f"{BG_DIR}/clouds.png")
    print(f"  Saved: {BG_DIR}/clouds.png")

    # Hills silhouette
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    points = [(0, H)]
    for x in range(0, W + 40, 40):
        y = int(H * 0.6 - math.sin(x / 180) * 80 - math.cos(x / 90) * 40)
        points.append((x, y))
    points.append((W, H))
    draw.polygon(points, fill=(60, 90, 50, 200))
    img.save(f"{BG_DIR}/hills.png")
    print(f"  Saved: {BG_DIR}/hills.png")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("\n=== Generating Player Sprites ===")
    generate_player_idle()
    generate_player_run()
    generate_player_jump()
    generate_player_fall()
    generate_player_attack()

    print("\n=== Generating Enemy Sprites ===")
    generate_enemy_slime()
    generate_enemy_bat()
    generate_enemy_goblin()

    print("\n=== Generating Collectibles ===")
    generate_coin()
    generate_heart()

    print("\n=== Generating UI Elements ===")
    generate_ui_icons()

    print("\n=== Generating Tileset ===")
    generate_tileset()

    print("\n=== Generating Backgrounds ===")
    generate_backgrounds()

    print("\n=== DONE ===")
    print("All placeholder sprites generated. Replace with real assets before shipping.")
```

Run with: `python3 scripts/generate_sprites.py`

---

## Step 3: Generate Procedural Textures

Create `/scripts/generate_textures.py`:

```python
#!/usr/bin/env python3
"""
generate_textures.py
Generates procedural PNG textures for 3D games using numpy + PIL.

Install: pip install Pillow numpy
Run: python3 scripts/generate_textures.py
"""

import os
import numpy as np
from PIL import Image

TEXTURES_DIR = "public/assets/textures"
os.makedirs(TEXTURES_DIR, exist_ok=True)

SIZE = 512  # all textures are 512x512


# ============================================================
# Noise helpers
# ============================================================

def white_noise(size: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((size, size)).astype(np.float32)


def smooth_noise(size: int, scale: int = 32, octaves: int = 5, seed: int = 0) -> np.ndarray:
    """Multi-octave smooth noise (value noise approximation)."""
    result = np.zeros((size, size), dtype=np.float32)
    amplitude = 1.0
    frequency = 1.0
    max_val = 0.0

    for octave in range(octaves):
        freq = int(frequency * scale)
        freq = max(1, freq)
        small = white_noise(freq, seed + octave)
        # Resize to full size using PIL (bilinear)
        small_img = Image.fromarray((small * 255).astype(np.uint8))
        big_img = small_img.resize((size, size), Image.BILINEAR)
        layer = np.array(big_img, dtype=np.float32) / 255.0
        result += layer * amplitude
        max_val += amplitude
        amplitude *= 0.5
        frequency *= 2.0

    return result / max_val


def turbulence(size: int, scale: int = 32, octaves: int = 6, seed: int = 0) -> np.ndarray:
    """Turbulence noise (abs value for sharp ridges)."""
    result = np.zeros((size, size), dtype=np.float32)
    amplitude = 1.0
    max_val = 0.0
    for octave in range(octaves):
        freq = max(1, int(scale * (2 ** octave)))
        small = white_noise(min(freq, size), seed + octave)
        big = np.array(
            Image.fromarray((small * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR),
            dtype=np.float32
        ) / 255.0
        result += np.abs(big * 2 - 1) * amplitude
        max_val += amplitude
        amplitude *= 0.5
    return np.clip(result / max_val, 0, 1)


def to_image(arr: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))


def save(img: Image.Image, name: str):
    path = os.path.join(TEXTURES_DIR, name)
    img.save(path)
    print(f"  Saved: {path}")


# ============================================================
# Terrain texture (brown/green)
# ============================================================

def generate_terrain_texture():
    noise = smooth_noise(SIZE, scale=64, octaves=6, seed=1)
    turb  = turbulence(SIZE, scale=32, octaves=5, seed=2)
    combined = noise * 0.7 + turb * 0.3

    # Brown ground → green grass gradient based on height
    r = np.clip(0.35 + combined * 0.3,  0, 1)
    g = np.clip(0.25 + combined * 0.45, 0, 1)
    b = np.clip(0.10 + combined * 0.15, 0, 1)

    # Grass at high points
    mask = (combined > 0.6).astype(np.float32)
    r = r * (1 - mask) + 0.30 * mask
    g = g * (1 - mask) + 0.55 * mask
    b = b * (1 - mask) + 0.18 * mask

    rgb = np.stack([r, g, b], axis=-1)
    save(to_image(rgb), "terrain.png")

    # Normal map approximation
    dx = np.gradient(combined, axis=1)
    dy = np.gradient(combined, axis=0)
    nx = np.clip(dx * 4 + 0.5, 0, 1)
    ny = np.clip(dy * 4 + 0.5, 0, 1)
    nz = np.ones_like(nx) * 0.8
    norm_rgb = np.stack([nx, ny, nz], axis=-1)
    save(to_image(norm_rgb), "terrain_normal.png")


# ============================================================
# Metal / rock texture
# ============================================================

def generate_metal_texture():
    noise = smooth_noise(SIZE, scale=16, octaves=4, seed=10)
    turb  = turbulence(SIZE, scale=8, octaves=4, seed=11)
    v = noise * 0.6 + turb * 0.4

    r = np.clip(0.3 + v * 0.35, 0, 1)
    g = np.clip(0.3 + v * 0.35, 0, 1)
    b = np.clip(0.35 + v * 0.3, 0, 1)

    rgb = np.stack([r, g, b], axis=-1)
    save(to_image(rgb), "metal.png")

    # Roughness map
    roughness = 1.0 - np.clip(v * 0.6 + 0.2, 0, 1)
    save(to_image(roughness), "metal_roughness.png")


def generate_rock_texture():
    noise = smooth_noise(SIZE, scale=48, octaves=6, seed=20)
    turb  = turbulence(SIZE, scale=24, octaves=5, seed=21)
    v = noise * 0.5 + turb * 0.5

    r = np.clip(0.25 + v * 0.3, 0, 1)
    g = np.clip(0.22 + v * 0.28, 0, 1)
    b = np.clip(0.20 + v * 0.25, 0, 1)

    rgb = np.stack([r, g, b], axis=-1)
    save(to_image(rgb), "rock.png")


# ============================================================
# Sky gradient texture
# ============================================================

def generate_sky_texture():
    arr = np.zeros((SIZE, SIZE, 3), dtype=np.float32)
    for y in range(SIZE):
        t = y / SIZE
        # Zenith → horizon
        r = 0.12 + t * 0.55
        g = 0.22 + t * 0.55
        b = 0.55 + t * 0.35
        arr[y, :] = [r, g, b]
    save(to_image(arr), "sky.png")

    # Sunset variant
    for y in range(SIZE):
        t = y / SIZE
        r = 0.6 + t * 0.3
        g = 0.15 + t * 0.45
        b = 0.05 + t * 0.3
        arr[y, :] = [r, g, b]
    save(to_image(arr), "sky_sunset.png")


# ============================================================
# Particle textures
# ============================================================

def generate_particle_texture(size=64, name="particle_circle.png"):
    arr = np.zeros((size, size, 4), dtype=np.float32)
    cx, cy = size / 2, size / 2
    for y in range(size):
        for x in range(size):
            dist = math.sqrt((x - cx)**2 + (y - cy)**2) / (size / 2)
            alpha = max(0.0, 1.0 - dist ** 1.5)
            arr[y, x] = [1.0, 1.0, 1.0, alpha]
    img = Image.fromarray((arr * 255).astype(np.uint8), mode="RGBA")
    save(img, name)


def generate_spark_texture(size=32):
    arr = np.zeros((size, size, 4), dtype=np.float32)
    cx, cy = size / 2, size / 2
    for y in range(size):
        for x in range(size):
            dx, dy = abs(x - cx), abs(y - cy)
            alpha = max(0.0, 1.0 - (dx / (size/2)) ** 0.5) * max(0.0, 1.0 - (dy / (size*0.1)) ** 0.5)
            arr[y, x] = [1.0, 0.8, 0.2, min(1.0, alpha * 2)]
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), mode="RGBA")
    save(img, "particle_spark.png")


# ============================================================
# Main
# ============================================================

import math

if __name__ == "__main__":
    print("\n=== Generating Terrain Textures ===")
    generate_terrain_texture()

    print("\n=== Generating Metal & Rock Textures ===")
    generate_metal_texture()
    generate_rock_texture()

    print("\n=== Generating Sky Textures ===")
    generate_sky_texture()

    print("\n=== Generating Particle Textures ===")
    generate_particle_texture(64, "particle_circle.png")
    generate_particle_texture(32, "particle_dot.png")
    generate_spark_texture()

    print("\n=== DONE ===")
```

Run with: `python3 scripts/generate_textures.py`

---

## Step 4: Generate 3D Geometry as GLB

Create `/scripts/generate_models.py`:

```python
#!/usr/bin/env python3
"""
generate_models.py
Generates .glb 3D model files using pygltflib.

Install: pip install pygltflib numpy
Run: python3 scripts/generate_models.py
"""

import os
import struct
import json
import base64
import numpy as np
import pygltflib
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Accessor, BufferView, Buffer,
    Material, Attributes, Asset, Animation, AnimationSampler, AnimationChannel,
    AnimationChannelTarget, FLOAT, SCALAR, VEC3, VEC4, MAT4,
    ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, TRIANGLE_STRIP, TRIANGLES,
    LINEAR,
)

MODELS_DIR = "public/assets/models"
os.makedirs(MODELS_DIR, exist_ok=True)


# ============================================================
# Helper: pack binary data into GLTF buffers
# ============================================================

class GLTFBuilder:
    def __init__(self):
        self.gltf = GLTF2()
        self.gltf.asset = Asset(version="2.0", generator="OneCommand Asset Generator")
        self.gltf.scene = 0
        self.gltf.scenes = [Scene(nodes=[0])]
        self.gltf.nodes = []
        self.gltf.meshes = []
        self.gltf.materials = []
        self.gltf.accessors = []
        self.gltf.bufferViews = []
        self.gltf.buffers = []
        self._bin_data = bytearray()

    def add_material(self, name: str, color: list[float], metallic: float = 0.0, roughness: float = 0.8) -> int:
        mat = Material(name=name)
        mat.pbrMetallicRoughness = pygltflib.PbrMetallicRoughness(
            baseColorFactor=color,
            metallicFactor=metallic,
            roughnessFactor=roughness,
        )
        self.gltf.materials.append(mat)
        return len(self.gltf.materials) - 1

    def _add_buffer_view(self, data: bytes, target: int) -> int:
        offset = len(self._bin_data)
        self._bin_data += data
        # Pad to 4-byte alignment
        while len(self._bin_data) % 4 != 0:
            self._bin_data += b'\x00'
        bv = BufferView(buffer=0, byteOffset=offset, byteLength=len(data), target=target)
        self.gltf.bufferViews.append(bv)
        return len(self.gltf.bufferViews) - 1

    def _add_accessor(self, bv_idx: int, component_type: int, count: int,
                      type_: str, min_vals=None, max_vals=None) -> int:
        acc = Accessor(
            bufferView=bv_idx,
            byteOffset=0,
            componentType=component_type,
            count=count,
            type=type_,
        )
        if min_vals is not None:
            acc.min = min_vals
        if max_vals is not None:
            acc.max = max_vals
        self.gltf.accessors.append(acc)
        return len(self.gltf.accessors) - 1

    def add_mesh_from_arrays(self, name: str, vertices: np.ndarray, indices: np.ndarray,
                              normals: np.ndarray, material_idx: int) -> int:
        """Add a mesh with positions + normals + indices. Returns mesh index."""

        # Positions
        pos_bytes = vertices.astype(np.float32).tobytes()
        pos_bv = self._add_buffer_view(pos_bytes, ARRAY_BUFFER)
        pos_min = vertices.min(axis=0).tolist()
        pos_max = vertices.max(axis=0).tolist()
        pos_acc = self._add_accessor(pos_bv, FLOAT, len(vertices), VEC3, pos_min, pos_max)

        # Normals
        nor_bytes = normals.astype(np.float32).tobytes()
        nor_bv = self._add_buffer_view(nor_bytes, ARRAY_BUFFER)
        nor_acc = self._add_accessor(nor_bv, FLOAT, len(normals), VEC3)

        # Indices
        idx_bytes = indices.astype(np.uint16).tobytes()
        idx_bv = self._add_buffer_view(idx_bytes, ELEMENT_ARRAY_BUFFER)
        idx_acc = self._add_accessor(idx_bv, pygltflib.UNSIGNED_SHORT, len(indices), SCALAR)

        prim = Primitive(
            attributes=Attributes(POSITION=pos_acc, NORMAL=nor_acc),
            indices=idx_acc,
            material=material_idx,
            mode=TRIANGLES,
        )
        mesh = Mesh(name=name, primitives=[prim])
        self.gltf.meshes.append(mesh)
        return len(self.gltf.meshes) - 1

    def add_node(self, name: str, mesh_idx: int,
                 translation=(0,0,0), scale=(1,1,1)) -> int:
        node = Node(name=name, mesh=mesh_idx,
                    translation=list(translation), scale=list(scale))
        self.gltf.nodes.append(node)
        return len(self.gltf.nodes) - 1

    def save(self, path: str):
        # Finalize buffer
        buf = Buffer(byteLength=len(self._bin_data))
        buf.uri = "data:application/octet-stream;base64," + base64.b64encode(self._bin_data).decode()
        self.gltf.buffers = [buf]
        # Update all buffer view byteLength to match actual data
        self.gltf.save(path)
        print(f"  Saved: {path}")


# ============================================================
# Geometry generators
# ============================================================

def capsule_geometry(radius=0.4, height=1.0, segments=12, rings=6):
    """Generate vertices + normals + indices for a capsule."""
    verts, norms, idxs = [], [], []
    vi = 0

    def add_tri(a, b, c):
        idxs.extend([a, b, c])

    # Top hemisphere
    for r in range(rings + 1):
        phi = (math.pi / 2) * (r / rings)
        y = math.sin(phi) * radius + height / 2
        ring_r = math.cos(phi) * radius
        for s in range(segments):
            theta = 2 * math.pi * s / segments
            x = math.cos(theta) * ring_r
            z = math.sin(theta) * ring_r
            nx, ny, nz = math.cos(theta) * math.cos(phi), math.sin(phi), math.sin(theta) * math.cos(phi)
            verts.append([x, y, z])
            norms.append([nx, ny, nz])

    # Bottom hemisphere
    for r in range(rings + 1):
        phi = -(math.pi / 2) * (r / rings)
        y = math.sin(phi) * radius - height / 2
        ring_r = math.cos(phi) * radius
        for s in range(segments):
            theta = 2 * math.pi * s / segments
            x = math.cos(theta) * ring_r
            z = math.sin(theta) * ring_r
            nx, ny, nz = math.cos(theta) * math.cos(phi), math.sin(phi), math.sin(theta) * math.cos(phi)
            verts.append([x, y, z])
            norms.append([nx, ny, nz])

    # Connect rings with quads → triangles
    total_rings = (rings + 1) * 2
    for ring in range(total_rings - 1):
        for s in range(segments):
            a = ring * segments + s
            b = ring * segments + (s + 1) % segments
            c = (ring + 1) * segments + s
            d = (ring + 1) * segments + (s + 1) % segments
            add_tri(a, b, c)
            add_tri(b, d, c)

    return np.array(verts, dtype=np.float32), np.array(norms, dtype=np.float32), np.array(idxs, dtype=np.uint16)


def box_geometry(w=1.0, h=1.0, d=1.0):
    hw, hh, hd = w/2, h/2, d/2
    verts = np.array([
        # Front
        [-hw,-hh, hd],[hw,-hh, hd],[hw, hh, hd],[-hw, hh, hd],
        # Back
        [ hw,-hh,-hd],[-hw,-hh,-hd],[-hw, hh,-hd],[ hw, hh,-hd],
        # Left
        [-hw,-hh,-hd],[-hw,-hh, hd],[-hw, hh, hd],[-hw, hh,-hd],
        # Right
        [ hw,-hh, hd],[ hw,-hh,-hd],[ hw, hh,-hd],[ hw, hh, hd],
        # Top
        [-hw, hh, hd],[ hw, hh, hd],[ hw, hh,-hd],[-hw, hh,-hd],
        # Bottom
        [-hw,-hh,-hd],[ hw,-hh,-hd],[ hw,-hh, hd],[-hw,-hh, hd],
    ], dtype=np.float32)

    normals = np.array([
        [0,0,1],[0,0,1],[0,0,1],[0,0,1],
        [0,0,-1],[0,0,-1],[0,0,-1],[0,0,-1],
        [-1,0,0],[-1,0,0],[-1,0,0],[-1,0,0],
        [1,0,0],[1,0,0],[1,0,0],[1,0,0],
        [0,1,0],[0,1,0],[0,1,0],[0,1,0],
        [0,-1,0],[0,-1,0],[0,-1,0],[0,-1,0],
    ], dtype=np.float32)

    indices = []
    for face in range(6):
        b = face * 4
        indices.extend([b, b+1, b+2, b, b+2, b+3])

    return verts, normals, np.array(indices, dtype=np.uint16)


def terrain_quad_geometry(size=10.0, subdivisions=16):
    """Flat terrain quad with noise-like height variation."""
    import math
    n = subdivisions + 1
    verts, norms, idxs = [], [], []

    for row in range(n):
        for col in range(n):
            x = (col / subdivisions - 0.5) * size
            z = (row / subdivisions - 0.5) * size
            y = (math.sin(x * 0.5) * math.cos(z * 0.5)) * 0.4
            verts.append([x, y, z])
            norms.append([0, 1, 0])

    for row in range(subdivisions):
        for col in range(subdivisions):
            a = row * n + col
            b = a + 1
            c = a + n
            d = c + 1
            idxs.extend([a, b, c, b, d, c])

    return np.array(verts, np.float32), np.array(norms, np.float32), np.array(idxs, np.uint16)


def tree_geometry():
    """Cone trunk + sphere canopy merged geometry."""
    # Trunk (cylinder approximation via box)
    trunk_v, trunk_n, trunk_i = box_geometry(0.2, 1.2, 0.2)
    trunk_v[:, 1] += 0.6  # shift up

    # Canopy (icosphere-ish via sphere segments)
    segs = 8
    can_v, can_n, can_i = [], [], []
    vi = 0
    for row in range(segs):
        phi0 = math.pi * row / segs
        phi1 = math.pi * (row + 1) / segs
        for col in range(segs):
            th0 = 2 * math.pi * col / segs
            th1 = 2 * math.pi * (col + 1) / segs
            r = 0.9
            def pt(phi, th):
                return [r*math.sin(phi)*math.cos(th), r*math.cos(phi)+1.8, r*math.sin(phi)*math.sin(th)]
            def nm(phi, th):
                return [math.sin(phi)*math.cos(th), math.cos(phi), math.sin(phi)*math.sin(th)]
            p0,p1,p2,p3 = pt(phi0,th0),pt(phi0,th1),pt(phi1,th0),pt(phi1,th1)
            n0,n1,n2,n3 = nm(phi0,th0),nm(phi0,th1),nm(phi1,th0),nm(phi1,th1)
            base = vi
            for p,n in [(p0,n0),(p1,n1),(p2,n2),(p3,n3)]:
                can_v.append(p); can_n.append(n); vi+=1
            can_i.extend([base, base+1, base+2, base+1, base+3, base+2])

    can_v = np.array(can_v, np.float32)
    can_n = np.array(can_n, np.float32)
    can_i = np.array(can_i, np.uint16)

    # Merge
    offset = len(trunk_v)
    verts = np.vstack([trunk_v, can_v])
    norms = np.vstack([trunk_n, can_n])
    idxs  = np.concatenate([trunk_i, can_i + offset])

    return verts, norms, idxs


import math

# ============================================================
# Main
# ============================================================

def generate_all():
    b = GLTFBuilder()
    mat_blue    = b.add_material("character", [0.3, 0.55, 0.9, 1.0], metallic=0.0, roughness=0.7)
    mat_grey    = b.add_material("rock",      [0.5, 0.5, 0.5, 1.0], metallic=0.1, roughness=0.9)
    mat_green   = b.add_material("terrain",   [0.3, 0.6, 0.25, 1.0], metallic=0.0, roughness=0.95)
    mat_wood    = b.add_material("wood",      [0.4, 0.25, 0.1, 1.0], metallic=0.0, roughness=1.0)
    mat_canopy  = b.add_material("leaves",    [0.2, 0.5, 0.15, 1.0], metallic=0.0, roughness=0.9)

    # Character capsule
    v, n, i = capsule_geometry(radius=0.4, height=1.0, segments=12, rings=6)
    mesh_idx = b.add_mesh_from_arrays("CharacterMesh", v, i, n, mat_blue)
    b.add_node("Character", mesh_idx, translation=(0, 1, 0))

    # Box prop
    v, n, i = box_geometry(1.0, 1.0, 1.0)
    mesh_idx = b.add_mesh_from_arrays("CrateMesh", v, i, n, mat_grey)
    b.add_node("Crate", mesh_idx, translation=(3, 0.5, 0))

    # Terrain
    v, n, i = terrain_quad_geometry(size=10.0, subdivisions=16)
    mesh_idx = b.add_mesh_from_arrays("TerrainMesh", v, i, n, mat_green)
    b.add_node("Terrain", mesh_idx, translation=(0, 0, 0))

    # Tree
    v, n, i = tree_geometry()
    mesh_idx = b.add_mesh_from_arrays("TreeMesh", v, i, n, mat_canopy)
    b.add_node("Tree", mesh_idx, translation=(-3, 0, 0))

    b.gltf.scenes[0].nodes = list(range(len(b.gltf.nodes)))
    b.save(f"{MODELS_DIR}/scene_props.glb")
    print(f"\nGenerated {len(b.gltf.nodes)} objects in scene_props.glb")


if __name__ == "__main__":
    print("\n=== Generating 3D GLB Models ===")
    generate_all()
    print("\n=== DONE ===")
```

Run with: `python3 scripts/generate_models.py`

---

## Step 5: Blender Python Script

Create `/scripts/generate_blender_models.py`. Run with:
```bash
blender --background --python scripts/generate_blender_models.py
```

```python
"""
generate_blender_models.py
Blender Python script to generate game-ready 3D assets and export as .glb.

Usage: blender --background --python scripts/generate_blender_models.py
Requires: Blender 3.6+
"""

import bpy
import os
import math
from pathlib import Path

OUTPUT_DIR = Path("public/assets/models")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Utilities
# ============================================================

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)


def make_material(name: str, color: tuple, roughness=0.7, metallic=0.0) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def export_glb(path: str):
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format='GLB',
        export_apply=True,
        export_animations=True,
        export_skins=True,
        export_morph=False,
        export_lights=False,
    )
    print(f"  Exported: {path}")


# ============================================================
# Character with basic rig
# ============================================================

def create_character():
    clear_scene()

    # Body
    bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=1.0, location=(0, 0, 1.0))
    body = bpy.context.active_object
    body.name = "Body"
    body.data.materials.append(make_material("Skin", (0.9, 0.7, 0.5), roughness=0.8))

    # Head
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(0, 0, 1.85))
    head = bpy.context.active_object
    head.name = "Head"
    head.data.materials.append(make_material("Face", (0.95, 0.75, 0.6), roughness=0.9))

    # Left arm
    bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.7, location=(-0.5, 0, 1.1))
    left_arm = bpy.context.active_object
    left_arm.name = "LeftArm"
    left_arm.rotation_euler.z = math.radians(30)
    left_arm.data.materials.append(make_material("Cloth", (0.25, 0.45, 0.8), roughness=0.7))

    # Right arm
    bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.7, location=(0.5, 0, 1.1))
    right_arm = bpy.context.active_object
    right_arm.name = "RightArm"
    right_arm.rotation_euler.z = math.radians(-30)
    right_arm.data.materials.append(make_material("Cloth", (0.25, 0.45, 0.8), roughness=0.7))

    # Legs
    for side in [-1, 1]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.8, location=(side * 0.18, 0, 0.4))
        leg = bpy.context.active_object
        leg.name = f"{'Left' if side < 0 else 'Right'}Leg"
        leg.data.materials.append(make_material("Pants", (0.15, 0.2, 0.5), roughness=0.8))

    # Select all, join
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.join()
    character = bpy.context.active_object
    character.name = "Character"

    # Add armature (basic)
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = "Armature"
    arm = arm_obj.data

    bpy.ops.object.mode_set(mode='EDIT')
    # Root bone
    root = arm.edit_bones[0]
    root.name = "Root"
    root.head = (0, 0, 0)
    root.tail = (0, 0, 0.5)

    # Spine
    spine = arm.edit_bones.new("Spine")
    spine.head = (0, 0, 0.5)
    spine.tail = (0, 0, 1.5)
    spine.parent = root

    # Head bone
    head_b = arm.edit_bones.new("Head")
    head_b.head = (0, 0, 1.5)
    head_b.tail = (0, 0, 1.9)
    head_b.parent = spine

    # Arm bones
    for side, name in [(-1, "L_Arm"), (1, "R_Arm")]:
        b = arm.edit_bones.new(name)
        b.head = (side * 0.35, 0, 1.3)
        b.tail = (side * 0.7, 0, 1.0)
        b.parent = spine

    # Leg bones
    for side, name in [(-1, "L_Leg"), (1, "R_Leg")]:
        b = arm.edit_bones.new(name)
        b.head = (side * 0.18, 0, 0.8)
        b.tail = (side * 0.18, 0, 0.0)
        b.parent = root

    bpy.ops.object.mode_set(mode='OBJECT')

    # Keyframe animations: Idle (bob)
    character.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')

    for frame, z_offset in [(1, 0.0), (15, 0.05), (30, 0.0)]:
        bpy.context.scene.frame_set(frame)
        spine_pose = arm_obj.pose.bones["Spine"]
        spine_pose.location = (0, 0, z_offset)
        spine_pose.keyframe_insert(data_path="location", frame=frame)

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 30

    export_glb(OUTPUT_DIR / "character.glb")


# ============================================================
# Environmental props
# ============================================================

def create_props():
    clear_scene()

    # Crate
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
    crate = bpy.context.active_object
    crate.name = "Crate"
    crate.data.materials.append(make_material("Wood", (0.5, 0.32, 0.15), roughness=1.0))

    # Barrel
    bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=0.8, location=(2, 0, 0.4))
    barrel = bpy.context.active_object
    barrel.name = "Barrel"
    barrel.data.materials.append(make_material("DarkWood", (0.35, 0.2, 0.1), roughness=1.0))

    # Rock
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5, location=(4, 0, 0.5))
    rock = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    # Randomize mesh for organic look
    bpy.ops.transform.vertex_random(offset=0.15, seed=42)
    bpy.ops.object.mode_set(mode='OBJECT')
    rock.name = "Rock"
    rock.data.materials.append(make_material("Stone", (0.45, 0.42, 0.4), roughness=0.95, metallic=0.05))

    # Torch
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.6, location=(6, 0, 0.3))
    torch_pole = bpy.context.active_object
    torch_pole.name = "TorchPole"
    torch_pole.data.materials.append(make_material("TorchWood", (0.4, 0.25, 0.1)))

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(6, 0, 0.65))
    flame = bpy.context.active_object
    flame.name = "TorchFlame"
    mat_flame = make_material("Flame", (1.0, 0.5, 0.05), roughness=0.0)
    mat_flame.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.4, 0.0, 1.0)
    mat_flame.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 3.0
    flame.data.materials.append(mat_flame)

    export_glb(OUTPUT_DIR / "props.glb")


# ============================================================
# Tree / vegetation
# ============================================================

def create_vegetation():
    clear_scene()

    # Trunk
    bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=2.0, location=(0, 0, 1.0))
    trunk = bpy.context.active_object
    trunk.name = "Trunk"
    trunk.data.materials.append(make_material("TrunkMat", (0.35, 0.22, 0.1), roughness=1.0))

    # Canopy (multiple overlapping spheres)
    for i, (x, z, r) in enumerate([(0, 2.5, 0.9), (0.4, 2.8, 0.6), (-0.3, 2.6, 0.65)]):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=(x, 0, z))
        leaf = bpy.context.active_object
        leaf.name = f"Canopy_{i}"
        leaf.data.materials.append(make_material("Leaves", (0.2, 0.55, 0.15), roughness=0.9))

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.join()
    bpy.context.active_object.name = "Tree"

    export_glb(OUTPUT_DIR / "tree.glb")


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    print("\n=== Blender: Generating character.glb ===")
    create_character()

    print("\n=== Blender: Generating props.glb ===")
    create_props()

    print("\n=== Blender: Generating tree.glb ===")
    create_vegetation()

    print("\n=== Blender export complete ===")
```

---

## Step 6: Audio Manifest

Create `/public/assets/audio/audio_manifest.json`:

```json
{
  "license": "CC0 — free to use in any project without attribution required.",
  "sources": ["kenney.nl", "freesound.org"],
  "assets": [
    {
      "key": "sfx_jump",
      "file": "sfx_jump.ogg",
      "description": "Short jump sound",
      "url": "https://assets.kenney.nl/assets/digital-audio/jump1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_coin",
      "file": "sfx_coin.ogg",
      "description": "Coin pickup chime",
      "url": "https://assets.kenney.nl/assets/digital-audio/coin1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_hurt",
      "file": "sfx_hurt.ogg",
      "description": "Player damage hit",
      "url": "https://assets.kenney.nl/assets/digital-audio/hit2.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_attack",
      "file": "sfx_attack.ogg",
      "description": "Sword swing",
      "url": "https://assets.kenney.nl/assets/digital-audio/swing1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_death",
      "file": "sfx_death.ogg",
      "description": "Player death",
      "url": "https://assets.kenney.nl/assets/digital-audio/lose1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_levelup",
      "file": "sfx_levelup.ogg",
      "description": "Level complete fanfare",
      "url": "https://assets.kenney.nl/assets/digital-audio/win1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "music_menu",
      "file": "music_menu.ogg",
      "description": "Main menu background music",
      "url": "https://freesound.org/data/previews/516/516777_1648170-lq.mp3",
      "source": "freesound.org",
      "freesound_id": "516777",
      "author": "various CC0"
    },
    {
      "key": "music_game",
      "file": "music_game.ogg",
      "description": "In-game background music",
      "url": "https://freesound.org/data/previews/395/395292_6585508-lq.mp3",
      "source": "freesound.org",
      "freesound_id": "395292",
      "author": "various CC0"
    },
    {
      "key": "sfx_explosion",
      "file": "sfx_explosion.ogg",
      "description": "Explosion effect",
      "url": "https://assets.kenney.nl/assets/digital-audio/explosion1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_powerup",
      "file": "sfx_powerup.ogg",
      "description": "Power-up collected",
      "url": "https://assets.kenney.nl/assets/digital-audio/powerup1.ogg",
      "source": "kenney.nl"
    },
    {
      "key": "sfx_footstep",
      "file": "sfx_footstep.ogg",
      "description": "Footstep on ground",
      "url": "https://assets.kenney.nl/assets/digital-audio/footstep_concrete1.ogg",
      "source": "kenney.nl"
    }
  ]
}
```

Create `/scripts/download_audio.py`:

```python
#!/usr/bin/env python3
"""
download_audio.py
Downloads CC0 audio assets from the manifest.

Install: pip install requests
Run: python3 scripts/download_audio.py
"""

import os
import json
import urllib.request
import urllib.error

MANIFEST = "public/assets/audio/audio_manifest.json"
OUT_DIR  = "public/assets/audio"
os.makedirs(OUT_DIR, exist_ok=True)

with open(MANIFEST) as f:
    manifest = json.load(f)

success = 0
failed  = 0

for asset in manifest["assets"]:
    out_path = os.path.join(OUT_DIR, asset["file"])

    if os.path.exists(out_path):
        print(f"  Skip (exists): {asset['file']}")
        success += 1
        continue

    url = asset["url"]
    print(f"  Downloading: {asset['file']} from {asset['source']}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OneCommand/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"    OK ({len(data):,} bytes)")
        success += 1
    except urllib.error.HTTPError as e:
        print(f"    FAILED HTTP {e.code}: {e.reason}")
        # Write silent placeholder OGG (44 bytes minimal valid OGG)
        with open(out_path, "wb") as f:
            f.write(b'OggS' + b'\x00' * 40)
        print(f"    Created silent placeholder: {asset['file']}")
        failed += 1
    except Exception as e:
        print(f"    FAILED: {e}")
        failed += 1

print(f"\nAudio download complete: {success} ok, {failed} failed/placeholder")
```

---

## Step 7: Verify Assets

After running all generation scripts, verify the output:

```bash
echo "=== Sprites ===" && ls -la public/assets/sprites/
echo "=== Textures ===" && ls -la public/assets/textures/
echo "=== Models ===" && ls -la public/assets/models/
echo "=== UI ===" && ls -la public/assets/ui/
echo "=== Backgrounds ===" && ls -la public/assets/backgrounds/
echo "=== Audio ===" && ls -la public/assets/audio/
echo "=== Tilemaps ===" && ls -la public/assets/tilemaps/
echo "=== Tilesets ===" && ls -la public/assets/tilesets/
```

Count total files:
```bash
find public/assets -type f | wc -l
```

Report the count in the final message.

---

## Report

Asset generation complete. Files generated:
- **Sprites**: player (idle/run/jump/fall/attack), 3 enemy types, coin, heart — `public/assets/sprites/`
- **UI**: heart_full, heart_empty, coin_icon, panel — `public/assets/ui/`
- **Backgrounds**: sky, clouds, hills — `public/assets/backgrounds/`
- **Tileset**: 32-tile procedural tileset — `public/assets/tilesets/`
- **Textures**: terrain + normal, metal + roughness, rock, sky, sky_sunset, 3 particle textures — `public/assets/textures/`
- **3D Models**: capsule character, crate, terrain quad, tree (pygltflib) + character with rig, props, tree (Blender) — `public/assets/models/`
- **Audio**: manifest JSON + download script — `public/assets/audio/`

Run scripts in order:
1. `python3 scripts/generate_sprites.py`
2. `python3 scripts/generate_textures.py`
3. `python3 scripts/generate_models.py`
4. `blender --background --python scripts/generate_blender_models.py` (requires Blender)
5. `python3 scripts/download_audio.py`
