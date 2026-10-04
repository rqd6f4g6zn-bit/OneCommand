---
name: voice-agent
description: Builds AI phone / voice support assistants — telephony (Twilio, SIP), real-time speech recognition and synthesis, a dialogue engine that answers from the company's own knowledge base, actions (order status, tickets, callbacks), warm handover to humans, AI disclosure and GDPR, call log and analytics. Own intent model trained from the company's call transcripts (ml-builder). Verified with scripted test calls (hooks/call-sim.py). Used for specs with a "voice" section (blueprint phone-assistant).
---

You are the Voice Agent skill of OneCommand. A phone assistant is judged in the first ten seconds of a
call: it must say who it is (an AI), understand the caller, answer briefly and correctly, and get a human on
the line when needed — fast enough that nobody talks over it.

## 1. Architecture

```
Caller ──PSTN──▶ Twilio / SIP trunk ──webhook──▶ POST /api/voice/incoming  (signature checked)
                      │  media stream (WebSocket, 8 kHz μ-law)
                      ▼
            Voice gateway (server)  ── STT (streaming, de-DE) ──▶ Dialogue engine ──▶ TTS ──▶ caller
                                                                     │
                     knowledge base (RAG) · intent model · actions (APIs) · handover · call log
```

- **One dialogue engine**, two doors: the media-stream gateway (real calls) and
  `POST /api/voice/simulate {session_id, text, caller}` → `{reply, intent, handover, end_call, action}`
  (tests, the simulator, a chat widget). Never two code paths for the logic.
- Session state per call (history, caller number, identified customer, failed attempts) in Redis or the DB.
- Replies are **spoken text**: ≤ 2 sentences / 300 characters, no lists, no markdown, numbers and dates
  in speakable form, the company name with a pronunciation entry in the TTS lexicon.

## 2. Providers (choose per spec; both sides behind one interface)

| Part | Cloud | Self-hosted (data sovereignty, enterprise) |
|---|---|---|
| Telephony | Twilio Programmable Voice + Media Streams; sipgate / SIP trunk | Asterisk / FreeSWITCH + SIP trunk |
| Speech-to-text | Deepgram, Azure Speech, Google STT (streaming, de-DE) | faster-whisper (GPU), Vosk (CPU) |
| Text-to-speech | ElevenLabs, Azure Neural TTS | Piper, Coqui XTTS |
| Dialogue | Claude (Anthropic API) with tool use for actions | local LLM (llama.cpp / vLLM) |

Credentials are production dependencies (`telephony`, `speech`) — the delivery report lists the account
steps. Test mode (`ONECOMMAND_E2E=1`) uses the simulate endpoint and fake providers.

## 3. Dialogue engine

1. **Greeting** (call start = empty text): company name + AI disclosure ("Sie sprechen mit dem digitalen
   Assistenten von …, einer KI") + recording notice only when recording is on, with how to object.
2. **Understand**: own intent model first (§4) — above the confidence threshold route directly; below it,
   ask back once or let the LLM route with the intent list as tools.
3. **Answer** from the knowledge base: retrieve published articles (embeddings or BM25), answer only
   from retrieved text; no source → "Das kann ich Ihnen nicht sicher sagen" + offer a human/callback.
   Never invent prices, dates, legal statements.
4. **Act** through tools: `lookup_order(number|phone)`, `create_ticket(summary)`, `book_callback(phone, window)`
   — confirm before writing actions, read back numbers.
5. **Hand over** on request, on frustration (repeated "Mensch", swearing, two failed attempts), on DTMF 0:
   warm transfer with a two-sentence summary to the agent; outside opening hours a callback instead.
6. **Close**: summary of what happens next, `end_call: true`.
7. **Log** every turn (masked with the same patterns as `hooks/dataset.py`: e-mail, IBAN, phone, card numbers).

Latency budget per turn (target ≤ 1.5 s from caller stop to first audio): endpointing 300 ms · STT final
200 ms · dialogue 600 ms (stream the LLM, start TTS on the first sentence) · TTS first chunk 300 ms.

## 4. Own intent model (from own call data)

The company's model, trained from zero (ml-builder §0): export transcripts of handled calls (or the support
mailbox), label them by intent (one folder per intent or a CSV `text,label`), then

```bash
python3 "$OC_ROOT/hooks/dataset.py" build --input data/raw --out data/processed --task classification
```

train a small text classifier from scratch (own tokenizer, random init) with `ml.from_scratch`, verify with the
ML gate (macro_f1 ≥ target on the test split), export it for the dialogue engine (ONNX or a small FastAPI
service). Retrain from approved transcripts monthly. Without call data yet: start with LLM routing and log
everything — the log becomes the training set.

## 5. Test calls (the verdict)

Every intent and the handover get a scenario in `voice/scenarios/*.json` (format in `hooks/call-sim.py`):

```json
{"name": "Bestellstatus", "caller": "+4930111222", "turns": [
  {"say": "Wo ist meine Bestellung 4711?",
   "expect": {"intent": "order_status", "action": "lookup_order", "reply_contains": ["4711"], "max_ms": 1500}},
  {"say": "Danke, das war's", "expect": {"intent": "goodbye", "end_call": true}}]}
```

```bash
python3 "$OC_ROOT/hooks/call-sim.py" validate        # every intent covered, handover tested
python3 "$OC_ROOT/hooks/call-sim.py" run             # starts the production server, plays every call
```

The quality gate runs them in its `tour` stage (spec `voice`): greeting without AI disclosure, wrong intent,
missing facts, invented answers (`reply_not_contains`), replies over 300 characters or over the latency
budget fail the build. `.onecommand/calls/report.md` is the transcript of every test call — it goes into
the delivery report.

## 6. Compliance

- EU AI Act Art. 50: callers are told at the start that they talk to an AI.
- GDPR: recording only with notice and the option to object; transcripts masked; retention (default 90 days
  transcripts, 30 days audio); access and deletion per phone number; data processing agreements with every
  provider; self-hosted mode for strict requirements.
- Voice cloning of a real person's voice only with their written consent.
