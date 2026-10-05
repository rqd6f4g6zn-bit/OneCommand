---
name: voice-agent
description: Builds AI phone / voice support assistants — telephony (Twilio, SIP), real-time speech recognition, a natural human-sounding voice (never robotic; own brand voice by consented clone or an own fine-tuned TTS model), a dialogue engine that answers from the company's own knowledge base, small talk, actions (order status, tickets, callbacks), warm handover to humans, AI disclosure and GDPR, call log and analytics. Own intent model trained from the company's call transcripts (ml-builder). Verified with scripted test calls, a small-talk probe and voice samples (hooks/call-sim.py). Used for specs with a "voice" section (blueprint phone-assistant).
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
| Text-to-speech | ElevenLabs (Flash v2.5 / Multilingual v2), Azure Neural HD | own fine-tuned model on a commercially licensed base (§3), Piper |
| Dialogue | Claude (Anthropic API) with tool use for actions | local LLM (llama.cpp / vLLM) |

Credentials are production dependencies (`telephony`, `speech`) — the delivery report lists the account
steps. Test mode (`ONECOMMAND_E2E=1`) uses the simulate endpoint and fake providers.

## 3. Voice — it must sound like a person

Callers judge the voice before the content. A robotic voice makes them press 0 or hang up.

- **One voice for everything.** Every sentence the caller hears is synthesised by the configured TTS — greeting,
  answers, hold messages, the handover sentence, errors. Never TwiML `<Say>` / `response.say()` (Twilio's built-in
  voice is a second, robotic voice) and never eSpeak, Festival, Flite or Pico. `call-sim validate` fails on both.
  For TwiML paths (DTMF, fallback) synthesise the text and `<Play>` the file, or speak through the media stream.
- **Neural, streaming, low latency:** ElevenLabs Flash v2.5 (≈ 75 ms) or Multilingual v2 for the most natural
  German; Azure Neural HD as the one-vendor option. Stream audio as it arrives; start speaking on the first
  sentence of the LLM reply.
- **Telephone format:** request 8 kHz μ-law (or 16 kHz and resample once) — no double conversion.
- **Speakable text:** numbers, dates, times, prices and order numbers written the way they are spoken
  ("vierzehn Uhr", "vier sieben eins eins"); abbreviations expanded; the company and product names in a
  pronunciation lexicon (phonemes / alias); no lists, brackets, emoji or URLs.
- **Prosody:** short sentences, a comma where a person breathes, a question at the end when a reply is
  expected; slightly slower than reading speed (call-sim requires 8–25 letters/s).
- **`POST /api/voice/tts {"text"}` → audio** (test mode and authenticated admins only), header
  `X-Voice-Provider: elevenlabs|azure|own-model|fake`, 503 when no provider is configured. Set
  `voice.tts_endpoint` in the spec: call-sim then synthesises every greeting and reply into
  `.onecommand/calls/audio/` — the owner listens to them before go-live (linked in the delivery report).

### Pronunciation test (automatic, every build with voice credentials)

The assistant also serves `POST /api/voice/stt` (raw audio → `{"text"}`, test mode and admins only, 503 without a
recogniser) on its own speech-to-text provider. With `voice.stt_endpoint` set, call-sim runs a round trip:
every reply plus a German test set — umlauts and ß, numbers, dates, prices, order digits, "Willkommen bei
<Firma>", every `voice.lexicon` term and every `voice.pronunciation` sentence — is spoken by the voice and
written back by the recogniser. A sentence whose transcript differs by more than `voice.max_wer` (word error
rate, default 0.2) or a company / product name the recogniser cannot find fails the build. That catches
mispronounced names, swallowed endings and wrong number readings. The fix is a lexicon entry (phonemes or alias), never a
changed test. The table in `.onecommand/calls/report.md` shows what was said and what was heard. Whether the
voice *sounds* human stays a listening decision. That is what the samples are for.

### Own voice (brand voice)

| Way | Data needed | Result | Notes |
|---|---|---|---|
| Catalogue voice | none | professional, natural | fastest start |
| Voice clone at the provider (ElevenLabs Professional Voice Clone) | 30 min – 3 h studio recordings of one speaker | sounds like your speaker | written consent of the speaker; voice stays with the provider |
| **Own model, self-hosted** — fine-tune an open, commercially licensed TTS model on your recordings | 1 h usable, 3 h+ for production | your own weights on your server, no per-minute cost | GPU for training (hours); licence of the base model must allow commercial use — check and record it (e.g. Piper: MIT; Kokoro, Fish Speech: Apache 2.0 — verify the current licence of the exact checkpoint). Non-commercial weights (XTTS-v2, F5-TTS) are excluded |
| From scratch | 24 h+ (50 h+ for natural prosody) of one speaker | fully own model | with less data it sounds robotic — say so plainly and recommend the fine-tune |

