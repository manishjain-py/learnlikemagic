# TTS bake-off tooling

Reusable scripts from the May 2026 ElevenLabs vs Google bake-off. Pairs with `docs/feature-development/baatcheet-expressive-tts/plan.md`.

Outputs land in `reports/baatcheet-tts-bakeoff/` (gitignored).

## Scripts

| Script | What it does |
|---|---|
| `audition_elevenlabs.py` | Renders 6 voice candidates (3 tutor + 3 peer) saying the same line with v3 audio tags so you can pick voices by ear. |
| `audition_google_baseline.py` | Renders the same audition lines through current production Google Chirp 3 HD voices for A/B reference. |
| `audition_kid_voices.py` | Renders 6 kid-coded candidates for the peer role (4 Indian + 2 non-Indian fallbacks). |
| `email_auditions.py` / `email_kid_auditions.py` / `email_bakeoff.py` | Emails the rendered MP3s + READMEs via macOS Mail.app (no SMTP creds needed). |
| `find_sample_dialogues.py` | Lists baatcheet dialogues in the DB so you can pick samples for rendering. |
| `dump_dialogue.py` | Dumps one dialogue + lesson plan as JSON for offline rendering. |
| `render_bakeoff.py` | Full bake-off renderer — Google + ElevenLabs end-to-end, plus isolated emotional-beat snippets, for one dialogue. |

## Usage

Set `ELEVENLABS_API_KEY` in `llm-backend/.env`. Then:

```bash
# 1. Audition voices to pick winners
python3 tools/tts-bakeoff/audition_elevenlabs.py
python3 tools/tts-bakeoff/audition_google_baseline.py

# 2. Pick a dialogue and dump it
python3 tools/tts-bakeoff/find_sample_dialogues.py
python3 tools/tts-bakeoff/dump_dialogue.py

# 3. Render the bake-off (edit voice IDs in render_bakeoff.py first)
python3 tools/tts-bakeoff/render_bakeoff.py

# 4. Email yourself the package for listen-testing
python3 tools/tts-bakeoff/email_bakeoff.py
```

All scripts are stdlib-only (no `requests` / `dotenv` dependency) so they run in any Python 3.x.
