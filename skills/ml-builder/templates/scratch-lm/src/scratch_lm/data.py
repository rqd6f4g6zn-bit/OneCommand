"""Token streams from the dataset built by OneCommand's dataset.py (data/processed/{train,val,test}.jsonl)."""

from __future__ import annotations

import json
from pathlib import Path

import torch


def read_split(data_dir: Path, name: str) -> list[str]:
    path = data_dir / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — build it: python3 $OC_ROOT/hooks/dataset.py build --task text")
    return [json.loads(line)["text"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode(tok, texts: list[str], eot_id: int) -> torch.Tensor:
    ids: list[int] = []
    for enc in tok.encode_batch(texts):
        ids.extend(enc.ids)
        ids.append(eot_id)
    return torch.tensor(ids, dtype=torch.long)


def batch(stream: torch.Tensor, block: int, size: int, gen: torch.Generator) -> tuple[torch.Tensor, torch.Tensor]:
    if len(stream) <= block + 1:
        raise ValueError(f"split has only {len(stream)} tokens, block_size is {block} — add data or lower block_size")
    ix = torch.randint(len(stream) - block - 1, (size,), generator=gen)
    x = torch.stack([stream[i:i + block] for i in ix])
    y = torch.stack([stream[i + 1:i + 1 + block] for i in ix])
    return x, y
