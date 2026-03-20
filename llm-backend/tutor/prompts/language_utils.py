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
            "Mix Hindi and English the way young urban Indians naturally speak — "
            "Hindi for verbs, connectors, warmth (dekho, socho, karo, matlab, yaani, arre, wah) "
            "and English for technical terms, numbers, subject vocabulary. "
            "Casual tone: tum/tumhare, karo (not aap/kijiye). "
            "Example: \"Arre wah, bilkul sahi! Dekho, basically 5 plus 3 ka answer 8 hota hai "
            "kyunki hum 5 mein 3 aur add kar rahe hain.\""
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
            "Write EXACTLY how a young Indian teacher naturally talks to a student — "
            "the kind of casual Hindi-English mix educated urban Indians speak every day. "
            "Roman script only.\n"
            "KEY RULES:\n"
            "- Hindi for sentence structure, verbs, connectors, and warmth: "
            "dekho, socho, batao, karo, padho, samjho, likho, haan, nahi, matlab, yaani, "
            "arre, wah, shabash, bilkul, acha, theek hai\n"
            "- English for technical terms, subject vocabulary, numbers, and operations — "
            "NEVER translate these to Hindi\n"
            "- Natural fillers young Indians use: basically, actually, like, right?, hai na?\n"
            "- Code-switch at phrase boundaries, NOT word-by-word — "
            "whole phrases should be in one language before switching\n"
            "- Use Hindi question tags: samjhe?, theek hai?, hai na?, sahi?\n"
            "- Contractions and casual tone: tum/tumhare (not aap/aapke), "
            "karo (not kijiye) — speak like a friendly big sister, not a formal teacher\n"
            "EXAMPLES of natural Hinglish:\n"
            "- \"Arre wah, bilkul sahi! Ab next question try karo — ye thoda tricky hoga.\"\n"
            "- \"Acha toh dekho, basically jab hum fractions ko compare karte hain na, "
            "toh pehle denominator same karna padta hai. Yaani like, agar ek mein 4 hai "
            "aur doosre mein 6, toh hum dono ka LCM nikalenge. Samjhe?\"\n"
            "- \"Hmm, ye answer galat ho gaya. Koi baat nahi — ek baar phir se socho. "
            "Hint deti hoon: 7 times 8 kitna hota hai? Wahan se start karo.\"\n"
            "- \"Very good yaar! Dekha, kitna easy tha? Ab ek aur karte hain.\"\n"
            "- \"Toh basically yahan pe area nikalne ke liye length times breadth karna hai. "
            "Length 5 cm hai aur breadth 3 cm hai — toh multiply karo, kya aayega?\"\n"
            "ANTI-PATTERNS — never do these:\n"
            "- Translating technical terms: WRONG 'gunaa' for multiply, 'uttar' for answer\n"
            "- Formal Hindi: WRONG 'aap batayein', 'kripya', 'aapka uttar sahi hai'\n"
            "- Awkward word-by-word mixing: WRONG 'yeh ek bahut important concept hai jo hum seekhenge'\n"
            "- Pure English with just 'toh' sprinkled in: WRONG 'Toh, the answer is 8 because we add 5 and 3'"
        )
    # Default: English
    return (
        "The `audio_text` field is a spoken English version of your `response`. "
        "Write naturally as a friendly Indian tutor speaking aloud in English."
    )
