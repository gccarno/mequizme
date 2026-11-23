"""Where AI answers come from. Optional: with no provider, AI features are hidden.

- `claude-code`: runs your installed Claude Code (`claude -p`) headless, signed in with your
  Claude account. No API key needed; usage counts against your plan. Meant for personal use
  on your own machine.
- `api`: the Anthropic API, when ANTHROPIC_API_KEY is set (`uv sync --extra api`).

MEQUIZME_LLM picks one: auto (default: api if a key is set, else claude-code if installed), claude-code,
api, off, or fake (canned answers for tests). MEQUIZME_LLM_MODEL overrides the model.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Protocol

DEFAULT_API_MODEL = "claude-sonnet-5-5"
DEFAULT_CLI_MODEL = "sonnet"  # Claude Code alias for the latest Sonnet
TIMEOUT_SEC = 240


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str
    model: str

    def json(self, system: str, prompt: str, schema: dict) -> dict:
        """Answer as an object matching `schema`."""

    def text(self, system: str, prompt: str) -> str:
        """Answer as markdown."""


class ClaudeCode:
    """`claude -p` with tools off, settings/MCP/plugins ignored and nothing saved, run from an empty
    folder so it only sees the prompt."""

    name = "claude-code"

    def __init__(self, exe: str, model: str | None = None):
        self.exe = exe
        self.model = model or DEFAULT_CLI_MODEL
        self._cwd = tempfile.mkdtemp(prefix="mequizme-llm-")

    def _run(self, system: str, prompt: str, schema: dict | None) -> dict:
        cmd = [self.exe, "-p", "--restricted", "--strict-mcp-config", "--tools", "",
               "--no-session-persistence", "--output-format", "json",
               "--model", self.model, "--system-prompt", system]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  timeout=TIMEOUT_SEC, cwd=self._cwd)
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"Claude Code didn't answer within {TIMEOUT_SEC} seconds") from e
        except OSError as e:
            raise LLMError(f"couldn't start Claude Code: {e}") from e
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            detail = (proc.stderr or proc.stdout).strip()[-500:]
            raise LLMError(f"Claude Code failed (exit {proc.returncode}): {detail}") from None
        if out.get("is_error") or out.get("subtype") != "success":
            raise LLMError(f"Claude Code failed: {str(out.get('result') or out.get('subtype'))[:500]}")
        return out

    def json(self, system: str, prompt: str, schema: dict) -> dict:
        out = self._run(system, prompt, schema)
        data = out.get("structured_output")
        if not isinstance(data, dict):
            try:
                data = json.loads(out.get("result") or "")
            except json.JSONDecodeError:
                raise LLMError("Claude Code returned no structured answer") from None
        return data

    def text(self, system: str, prompt: str) -> str:
        return str(self._run(system, prompt, None).get("result") or "").strip()


class AnthropicAPI:
    name = "api"

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as e:  # optional dependency
            raise LLMError("ANTHROPIC_API_KEY is set but the anthropic package isn't installed "
                           "(uv sync --extra api)") from e
        self._client = anthropic.Anthropic()
        self.model = model or DEFAULT_API_MODEL

    def json(self, system: str, prompt: str, schema: dict) -> dict:
        # A forced tool call is the portable way to get schema-shaped output.
        msg = self._client.messages.create(
            model=self.model, max_tokens=8000, system=system,
            tools=[{"name": "answer", "description": "Give the answer.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": "answer"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in msg.content:
            if block.type == "tool_use":
                return dict(block.input)
        raise LLMError("the API returned no structured answer")

    def text(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model, max_tokens=4000, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()


def author(llm: LLM) -> str:
    """How a draft records who wrote it."""
    via = {"claude-code": "Claude Code", "api": "the Anthropic API"}.get(llm.name, "canned test answers")
    return f"{llm.model} via {via}"


def from_env() -> tuple[LLM | None, str]:
    """(provider or None, reason shown when there is none)."""
    choice = os.environ.get("MEQUIZME_LLM", "auto").lower()
    model = os.environ.get("MEQUIZME_LLM_MODEL") or None
    if choice == "off":
        return None, "AI features are turned off (MEQUIZME_LLM=off)."
    if choice == "fake":
        from app.llm.fake import FakeLLM
        return FakeLLM(), ""
    if choice in ("api", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicAPI(model), ""
        except LLMError as e:
            if choice == "api":
                return None, str(e)
    if choice in ("claude-code", "auto"):
        exe = os.environ.get("MEQUIZME_CLAUDE") or shutil.which("claude")
        if exe:
            return ClaudeCode(exe, model), ""
        if choice == "claude-code":
            return None, "Claude Code isn't installed or isn't on PATH."
    if choice == "api":
        return None, "Set ANTHROPIC_API_KEY to use the API."
    return None, "Install Claude Code and sign in, or set ANTHROPIC_API_KEY, to turn on AI features."
