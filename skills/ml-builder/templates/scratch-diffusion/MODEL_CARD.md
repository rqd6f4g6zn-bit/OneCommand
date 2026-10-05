# Model card — <Name>

**Trained from scratch:** a diffusion model (U-Net noise predictor, DDPM objective, DDIM sampler) with random
initialisation. No pretrained weights, no pretrained autoencoder, no text encoder.

## Intended use
<what it generates (product shots, textures, brand-style backgrounds, short clips …), who uses it, what not>

## Dataset
Own images / videos built with OneCommand's `dataset.py --task images|videos` — see `data/processed/DATASHEET.md`
(provenance, rights to use, exact and visual duplicates removed, split by file). People in images: consent.

## Training
Config `configs/<run>.yaml`; parameters, items, device and time in `runs/<run>/metrics.json`.

## Metrics
| Run | final loss | nn_ratio (samples vs noise, lower is better) | nn distance of the test set (reference) |
|---|---|---|---|
| smoke | <…> | <…> | <…> |

## Limitations
Resolution and variety are bounded by the data and compute: small datasets are memorised (outputs resemble
training images). No text prompts — conditioning only by the dataset's labels. Mark generated media as generated.
