"""Application constants - all magic numbers centralized."""

# Mastery scoring
MASTERY_EMA_ALPHA = 0.4  # Exponential moving average smoothing factor
MASTERY_COMPLETION_THRESHOLD = 0.85  # Score needed to complete session
MASTERY_ADVANCE_THRESHOLD = 0.8  # Score needed to advance without remediation

# Session progression
MAX_STEPS = 10  # Maximum steps per session
STEP_PROGRESSION_STAGES = {
    "easy": (0, 2),  # Steps 0-2: Easy, concrete examples
    "build": (3, 5),  # Steps 3-5: Build on basics
    "why": (6, 7),  # Steps 6-7: "Why" questions
    "real_life": (8, 9)  # Steps 8-9: Real-life scenarios
}

# Grading thresholds (score bands)
SCORE_EXCELLENT = 0.9  # 0.9-1.0: Excellent understanding
SCORE_GOOD = 0.7  # 0.7-0.89: Good understanding with minor gaps
SCORE_PARTIAL = 0.5  # 0.5-0.69: Partial understanding
SCORE_SIGNIFICANT_GAPS = 0.3  # 0.3-0.49: Significant misconceptions
# 0.0-0.29: Minimal understanding

# Confidence thresholds
MIN_CONFIDENCE_FOR_ADVANCE = 0.6  # Minimum confidence to advance

# Default/fallback values
DEFAULT_GUIDELINE = "Teach this topic step by step using grade-appropriate language."
DEFAULT_MESSAGE = "Hello!"

# LLM settings
DEFAULT_LLM_MODEL = "gpt-4o-mini"
MAX_MESSAGE_LENGTH = 80  # words for teaching messages
MAX_REMEDIATION_LENGTH = 60  # words for remediation messages
