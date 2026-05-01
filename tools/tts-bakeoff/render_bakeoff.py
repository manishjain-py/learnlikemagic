"""Bake-off renderer: produce Google + ElevenLabs MP3s for one baatcheet dialogue.

Outputs into reports/baatcheet-tts-bakeoff/dialogue-1-place-value/:
  google.mp3       — full dialogue, current production voices, no emotion tags (per-line synth + ffmpeg concat)
  elevenlabs.mp3   — full dialogue via Text-to-Dialogue API with audio tags from move grammar
  snippets/        — 5 emotional-beat lines, each as Google + ElevenLabs MP3
  transcript.md    — full text + which tag was applied per card

Voices (locked by user):
  tutor (Mr. Verma): Sekhar — Warm & Energetic   (81uXfTrZ08xcmV31Rvrb)
  peer  (Meera)    : Amara  — Calm Intellectual  (IEBxKtmsE9KTrXUwNazR)
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / "llm-backend" / ".env"
DIALOGUE_JSON = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "dialogue.json"
OUT_DIR = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "dialogue-1-place-value"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SNIPPET_DIR = OUT_DIR / "snippets"
SNIPPET_DIR.mkdir(parents=True, exist_ok=True)

STUDENT_NAME = "Arjun"  # for {student_name} substitution

TUTOR_VOICE_ID = "81uXfTrZ08xcmV31Rvrb"     # Sekhar
PEER_VOICE_ID  = "IEBxKtmsE9KTrXUwNazR"     # Amara

# Current prod Google voices
TUTOR_GOOGLE_VOICE = ("en-IN", "en-IN-Chirp3-HD-Orus")
PEER_GOOGLE_VOICE  = ("en-IN", "en-IN-Chirp3-HD-Leda")

# move → audio tag (v3 interprets natural-language emotion words in [brackets])
MOVE_TAG_TUTOR = {
    "hook":                 "warm",
    "activate":             "curious",
    "concretize":           "warm",
    "notate":               "calm",
    "trap-set":             "curious",
    "student-act":          "excited",
    "funnel":               "gentle",
    "articulate":           "warm",
    "callback":             "warm",
    "reframe":              "empathetic",
    "practice-guided":      "encouraging",
    "practice-independent": "encouraging",
    "close":                "proud",
    "fall":                 "warm",  # tutor "fall" is rare; safe default
}
MOVE_TAG_PEER = {
    "fall":      "hesitant",
    "observe":   "curious",
    "callback":  "excited",   # spine callback = aha moment for Meera
    "activate":  "curious",
    "articulate": "excited",  # Meera articulating = aha moment
    "notate":    "curious",
    "reframe":   "tired",     # "my head is so full"
}

# Emotional-beat snippets to render in isolation.
# Card indices verified against plan move grammar.
SNIPPETS = [
    {"key": "01-hook-warm",          "card_idx": 2,  "label": "Mr Verma — warm hook (open the lesson)"},
    {"key": "02-trap-curious",       "card_idx": 8,  "label": "Mr Verma — curious trap-set (47,352 read-aloud)"},
    {"key": "03-fall-hesitant",      "card_idx": 9,  "label": "Meera — hesitant fall (digit-by-digit)"},
    {"key": "04-articulate-warm",    "card_idx": 13, "label": "Mr Verma — warm articulate / praise"},
    {"key": "05-meera-aha",          "card_idx": 22, "label": "Meera — aha! callback to spine"},
    {"key": "06-meera-tired",        "card_idx": 33, "label": "Meera — reframe (head is full)"},
    {"key": "07-tutor-empathetic",   "card_idx": 34, "label": "Mr Verma — empathetic reframe response", "tag_override": "empathetic"},
    {"key": "08-close-proud",        "card_idx": 39, "label": "Mr Verma — proud close"},
]


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV = load_env(ENV_PATH)
EL_KEY = ENV["ELEVENLABS_API_KEY"]
GOOGLE_KEY = ENV["GOOGLE_CLOUD_TTS_API_KEY"]


def substitute(text: str) -> str:
    return text.replace("{student_name}", STUDENT_NAME)


def tag_for(card_idx: int, speaker: str, plan_card: dict | None) -> str | None:
    if plan_card is None:
        return None
    move = plan_card.get("move")
    if speaker == "tutor":
        return MOVE_TAG_TUTOR.get(move)
    if speaker == "peer":
        return MOVE_TAG_PEER.get(move)
    return None


def card_text_combined(card: dict) -> str:
    """Join the card's lines into a single string for TTS."""
    lines = card.get("lines") or []
    parts = []
    for ln in lines:
        a = (ln.get("audio") or ln.get("display") or "").strip()
        if a:
            parts.append(substitute(a))
    return " ".join(parts).strip()


