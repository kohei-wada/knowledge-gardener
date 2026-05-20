# garden-connect — Design

- **Date**: 2026-05-17
- **Status**: Approved (pending spec review)
- **Target release**: knowledge-gardener v0.5.0
- **Sibling skills**: [garden-plant](../../skills/garden-plant/SKILL.md) (C), [garden-survey](../../skills/garden-survey/SKILL.md) (R), [garden-water](../../skills/garden-water/SKILL.md) (U), [garden-recap](../../skills/garden-recap/SKILL.md) (session wrap-up)

## Goal

Ship the **Link** operation of the CRUD set as `garden-connect`. After this release the only missing CRUD primitive is `garden-prune` (Delete).

## Scope

garden-connect adds a graph edge between a **MOC** and one or more **child notes**. That is the entire scope; arbitrary note-to-note links and "link with surrounding explanatory text" stay in garden-water.

### In scope (v0.5.0)

- MOC → child note: append a bullet under the most appropriate sub-heading of the MOC.
- Bi-directional (default for MOC ↔ child): same operation also adds a back-link from the child note into its existing Related / MOC section, in the same commit.
- Batch over a single MOC: `connect: 4 ssh notes ↔ ssh-MOC` may touch the MOC + N child notes in one commit, as long as the change is identical in shape per child.

### Out of scope (deferred or delegated)

- Arbitrary note-to-note linking that is not MOC ↔ child. If the user wants this, route to garden-water (which can do the edit with surrounding context).
- Creating a Related section on a child note that lacks one. garden-connect will not insert section headings. When a back-link is requested but no Related section exists, the skill falls back to MOC → child uni-directional and recommends garden-water for adding the section as a follow-up change (see Edge Cases).
- Removing or rewriting existing links. Removal → garden-prune (future). Rewriting → garden-water.
- Semantic discovery of what *should* be linked. The user (or a calling skill like garden-survey) names the source and target; this skill does not infer relationships.

## Why MOC-only

The MOC ↔ child case is by far the most common Zettelkasten link operation and is structurally regular: the MOC has named sub-headings, the child has a "Related" / "MOC" section. The skill can act with high confidence and minimal diff on this shape. Generic note-to-note linking has too much variance (where in the prose does the link go? does it need a preamble?) and is already covered by garden-water with explanatory context.

This scope cut keeps garden-connect a true graph-edge primitive — single-purpose and predictable.

## Behavioral Defaults

### Direction

- **Default**: bi-directional. MOC ↔ child is almost always reciprocal in practice (the MOC indexes the child; the child points back to its MOC).
- **Override**: user may explicitly request uni-directional ("MOC への片方向だけ" / "no back-link"). Honor it.
- If the child note's Related/MOC section is missing, fall back to uni-directional (MOC → child only) and surface the gap with a suggestion to run garden-water for the section, rather than failing the whole operation.

### Insertion points

| Side | Where the bullet goes |
|------|----------------------|
| **MOC** | Sub-heading chosen by matching the child's tags / title against the MOC's headings. Skill proposes one; user can redirect. If no heading is a clear match, list candidate headings and ask. |
| **Child** | Existing `## 関連` / `## 🔗 Related Links` / `## Related` / `## MOC` section. If multiple match, ask. If none, fall back to uni-directional per above. |

### Batch

- Allowed when: same target MOC, multiple source children, identical bullet shape per child. One commit, subject pluralized.
- Not allowed: heterogeneous source/target combinations. Split into separate invocations.
- Bi + batch is fine: one commit touches the MOC plus all child notes that got back-links.

## Process (mirrors garden-water shape)

