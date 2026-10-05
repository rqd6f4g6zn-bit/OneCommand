"""Inference API: GET /health, POST /generate → base64 PNG images or MP4 clips."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .generate import Generator

app = FastAPI(title="scratch-diffusion")
gen = Generator(Path(os.environ.get("MODEL_DIR", "runs/smoke")))


class Request(BaseModel):
    n: int = Field(default=1, ge=1, le=8)
    seed: int = Field(default=0, ge=0)
    label: str | None = None
    steps: int = Field(default=25, ge=5, le=250)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "kind": gen.cfg["kind"], "size": gen.cfg["size"], "labels": gen.labels}


@app.post("/generate")
def generate(r: Request) -> dict:
    try:
        x = gen.sample(r.n, r.seed, r.label, r.steps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    kind = gen.cfg["kind"]
    return {"format": "png" if kind == "image" else "mp4", "width": gen.cfg["size"], "height": gen.cfg["size"],
            "frames": gen.cfg.get("frames") or 1, "items": gen.encode(x)}
