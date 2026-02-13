"""Generate PDF evaluation report from comparison data."""
import json
from pathlib import Path
from fpdf import FPDF

RUNS_DIR = Path("/Users/manishjain/repos/learnlikemagic/llm-backend/evaluation/runs")
COMPARISON_DIR = RUNS_DIR / "comparison_20260213_134833"
OUTPUT_PATH = Path("/Users/manishjain/repos/learnlikemagic/tmp/eval_report_opus46.pdf")

# Run directories in order
RUN_DIRS = {
    "ace": RUNS_DIR / "run_20260213_130136_ace",
    "average_student": RUNS_DIR / "run_20260213_130538_average_student",
    "confused_confident": RUNS_DIR / "run_20260213_131152_confused_confident",
    "distractor": RUNS_DIR / "run_20260213_132158_distractor",
    "quiet_one": RUNS_DIR / "run_20260213_133005_quiet_one",
    "struggler": RUNS_DIR / "run_20260213_133817_struggler",
}


class EvalReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "LearnLikeMagic - Tutor Evaluation Report", align="R")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title, size=16):
        self.set_font("Helvetica", "B", size)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, title)
        self.ln(12)

    def sub_title(self, title, size=12):
        self.set_font("Helvetica", "B", size)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, title)
        self.ln(10)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)
        self.ln(3)

    def bold_text(self, label, value):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(40, 40, 40)
        self.cell(self.get_string_width(label) + 2, 6, label)
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, value)
        self.ln(6)

    def score_bar(self, label, score, max_score=10, bar_width=80):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        label_w = 55
        self.cell(label_w, 6, label)

        # Background bar
        x = self.get_x()
        y = self.get_y()
        self.set_fill_color(230, 230, 230)
        self.rect(x, y + 1, bar_width, 4, "F")

        # Score bar
        fill_w = (score / max_score) * bar_width
        if score >= 8:
            self.set_fill_color(76, 175, 80)  # green
        elif score >= 6:
            self.set_fill_color(255, 193, 7)  # amber
        else:
            self.set_fill_color(244, 67, 54)  # red
        self.rect(x, y + 1, fill_w, 4, "F")

        self.set_x(x + bar_width + 5)
        self.set_font("Helvetica", "B", 10)
        self.cell(15, 6, f"{score}/10")
        self.ln(7)

    def add_table_row(self, cells, widths, bold=False, fill=False):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, 9)
        if fill:
            self.set_fill_color(240, 240, 240)
        for i, (cell, w) in enumerate(zip(cells, widths)):
            self.cell(w, 7, str(cell), border=1, fill=fill, align="C" if i > 0 else "L")
        self.ln(7)


def load_review(run_dir):
    review_path = run_dir / "review.md"
    return review_path.read_text() if review_path.exists() else ""


def parse_review_sections(text):
    """Extract summary and detailed analysis from review markdown."""
    sections = {}
    current = None
    lines = text.split("\n")
    for line in lines:
        if line.startswith("### Summary") or line.startswith("## Summary"):
            current = "summary"
            sections[current] = []
        elif line.startswith("### Detailed Analysis") or line.startswith("## Detailed Analysis"):
            current = "analysis"
            sections[current] = []
        elif line.startswith("### Top Problems") or line.startswith("## Top Problems"):
            current = "problems"
            sections[current] = []
        elif line.startswith("### ") or line.startswith("## Scores"):
            if current == "summary" or current == "analysis" or current == "problems":
                current = None
        elif current:
            sections.setdefault(current, []).append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


def extract_problems(text):
    """Extract problem titles and severities from the problems section."""
    problems = []
    lines = text.split("\n")
    for line in lines:
        if line.startswith("**") and "[" in line and "]" in line:
            # e.g. **1. Difficulty ceiling never reached [MAJOR]**
            title = line.strip("*").strip()
            # Extract severity
            severity = ""
            for sev in ["CRITICAL", "MAJOR", "MINOR"]:
                if sev in title:
                    severity = sev
                    title = title.replace(f"[{sev}]", "").strip()
                    break
            # Remove numbering
            if title and title[0].isdigit():
                title = title.split(".", 1)[-1].strip()
            problems.append((title, severity))
    return problems


