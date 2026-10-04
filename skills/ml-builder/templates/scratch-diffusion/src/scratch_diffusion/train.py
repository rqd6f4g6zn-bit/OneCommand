"""Train the diffusion model from random initialisation on the own images / videos.

python -m scratch_diffusion.train --config configs/smoke.yaml
Writes runs/<run>/: model.safetensors (EMA weights), config.json, labels.json, metrics.json, samples/
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path

import torch
import yaml
from safetensors.torch import save_file

from .data import Normaliser, color_histogram, load_split, nn_distance, records, save_grid, save_video
from .diffusion import Diffusion
from .model import UNet, UNetConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/smoke.yaml")
    cfg = yaml.safe_load(Path(parser.parse_args().config).read_text())
    torch.manual_seed(cfg["seed"])
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    out = Path("runs") / cfg["run"]
    (out / "samples").mkdir(parents=True, exist_ok=True)

    rows, _ = records(Path(cfg["data_dir"]), "train")
    labels = sorted({r["label"] for r in rows if r.get("label")})
    label_ids = {name: i for i, name in enumerate(labels)} if labels else None
    x_train, y_train = load_split(cfg, "train", label_ids)
    x_test, _ = load_split(cfg, "test", label_ids)
    norm = Normaliser.fit(x_train)
    x_raw = x_train
    x_train = norm.encode(x_train)

    mcfg = UNetConfig(dims=2 if cfg["kind"] == "image" else 3, num_classes=len(labels), **cfg["model"])
    model = UNet(mcfg).to(device)
    ema = copy.deepcopy(model).eval()
    diff = Diffusion(cfg["diffusion"]["timesteps"])
    t = cfg["train"]
    opt = torch.optim.AdamW(model.parameters(), lr=t["lr"], weight_decay=0.0)
    gen = torch.Generator().manual_seed(cfg["seed"])

    history, started = [], time.time()
    for step in range(t["steps"]):
        lr = t["lr"] * min(1.0, (step + 1) / t["warmup"])
        lr *= 0.5 * (1 + math.cos(math.pi * step / t["steps"])) if step >= t["warmup"] else 1.0
        for g in opt.param_groups:
            g["lr"] = lr
        idx = torch.randint(len(x_train), (t["batch_size"],), generator=gen)
        x = x_train[idx]
        if torch.rand(1, generator=gen).item() < 0.5:
            x = x.flip(-1)  # horizontal flip
        y = y_train[idx].to(device) if y_train is not None else None
        loss = diff.loss(model, x.to(device), y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        with torch.no_grad():
            for pe, pm in zip(ema.parameters(), model.parameters()):
                pe.lerp_(pm, 1 - t["ema"])
        if step % 10 == 0 or step == t["steps"] - 1:
            history.append([step, round(loss.item(), 4)])
        if (step + 1) % max(1, t["steps"] // 10) == 0:
            print(f"step {step + 1}/{t['steps']} loss {loss.item():.4f}", flush=True)

    # Sample with the EMA weights and compare colour statistics with the held-out test set.
    n = t["samples"]
    shape = (n, 3, cfg["size"], cfg["size"]) if cfg["kind"] == "image" else (n, 3, cfg["frames"], cfg["size"], cfg["size"])
    y = torch.arange(n, device=device) % len(labels) if labels else None
    lo, hi = norm.bounds()
    samples = norm.decode(diff.sample(ema, shape, cfg["diffusion"]["sample_steps"], y,
                                      torch.Generator().manual_seed(0), lo, hi).cpu())
    noise = torch.randn(shape, generator=torch.Generator().manual_seed(1)).clamp(-1, 1)
    ref = color_histogram(x_test)
    dist = (color_histogram(samples) - ref).abs().sum().item()
    dist_noise = (color_histogram(noise) - ref).abs().sum().item()
    nn_samples, nn_noise, nn_test = nn_distance(samples, x_raw), nn_distance(noise, x_raw), nn_distance(x_test, x_raw)
    if cfg["kind"] == "image":
        save_grid(samples, out / "samples" / "grid.png")
    else:
        for i, clip in enumerate(samples):
            save_video(clip, out / "samples" / f"clip-{i}.mp4", cfg.get("fps", 8))
        save_grid(samples[:, :, 0], out / "samples" / "grid.png")  # first frames

    save_file({k: v.detach().cpu().contiguous() for k, v in ema.state_dict().items()}, str(out / "model.safetensors"))
    (out / "config.json").write_text(json.dumps({"unet": mcfg.to_dict(), "kind": cfg["kind"], "size": cfg["size"],
                                                 "frames": cfg.get("frames"), "fps": cfg.get("fps"),
                                                 "timesteps": cfg["diffusion"]["timesteps"],
                                                 "norm": norm.to_dict()}, indent=2))
    (out / "labels.json").write_text(json.dumps(labels))
    metrics = {
        "from_scratch": True, "kind": cfg["kind"], "params": model.num_params(), "train_items": len(x_train),
        "device": device, "train_seconds": round(time.time() - started, 1),
        "loss_first": history[0][1], "loss_last": history[-1][1], "loss_history": history,
        "color_distance": round(dist, 4), "color_distance_noise": round(dist_noise, 4),
        "color_ratio": round(dist / max(dist_noise, 1e-9), 4),
        # main metric: samples vs pure noise, measured as distance to the nearest real training item
        "nn_distance": round(nn_samples, 4), "nn_distance_noise": round(nn_noise, 4),
        "nn_distance_test": round(nn_test, 4), "nn_ratio": round(nn_samples / max(nn_noise, 1e-9), 4),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if k != "loss_history"}, indent=2))


if __name__ == "__main__":
    main()
