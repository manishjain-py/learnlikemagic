"""
Claude Code CLI Adapter

Calls the Claude Code CLI (`claude`) as a subprocess to use it as an LLM
backend. Designed for local/admin workflows (book ingestion, etc.) where
Claude Code is running on the same machine.

Returns the standard {output_text, reasoning, parsed} dict used by LLMService.
"""

import json
import logging
import re
import subprocess
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ClaudeCodeAdapter:
    """Adapter that calls the Claude Code CLI as an LLM backend."""

    _cli_available: Optional[bool] = None  # class-level cache

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def _ensure_cli_available(self):
        """Verify Claude Code CLI is installed (cached after first check)."""
        if ClaudeCodeAdapter._cli_available is True:
            return
        try:
            subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ClaudeCodeAdapter._cli_available = True
        except FileNotFoundError:
            ClaudeCodeAdapter._cli_available = False
            raise ClaudeCodeError(
                "Claude Code CLI ('claude') not found. "
                "Ensure Claude Code is installed and available in PATH."
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCodeError("Claude Code CLI timed out on version check.")

    def call_sync(
        self,
        prompt: str,
        reasoning_effort: str = "none",
        json_mode: bool = True,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> Dict[str, Any]:
        """Call Claude Code CLI and return standard output dict."""
        self._ensure_cli_available()

        full_prompt = self._build_prompt(prompt, json_mode, json_schema, schema_name)

        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "starting",
            "model": "claude-code",
            "params": {
                "json_mode": json_mode,
                "has_schema": json_schema is not None,
                "prompt_length": len(full_prompt),
            }
        }))
        start_time = time.time()

        # Call Claude Code CLI via subprocess
        # Automation flags:
        #   --dangerously-skip-permissions  — no interactive permission prompts
        #   --no-session-persistence        — don't save sessions to disk
        #   --max-turns 1                   — single turn, no agentic loops
        cmd = [
            "claude",
            "-p", full_prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--max-turns", "1",
        ]

        # Map reasoning_effort to Claude CLI --effort flag
        if reasoning_effort and reasoning_effort != "none":
            # CLI accepts: low, medium, high, max
            # LLMService passes: none, low, medium, high, xhigh
            effort_map = {"low": "low", "medium": "medium", "high": "high", "xhigh": "max"}
            cli_effort = effort_map.get(reasoning_effort, reasoning_effort)
            cmd.extend(["--effort", cli_effort])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCodeError(
                f"Claude Code CLI timed out after {self.timeout}s"
            )

        duration_ms = int((time.time() - start_time) * 1000)

        if result.returncode != 0:
            logger.error(
                f"Claude Code CLI failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )
            raise ClaudeCodeError(
                f"Claude Code CLI exited with code {result.returncode}: "
                f"{result.stderr[:500]}"
            )

        # Parse the CLI JSON envelope
        try:
            cli_output = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ClaudeCodeError(
                f"Failed to parse Claude Code output as JSON: "
                f"{result.stdout[:500]}"
            )

        if cli_output.get("is_error"):
            raise ClaudeCodeError(
                f"Claude Code returned error: "
                f"{cli_output.get('result', 'unknown error')}"
            )

        response_text = cli_output.get("result", "")

        # Parse the LLM response as JSON if requested
        parsed = None
        if json_mode or json_schema:
            parsed = self._extract_json(response_text)

        # If we got parsed JSON, use its serialization as output_text
        # so downstream consumers see clean JSON
        output_text = json.dumps(parsed) if parsed else response_text

        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "complete",
            "model": "claude-code",
            "output": {"response_length": len(response_text)},
            "duration_ms": duration_ms,
            "cost_usd": cli_output.get("total_cost_usd"),
            "num_turns": cli_output.get("num_turns"),
        }))

        return {
            "output_text": output_text,
            "reasoning": None,
            "parsed": parsed,
        }

    def _build_prompt(
        self,
        prompt: str,
        json_mode: bool,
        json_schema: Optional[Dict[str, Any]],
        schema_name: str,
    ) -> str:
        """Append JSON output instructions to the prompt when needed."""
        if json_schema:
            schema_str = json.dumps(json_schema, indent=2)
            return (
                f"{prompt}\n\n"
                f"You MUST respond with valid JSON only — no markdown fences, "
                f"no explanation outside the JSON.\n"
                f"Your response must conform to this JSON schema:\n"
                f"{schema_str}"
            )
        if json_mode:
            return (
                f"{prompt}\n\n"
                f"You MUST respond with valid JSON only. "
                f"No markdown fences, no explanation outside the JSON."
            )
        return prompt

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from response text, handling markdown fences and wrapping."""
        # 1. Direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # 2. Extract from markdown code fence
        match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Find first balanced {...} block
        start = text.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

        return None


class ClaudeCodeError(Exception):
    """Error from Claude Code CLI operations."""
    pass
