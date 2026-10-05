"""Load a trained run and generate text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from safetensors.torch import load_file

from .model import GPT, GPTConfig
from .tokenizer import EOT, load_tokenizer


class Generator:
    def __init__(self, run_dir: Path):
        self.tok = load_tokenizer(run_dir / "tokenizer.json")
        self.model = GPT(GPTConfig(**json.loads((run_dir / "config.json").read_text())))
        missing, unexpected = self.model.load_state_dict(load_file(str(run_dir / "model.safetensors")), strict=False)
        if set(missing) - {"head.weight"} or unexpected:  # head.weight is tied to the embedding, not stored
            raise RuntimeError(f"checkpoint does not match the model: missing {missing}, unexpected {unexpected}")
        self.model.eval()
        self.eot = self.tok.token_to_id(EOT)

    def __call__(self, prompt: str, max_new_tokens: int = 80, temperature: float = 0.8, top_k: int = 50) -> dict:
        ids = self.tok.encode(prompt).ids or [self.eot]
        out = self.model.generate(torch.tensor([ids]), max_new_tokens, temperature, top_k, stop_id=self.eot)
        new = [i for i in out[0, len(ids):].tolist() if i != self.eot]
        return {"text": self.tok.decode(new), "prompt_tokens": len(ids), "new_tokens": len(new)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--run", default="runs/smoke")
    parser.add_argument("--max-new-tokens", type=int, default=80)
    args = parser.parse_args()
    print(Generator(Path(args.run))(args.prompt, args.max_new_tokens)["text"])


if __name__ == "__main__":
    main()
