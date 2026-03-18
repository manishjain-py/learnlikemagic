"""
Report Generator for Explanation Quality Evaluation

Saves structured artifacts for each evaluation run:
config, cards, evaluation scores, and human-readable review.
"""

import json
from datetime import datetime
from pathlib import Path


class ExplanationReportGenerator:
    """Creates and saves all run artifacts."""

    def __init__(self, run_dir: Path, config, started_at: str = ""):
        self.run_dir = run_dir
        self.config = config
        self.started_at = started_at
        run_dir.mkdir(parents=True, exist_ok=True)

    def save_config(self):
        """Save config.json."""
        data = self.config.to_dict()
        data["started_at"] = self.started_at
        (self.run_dir / "config.json").write_text(json.dumps(data, indent=2))

    def save_cards(self, variant_key: str, variant_label: str, cards: list[dict]):
        """Save cards for a variant as JSON and markdown."""
        # JSON
        (self.run_dir / f"cards_{variant_key}.json").write_text(
            json.dumps(cards, indent=2)
        )

        # Markdown
        lines = [f"# Explanation Cards — Variant {variant_key}: {variant_label}\n"]
        for card in cards:
            idx = card.get("card_idx", "?")
            card_type = card.get("card_type", "?")
            title = card.get("title", "Untitled")
            content = card.get("content", "")
            visual = card.get("visual", "")

            lines.append(f"## Card {idx} [{card_type}]: {title}\n")
            lines.append(f"{content}\n")
            if visual:
                lines.append(f"**Visual:**\n```\n{visual}\n```\n")
        (self.run_dir / f"cards_{variant_key}.md").write_text("\n".join(lines))

    def save_evaluation(self, variant_key: str, evaluation: dict):
        """Save evaluation JSON for a variant."""
        scores = evaluation.get("scores", {})
        avg = sum(scores.values()) / len(scores) if scores else 0
        evaluation["avg_score"] = round(avg, 4)
        evaluation["evaluated_at"] = datetime.now().isoformat()
        (self.run_dir / f"evaluation_{variant_key}.json").write_text(
            json.dumps(evaluation, indent=2)
        )

    def save_review(self, all_evaluations: dict, topic_title: str):
        """Save a combined human-readable review markdown."""
        lines = [f"# Explanation Quality Review: {topic_title}\n"]
        lines.append(f"**Generated at:** {self.started_at}\n")

        for variant_key, eval_data in sorted(all_evaluations.items()):
            scores = eval_data.get("scores", {})
            avg = eval_data.get("avg_score", 0)
            summary = eval_data.get("summary", "")
            dim_analysis = eval_data.get("dimension_analysis", {})
            problems = eval_data.get("problems", [])

            lines.append(f"\n## Variant {variant_key} — Score: {avg:.1f}/10\n")

            # Scores table
            lines.append("| Dimension | Score |")
            lines.append("|-----------|-------|")
            for dim, score in scores.items():
                dim_label = dim.replace("_", " ").title()
                lines.append(f"| {dim_label} | {score}/10 |")

            # Summary
            lines.append(f"\n**Summary:** {summary}\n")

            # Dimension analysis
            if dim_analysis:
                lines.append("### Dimension Analysis\n")
                for dim, analysis in dim_analysis.items():
                    dim_label = dim.replace("_", " ").title()
                    lines.append(f"**{dim_label}:** {analysis}\n")

            # Problems
            if problems:
                lines.append("### Problems Found\n")
                for p in problems:
                    sev = p.get("severity", "?").upper()
                    title = p.get("title", "")
                    desc = p.get("description", "")
                    root = p.get("root_cause", "?")
                    cards = p.get("cards", [])
                    lines.append(f"- **[{sev}]** {title} (cards: {cards}, root: {root})")
                    lines.append(f"  {desc}")
                lines.append("")

        (self.run_dir / "review.md").write_text("\n".join(lines))
