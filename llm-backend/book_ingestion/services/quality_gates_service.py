"""
Quality Gates Service

Responsibility: Validate subtopic shards meet quality standards.

Single Responsibility Principle:
- Only handles quality validation logic
- No LLM calls (rule-based validation)
- Returns validation results with detailed feedback

Quality Criteria (MVP v1):
1. Minimum facts: ≥2 objectives, ≥1 misconception, ≥1 assessment
2. Teaching description: present, valid length, contains key elements
3. Content completeness: at least 1 page, reasonable page range
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from ..models.guideline_models import SubtopicShard, QualityFlags

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of quality validation"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    quality_score: float  # 0.0-1.0


class QualityGatesService:
    """
    Validate subtopic shards against quality standards.

    Quality gates ensure that:
    1. Enough educational content is extracted
    2. Teaching description is present and useful
    3. Shard is ready for AI tutor consumption
    """

    # Quality thresholds (configurable)
    MIN_OBJECTIVES = 2
    MIN_EXAMPLES = 1
    MIN_MISCONCEPTIONS = 1
    MIN_ASSESSMENTS = 1
    MIN_PAGES = 1
    MAX_PAGES_PER_SUBTOPIC = 15  # Warning if exceeded
    MIN_TEACHING_DESC_LENGTH = 100  # chars
    MAX_TEACHING_DESC_LENGTH = 600  # chars

    def __init__(
        self,
        min_objectives: int = MIN_OBJECTIVES,
        min_examples: int = MIN_EXAMPLES,
        min_misconceptions: int = MIN_MISCONCEPTIONS,
        min_assessments: int = MIN_ASSESSMENTS
    ):
        """
        Initialize quality gates service.

        Args:
            min_objectives: Minimum number of objectives required
            min_examples: Minimum number of examples required
            min_misconceptions: Minimum number of misconceptions required
            min_assessments: Minimum number of assessments required
        """
        self.min_objectives = min_objectives
        self.min_examples = min_examples
        self.min_misconceptions = min_misconceptions
        self.min_assessments = min_assessments

        logger.info(
            f"Initialized QualityGates with thresholds: "
            f"objectives≥{min_objectives}, examples≥{min_examples}, "
            f"misconceptions≥{min_misconceptions}, assessments≥{min_assessments}"
        )

    def validate(self, shard: SubtopicShard) -> ValidationResult:
        """
        Validate a subtopic shard.

        Args:
            shard: Subtopic shard to validate

        Returns:
            ValidationResult with detailed feedback

        Quality checks:
        1. Fact completeness (objectives, examples, misconceptions, assessments)
        2. Teaching description quality
        3. Content volume (page count)
        4. Assessment diversity (difficulty levels)
        """
        errors = []
        warnings = []

        # 1. Validate fact completeness
        fact_errors, fact_warnings = self._validate_facts(shard)
        errors.extend(fact_errors)
        warnings.extend(fact_warnings)

        # 2. Validate teaching description
        desc_errors, desc_warnings = self._validate_teaching_description(shard)
        errors.extend(desc_errors)
        warnings.extend(desc_warnings)

        # 3. Validate content volume
        volume_errors, volume_warnings = self._validate_content_volume(shard)
        errors.extend(volume_errors)
        warnings.extend(volume_warnings)

        # 4. Validate assessment diversity
        assess_errors, assess_warnings = self._validate_assessment_diversity(shard)
        errors.extend(assess_errors)
        warnings.extend(assess_warnings)

        # Calculate quality score
        quality_score = self._calculate_quality_score(shard, errors, warnings)

        is_valid = len(errors) == 0

        if is_valid:
            logger.info(
                f"Quality validation PASSED for {shard.subtopic_key}: "
                f"score={quality_score:.2f}, {len(warnings)} warnings"
            )
        else:
            logger.warning(
                f"Quality validation FAILED for {shard.subtopic_key}: "
                f"{len(errors)} errors, {len(warnings)} warnings"
            )

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            quality_score=quality_score
        )

    def _validate_facts(
        self,
        shard: SubtopicShard
    ) -> tuple[List[str], List[str]]:
        """Validate fact completeness"""
        errors = []
        warnings = []

        # Check objectives
        if len(shard.objectives) < self.min_objectives:
            errors.append(
                f"Insufficient objectives: {len(shard.objectives)}/{self.min_objectives} required"
            )
        elif len(shard.objectives) < 3:
            warnings.append(
                f"Few objectives: {len(shard.objectives)} (recommended: ≥3)"
            )

        # Check examples
        if len(shard.examples) < self.min_examples:
            errors.append(
                f"Insufficient examples: {len(shard.examples)}/{self.min_examples} required"
            )
        elif len(shard.examples) < 3:
            warnings.append(
                f"Few examples: {len(shard.examples)} (recommended: ≥3)"
            )

        # Check misconceptions
        if len(shard.misconceptions) < self.min_misconceptions:
            errors.append(
                f"Insufficient misconceptions: {len(shard.misconceptions)}/{self.min_misconceptions} required"
            )

        # Check assessments
        if len(shard.assessments) < self.min_assessments:
            errors.append(
                f"Insufficient assessments: {len(shard.assessments)}/{self.min_assessments} required"
            )
        elif len(shard.assessments) < 3:
            warnings.append(
                f"Few assessments: {len(shard.assessments)} (recommended: ≥3)"
            )

        return errors, warnings

    def _validate_teaching_description(
        self,
        shard: SubtopicShard
    ) -> tuple[List[str], List[str]]:
        """Validate teaching description"""
        errors = []
        warnings = []

        if not shard.teaching_description:
            errors.append("Missing teaching description")
            return errors, warnings

        desc = shard.teaching_description
        desc_len = len(desc)

        # Check length
        if desc_len < self.MIN_TEACHING_DESC_LENGTH:
            errors.append(
                f"Teaching description too short: {desc_len}/{self.MIN_TEACHING_DESC_LENGTH} chars"
            )
        elif desc_len > self.MAX_TEACHING_DESC_LENGTH:
            warnings.append(
                f"Teaching description too long: {desc_len}/{self.MAX_TEACHING_DESC_LENGTH} chars"
            )

        # Check line count
        lines = [line for line in desc.split('\n') if line.strip()]
        if len(lines) < 3:
            errors.append(
                f"Teaching description too few lines: {len(lines)}/3 minimum"
            )
        elif len(lines) > 6:
            warnings.append(
                f"Teaching description too many lines: {len(lines)}/6 recommended"
            )

        # Check for teaching-related content (heuristic)
        lower_desc = desc.lower()
        has_teaching_words = any(word in lower_desc for word in [
            "teach", "explain", "demonstrate", "show", "help",
            "understand", "learn", "practice", "check", "assess",
            "concept", "example", "misconception"
        ])

        if not has_teaching_words:
            warnings.append("Teaching description lacks teaching-related vocabulary")

        return errors, warnings

    def _validate_content_volume(
        self,
        shard: SubtopicShard
    ) -> tuple[List[str], List[str]]:
        """Validate content volume (page count)"""
        errors = []
        warnings = []

        num_pages = len(shard.source_pages)

        if num_pages < self.MIN_PAGES:
            errors.append(
                f"Too few pages: {num_pages}/{self.MIN_PAGES} minimum"
            )

        if num_pages > self.MAX_PAGES_PER_SUBTOPIC:
            warnings.append(
                f"Many pages for one subtopic: {num_pages} pages "
                f"(may indicate boundary detection issues)"
            )

        # Check page range consistency
        if shard.source_page_start > shard.source_page_end:
            errors.append(
                f"Invalid page range: start={shard.source_page_start}, "
                f"end={shard.source_page_end}"
            )

        expected_pages = set(range(shard.source_page_start, shard.source_page_end + 1))
        actual_pages = set(shard.source_pages)
        missing_pages = expected_pages - actual_pages

        if missing_pages:
            # This is normal if boundary detection skipped pages
            warnings.append(
                f"Non-contiguous pages: missing {len(missing_pages)} pages in range"
            )

        return errors, warnings

    def _validate_assessment_diversity(
        self,
        shard: SubtopicShard
    ) -> tuple[List[str], List[str]]:
        """Validate assessment diversity (difficulty levels)"""
        errors = []
        warnings = []

        if not shard.assessments:
            # Already caught in _validate_facts
            return errors, warnings

        # Count assessments by level
        level_counts = {"basic": 0, "proficient": 0, "advanced": 0}
        for assessment in shard.assessments:
            level_counts[assessment.level] += 1

        # Check for diversity
        if level_counts["basic"] == 0:
            warnings.append("No basic-level assessments")
        if level_counts["proficient"] == 0:
            warnings.append("No proficient-level assessments")
        if level_counts["advanced"] == 0:
            warnings.append("No advanced-level assessments")

        # Check for balance (not too skewed)
        total = len(shard.assessments)
        if total >= 3:
            max_ratio = max(count / total for count in level_counts.values())
            if max_ratio > 0.8:
                warnings.append(
                    f"Assessments heavily skewed to one level "
                    f"(basic={level_counts['basic']}, "
                    f"proficient={level_counts['proficient']}, "
                    f"advanced={level_counts['advanced']})"
                )

        return errors, warnings

    def _calculate_quality_score(
        self,
        shard: SubtopicShard,
        errors: List[str],
        warnings: List[str]
    ) -> float:
        """
        Calculate quality score (0.0-1.0).

        Scoring:
        - Start at 1.0
        - Deduct 0.2 per error
        - Deduct 0.05 per warning
        - Minimum 0.0

        Additional bonuses for exceeding minimums:
        - +0.1 if objectives ≥ 4
        - +0.1 if examples ≥ 5
        - +0.1 if assessments ≥ 5 with diversity
        """
        score = 1.0

        # Deduct for errors and warnings
        score -= len(errors) * 0.2
        score -= len(warnings) * 0.05

        # Bonuses for exceeding minimums
        if len(shard.objectives) >= 4:
            score += 0.1
        if len(shard.examples) >= 5:
            score += 0.1
        if len(shard.assessments) >= 5:
            # Check diversity
            level_counts = {"basic": 0, "proficient": 0, "advanced": 0}
            for assessment in shard.assessments:
                level_counts[assessment.level] += 1
            if all(count > 0 for count in level_counts.values()):
                score += 0.1

        # Clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, score))

        return round(score, 2)

    def update_quality_flags(
        self,
        shard: SubtopicShard,
        validation_result: ValidationResult
    ) -> SubtopicShard:
        """
        Update shard quality flags based on validation result (immutable).

        Args:
            shard: Current subtopic shard
            validation_result: Validation result

        Returns:
            New shard with updated quality flags

        Note:
            This function does NOT mutate the input shard.
            It returns a new shard with updated quality flags.
        """
        from copy import deepcopy
        updated_shard = deepcopy(shard)

        # Update quality flags
        updated_shard.quality_flags = QualityFlags(
            passed_validation=validation_result.is_valid,
            quality_score=validation_result.quality_score,
            validation_errors=validation_result.errors,
            validation_warnings=validation_result.warnings
        )

        # Update status based on validation
        if validation_result.is_valid:
            if updated_shard.status == "stable":
                # Passed quality gates - ready for final or DB sync
                updated_shard.status = "final"
                logger.info(
                    f"Shard {updated_shard.subtopic_key} passed quality gates: "
                    f"stable → final (score={validation_result.quality_score})"
                )
        else:
            # Failed quality gates - needs review
            updated_shard.status = "needs_review"
            logger.warning(
                f"Shard {updated_shard.subtopic_key} failed quality gates: "
                f"marked as needs_review ({len(validation_result.errors)} errors)"
            )

        updated_shard.version += 1

        return updated_shard

    def get_validation_summary(self, shard: SubtopicShard) -> Dict[str, Any]:
        """
        Get human-readable validation summary.

        Args:
            shard: Subtopic shard

        Returns:
            Dict with validation summary (for UI display)
        """
        validation_result = self.validate(shard)

        return {
            "subtopic_key": shard.subtopic_key,
            "subtopic_title": shard.subtopic_title,
            "is_valid": validation_result.is_valid,
            "quality_score": validation_result.quality_score,
            "status": shard.status,
            "errors": validation_result.errors,
            "warnings": validation_result.warnings,
            "stats": {
                "objectives": len(shard.objectives),
                "examples": len(shard.examples),
                "misconceptions": len(shard.misconceptions),
                "assessments": len(shard.assessments),
                "pages": len(shard.source_pages),
                "page_range": f"{shard.source_page_start}-{shard.source_page_end}",
                "teaching_desc_length": len(shard.teaching_description or "")
            }
        }