def main():
    pdf = EvalReport()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Load comparison data
    comparison_json = COMPARISON_DIR / "comparison.json"
    with open(comparison_json) as f:
        comparison = json.load(f)

    results = comparison["results"]

    # === COVER PAGE ===
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 15, "Tutor Evaluation Report", align="C")
    pdf.ln(18)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "Claude Opus 4.6 + P0 Prompt Fixes", align="C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Topic: 4-Digit Place Value (Grade 3-5)", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "Date: 2026-02-13", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "6 Student Personas | 5 Evaluation Dimensions", align="C")
    pdf.ln(25)

    # Overall average
    avg_all = sum(r["avg_score"] for r in results) / len(results)
    pdf.set_font("Helvetica", "B", 36)
    if avg_all >= 8:
        pdf.set_text_color(76, 175, 80)
    elif avg_all >= 7:
        pdf.set_text_color(255, 152, 0)
    else:
        pdf.set_text_color(244, 67, 54)
    pdf.cell(0, 20, f"{avg_all:.1f}/10", align="C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "Overall Average Score", align="C")

    # === OVERVIEW PAGE ===
    pdf.add_page()
    pdf.section_title("Overview")

    pdf.bold_text("Model: ", "Claude Opus 4.6 (anthropic)")
    pdf.bold_text("Evaluator: ", "Claude Opus 4.6 (claude-opus-4-6)")
    pdf.bold_text("Topic: ", "4-Digit Place Value")
    pdf.bold_text("Overall Average: ", f"{avg_all:.1f}/10")
    pdf.ln(5)

    # Summary table
    pdf.sub_title("Scores by Persona")
    widths = [35, 25, 20, 25, 25, 25, 20, 25]
    headers = ["Persona", "Name", "Corr%", "Avg", "Respond.", "Explain.", "Pacing", "Auth."]
    pdf.add_table_row(headers, widths, bold=True, fill=True)

    dimensions = ["responsiveness", "explanation_quality", "pacing", "authenticity"]
    for r in results:
        p = r["persona"]
        s = r["scores"]
        correct_pct = f"{int(p.get('correct_answer_probability', 0.6) * 100)}%"
        row = [
            p["persona_id"],
            p["name"],
            correct_pct,
            f"{r['avg_score']:.1f}",
            str(s.get("responsiveness", "-")),
            str(s.get("explanation_quality", "-")),
            str(s.get("pacing", "-")),
            str(s.get("authenticity", "-")),
        ]
        pdf.add_table_row(row, widths)

    pdf.ln(8)

    # Dimension averages
    pdf.sub_title("Average Score by Dimension")
    all_dims = ["responsiveness", "explanation_quality", "emotional_attunement", "pacing", "authenticity"]
    dim_labels = {
        "responsiveness": "Responsiveness",
        "explanation_quality": "Explanation Quality",
        "emotional_attunement": "Emotional Attunement",
        "pacing": "Pacing",
        "authenticity": "Authenticity",
    }
    for dim in all_dims:
        vals = [r["scores"].get(dim, 0) for r in results if r["scores"]]
        avg = sum(vals) / len(vals) if vals else 0
        pdf.score_bar(dim_labels[dim], avg)

    # === PER-PERSONA PAGES ===
    for persona_id, run_dir in RUN_DIRS.items():
        review_text = load_review(run_dir)
        sections = parse_review_sections(review_text)
        result = next((r for r in results if r["persona"]["persona_id"] == persona_id), None)
        if not result:
            continue

        persona = result["persona"]
        scores = result["scores"]

        pdf.add_page()
        pdf.section_title(f"{persona['name']} ({persona_id})")

        pdf.bold_text("Description: ", persona.get("description", ""))
        pdf.bold_text("Correct Answer Probability: ", f"{int(persona.get('correct_answer_probability', 0.6) * 100)}%")
        pdf.bold_text("Messages: ", str(result["message_count"]))
        pdf.bold_text("Average Score: ", f"{result['avg_score']:.1f}/10")
        pdf.ln(5)

        # Score bars
        pdf.sub_title("Scores")
        for dim in all_dims:
            score = scores.get(dim, 0)
            pdf.score_bar(dim_labels[dim], score)
        pdf.ln(5)

        # Summary
        if "summary" in sections:
            pdf.sub_title("Summary")
            summary = sections["summary"].replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2014", " -- ").replace("\u2013", " - ").replace("\u2026", "...")
            pdf.body_text(summary)

        # Top problems
        if "problems" in sections:
            problems = extract_problems(sections["problems"])
            if problems:
                pdf.sub_title("Top Problems")
                for title, severity in problems[:5]:
                    clean_title = title.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2014", " -- ").replace("\u2013", " - ")
                    sev_label = f"[{severity}] " if severity else ""
                    pdf.set_font("Helvetica", "", 9)
                    self_color = (244, 67, 54) if severity == "CRITICAL" else (255, 152, 0) if severity == "MAJOR" else (100, 100, 100)
                    pdf.set_text_color(*self_color)
                    bullet = f"  {sev_label}{clean_title}"
                    pdf.multi_cell(0, 5, bullet)
                    pdf.ln(2)
                pdf.set_text_color(40, 40, 40)

    # === KEY FINDINGS PAGE ===
    pdf.add_page()
    pdf.section_title("Key Findings & Patterns")

    pdf.sub_title("Strengths")
    strengths = [
        "Misconception detection: Consistently catches confidently wrong answers (Dev 9/10, Kabir 9/10 responsiveness)",
        "Emotional warmth: Never shames students for errors, celebrates genuine breakthroughs proportionally",
        "Creative analogies: Varies explanations across Number City, cricket, pizza, sports, lunchboxes",
        "Off-topic handling: Acknowledges tangents warmly, redirects efficiently (Kabir scored 9/10 attunement)",
    ]
    for s in strengths:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(76, 175, 80)
        pdf.cell(5, 6, "+")
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 5.5, f" {s}")
        pdf.ln(2)

    pdf.ln(5)
    pdf.sub_title("Recurring Issues")
    issues = [
        "Pacing (weakest dimension, 5-8/10): Overly dense opening explanation flagged as MAJOR in ALL 6 personas",
        "Response length mismatch: Tutor writes long responses regardless of student's communication style (critical for Meera)",
        "Repetitive correction: When same error appears twice, tutor uses similar approach rather than switching modality",
        "Difficulty ceiling for ace: Never challenges Arjun despite 5 requests for harder material",
        "Premature progression for struggler: Moves to harder operations before mastery of basics (Priya)",
    ]
    for iss in issues:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(244, 67, 54)
        pdf.cell(5, 6, "-")
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 5.5, f" {iss}")
        pdf.ln(2)

    pdf.ln(5)
    pdf.sub_title("Comparison: Haiku 4.5 vs Opus 4.6")
    pdf.body_text("Previous Haiku 4.5 evaluation (3 personas): 6.3/10 average")
    pdf.body_text(f"Current Opus 4.6 evaluation (6 personas): {avg_all:.1f}/10 average")
    pdf.body_text(f"Improvement: +{avg_all - 6.3:.1f} points (+{((avg_all - 6.3) / 6.3 * 100):.0f}%)")
    pdf.ln(3)
    pdf.body_text("Key improvements from model upgrade + prompt fixes:")
    improvements = [
        "Session closings: No more robotic/canned endings (was 6/6 personas in Haiku)",
        "System note leaks: No leaked internal language detected (was 2/6 in Haiku)",
        "Answer verification: No wrong-answer validation observed (was 1/6 in Haiku)",
    ]
    for imp in improvements:
        pdf.body_text(f"  * {imp}")

    # Save
    pdf.output(str(OUTPUT_PATH))
    print(f"PDF saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
