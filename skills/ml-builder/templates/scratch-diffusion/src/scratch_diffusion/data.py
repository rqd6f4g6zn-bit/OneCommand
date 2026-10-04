"""Own images / videos from OneCommand's dataset.py manifest → tensors in [-1, 1], cached per split."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch
from PIL import Image


def records(data_dir: Path, split: str) -> tuple[list[dict], Path]:
    manifest = json.loads((data_dir / "manifest.json").read_text())
    rows = [json.loads(line) for line in (data_dir / f"{split}.jsonl").read_text().splitlines() if line.strip()]
    return rows, Path(manifest["input"]["root"])


def load_image(path: Path, size: int) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    return np.asarray(img.resize((size, size), Image.Resampling.BICUBIC), dtype=np.uint8)  # H W C


def load_clips(path: Path, size: int, frames: int, fps: int, max_clips: int = 16) -> list[np.ndarray]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to read videos (apt install ffmpeg / brew install ffmpeg)")
    vf = f"fps={fps},scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-frames:v", str(frames * max_clips),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, size, size, 3)
    return [arr[i:i + frames] for i in range(0, len(arr) - frames + 1, frames)]  # each T H W C


def load_split(cfg: dict, split: str, label_ids: dict[str, int] | None = None) -> tuple[torch.Tensor, torch.Tensor | None]:
    data_dir = Path(cfg["data_dir"])
    cache = Path("data/cache") / f"{split}-{cfg['kind']}-{cfg['size']}-{cfg.get('frames', 1)}.pt"
    if cache.exists():
        blob = torch.load(cache)
        return blob["x"], blob["y"]
    rows, root = records(data_dir, split)
    xs, ys = [], []
    for r in rows:
        path = root / r["path"]
        if cfg["kind"] == "image":
            items = [load_image(path, cfg["size"])[None]]  # 1 H W C
        else:
            items = load_clips(path, cfg["size"], cfg["frames"], cfg.get("fps", 8))
        for it in items:
            xs.append(torch.from_numpy(it.copy()))
            ys.append(label_ids[r["label"]] if label_ids and r.get("label") in label_ids else -1)
    if not xs:
        raise ValueError(f"no usable {cfg['kind']} in the {split} split")
    x = torch.stack(xs).float().div(127.5).sub(1)            # N T H W C
    x = x.permute(0, 4, 1, 2, 3)                              # N C T H W
    if cfg["kind"] == "image":
        x = x[:, :, 0]                                        # N C H W
    y = torch.tensor(ys) if label_ids else None
    cache.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"x": x, "y": y}, cache)
    return x, y


class Normaliser:
    """Per-channel zero mean / unit variance. Without it, data far from mid-grey (white screenshots, dark
    footage) cannot be recovered from pure noise: samples get stuck at the wrong brightness."""

    def __init__(self, mean: list[float], std: list[float]):
        self.mean, self.std = torch.tensor(mean), torch.tensor(std).clamp(min=1e-3)

    @classmethod
    def fit(cls, x: torch.Tensor) -> Normaliser:
        dims = [d for d in range(x.dim()) if d != 1]
        return cls(x.mean(dim=dims).tolist(), x.std(dim=dims).tolist())

    def _view(self, x: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
        return v.view(1, -1, *([1] * (x.dim() - 2))).to(x.device)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        return (x - self._view(x, self.mean)) / self._view(x, self.std)

    def decode(self, x: torch.Tensor) -> torch.Tensor:
        return (x * self._view(x, self.std) + self._view(x, self.mean)).clamp(-1, 1)

    def bounds(self) -> tuple[torch.Tensor, torch.Tensor]:
        return (-1 - self.mean) / self.std, (1 - self.mean) / self.std

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}


def to_uint8(x: torch.Tensor) -> np.ndarray:
    return ((x.clamp(-1, 1) + 1) * 127.5).round().byte().cpu().numpy()


def save_grid(images: torch.Tensor, path: Path, cols: int = 4) -> None:
    """images: N C H W in [-1, 1]."""
    arr = to_uint8(images).transpose(0, 2, 3, 1)
    n, h, w, _ = arr.shape
    rows = (n + cols - 1) // cols
    grid = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
    for i, im in enumerate(arr):
        grid[(i // cols) * h:(i // cols + 1) * h, (i % cols) * w:(i % cols + 1) * w] = im
    Image.fromarray(grid).resize((cols * w * 4, rows * h * 4), Image.Resampling.NEAREST).save(path)


def save_video(clip: torch.Tensor, path: Path, fps: int) -> None:
    """clip: C T H W in [-1, 1] → MP4 (H.264) via ffmpeg, upscaled ×4 for viewing."""
    frames = to_uint8(clip).transpose(1, 2, 3, 0)  # T H W C
    _, h, w, _ = frames.shape
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-r", str(fps), "-i", "-", "-vf", f"scale={w * 4}:{h * 4}:flags=neighbor", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
                   input=frames.tobytes(), check=True)


def nn_distance(a: torch.Tensor, ref: torch.Tensor, side: int = 16) -> float:
    """Mean distance of every item in a to its nearest neighbour in ref (RMS per pixel at side×side; videos
    keep every frame — averaging over time would make noise look like flat grey data)."""
    def flat(x: torch.Tensor) -> torch.Tensor:
        if x.dim() == 5:
            n, c, t, h, w = x.shape
            frames = x.float().transpose(1, 2).reshape(n * t, c, h, w)
            return torch.nn.functional.adaptive_avg_pool2d(frames, side).reshape(n, -1)
        return torch.nn.functional.adaptive_avg_pool2d(x.float(), side).flatten(1)
    fa, fr = flat(a), flat(ref)
    return (torch.cdist(fa, fr).min(dim=1).values / fa.shape[1] ** 0.5).mean().item()


def color_histogram(x: torch.Tensor, bins: int = 16) -> torch.Tensor:
    """Per-channel colour histogram of a batch (any shape N C ...), normalised."""
    c = x.shape[1]
    v = x.transpose(0, 1).reshape(c, -1)
    hist = torch.stack([torch.histc(v[i], bins=bins, min=-1, max=1) for i in range(c)])
    return hist / hist.sum(dim=1, keepdim=True)
