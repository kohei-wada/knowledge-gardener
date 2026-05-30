from __future__ import annotations

import re

# Bare sid8 marker only — the trailing (?![-\w]) guard prevents matching a
# legacy `kg-recap-sid:{sid8}-{HHMM}` block.
def _open_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


def _close_re(sid8: str) -> re.Pattern:
    return re.compile(rf"<!--\s*/kg-recap-sid:{re.escape(sid8)}(?![-\w])\s*-->", re.IGNORECASE)


_HEADER_RE = re.compile(r"^##\s+Session\s+(\d{2}:\d{2})\s*[〜~]\s*(\d{2}:\d{2})\s*(.*?)\s*$", re.MULTILINE)
_KPT_RE = re.compile(r"^### KPT[ \t]*\n.*?(?=\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)
_TIMELINE_RE = re.compile(r"(^### Timeline[ \t]*\n)(.*?)(?=\n### |\n## |\n<!-- /kg-recap-sid:|\Z)", re.DOTALL | re.MULTILINE)


def extract_kpt_section(text: str) -> str | None:
    m = _KPT_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip()


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
        # preserve the existing start; refresh end + topic
        hm = _HEADER_RE.search(block)
        start = hm.group(1) if hm else start_hhmm
        new_topic = topic or (hm.group(3).strip() if hm else "")
        new_header = _render_header(start, end_hhmm, new_topic)
        block = _HEADER_RE.sub(lambda _m: new_header, block, count=1) if hm else block
        # append timeline (dedup exact bullet lines)
        tm = _TIMELINE_RE.search(block)
        if tm:
            existing = tm.group(2).rstrip("\n")
            have = set(existing.splitlines())
            fresh = [b for b in timeline_bullets if b not in have]
            body = existing + ("\n" + "\n".join(fresh) if fresh else "")
            block = block[:tm.start(2)] + body + block[tm.end(2):]
        # replace or insert KPT
        if kpt_section is not None:
            if _KPT_RE.search(block):
                block = _KPT_RE.sub(lambda _m: kpt_section.rstrip(), block, count=1)
            else:
                close = _close_re(sid8).search(block)
                block = block[:close.start()].rstrip() + "\n\n" + kpt_section.rstrip() + "\n" + block[close.start():]
        return note_text[:om.start()] + block + note_text[cm.end():]

    # block absent → build and insert
    new = _new_block(sid8, start_hhmm, end_hhmm, topic, timeline_bullets, kpt_section)
    anchor = insert_before.strip()
    m = re.search(r"\n" + re.escape(anchor), note_text) if anchor else None
    if m:
        return note_text[:m.start()] + "\n" + new + note_text[m.start():]
    sep = "" if note_text.endswith("\n") or not note_text else "\n"
    return note_text + sep + new