def card_with_tag(card: dict, tag: str | None) -> str:
    text = card_text_combined(card)
    if not text:
        return ""
    if tag:
        return f"[{tag}] {text}"
    return text


def google_synth(voice: tuple[str, str], text: str) -> bytes:
    lang, name = voice
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_KEY}"
    body = {
        "input": {"text": text},
        "voice": {"languageCode": lang, "name": name},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    req = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=60) as r:
        payload = json.loads(r.read())
    return base64.b64decode(payload["audioContent"])


def el_tts(voice_id: str, text: str) -> bytes:
    """Single-voice ElevenLabs v3 synth (used for snippets)."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.4, "use_speaker_boost": True},
    }
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"xi-api-key": EL_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as r:
            return r.read()
    except HTTPError as e:
        sys.exit(f"EL TTS error {e.code}: {e.read().decode('utf-8','replace')[:400]}")


def el_dialogue(inputs: list[dict]) -> bytes:
    """ElevenLabs v3 Text-to-Dialogue (multi-speaker, one MP3)."""
    url = "https://api.elevenlabs.io/v1/text-to-dialogue"
    body = {"model_id": "eleven_v3", "inputs": inputs}
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"xi-api-key": EL_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=600) as r:
            return r.read()
    except HTTPError as e:
        sys.exit(f"EL dialogue error {e.code}: {e.read().decode('utf-8','replace')[:600]}")


def ffmpeg_concat(mp3_paths: list[Path], out_path: Path, gap_ms: int = 250) -> None:
    """Concat MP3s with brief silence gaps via ffmpeg concat demuxer.

    Re-encodes to keep timing clean.
    """
    silence = OUT_DIR / "_silence.mp3"
    if not silence.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"anullsrc=r=44100:cl=mono", "-t", str(gap_ms / 1000.0),
             "-acodec", "libmp3lame", "-q:a", "4", str(silence)],
            check=True,
        )

    list_file = OUT_DIR / "_concat.txt"
    interleaved: list[Path] = []
    for i, p in enumerate(mp3_paths):
        interleaved.append(p)
        if i < len(mp3_paths) - 1:
            interleaved.append(silence)
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in interleaved))

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-acodec", "libmp3lame", "-q:a", "4", str(out_path)],
        check=True,
    )
    list_file.unlink(missing_ok=True)


def render_google_baseline(cards: list[dict], plan_by_slot: dict, work_dir: Path) -> Path:
    """Per-line Google synth, then ffmpeg concat into one full-dialogue MP3."""
    print("=== Google baseline (per-line synth + concat) ===")
    line_dir = work_dir / "_google_lines"
    line_dir.mkdir(exist_ok=True)
    paths: list[Path] = []
    line_no = 0
    for card in cards:
        speaker = card.get("speaker")
        if not speaker or not card.get("lines"):
            continue
        voice = TUTOR_GOOGLE_VOICE if speaker == "tutor" else PEER_GOOGLE_VOICE
        for ln in card["lines"]:
            text = substitute((ln.get("audio") or ln.get("display") or "").strip())
            if not text:
                continue
            line_no += 1
            p = line_dir / f"{line_no:03d}.mp3"
            p.write_bytes(google_synth(voice, text))
            paths.append(p)
            time.sleep(0.05)
    out = work_dir / "google.mp3"
    ffmpeg_concat(paths, out, gap_ms=250)
    print(f"  -> {out.name}  ({out.stat().st_size/1024:.0f} KB, {line_no} lines)")
    shutil.rmtree(line_dir, ignore_errors=True)
    return out


def render_elevenlabs_dialogue(cards: list[dict], plan_by_slot: dict, work_dir: Path) -> tuple[Path, list[dict]]:
    """One ElevenLabs Text-to-Dialogue call; returns mp3 path + transcript inputs."""
    print("=== ElevenLabs v3 (Text-to-Dialogue, single call) ===")
    inputs: list[dict] = []
    transcript: list[dict] = []
    total_chars = 0
    for card in cards:
        speaker = card.get("speaker")
        if not speaker or not card.get("lines"):
            continue
        plan_card = plan_by_slot.get(card.get("card_idx"))
        tag = tag_for(card.get("card_idx", 0), speaker, plan_card)
        text = card_with_tag(card, tag)
        if not text:
            continue
        voice_id = TUTOR_VOICE_ID if speaker == "tutor" else PEER_VOICE_ID
        inputs.append({"voice_id": voice_id, "text": text})
        transcript.append({
            "card_idx": card.get("card_idx"),
            "speaker": speaker,
            "move": (plan_card or {}).get("move"),
            "tag": tag,
            "text": text,
        })
        total_chars += len(text)
    print(f"  Inputs: {len(inputs)} cards, {total_chars} chars")
    audio = el_dialogue(inputs)
    out = work_dir / "elevenlabs.mp3"
    out.write_bytes(audio)
    print(f"  -> {out.name}  ({out.stat().st_size/1024:.0f} KB)")
    return out, transcript


def render_snippets(cards: list[dict], plan_by_slot: dict) -> list[dict]:
    print("=== Emotional-beat snippets ===")
    by_idx = {c.get("card_idx"): c for c in cards}
    out_meta: list[dict] = []
    for s in SNIPPETS:
        card = by_idx.get(s["card_idx"])
        if not card or not card.get("lines"):
            print(f"  SKIP {s['key']}: card_idx={s['card_idx']} has no lines")
            continue
        speaker = card.get("speaker")
        plan_card = plan_by_slot.get(s["card_idx"])
        tag = s.get("tag_override") or tag_for(s["card_idx"], speaker, plan_card)
        plain = card_text_combined(card)
        tagged = card_with_tag(card, tag)

        # Google
        gv = TUTOR_GOOGLE_VOICE if speaker == "tutor" else PEER_GOOGLE_VOICE
        gp = SNIPPET_DIR / f"{s['key']}.google.mp3"
        gp.write_bytes(google_synth(gv, plain))

        # ElevenLabs
        elv = TUTOR_VOICE_ID if speaker == "tutor" else PEER_VOICE_ID
        ep = SNIPPET_DIR / f"{s['key']}.elevenlabs.mp3"
        ep.write_bytes(el_tts(elv, tagged))

        print(f"  {s['key']:30s} | {speaker:5s} | move={(plan_card or {}).get('move','?'):14s} | tag={tag or '-':12s} | google={gp.stat().st_size/1024:.0f}KB el={ep.stat().st_size/1024:.0f}KB")
        out_meta.append({
            "key": s["key"], "label": s["label"], "card_idx": s["card_idx"],
            "speaker": speaker, "move": (plan_card or {}).get("move"),
            "tag": tag, "plain_text": plain, "tagged_text": tagged,
        })
        time.sleep(0.2)
    return out_meta


def write_transcript(d: dict, transcript_inputs: list[dict], snippet_meta: list[dict]) -> None:
    md = []
    md.append(f"# Bake-off transcript: {d['topic_title']}")
    md.append(f"")
    md.append(f"- guideline_id: `{d['guideline_id']}`")
    md.append(f"- subject: {d['subject']}, grade {d['grade']}")
    md.append(f"- chapter: {d['chapter_title']}")
    md.append(f"- cards: {len(d['cards_json'])}")
    md.append(f"- generator_model: {d['generator_model']}")
    md.append(f"")
    md.append(f"## Voices")
    md.append(f"- Mr. Verma: Sekhar — Warm & Energetic (`{TUTOR_VOICE_ID}`)")
    md.append(f"- Meera: Amara — Calm Intellectual (`{PEER_VOICE_ID}`)")
    md.append(f"- Google baseline: Orus (tutor), Leda (peer)")
    md.append(f"")
    md.append(f"## Lesson plan")
    plan = d["plan_json"]
    spine = (plan.get("spine") or {}).get("situation", "")
    md.append(f"**Spine:** {spine}")
    md.append(f"")
    md.append(f"**Misconceptions:**")
    for m in plan.get("misconceptions", []):
        md.append(f"- **{m.get('id')}** {m.get('name')} — {m.get('description','')[:160]}")
    md.append(f"")
    md.append(f"## Move → audio-tag mapping used")
    md.append(f"")
    md.append(f"| Move | Tutor tag | Peer tag |")
    md.append(f"|---|---|---|")
    all_moves = sorted(set(list(MOVE_TAG_TUTOR) + list(MOVE_TAG_PEER)))
    for m in all_moves:
        md.append(f"| `{m}` | {MOVE_TAG_TUTOR.get(m,'-')} | {MOVE_TAG_PEER.get(m,'-')} |")
    md.append(f"")
    md.append(f"## Full dialogue (with applied tags)")
    md.append(f"")
    for t in transcript_inputs:
        md.append(f"**{t['speaker']}** (card {t['card_idx']}, move=`{t['move']}`, tag=`{t['tag']}`):  ")
        md.append(f"  {t['text']}")
        md.append(f"")
    md.append(f"## Snippets (isolated emotional beats)")
    md.append(f"")
    for s in snippet_meta:
        md.append(f"### {s['label']} — `{s['key']}`")
        md.append(f"- card_idx: {s['card_idx']}, speaker: {s['speaker']}, move: `{s['move']}`, tag: `{s['tag']}`")
        md.append(f"- text (google): `{s['plain_text']}`")
        md.append(f"- text (elevenlabs): `{s['tagged_text']}`")
        md.append(f"")
    (OUT_DIR / "transcript.md").write_text("\n".join(md))
    print(f"=== wrote transcript.md ({(OUT_DIR/'transcript.md').stat().st_size} bytes) ===")


def main() -> None:
    d = json.loads(DIALOGUE_JSON.read_text())
    cards = d["cards_json"]
    plan = d["plan_json"]

    # plan card_plan slots are 1-based+offset; align with card_idx
    plan_by_slot: dict[int, dict] = {}
    for cp in plan.get("card_plan", []):
        slot = cp.get("slot")
        if isinstance(slot, int):
            plan_by_slot[slot] = cp

    # Quick coverage check
    matched = sum(1 for c in cards if c.get("card_idx") in plan_by_slot)
    print(f"plan match: {matched}/{len(cards)} cards aligned to plan slots")
    print()

    google_path = render_google_baseline(cards, plan_by_slot, OUT_DIR)
    print()
    el_path, transcript_inputs = render_elevenlabs_dialogue(cards, plan_by_slot, OUT_DIR)
    print()
    snippet_meta = render_snippets(cards, plan_by_slot)
    print()
    write_transcript(d, transcript_inputs, snippet_meta)
    print(f"\nAll output: {OUT_DIR}")


if __name__ == "__main__":
    main()
