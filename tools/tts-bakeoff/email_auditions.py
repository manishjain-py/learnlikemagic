"""Email the audition MP3s + README via macOS Mail.app (no SMTP creds needed).

Mirrors the pattern in llm-backend/autoresearch/simplification_quality/email_report.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDITIONS = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "auditions"

TO = "manishjain.py@gmail.com"
SUBJECT = "Baatcheet TTS bake-off — voice auditions (ElevenLabs vs Google)"

BODY = """Voice auditions for the baatcheet TTS upgrade.

8 short clips (~5 sec each), all saying the same line. ElevenLabs clips use v3 with inline audio tags ([warm], [curious], [hesitant], [excited]) so you can hear the voice's emotional range.

Tutor (Mr. Verma) candidates:
  tutor-google.mp3   — Current prod (en-IN-Chirp3-HD-Orus, no emotion control)
  tutor-sekhar.mp3   — Sekhar — Warm & Energetic (educational use case)
  tutor-arin.mp3     — Arin — Deep, Assured, Warm
  tutor-karthik.mp3  — Karthik — Indian AI Voice

Peer (Meera) candidates:
  peer-google.mp3    — Current prod (en-IN-Chirp3-HD-Leda, no emotion control)
  peer-devi.mp3      — Devi — Engaging Tutor Voice (educational use case)
  peer-amara.mp3     — Amara — Calm Intellectual Narrator
  peer-ayu.mp3       — Ayu — Education / Podcast

Listen for:
  - Warmth on "Aha, spot on!"
  - Curiosity shift on "But tell me..."
  - Real hesitation on "Hmm... I think..."
  - Burst of excitement on "Oh wait!"
  - Indian English cadence — does it feel like a Grade-4 classroom?

Reply with one tutor + one peer (e.g., "tutor: arin, peer: devi") and I'll move on to the full bake-off.
"""


def escape_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main() -> None:
    files = sorted([p for p in AUDITIONS.iterdir() if p.suffix in (".mp3", ".md")])
    if not files:
        raise SystemExit(f"No files found in {AUDITIONS}")

    print(f"Attaching {len(files)} files:")
    for f in files:
        print(f"  {f.name} ({f.stat().st_size / 1024:.0f} KB)")

    attachment_lines = "\n        ".join(
        f'make new attachment with properties {{file name:POSIX file "{f}"}} at after the last paragraph'
        for f in files
    )

    applescript = f'''
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:"{escape_applescript(SUBJECT)}", content:"{escape_applescript(BODY)}", visible:false}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{TO}"}}
        {attachment_lines}
    end tell
    send newMessage
end tell
'''

    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print("Mail.app error:")
        print(result.stderr)
        raise SystemExit(1)
    print(f"\nSent to {TO}")


if __name__ == "__main__":
    main()