Where voice data may come from — every folder is recorded in `voice/recordings/sources.json` (name, licence,
URL; own recordings with the consent file), `dataset.py --task speech` refuses to build without it:

| Source | Use | Licence |
|---|---|---|
| Your own speaker (studio recordings, written consent) | the brand voice itself | own |
| Mozilla Common Voice | base model: many speakers, 100+ languages, with text | CC0 |
| Multilingual LibriSpeech (OpenSLR 94) | base model: read audiobooks in 8 languages incl. German | CC BY 4.0 (credit → ATTRIBUTION.md) |
| LibriVox | base model: public-domain audiobooks | public domain |

Never YouTube, TikTok, Spotify, podcasts or other platform content — their terms forbid downloading for
training, the recordings are copyrighted and the voices belong to their speakers (personality rights, GDPR);
`dataset.py` rejects platform URLs. Singing does not help a speaking voice. Non-commercial corpora (CC BY-NC,
e.g. many research sets) only with `--allow-noncommercial` for research — never for a company hotline.
Mixing works like this: a base model learns the language from many licensed speakers, then 1–3 h of your own
speaker turn it into one consistent voice.

Recording kit (the build writes it to `voice/recording/`):
- `script.md`: every sentence the assistant says (greeting, all knowledge-base answers, handover, goodbye),
  numbers 0–100, weekdays, months, times, prices, order-number digits, product and street names, plus
  phonetically varied German sentences (ä ö ü ß, ich-/ach-Laut, pf, z, ng, sp/st, r-Varianten) — 1 sentence per clip,
  3–15 seconds each.
- `GUIDE.md`: quiet room (no echo), the same microphone and distance every session, 44.1 or 48 kHz WAV,
  peaks around −6 dB (never clipping), friendly and calm like on the phone, 0.3 s silence before and after,
  breaks every 30 minutes, the speaker's signed consent (training, use, duration, revocation).
- Check the recordings before training:

```bash
python3 "$OC_ROOT/hooks/dataset.py" build --input voice/recordings --out voice/dataset --task speech --min-hours 1
```

  It rejects clips without transcript, too short/long, below 22.05 kHz (phone recordings cannot teach a voice),
  clipped, too quiet, with long silence or with a transcript that does not fit the audio length, and prints
  which way the hours support. Real customer calls are never training data for a voice.

The voice is still an AI voice: the greeting discloses it (EU AI Act Art. 50); a cloned real person's voice only
with their written consent, and never to impersonate a person.

## 4. Dialogue engine

