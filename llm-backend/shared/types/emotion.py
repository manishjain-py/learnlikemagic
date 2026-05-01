"""Canonical 11-value emotion vocabulary for ElevenLabs v3 audio tags.

Authored per-line by the V2 baatcheet dialogue generator. Validator
canonicalizes synonyms (`warmly` -> `warm`) and rejects unknown values to
`None` so a hallucinated tag never reaches the TTS request.

No tutor/peer split is enforced — both speakers can use any value. Prompt-
level guidance suggests typical fits per role, but the schema accepts any
value for either speaker.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Emotion(str, Enum):
    WARM = "warm"
    CURIOUS = "curious"
    ENCOURAGING = "encouraging"
    GENTLE = "gentle"
    PROUD = "proud"
    EMPATHETIC = "empathetic"
    CALM = "calm"
    EXCITED = "excited"
    HESITANT = "hesitant"
    CONFUSED = "confused"
    TIRED = "tired"


# Common LLM synonyms that map cleanly onto the canonical set. Keys are
# lowercased; canonicalize_emotion() lowercases its input first.
_SYNONYMS: dict[str, Emotion] = {
    "warmly": Emotion.WARM,
    "kind": Emotion.WARM,
    "kindly": Emotion.WARM,
    "friendly": Emotion.WARM,
    "joyful": Emotion.EXCITED,
    "happy": Emotion.EXCITED,
    "thrilled": Emotion.EXCITED,
    "delighted": Emotion.EXCITED,
    "excitedly": Emotion.EXCITED,
    "enthusiastic": Emotion.EXCITED,
    "supportive": Emotion.ENCOURAGING,
    "encouragingly": Emotion.ENCOURAGING,
    "soothing": Emotion.GENTLE,
    "soft": Emotion.GENTLE,
    "softly": Emotion.GENTLE,
    "tender": Emotion.GENTLE,
    "gently": Emotion.GENTLE,
    "compassionate": Emotion.EMPATHETIC,
    "empathising": Emotion.EMPATHETIC,
    "empathizing": Emotion.EMPATHETIC,
    "empathic": Emotion.EMPATHETIC,
    "empathetically": Emotion.EMPATHETIC,
    "calmly": Emotion.CALM,
    "steady": Emotion.CALM,
    "neutral": Emotion.CALM,
    "inquisitive": Emotion.CURIOUS,
    "wondering": Emotion.CURIOUS,
    "curiously": Emotion.CURIOUS,
    "uncertain": Emotion.HESITANT,
    "unsure": Emotion.HESITANT,
    "hesitantly": Emotion.HESITANT,
    "tentative": Emotion.HESITANT,
    "puzzled": Emotion.CONFUSED,
    "lost": Emotion.CONFUSED,
    "confusedly": Emotion.CONFUSED,
    "weary": Emotion.TIRED,
    "exhausted": Emotion.TIRED,
    "tiredly": Emotion.TIRED,
    "proudly": Emotion.PROUD,
}


def canonicalize_emotion(value: object) -> Optional[Emotion]:
    """Return a canonical Emotion or None.

    Accepts str / Emotion / None. Strings are lowercased and trimmed; an
    exact match against the canonical vocabulary wins, otherwise the
    synonym map is consulted. Out-of-vocab values log a warning and
    return None — synthesis falls back to the steady voice preset.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Emotion):
        return value
    if not isinstance(value, str):
        logger.warning(f"emotion value of type {type(value).__name__!r} rejected -> None")
        return None
    key = value.strip().lower()
    if not key:
        return None
    try:
        return Emotion(key)
    except ValueError:
        pass
    if key in _SYNONYMS:
        return _SYNONYMS[key]
    logger.warning(f"emotion value {value!r} not in canonical vocabulary -> None")
    return None
