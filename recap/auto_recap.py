#!/usr/bin/env python3
"""Phase 3 of issue #1 — Stop hook that silently writes today's session
block to the vault's daily note via headless Claude.

Opt-in: requires KG_AUTO_RECAP=1 in the environment. When unset (or any
other value), the hook is a fast no-op. See
docs/specs/2026-05-20-auto-recap-design.md for the design rationale.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from recap_common import (  # noqa: E402
    DEBOUNCE_SECONDS,
    DEFAULT_TIMEOUT,
    _resolve_under_vault,
    debounce_marker,
    emit_continue,
    log,
    plugin_root,
    read_text,
    session_log_path,
    write_cursor,
)
from recap_context import RecapContext  # noqa: E402
from session_aggregator import SessionAggregator  # noqa: E402
from daily_note_resolver import DailyNoteResolver  # noqa: E402
from daily_note import DailyNote, extract_block, extract_topic  # noqa: E402


def load_vault_context(vault: pathlib.Path) -> tuple[str, str]:
    """Return (readme_excerpt, daily_template_excerpt).

    The daily-note folder and filename are not pre-resolved here — they are
    discovered by Claude from the README inside the same prompt that composes
    the recap block (see parse_discovery / main).

    - KG_DAILY_TEMPLATE: optional env var. Relative to $KG_VAULT or absolute.
      When unset, the template excerpt is empty and the prompt instructs
      Claude to fall back to the README's description of the daily-note
      structure.
    """
    readme_parts: list[str] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        if candidate.is_file():
            readme_parts.append(f"--- {candidate} ---\n{read_text(candidate)}")
    readme_excerpt = "\n\n".join(readme_parts) or "(no README found)"

    template_path = _resolve_under_vault(vault, os.environ.get("KG_DAILY_TEMPLATE"))
    template_excerpt = (
        read_text(template_path) if template_path and template_path.is_file()
        else ""
    )

    return readme_excerpt, template_excerpt


def compose_prompt(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for k, v in substitutions.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def call_claude(prompt: str, timeout: int) -> str | None:
    cmd_name = os.environ.get("KG_AUTO_RECAP_CLAUDE_CMD", "claude")
    cmd_path = shutil.which(cmd_name) or cmd_name
    try:
        proc = subprocess.run(
            [cmd_path, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"claude invocation failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"claude exit={proc.returncode} stderr={proc.stderr[:300]!r}")
        return None
    return proc.stdout


class AutoRecap:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def run(self) -> None:
        ctx = self._ctx

        # debounce
        marker = debounce_marker(ctx.sid8)
        try:
            if marker.exists():
                age = time.time() - marker.stat().st_mtime
                if age < DEBOUNCE_SECONDS:
                    return
        except OSError:
            pass

        # session log must exist and be non-empty
        log_path = session_log_path(ctx.sid8)
        if not log_path.is_file() or log_path.stat().st_size == 0:
            return

        agg = SessionAggregator(ctx).aggregate()
        if agg is None:
            return
        marker_key = f"{ctx.sid8}-{agg.start_hhmm.replace(':', '')}"

        resolver = DailyNoteResolver(ctx)
        pre = resolver.pre_resolve()

        readme, template = load_vault_context(ctx.vault)
        if pre is not None:
            daily_path, insert_before = pre
            try:
                existing_daily = (
                    daily_path.read_text(encoding="utf-8")
                    if daily_path.is_file()
                    else "(file does not exist yet)"
                )
            except OSError:
                existing_daily = "(file does not exist yet)"
            prompt_template_path = plugin_root() / "recap" / "prompts" / "auto_recap_compose_prompt.md"
        else:
            daily_path = None
            insert_before = ""
            existing_daily = "(unknown until folder is discovered)"
            prompt_template_path = plugin_root() / "recap" / "prompts" / "auto_recap_prompt.md"

        if not prompt_template_path.is_file():
            log(f"prompt template missing: {prompt_template_path}")
            return
        prompt_template = prompt_template_path.read_text(encoding="utf-8")

        prompt = compose_prompt(
            prompt_template,
            {
                "SID8": ctx.sid8,
                "MARKER_KEY": marker_key,
                "START_HHMM": agg.start_hhmm,
                "TODAY": ctx.today_str,
                "VAULT_README": readme,
                "DAILY_TEMPLATE": template,
                "EXISTING_DAILY": existing_daily,
                "AGGREGATOR_OUTPUT": agg.text,
            },
        )

        timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
        out = call_claude(prompt, timeout=timeout)
        if not out:
            return

        if pre is None:
            resolved = resolver.resolve_from_discovery(out)
            if resolved is None:
                return
            daily_path, insert_before = resolved

        block = extract_block(out, marker_key)
        if not block:
            log("claude output missing recap markers")
            return

        topic = extract_topic(block)
        if topic is None:
            log(f"could not extract topic from block for {marker_key}; using fallback subject")

        note = DailyNote(ctx.vault, daily_path)
        if not note.apply_block(marker_key, block, insert_before):
            return

        if not note.has_repo:
            log("vault is not in a git repo — skipping commit; cursor still updated")
            write_cursor(ctx.sid8, agg.end_hhmm)
            return
        note.commit(marker_key, agg.start_hhmm, topic)
        write_cursor(ctx.sid8, agg.end_hhmm)

        resolver.persist_cache()

        try:
            marker = debounce_marker(ctx.sid8)
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker.touch()
        except OSError:
            pass


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        emit_continue()
        return

    ctx = RecapContext.from_hook(raw, os.environ)
    if ctx is None:
        emit_continue()
        return

    try:
        AutoRecap(ctx).run()
    except Exception:
        log("uncaught: " + traceback.format_exc().splitlines()[-1])
    finally:
        emit_continue()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("uncaught: " + traceback.format_exc().splitlines()[-1])
        emit_continue()
