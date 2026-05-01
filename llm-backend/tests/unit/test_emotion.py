"""Unit tests for the emotion canonicalization helper."""
from shared.types.emotion import Emotion, canonicalize_emotion


class TestCanonicalizeExactMatches:
    def test_returns_enum_for_canonical_lowercase(self):
        assert canonicalize_emotion("warm") is Emotion.WARM
        assert canonicalize_emotion("hesitant") is Emotion.HESITANT
        assert canonicalize_emotion("tired") is Emotion.TIRED

    def test_lowercases_and_trims(self):
        assert canonicalize_emotion("  Warm  ") is Emotion.WARM
        assert canonicalize_emotion("CURIOUS") is Emotion.CURIOUS

    def test_passthrough_enum_value(self):
        assert canonicalize_emotion(Emotion.PROUD) is Emotion.PROUD


class TestCanonicalizeSynonyms:
    def test_warmly_maps_to_warm(self):
        assert canonicalize_emotion("warmly") is Emotion.WARM

    def test_joyful_maps_to_excited(self):
        assert canonicalize_emotion("joyful") is Emotion.EXCITED

    def test_soothing_maps_to_gentle(self):
        assert canonicalize_emotion("soothing") is Emotion.GENTLE

    def test_compassionate_maps_to_empathetic(self):
        assert canonicalize_emotion("compassionate") is Emotion.EMPATHETIC

    def test_unsure_maps_to_hesitant(self):
        assert canonicalize_emotion("unsure") is Emotion.HESITANT


class TestCanonicalizeNullish:
    def test_none_returns_none(self):
        assert canonicalize_emotion(None) is None

    def test_empty_string_returns_none(self):
        assert canonicalize_emotion("") is None

    def test_whitespace_only_returns_none(self):
        assert canonicalize_emotion("   ") is None


class TestCanonicalizeRejection:
    def test_unknown_value_returns_none(self):
        assert canonicalize_emotion("evil") is None

    def test_non_string_returns_none(self):
        assert canonicalize_emotion(42) is None
        assert canonicalize_emotion({"emotion": "warm"}) is None

    def test_unicode_garbage_returns_none(self):
        assert canonicalize_emotion("🔥🔥🔥") is None