1. **Resolve vault path** — `KG_VAULT`, fail loud if unset.
2. **Load vault conventions** — `$KG_VAULT/README.md`, parent `README.md`, `CLAUDE.md`, and the target folder's `README.md` if present. Extract link syntax, frontmatter schema, MOC convention (filename, tag, or folder), Versioning Discipline.
3. **Identify MOC and child(ren)** — explicit path or filename preferred. If only a topic is given, call garden-survey for candidates and ask which.
4. **Detect MOC-ness** — by README convention (e.g. `tags: [moc]`, filename suffix `-MOC.md`, or `02_MOCs/` folder). If the named "MOC" is not actually a MOC per the README, stop and ask.
5. **Decide direction** — bi-directional by default; uni if user overrode or child has no Related section.
6. **Locate insertion sections** — parse MOC sub-headings; pick best fit by child tags/title. For each child (bi mode), find the existing Related/MOC section.
7. **Read every target file with the Read tool** — Edit requires per-file Read history; Bash reads do not count.
8. **Draft the diff** — one bullet per file, byte-exact anchor. Skip files whose link is already present (report as no-op, do not edit).
9. **Propose** — show paths, per-file diffs, and a one-line rationale ("connect <child> ↔ <MOC>" or "connect N children ↔ <MOC>"). Exception: an explicit "connect X to Y" request counts as approval, but still show the diff.
10. **Apply with Edit tool** — never Write. Preserve surrounding bytes.
11. **Lint, commit, push** — `pre-commit run --files ...` (never `--no-verify`), `git add` only the touched files, single commit, push to remote.

## Commit Subjects

| Operation | Subject |
|-----------|---------|
| Uni single (MOC → child) | `connect: ssh-MOC → ssh-key-management` |
| Bi single | `connect: ssh-port-forwarding ↔ ssh-MOC` |
| Batch into MOC (uni) | `connect: 4 ssh notes → ssh-MOC` |
| Bi batch | `connect: 4 ssh notes ↔ ssh-MOC` |

Cap at ~60 chars; detail in commit body when needed.

## Edge Cases

- **MOC not found / not actually a MOC**: stop. Suggest garden-plant if the MOC should exist, or correct the target.
- **Child not found**: stop. Suggest garden-plant.
- **Link already present** on a side: skip that side as a no-op, report it. If both sides are already present, do nothing and report.
- **Child has no Related section** and user asked for bi-directional: fall back to uni-directional and recommend garden-water for adding the section as a separate change.
- **No clear MOC heading match for the child**: ask the user, do not silently pick.
- **MOC has no sub-headings at all** (flat bullet list): append at the end of the body, before any trailing section like "Related MOCs". Surface the structure choice in the proposal.
- **Pre-commit reformat changes the diff** (e.g. markdownlint normalises bullet indent): re-read, confirm intent preserved, retry commit.

## Boundary with garden-water (re-statement)

| If the change is… | Use |
|-------------------|-----|
| A bare link bullet, no surrounding prose, MOC ↔ child | garden-connect |
| A link bullet with explanatory text on the same line or in the same paragraph | garden-water |
| Creating a Related/MOC section that does not yet exist | garden-water |
| Adding a link between two non-MOC notes | garden-water |
| Anything that touches more than the link line itself | garden-water |

garden-water's existing "When NOT to Use" entry that says `garden-connect (when shipped)` has its parenthetical removed by this release.

## Release Checklist (knowledge-gardener v0.5.0)

1. New `skills/garden-connect/SKILL.md` per this design.
2. Update `skills/using-knowledge-gardener/SKILL.md`:
   - Add garden-connect row to the Available Skills table.
   - Add routing entries for "X と Y を link" / "MOC に追加" / "link <X> to <Y>" / internal "garden-survey surfaced an orphan note" trigger.
3. Update `skills/garden-water/SKILL.md`: drop the "(when shipped)" qualifier in the "When NOT to Use" section.
4. Update root `README.md` and `CLAUDE.md` skill tables (and remove garden-connect from the planned/not-yet-shipped list).
5. Bump `package.json` version `0.4.0` → `0.5.0`.
6. Commit, tag `v0.5.0`, push.

## Open Questions

None at design time; all branches have a default and a documented override.

## Non-goals

- A general-purpose link manager. If real-world use surfaces note-to-note demand, evaluate then.
- Auto-discovery of orphan notes. That is garden-survey's job (or a future report skill); garden-connect only consumes a named pair.
