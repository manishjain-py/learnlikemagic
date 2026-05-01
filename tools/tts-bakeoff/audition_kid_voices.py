"""Audition candidate 'kid-like' voices for Meera.

ElevenLabs prohibits actual child voices — best alternatives are 'youthful',
'characters_animation' use case, or 'very young' descriptors.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / "llm-backend" / ".env"


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
API_KEY = ENV["ELEVENLABS_API_KEY"]
OUT_DIR = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "auditions-kid"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Candidates spanning Indian + non-Indian, female + male, all marketed as young/kid-adjacent.
CANDIDATES = [
    # Indian
    ("kiran",   "o80picuztV1xYiPeIrpa", "Kiran — Very Young Adorable Story Narrator (IN female)"),
    ("bheem",   "kp7BqyMoDqqeVWfDZZlN", "Bheem — Confident, Friendly & Natural (IN male, characters)"),
    ("kalpana", "llsUsrN3CKAHdUcqg2c6", "Kalpana G — Casual GenZ Creator (IN female)"),
    ("sia",     "k1smwybPgJKo52uEOuQK", "Sia — The Commercial Ad Voice (IN female, excited)"),
    # Non-Indian fallbacks (if Indian options skew adult)
    ("dorothy", "AFpJHw6AxGC0nx0fpvpi", "Dorothy — British Children's Storyteller (UK female)"),
    ("cleo",    "0VXT7iQ2kXG7EERbbG9T", "Cleo — Youthful Irish female voice (IE female)"),
]

TEXT = (
    "[hesitant] Hmm... I think... bigger numbers are bigger fractions? "
    "[excited] Oh wait! The bottom number is how many pieces, not how big!"
)


def synth(voice_id: str, text: str, out_path: Path) -> None:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.4, "use_speaker_boost": True},
    }
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as r:
            out_path.write_bytes(r.read())
    except HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode('utf-8','replace')[:300]}", file=sys.stderr)
        raise
    print(f"  -> {out_path.name}  ({out_path.stat().st_size/1024:.0f} KB)")


def main() -> None:
    print(f"Output dir: {OUT_DIR}")
    print(f"Text ({len(TEXT)} chars): {TEXT}\n")
    for short, vid, label in CANDIDATES:
        print(f"[{short}] {label}  ({vid})")
        synth(vid, TEXT, OUT_DIR / f"peer-{short}.mp3")
        time.sleep(0.3)
    print("\nDone.")


if __name__ == "__main__":
    main()
