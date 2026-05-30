from __future__ import annotations

import re

# Bare sid8 marker only — the trailing (?![-\w]) guard prevents matching a
# legacy `kg-recap-sid:{sid8}-{HHMM}` block.
def _open_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


def _close_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


_HEADER_RE = re.compile(r"^##[ \t]+Session[ \t]+(\d{2}:\d{2})[ \t]*[〜~][ \t]*(\d{2}:\d{2})[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_KPT_RE = re.compile(r"^### KPT[ \t]*\n.*?(?=\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)
_TIMELINE_RE = re.compile(r"(^### Timeline[ \t]*\n)(.*?)(?=\n### |\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)
_TIMELINE_SECTION_RE = re.compile(
    r"^### Timeline[ \t]*\n.*?(?=\n### |\n## |\n<!-- /kg-recap-sid:|\Z)",
    re.DOTALL | re.MULTILINE,
)


_TIMELINE_TIME_RE = re.compile(r"^-\s+(\d{2}:\d{2})")


def _timeline_sort_key(line: str) -> str:
    """Sort key for a Timeline bullet — its leading `HH:MM` (zero-padded, so
    lexical order is chronological). Stable sort keeps same-minute order.
    render_timeline always emits a timestamp; a line without one (only possible
    via hand-editing) sorts last rather than jumping ahead of real entries."""
    m = _TIMELINE_TIME_RE.match(line)
    return m.group(1) if m else "99:99"


def extract_kpt_section(text: str) -> str | None:
    m = _KPT_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip()


def extract_timeline_bullets(text: str) -> list[str] | None:
    """Pull the bullet lines out of an LLM-emitted `### Timeline` section.
    Returns None when no Timeline section is present (LLM omitted it)."""
    m = _TIMELINE_SECTION_RE.search(text)
    if not m:
        return None
    lines = m.group(0).splitlines()[1:]  # drop the "### Timeline" header line
    return [ln for ln in lines if ln.strip()]


def topic_from_kpt(kpt_section: str) -> str:
    """Derive a short topic from the KPT's first `Keep:` bullet (≤30 chars)."""
    for line in kpt_section.splitlines():
        s = line.strip()
        if s.lower().startswith("- keep:"):
            return s.split(":", 1)[1].strip()[:30]
    return ""


def _render_header(start: str, end: str, topic: str) -> str:
    base = f"## Session {start}〜{end}"
    return f"{base}  {topic}".rstrip() if topic else base


def _new_block(sid8, start, end, topic, timeline_bullets, kpt_section) -> str:
    parts = [
        f"<!-- kg-recap-sid:{sid8} -->",
        _render_header(start, end, topic),
        "",
        "### Timeline",
        *timeline_bullets,
    ]
    if kpt_section:
        parts += ["", kpt_section.rstrip()]
    parts += [f"<!-- /kg-recap-sid:{sid8} -->"]
    return "\n".join(parts) + "\n"


def upsert_session_block(note_text: str, sid8: str, *, start_hhmm: str, end_hhmm: str,
                         topic: str, timeline_bullets: list[str],
                         kpt_section: str | None, insert_before: str = "") -> str:
    om = _open_re(sid8).search(note_text)
    cm = _close_re(sid8).search(note_text)
    if om and cm and cm.start() > om.start():
        block = note_text[om.start():cm.end()]
        # refresh end + topic; start = earliest of the existing header and the
        # incoming window (a manual full-session recap can begin earlier than an
        # auto block that started mid-session; monotonic auto increments are
        # later, so the existing start is preserved for them).
        hm = _HEADER_RE.search(block)
        start = min(hm.group(1), start_hhmm) if hm else start_hhmm
        new_topic = topic or (hm.group(3).strip() if hm else "")
        new_header = _render_header(start, end_hhmm, new_topic)
        block = _HEADER_RE.sub(lambda _m: new_header, block, count=1) if hm else block
        # merge timeline: dedup exact bullet lines, then sort chronologically
        # (fresh bullets may predate existing ones on a full-session recap).
        tm = _TIMELINE_RE.search(block)
        if tm:
            existing_lines = tm.group(2).rstrip("\n").splitlines()
            have = set(existing_lines)
            fresh = [b for b in timeline_bullets if b not in have]
            merged = sorted(existing_lines + fresh, key=_timeline_sort_key)
            block = block[:tm.start(2)] + "\n".join(merged) + block[tm.end(2):]
        # replace or insert KPT
        if kpt_section is not None:
            if _KPT_RE.search(block):
                block = _KPT_RE.sub(lambda _m: kpt_section.rstrip(), block, count=1)
            else:
                close = _close_re(sid8).search(block)
                block = block[:close.start()].rstrip() + "\n\n" + kpt_section.rstrip() + "\n" + block[close.start():]
        # normalize section spacing so re-applying identical inputs is a byte-level no-op
        # (matches _new_block: one blank line before each ### subheading, none before the close marker)
        block = re.sub(r"\n+(### )", r"\n\n\1", block)
        block = re.sub(r"\n+(<!--\s*/kg-recap-sid:)", r"\n\1", block)
        return note_text[:om.start()] + block + note_text[cm.end():]

    # block absent → build and insert
    new = _new_block(sid8, start_hhmm, end_hhmm, topic, timeline_bullets, kpt_section)
    anchor = insert_before.strip()
    m = re.search(r"\n" + re.escape(anchor), note_text) if anchor else None
    if m:
        return note_text[:m.start()] + "\n" + new + note_text[m.start():]
    sep = "" if note_text.endswith("\n") or not note_text else "\n"
    return note_text + sep + new
