# Own language model, trained from scratch

```bash
python3 "$OC_ROOT/hooks/dataset.py" build --input data/raw --out data/processed --task text
uv sync
uv run python -m scratch_lm.train --config configs/smoke.yaml     # CPU, ~1–2 min
uv run python -m scratch_lm.train --config configs/default.yaml   # GPU recommended
uv run python -m scratch_lm.generate "Unser Produkt" --run runs/smoke
MODEL_DIR=runs/smoke uv run uvicorn scratch_lm.serve:app --port 8000
```
