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

from ..shared.hook_io import DEBOUNCE_SECONDS, DEFAULT_TIMEOUT, emit_continue, log
from ..shared.fs import _resolve_under_vault, plugin_root, read_text
from ..shared.paths import debounce_marker, session_log_path
from ..shared.cursor import write_cursor
from .context import RecapContext
from .session_aggregator import SessionAggregator
from .daily_note_resolver import DailyNoteResolver
from .daily_note import DailyNote
from .gate import is_substantive
from .transcript import slice_transcript
from .block import extract_kpt_section, extract_timeline_bullets, topic_from_kpt


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

        marker = debounce_marker(ctx.sid8)
        try:
            if marker.exists() and (time.time() - marker.stat().st_mtime) < DEBOUNCE_SECONDS:
                return
        except OSError:
            pass

        log_path = session_log_path(ctx.sid8)
        if not log_path.is_file() or log_path.stat().st_size == 0:
            return

        agg = SessionAggregator(ctx).aggregate()
        if agg is None:
            return

        resolver = DailyNoteResolver(ctx)
        pre = resolver.pre_resolve()

        substantive = is_substantive(agg.durable_change, agg.entry_count, agg.duration_min, os.environ)

        # Path resolution. Timeline-only (non-substantive) needs a pre-resolved
        # path (env/warm cache) — we never spend an LLM discovery call for it.
        if pre is not None:
            daily_path, insert_before = pre
        elif not substantive:
            log("no pre-resolved daily path and non-substantive window -> skip (cache warms on a substantive Stop)")
            return
        else:
            daily_path, insert_before = None, ""  # resolved from discovery after the LLM call

        det_bullets = agg.timeline          # whole-session, deterministic, filtered
        timeline_bullets = det_bullets
        kpt_section: str | None = None
        topic = ""

        if substantive:
            readme, template = load_vault_context(ctx.vault)
            prior_block = self._read_existing_block(daily_path, ctx.sid8) if daily_path else ""
            prior_kpt = extract_kpt_section(prior_block) or ""
            tslice = slice_transcript(ctx.transcript_path, ctx.since, ctx.today_str)
            timeline_text = "\n".join(agg.timeline)

            if pre is not None:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_compose_prompt.md"
            else:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_prompt.md"
            if not tmpl_path.is_file():
                log(f"prompt template missing: {tmpl_path}")
                return
            prompt = compose_prompt(tmpl_path.read_text(encoding="utf-8"), {
                "TODAY": ctx.today_str,
                "DAILY_TEMPLATE": template,
                "VAULT_README": readme,
                "EXISTING_DAILY": (daily_path.read_text(encoding="utf-8") if daily_path and daily_path.is_file() else "(file does not exist yet)"),
                "PRIOR_KPT": prior_kpt,
                "TIMELINE": timeline_text,
                "TRANSCRIPT_SLICE": tslice or "(transcript unavailable)",
            })
            timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
            out = call_claude(prompt, timeout=timeout)
            if out:
                if pre is None:
                    resolved = resolver.resolve_from_discovery(out)
                    if resolved is None:
                        return
                    daily_path, insert_before = resolved
                ai_bullets = extract_timeline_bullets(out)
                if ai_bullets:
                    timeline_bullets = ai_bullets
                kpt_section = extract_kpt_section(out)
                if kpt_section is None:
                    log("claude output missing ### KPT section; writing Timeline only")
                else:
                    topic = topic_from_kpt(kpt_section)
            elif pre is None:
                log("claude failed and no pre-resolved daily path -> skip")
                return
            # else: claude failed but path is known -> fall through, write deterministic block

        note = DailyNote(ctx.vault, daily_path)
        if not note.apply_block(
            ctx.sid8, start_hhmm=agg.start_hhmm, end_hhmm=agg.end_hhmm, topic=topic,
            timeline_bullets=timeline_bullets, kpt_section=kpt_section, insert_before=insert_before,
        ):
            write_cursor(ctx.sid8, agg.end_hhmm)
            return

        if not note.has_repo:
            log("vault not in a git repo - skipping commit; cursor updated")
            write_cursor(ctx.sid8, agg.end_hhmm)
            return
        note.commit(ctx.sid8, agg.start_hhmm, topic or None)
        write_cursor(ctx.sid8, agg.end_hhmm)
        if substantive:
            resolver.persist_cache()

        try:
            marker = debounce_marker(ctx.sid8)
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker.touch()
        except OSError:
            pass

    @staticmethod
    def _read_existing_block(daily_path, sid8: str) -> str:
        try:
            text = daily_path.read_text(encoding="utf-8") if daily_path and daily_path.is_file() else ""
        except OSError:
            return ""
        from .block import _open_re, _close_re
        om = _open_re(sid8).search(text)
        cm = _close_re(sid8).search(text)
        return text[om.start():cm.end()] if om and cm and cm.start() > om.start() else ""

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
