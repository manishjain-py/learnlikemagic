"""
Topic Name Refinement Service

Responsibility: Refine topic and subtopic names after complete guidelines are generated.

Uses LLM to analyze complete guidelines and propose better, more accurate names
based on the actual content rather than initial quick assessments.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any
from openai import OpenAI

from ..models.guideline_models import SubtopicShard, TopicNameRefinement

logger = logging.getLogger(__name__)


class TopicNameRefinementService:
    """
    Service to refine topic/subtopic names after guidelines are complete.

    Called during finalize_book() to improve names based on full guideline content.
    """

    def __init__(self, openai_client: OpenAI):
        self.client = openai_client
        self.model = "gpt-4o-mini"
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the refinement prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "topic_name_refinement.txt"
        return prompt_path.read_text()

    def refine_names(
        self,
        shard: SubtopicShard,
        book_metadata: Dict[str, Any]
    ) -> TopicNameRefinement:
        """
        Refine topic and subtopic names based on complete guidelines.

        Args:
            shard: Complete subtopic shard with guidelines
            book_metadata: Book context (grade, subject, board, country)

        Returns:
            TopicNameRefinement with new names and reasoning
        """
        try:
            # Build the prompt
            prompt = self.prompt_template.format(
                grade=book_metadata.get("grade", "Unknown"),
                subject=book_metadata.get("subject", "Unknown"),
                board=book_metadata.get("board", "Unknown"),
                country=book_metadata.get("country", "India"),
                current_topic_title=shard.topic_title,
                current_topic_key=shard.topic_key,
                current_subtopic_title=shard.subtopic_title,
                current_subtopic_key=shard.subtopic_key,
                guidelines=shard.guidelines[:2000],  # Limit to 2000 chars for token management
                page_start=shard.source_page_start,
                page_end=shard.source_page_end
            )

            import time
            import json
            start_time = time.time()

            logger.info(json.dumps({
                "step": "TOPIC_REFINEMENT",
                "status": "starting",
                "input": {
                    "topic_key": shard.topic_key,
                    "subtopic_key": shard.subtopic_key,
                    "guidelines_len": len(shard.guidelines)
                }
            }))

            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                max_tokens=300,
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            # Parse response
            raw_response = response.choices[0].message.content
            refinement_data = json.loads(raw_response)

            refinement = TopicNameRefinement(**refinement_data)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "TOPIC_REFINEMENT",
                "status": "complete",
                "output": {
                    "old_topic": shard.topic_title,
                    "new_topic": refinement.topic_title,
                    "old_subtopic": shard.subtopic_title,
                    "new_subtopic": refinement.subtopic_title,
                    "changed": (shard.topic_title != refinement.topic_title or 
                               shard.subtopic_title != refinement.subtopic_title)
                },
                "duration_ms": duration_ms
            }))

            return refinement

        except Exception as e:
            logger.error(f"Failed to refine names for {shard.topic_key}/{shard.subtopic_key}: {str(e)}")
            # Return original names on error
            return TopicNameRefinement(
                topic_title=shard.topic_title,
                topic_key=shard.topic_key,
                subtopic_title=shard.subtopic_title,
                subtopic_key=shard.subtopic_key,
                reasoning=f"Error during refinement: {str(e)}"
            )
