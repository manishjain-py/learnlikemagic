"""Render ElevenLabs v3 audition clips for Mr. Verma and Meera candidates.

Each clip uses inline audio tags ([warm], [curious], [hesitant], [excited]) so we
hear the voice's emotional range, not just baseline timbre.

Output: reports/baatcheet-tts-bakeoff/auditions/{role}-{name}.mp3

Stdlib-only (no requests/dotenv) so it runs in any Python 3.x.
"""

from __future__ import annotations

import json
import os
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
API_KEY = ENV.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
if not API_KEY:
    sys.exit("ELEVENLABS_API_KEY not found in env")

MODEL_ID = "eleven_v3"
OUT_DIR = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "auditions"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TUTOR_CANDIDATES = [
    ("sekhar",  "81uXfTrZ08xcmV31Rvrb", "Sekhar - Warm & Energetic"),
    ("arin",    "rKlA9IV83pv3fHXXQqpm", "Arin - Deep, Assured, Warm"),
    ("karthik", "oaz5NvoRIhcJystOASAA", "Karthik - Indian AI Voice"),
]

PEER_CANDIDATES = [
    ("devi",  "Ghr5KCyOzBvJpcdBbJhE", "Devi - The Engaging Tutor Voice"),
    ("amara", "IEBxKtmsE9KTrXUwNazR", "Amara - Calm & Intellectual Narrator"),
    ("ayu",   "0k7C0T4TCad8X8b3kmnz", "Ayu - Education, Podcast & Social Media"),
]

TUTOR_TEXT = (
    "[warm] Aha, spot on! "
    "[curious] But tell me — if I split this chapati into four pieces, "
    "are all the pieces really the same size?"
)

PEER_TEXT = (
    "[hesitant] Hmm... I think... bigger numbers are bigger fractions? "
    "[excited] Oh wait! The bottom number is how many pieces, not how big!"
)


def synth(voice_id: str, text: str, out_path: Path) -> None:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.4,
            "use_speaker_boost": True,
        },
    }
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "xi-api-key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as resp:
            data = resp.read()
    except HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode('utf-8', 'replace')[:400]}", file=sys.stderr)
        raise
    out_path.write_bytes(data)
    print(f"  -> {out_path.name}  ({len(data) / 1024:.0f} KB)")


def main() -> None:
    print(f"Output dir: {OUT_DIR}")
    print(f"Model: {MODEL_ID}\n")

    print(f"Tutor text ({len(TUTOR_TEXT)} chars):\n  {TUTOR_TEXT}\n")
    for short, vid, label in TUTOR_CANDIDATES:
        print(f"[tutor] {label}  ({vid})")
        synth(vid, TUTOR_TEXT, OUT_DIR / f"tutor-{short}.mp3")
        time.sleep(0.3)

    print(f"\nPeer text ({len(PEER_TEXT)} chars):\n  {PEER_TEXT}\n")
    for short, vid, label in PEER_CANDIDATES:
        print(f"[peer]  {label}  ({vid})")
        synth(vid, PEER_TEXT, OUT_DIR / f"peer-{short}.mp3")
        time.sleep(0.3)

    print("\nDone.")


if __name__ == "__main__":
    main()
