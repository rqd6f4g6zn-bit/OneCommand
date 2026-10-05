# Model card — <Name>

**Trained from scratch:** random initialisation, own architecture (decoder-only transformer), own BPE
tokenizer trained on our training split. No pretrained weights or vocabularies were used.

## Intended use
<what the model is for, who uses it, what it must not be used for>

## Dataset
Own data, built with OneCommand's `dataset.py` — see `data/processed/DATASHEET.md` (provenance, license /
right to use, personal data scrubbed, duplicates removed, train/val/test by document).

## Training
Config `configs/<run>.yaml`; parameters, tokens seen, device and time in `runs/<run>/metrics.json`.

## Metrics
| Run | test perplexity | unigram baseline | perplexity_ratio |
|---|---|---|---|
| smoke | <from metrics.json> | <…> | <…> |

## Limitations
Small models trained on small corpora reproduce the style and vocabulary of their data and invent facts.
They know nothing outside the training data. <languages, time range, gaps of the data>