1. **Greeting** (call start = empty text): company name + AI disclosure ("Sie sprechen mit dem digitalen
   Assistenten von …, einer KI") + recording notice only when recording is on, with how to object.
2. **Small talk** (`smalltalk` intent): "Hallo?", "Ja, hallo", "Moment bitte", "Sind Sie noch da?", "Danke" are
   normal on the phone — greet back / wait / confirm and ask how to help. Never "nicht verstanden", never a
   handover because of them (call-sim plays these in every run).
3. **Remember the conversation.** The session keeps the last intent, the last topic (article) and every entity
   the caller gave: order number, phone number, product, date. Callers talk in follow-ups — "Wann kommt es
   denn?", "Kostet das was?", "Und am Sonntag?" — so before routing, resolve short or pronoun-only turns
   against the last topic: a delivery question after an order lookup reuses that order number, a cost
   question after a return explanation asks about return costs. A number the caller says after the assistant
   asked for one fills that slot ("Meine Nummer ist 0171 …" after a callback request) — never "nicht
   verstanden". Never ask again for something the caller already said (call-sim plays a follow-up in every run).
4. **Complaints** (`complaint` intent): anger, "schon wieder", "falsch geliefert", "kaputt", "unverschämt",
   "Beschwerde" — acknowledge and apologise once ("Das tut mir leid, das ist ärgerlich."), create a ticket
   with a summary or hand over warmly; never "nicht verstanden", never a cheerful standard answer. The intent
   model and the LLM routing both know this class (call-sim plays a complaint in every run).
5. **Understand**: own intent model first (§5) — above the confidence threshold route directly; below it,
   ask back once or let the LLM route with the intent list and the conversation state as tools.
6. **Answer the question that was asked** from the knowledge base: retrieve published articles (embeddings or
   BM25), answer only from retrieved text. When the article does not cover the specific thing asked — another
   country, a product, Sunday — say exactly that ("Für Österreich habe ich leider keine Angabe") instead of
   answering a neighbouring question; no source → "Das kann ich Ihnen nicht sicher sagen" + offer a
   human/callback. A topic word alone ("Rechnung") gets a clarifying question, not the nearest article.
   Never invent prices, dates, legal statements.
7. **Act** through tools: `lookup_order(number|phone)`, `create_ticket(summary)`, `book_callback(phone, window)`
   — confirm before writing actions, read back numbers.
8. **Hand over** on request, on frustration (repeated "Mensch", swearing, two failed attempts), on DTMF 0:
   warm transfer with a two-sentence summary to the agent; outside opening hours a callback instead.
9. **Close**: summary of what happens next, `end_call: true`.
10. **Log** every turn (masked with the same patterns as `hooks/dataset.py`: e-mail, IBAN, phone, card numbers).

Latency budget per turn (target ≤ 1.5 s from caller stop to first audio): endpointing 300 ms · STT final
200 ms · dialogue 600 ms (stream the LLM, start TTS on the first sentence) · TTS first chunk 300 ms.

### Recognising the caller

- **By phone number (caller ID):** look the number up in the customer / order data at call start (normalised
  E.164). Found → use it for convenience: "Guten Tag, spreche ich mit Frau Neumann?" and offer the latest order
  ("Geht es um Ihre Bestellung vier sieben eins eins?"); remember earlier calls from the call log ("Sie hatten
  letzte Woche wegen … angerufen"). Several customers on one number → ask which one. Suppressed or unknown
  number → ask for the order or customer number.
- **A phone number is not proof of identity** — it can be spoofed and is shared in families and offices. Status
  information (order status, delivery day) may follow a number match plus the confirmed name. **Anything that
  changes data or reveals more** — address, payment, cancellation, refund, invoice copies, personal data — needs a
  second factor first: postcode of the delivery address, customer number, date of birth, or a one-time code sent
  by SMS / e-mail to the registered contact; otherwise hand over. call-sim plays such a request from a known
  number in every run (`identity` probe): changing it straight away fails the build.
- **By voice (voice biometrics)** only as an opt-in enterprise extra: it is biometric data (GDPR Art. 9) — explicit
  written consent, an alternative for those who decline, never the only factor (cloned voices exist).
- Log who was identified and how (`identifiedBy: phone|order_number|second_factor|voice`), never the second factor
  itself.

## 5. Own intent model (from own call data)

The company's model, trained from zero (ml-builder §0): export transcripts of handled calls (or the support
mailbox), label them by intent (one folder per intent or a CSV `text,label`), then

```bash
python3 "$OC_ROOT/hooks/dataset.py" build --input data/raw --out data/processed --task classification
```

train a small text classifier from scratch (own tokenizer, random init) with `ml.from_scratch` (include small talk
and complaint as their own classes), verify with the
ML gate (macro_f1 ≥ target on the test split), export it for the dialogue engine (ONNX or a small FastAPI
service). Retrain from approved transcripts monthly. Without call data yet: start with LLM routing and log
everything — the log becomes the training set.

## 6. Test calls (the verdict)

Every intent and the handover get a scenario in `voice/scenarios/*.json` (format in `hooks/call-sim.py`). Every
turn checks content — an intent or words; a turn that only checks length or latency is rejected, because a
"not understood" reply would pass it:

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
budget, small talk answered with "not understood" or a handover, a complaint not recognised, a follow-up that
forgets the conversation, TwiML `<Say>` or a robotic engine in the code,
and (with credentials) voice samples that are missing or rushed fail the build. `.onecommand/calls/report.md` is the transcript of every test call — it goes into
the delivery report.

## 7. Compliance

- EU AI Act Art. 50: callers are told at the start that they talk to an AI.
- GDPR: recording only with notice and the option to object; transcripts masked; retention (default 90 days
  transcripts, 30 days audio); access and deletion per phone number; data processing agreements with every
  provider; self-hosted mode for strict requirements.
- Voice cloning of a real person's voice only with their written consent.
