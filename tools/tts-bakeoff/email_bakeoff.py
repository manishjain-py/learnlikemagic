"""Email the full bake-off package via macOS Mail.app.

Attaches: README + transcript + 2 full-dialogue MP3s + 16 snippet MP3s = 20 files (~9 MB).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "reports" / "baatcheet-tts-bakeoff" / "dialogue-1-place-value"

TO = "manishjain.py@gmail.com"
SUBJECT = "Baatcheet TTS bake-off — Place Value (Grade 4): Google vs ElevenLabs v3"

BODY = """Bake-off ready. One full dialogue rendered both ways, plus 8 isolated emotional-beat snippets for A/B listening.

Topic: Reading and Writing 5- and 6-Digit Numbers (Grade 4 Math, 39 cards).
Voices: Mr. Verma = Sekhar (warm-energetic Indian male), Meera = Amara (calm-intellectual Indian female).
Method: ElevenLabs v3 with audio tags derived from the lesson plan's move grammar (hook, fall, articulate, reframe, ...).

How to listen:
1. Start with google.mp3 (~6 min) and elevenlabs.mp3 (~6 min) end-to-end — overall feel.
2. Then go snippet-by-snippet. The diagnostic ones:
   - 03-fall-hesitant — does Meera actually sound hesitant?
   - 05-meera-aha — does the "Oh wait!" land?
   - 06-meera-tired + 07-tutor-empathetic — the reframe pair, where pedagogy meets emotion.
   - 08-close-proud — does "High five!" feel like a real proud teacher?

Open README.md for the full guide and what each snippet maps to. Open transcript.md for the dialogue text + every audio tag applied.

Quota note: ~12K of 40K monthly chars used so far on ElevenLabs starter. Room to iterate.

Once you've listened, reply with one of:
  - "ship it" — proceed to schema change + pipeline migration
  - "partial — only on [reframe / fall / articulate / close]" — narrower rollout
  - "audition Cartesia too" — render the same package on Sonic-3 for comparison
  - "stay on Google" — drop the migration
"""


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main() -> None:
    files: list[Path] = []
    files.append(PKG / "README.md")
    files.append(PKG / "transcript.md")
    files.append(PKG / "google.mp3")
    files.append(PKG / "elevenlabs.mp3")
    snippets = sorted((PKG / "snippets").iterdir())
    files.extend(snippets)

    print(f"Attaching {len(files)} files:")
    total = 0
    for f in files:
        sz = f.stat().st_size
        total += sz
        print(f"  {f.name}  ({sz/1024:.0f} KB)")
    print(f"  total: {total/1024/1024:.1f} MB")

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
    r = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("Mail.app error:")
        print(r.stderr)
        raise SystemExit(1)
    print(f"\nSent to {TO}")


if __name__ == "__main__":
    main()
