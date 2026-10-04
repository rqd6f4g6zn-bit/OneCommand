"""Train the GPT from random initialisation on the own dataset.

python -m scratch_lm.train --config configs/smoke.yaml
Writes runs/<run>/: model.safetensors, config.json, tokenizer.json, metrics.json, params.json
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections import Counter
from pathlib import Path

import torch
import yaml
from safetensors.torch import save_file

from .data import batch, encode, read_split
from .model import GPT, GPTConfig
from .tokenizer import EOT, train_tokenizer


@torch.no_grad()
def eval_loss(model: GPT, stream: torch.Tensor, block: int, size: int, n: int, gen: torch.Generator) -> float:
    model.eval()
    losses = [model(*batch(stream, block, size, gen))[1].item() for _ in range(n)]
    model.train()
    return sum(losses) / len(losses)


def unigram_perplexity(train: torch.Tensor, test: torch.Tensor, vocab: int) -> float:
    """Baseline: a model that only knows token frequencies (add-one smoothing)."""
    counts = Counter(train.tolist())
    total = len(train) + vocab
    nll = -sum(math.log((counts.get(t, 0) + 1) / total) for t in test.tolist()) / len(test)
    return math.exp(nll)


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/smoke.yaml")
    cfg = yaml.safe_load(Path(parser.parse_args().config).read_text())
    torch.manual_seed(cfg["seed"])
    gen = torch.Generator().manual_seed(cfg["seed"])
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    out = Path("runs") / cfg["run"]
    out.mkdir(parents=True, exist_ok=True)

    data_dir = Path(cfg["data_dir"])
    train_texts, val_texts, test_texts = (read_split(data_dir, s) for s in ("train", "val", "test"))
    tok = train_tokenizer(train_texts, cfg["vocab_size"])  # trained on train only: no test leakage
    tok.save(str(out / "tokenizer.json"))
    eot = tok.token_to_id(EOT)
    train, val, test = (encode(tok, t, eot) for t in (train_texts, val_texts, test_texts))

    mcfg = GPTConfig(vocab_size=tok.get_vocab_size(), **cfg["model"])
    model = GPT(mcfg).to(device)
    t = cfg["train"]
    opt = torch.optim.AdamW(model.parameters(), lr=t["lr"], betas=(0.9, 0.95), weight_decay=t["weight_decay"])

    def lr_at(step: int) -> float:
        if step < t["warmup"]:
            return t["lr"] * (step + 1) / t["warmup"]
        progress = (step - t["warmup"]) / max(1, t["steps"] - t["warmup"])
        return t["lr"] * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))

    history, evals, best = [], [], float("inf")
    started = time.time()
    for step in range(t["steps"]):
        for g in opt.param_groups:
            g["lr"] = lr_at(step)
        x, y = batch(train, mcfg.block_size, t["batch_size"], gen)
        _, loss = model(x.to(device), y.to(device))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % 10 == 0 or step == t["steps"] - 1:
            history.append([step, round(loss.item(), 4)])
        if (step + 1) % t["eval_every"] == 0 or step == t["steps"] - 1:
            vl = eval_loss(model, val.to(device), mcfg.block_size, t["batch_size"], t["eval_batches"], gen)
            evals.append([step + 1, round(vl, 4)])
            print(f"step {step + 1}/{t['steps']} train {loss.item():.3f} val {vl:.3f}", flush=True)
            if vl < best:
                best = vl
                save_file({k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()
                           if k != "head.weight"}, str(out / "model.safetensors"))

    test_loss = eval_loss(model, test.to(device), mcfg.block_size, t["batch_size"], t["eval_batches"], gen)
    test_ppl, uni_ppl = math.exp(test_loss), unigram_perplexity(train, test, tok.get_vocab_size())
    metrics = {
        "from_scratch": True, "params": model.num_params(), "tokens_train": len(train),
        "tokens_seen": t["steps"] * t["batch_size"] * mcfg.block_size, "device": device,
        "train_seconds": round(time.time() - started, 1),
        "loss_first": history[0][1], "loss_last": history[-1][1], "loss_history": history, "val_history": evals,
        "val_loss": best, "test_loss": round(test_loss, 4), "test_perplexity": round(test_ppl, 2),
        "unigram_perplexity": round(uni_ppl, 2), "perplexity_ratio": round(test_ppl / uni_ppl, 4),
    }
    (out / "config.json").write_text(json.dumps(mcfg.to_dict(), indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out / "params.json").write_text(json.dumps({"config": cfg, "git_sha": git_sha()}, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if not k.endswith("history")}, indent=2))


if __name__ == "__main__":
    main()
