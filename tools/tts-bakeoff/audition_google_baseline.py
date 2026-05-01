"""Render Google Chirp 3 HD baselines (current production voices) for the same
audition lines used by ElevenLabs, so we can A/B by ear.

Audio tags ([warm], [curious], etc.) are stripped — Chirp 3 HD ignores them.

Output: reports/baatcheet-tts-bakeoff/auditions/{role}-google.mp3
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
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
API_KEY = ENV.get("GOOGLE_CLOUD_TTS_API_KEY") or os.environ.get("GOOGLE_CLOUD_TTS_API_KEY")
if not API_KEY:
    sys.exit("GOOGLE_CLOUD_TTS_API_KEY not found")

OUT_DIR = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "auditions"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Current production voices (from llm-backend/book_ingestion_v2/services/audio_generation_service.py:46-56)
TUTOR_VOICE = ("en-IN", "en-IN-Chirp3-HD-Orus")     # Mr. Verma
PEER_VOICE  = ("en-IN", "en-IN-Chirp3-HD-Leda")     # Meera

TUTOR_TEXT = (
    "[warm] Aha, spot on! "
    "[curious] But tell me — if I split this chapati into four pieces, "
    "are all the pieces really the same size?"
)
PEER_TEXT = (
    "[hesitant] Hmm... I think... bigger numbers are bigger fractions? "
    "[excited] Oh wait! The bottom number is how many pieces, not how big!"
)


def strip_tags(text: str) -> str:
    """Remove [tag] markers — Chirp 3 HD doesn't understand them."""
    return re.sub(r"\[[^\]]+\]\s*", "", text).strip()


def synth(voice: tuple[str, str], text: str, out_path: Path) -> None:
    lang, name = voice
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={API_KEY}"
    body = {
        "input": {"text": text},
        "voice": {"languageCode": lang, "name": name},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
    except HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode('utf-8','replace')[:400]}", file=sys.stderr)
        raise
    audio = base64.b64decode(payload["audioContent"])
    out_path.write_bytes(audio)
    print(f"  -> {out_path.name}  ({len(audio)/1024:.0f} KB)")


def main() -> None:
    print(f"Output dir: {OUT_DIR}\n")

    tutor_clean = strip_tags(TUTOR_TEXT)
    peer_clean  = strip_tags(PEER_TEXT)

    print(f"[tutor:google] voice={TUTOR_VOICE[1]}")
    print(f"  text: {tutor_clean}")
    synth(TUTOR_VOICE, tutor_clean, OUT_DIR / "tutor-google.mp3")

    print(f"\n[peer:google]  voice={PEER_VOICE[1]}")
    print(f"  text: {peer_clean}")
    synth(PEER_VOICE, peer_clean, OUT_DIR / "peer-google.mp3")

    print("\nDone.")


if __name__ == "__main__":
    main()
