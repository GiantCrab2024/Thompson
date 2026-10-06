# Thompson: Interpretation Flagging Feature — Spec for Claude Code

## Goal
Add a two-stage check to Thompson's generation pipeline that flags AI-generated
interpretations of MODES records which are either (a) based on records with
insufficient source detail, or (b) rely on unsupported "closed-corpus" general
knowledge rather than the record's own fields.

## Stage 1 — Detail Score (pre-generation gate)
Run against the raw MODES record fields, before generating any interpretive text.

Checks:
- Description field word count (flag if very short, e.g. <15 words)
- Key fields empty: maker/creator, date/period, materials, acquisition context, provenance
- Description is only a generic object-type label with no distinguishing detail
- No marks, inscriptions, or condition notes present

Output: **Detail Score 0–3** (0 = insufficient to interpret, 3 = well-documented).
If score is 0–1, either skip generation or generate only a labelled stub
("insufficient source material for interpretation").

## Stage 2 — Corpus Reliance Score (post-generation grounding check)
Two separate model calls, each with fresh/limited context (don't reuse the
original generation prompt — that biases the check toward agreeing with itself).

**Call A — Claim extraction**
Input: record fields + generated text.
Output: numbered list of atomic factual claims made in the text.

**Call B — Grounding check**
Input: claim list + record fields only (not the original prose).
Output per claim: GROUNDED / INFERRED / UNGROUNDED + one-line reason.
Rule: if unsure between INFERRED and UNGROUNDED, default to UNGROUNDED.

Scoring: 0 ungrounded claims → 0; 1–2 → 1; 3–4 → 2; 5+ OR any invented named
specific (a maker's name, a precise date) → 3, regardless of count.

## Combine into a flag

| Detail Score | Corpus Reliance | Result |
|---|---|---|
| 3 | 0–1 | Pass |
| 2 | 0–1 | Pass, minor note |
| 2–3 | 2–3 | Amber — human review before publishing |
| 0–1 | any | Red — stub only / no generation |

## Output requirements
Store per record: Detail Score, Corpus Reliance Score, full claim/classification
table, final flag colour. This is what makes the review queue usable — a
curator or volunteer needs to see *why* something was flagged, not just a score.

## Build notes
- Keep Stage 2's two calls genuinely separate (different context windows).
- Early on, run the grounding check twice on a small sample and compare results,
  to sanity-check consistency before trusting it at scale.
- This logic is independent of UI — it can be built and tested as a standalone
  scoring function first, then wired into wherever Thompson currently generates
  interpretations.
