"""
Claude Code CLI Adapter

Calls the Claude Code CLI (`claude`) as a subprocess to use it as an LLM
backend. Designed for local/admin workflows (book ingestion, etc.) where
Claude Code is running on the same machine.

Returns the standard {output_text, reasoning, parsed} dict used by LLMService.
"""

import json
import logging
import os
import re
import subprocess
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ClaudeCodeAdapter:
    """Adapter that calls the Claude Code CLI as an LLM backend."""

    _cli_available: Optional[bool] = None  # class-level cache

    # Retryable error patterns (credit checks, rate limits)
    _RETRYABLE_PATTERNS = [
        "credit balance",
        "rate limit",
        "too many requests",
        "overloaded",
    ]

    def __init__(self, timeout: int = 300, max_retries: int = 3, retry_base_delay: float = 10.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

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

    def _is_retryable_error(self, error_msg: str) -> bool:
        """Check if an error message indicates a transient/retryable condition."""
        lower = error_msg.lower()
        return any(pat in lower for pat in self._RETRYABLE_PATTERNS)

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

        # Build command — prompt goes via stdin, NOT as a CLI argument.
        # Stdin is more robust for large/complex prompts with special chars.
        cmd = [
            "claude",
            "-p",
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--max-turns", "1",
            "--model", "claude-opus-4-6",
        ]

        # CRITICAL: Strip ANTHROPIC_API_KEY from the subprocess environment.
        # When load_dotenv() runs (common in import chains), it sets
        # ANTHROPIC_API_KEY. The Claude Code CLI detects this and
        # authenticates with Anthropic's API directly (instead of the
        # user's Claude subscription), causing "Credit balance is too low"
        # rejections. We want Claude Code to use its own auth.
        clean_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        # Map reasoning_effort to Claude CLI --effort flag (default: high)
        effective_effort = reasoning_effort if reasoning_effort and reasoning_effort != "none" else "high"
        effort_map = {"low": "low", "medium": "medium", "high": "high", "xhigh": "max"}
        cli_effort = effort_map.get(effective_effort, effective_effort)
        cmd.extend(["--effort", cli_effort])

        logger.info(json.dumps({
            "step": "LLM_CALL",
            "status": "cli_command",
            "cmd": " ".join(cmd),
            "timeout": self.timeout,
            "prompt_length": len(full_prompt),
        }))

        # Retry loop — handles transient credit-balance / rate-limit errors
        last_error = None
        for attempt in range(self.max_retries):
            start_time = time.time()
            try:
                result = subprocess.run(
                    cmd,
                    input=full_prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=clean_env,
                )
            except subprocess.TimeoutExpired:
                raise ClaudeCodeError(
                    f"Claude Code CLI timed out after {self.timeout}s"
                )

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode != 0:
                error_msg = result.stderr[:500]
                logger.error(
                    f"Claude Code CLI failed (exit {result.returncode}): {error_msg}"
                )
                if self._is_retryable_error(error_msg) and attempt < self.max_retries - 1:
                    wait = self.retry_base_delay * (2 ** attempt)
                    logger.warning(f"Retryable CLI error, waiting {wait}s (attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(wait)
                    continue
                raise ClaudeCodeError(
                    f"Claude Code CLI exited with code {result.returncode}: {error_msg}"
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
                error_msg = cli_output.get("result", "unknown error")
                if self._is_retryable_error(error_msg) and attempt < self.max_retries - 1:
                    wait = self.retry_base_delay * (2 ** attempt)
                    logger.warning(json.dumps({
                        "step": "LLM_CALL",
                        "status": "retrying",
                        "model": "claude-code",
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries,
                        "wait_seconds": wait,
                        "error": error_msg,
                        "duration_api_ms": cli_output.get("duration_api_ms"),
                    }))
                    time.sleep(wait)
                    last_error = error_msg
                    continue
                raise ClaudeCodeError(f"Claude Code returned error: {error_msg}")

            # Success — parse response
            response_text = cli_output.get("result", "")

            parsed = None
            if json_mode or json_schema:
                parsed = self._extract_json(response_text)

            output_text = json.dumps(parsed) if parsed else response_text

            logger.info(json.dumps({
                "step": "LLM_CALL",
                "status": "complete",
                "model": "claude-code",
                "output": {"response_length": len(response_text)},
                "duration_ms": duration_ms,
                "cost_usd": cli_output.get("total_cost_usd"),
                "num_turns": cli_output.get("num_turns"),
                "attempt": attempt + 1,
            }))

            return {
                "output_text": output_text,
                "reasoning": None,
                "parsed": parsed,
            }

        # All retries exhausted
        raise ClaudeCodeError(
            f"Claude Code CLI failed after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        )

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
