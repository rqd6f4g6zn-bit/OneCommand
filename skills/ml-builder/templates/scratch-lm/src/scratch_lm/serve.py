"""Inference API: GET /health, POST /generate."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .generate import Generator

app = FastAPI(title="scratch-lm")
gen = Generator(Path(os.environ.get("MODEL_DIR", "runs/smoke")))


class Prompt(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    max_new_tokens: int = Field(default=80, ge=1, le=400)
    temperature: float = Field(default=0.8, gt=0, le=2)
    top_k: int = Field(default=50, ge=1, le=1000)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "params": gen.model.num_params()}


@app.post("/generate")
def generate(p: Prompt) -> dict:
    return gen(p.prompt, p.max_new_tokens, p.temperature, p.top_k)
