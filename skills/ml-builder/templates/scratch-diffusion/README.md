# Own image / video generator, trained from scratch

```bash
python3 "$OC_ROOT/hooks/dataset.py" build --input data/raw --out data/processed --task images   # or --task videos
uv sync                                                                # blocked PyTorch host: uv sync --no-sources
uv run python -m scratch_diffusion.train --config configs/smoke.yaml   # images, CPU ~1–2 min
uv run python -m scratch_diffusion.train --config configs/video-smoke.yaml
uv run python -m scratch_diffusion.generate --run runs/smoke --n 8 --label <folder name>
MODEL_DIR=runs/smoke uv run uvicorn scratch_diffusion.serve:app --port 8000
```
