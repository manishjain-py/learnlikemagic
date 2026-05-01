"""Email kid-voice auditions for Meera via Mail.app."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIR = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "auditions-kid"

TO = "manishjain.py@gmail.com"
SUBJECT = "Baatcheet TTS — kid-voice auditions for Meera (6 candidates)"

BODY = """Kid-voice auditions for Meera — 6 candidates rendered with the same hesitant→excited line.

Note: ElevenLabs (and all major TTS providers) ban actual child voices for child-safety reasons. All these are adult voice actors performing youthful characters, same as animated film. We don't lose anything functionally.

Indian:
  peer-kiran.mp3   — Kiran — Very Young Adorable (most likely kid-coded)
  peer-bheem.mp3   — Bheem — boy peer option
  peer-kalpana.mp3 — Kalpana — GenZ creator energy
  peer-sia.mp3     — Sia — Commercial Ad Voice (excited)

Non-Indian fallbacks (if Indian options skew adult):
  peer-dorothy.mp3 — British Children's Storyteller (dedicated kids voice)
  peer-cleo.mp3    — Irish 'youthful' (sanity check)

See README.md for the listening guide.

Reply with one (e.g., "kiran"). If none feel kid enough, say so and I'll audition Cartesia voices for comparison.
"""


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main() -> None:
    files = sorted([p for p in DIR.iterdir() if p.suffix in (".mp3", ".md")])
    print(f"Attaching {len(files)} files:")
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")

    attachment_lines = "\n        ".join(
        f'make new attachment with properties {{file name:POSIX file "{f}"}} at after the last paragraph'
        for f in files
    )
    applescript = f'''
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:"{escape(SUBJECT)}", content:"{escape(BODY)}", visible:false}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{TO}"}}
        {attachment_lines}
    end tell
    send newMessage
end tell
'''
    r = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print("Mail.app error:")
        print(r.stderr)
        raise SystemExit(1)
    print(f"\nSent to {TO}")


if __name__ == "__main__":
    main()
