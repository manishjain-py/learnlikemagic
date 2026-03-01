"""Language instruction helpers for tutor prompts."""


def get_response_language_instruction(text_lang: str) -> str:
    """Return prompt instruction for the `response` field language."""
    if text_lang == "hi":
        return (
            "Write the `response` field in Hindi (Devanagari script). "
            "Use pure Hindi for explanations and conversational text. "
            "Keep technical/mathematical terms in English where natural."
        )
    if text_lang == "hinglish":
        return (
            "Write the `response` field in Hinglish (Hindi-English mix, Roman script). "
            "Mix Hindi and English naturally — Hindi for conversational glue and English "
            "for technical terms. Example: \"Toh dekho, 5 plus 3 ka answer 8 hota hai.\""
        )
    # Default: English
    return "Write the `response` field in English."


def get_audio_language_instruction(audio_lang: str) -> str:
    """Return prompt instruction for the `audio_text` field language."""
    if audio_lang == "hi":
        return (
            "The `audio_text` field is a spoken Hindi version of your `response`. "
            "Write in Hindi using Roman script (transliteration) so TTS can pronounce it. "
            "Keep technical terms in English."
        )
    if audio_lang == "hinglish":
        return (
            "The `audio_text` field is a spoken Hinglish version of your `response`. "
            "Write as a friendly Indian tutor speaking aloud — mix Hindi and English naturally. "
            "Hindi for conversational glue (\"toh\", \"dekho\", \"samjho\", \"acha\") and English "
            "for technical terms. Roman script only. "
            "Example: \"Bahut accha! Toh 5 plus 3 ka answer kya hoga? Sochke batao.\""
        )
    # Default: English
    return (
        "The `audio_text` field is a spoken English version of your `response`. "
        "Write naturally as a friendly Indian tutor speaking aloud in English."
    )
