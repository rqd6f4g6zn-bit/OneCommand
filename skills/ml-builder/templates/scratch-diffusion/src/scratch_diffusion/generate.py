"""Load a trained run and generate images or video clips."""

from __future__ import annotations

import argparse
import base64
import io
import json
import tempfile
from pathlib import Path

import torch
from PIL import Image
from safetensors.torch import load_file

from .data import Normaliser, save_video, to_uint8
from .diffusion import Diffusion
from .model import UNet, UNetConfig


class Generator:
    def __init__(self, run_dir: Path):
        self.cfg = json.loads((run_dir / "config.json").read_text())
        self.labels = json.loads((run_dir / "labels.json").read_text())
        self.model = UNet(UNetConfig(**self.cfg["unet"]))
        self.model.load_state_dict(load_file(str(run_dir / "model.safetensors")))
        self.model.eval()
        self.diff = Diffusion(self.cfg["timesteps"])
        self.norm = Normaliser(**self.cfg["norm"])

    def sample(self, n: int = 1, seed: int = 0, label: str | None = None, steps: int = 50) -> torch.Tensor:
        s = self.cfg["size"]
        shape = (n, 3, s, s) if self.cfg["kind"] == "image" else (n, 3, self.cfg["frames"], s, s)
        y = None
        if self.labels:
            if label is not None and label not in self.labels:
                raise ValueError(f"unknown label '{label}' — known: {', '.join(self.labels)}")
            y = torch.full((n,), self.labels.index(label) if label else 0, dtype=torch.long)
        lo, hi = self.norm.bounds()
        return self.norm.decode(self.diff.sample(self.model, shape, steps, y, torch.Generator().manual_seed(seed), lo, hi))

    def encode(self, x: torch.Tensor) -> list[str]:
        out = []
        for item in x:
            if self.cfg["kind"] == "image":
                buf = io.BytesIO()
                Image.fromarray(to_uint8(item).transpose(1, 2, 0)).save(buf, format="PNG")
                out.append(base64.b64encode(buf.getvalue()).decode())
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "clip.mp4"
                    save_video(item, path, self.cfg.get("fps") or 8)
                    out.append(base64.b64encode(path.read_bytes()).decode())
        return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/smoke")
    parser.add_argument("--n", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--label")
    parser.add_argument("--out", default="generated")
    args = parser.parse_args()
    gen = Generator(Path(args.run))
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    for i, item in enumerate(gen.encode(gen.sample(args.n, args.seed, args.label))):
        ext = "png" if gen.cfg["kind"] == "image" else "mp4"
        (out / f"{args.seed}-{i}.{ext}").write_bytes(base64.b64decode(item))
    print(f"wrote {args.n} file(s) to {out}/")


if __name__ == "__main__":
    main()
