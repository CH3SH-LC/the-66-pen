"""Offline test #9 — a demo doc must not describe the demo as more finished than it is.

The doctrine (``CLAUDE.md`` §一.3, §四, §六) draws the line the demo docs keep
re-drawing themselves::

    文档写了什么  /  工具能做什么  /  真机验证过什么

and the demo docs are explicit that the whole slice stops at *"saved, not
played"* — ``runtimeVerified:false`` / ``officialPlaytestVerified:false``, with
the five runtime steps each blocked on a write primitive that is proven not to
exist.  That honesty is load-bearing: it is the one thing keeping a "vertical
slice" from being read as a finished game.  Nothing in the suite checked that a
*new* line added to a demo doc cannot quietly claim the demo is **playable** or
that a runtime behaviour is **verified** when neither is true.  This module does.

The rule
--------
A logical line is a **playability / verification claim** iff it carries the
claim vocabulary (:data:`_CLAIM`: ``能玩`` / ``可玩`` / ``可以玩`` / ``试玩通过`` /
``playable`` / ``已验证`` / ``verified`` / ``跑通`` / ``正常触发``).  Every such
claim must be

  (a) **hedged** — accompanied by an explicit caveat (:data:`_HEDGE`: 未真机 /
      不能 / 离线 / 只有…才算 / ≠ / blocked / OFFLINE …), **or**
  (b) **backed** — accompanied by at least one cited artefact that actually
      **exists on disk** (a directory-qualified repo path, per
      ``test_verification_claims``).

A claim with **neither** fails.  The main check reports the count it checked and
names every offender as ``doc:line -> claim``; it never edits the docs.

Conservative by construction
----------------------------
Tuned *against these docs*: on 2026-10-10 the scan finds ~30 claim-bearing units
across the ``docs/gameplan/*.md`` set and **0** offenders — every honest line
carries an explicit hedge (the artefact-backed branch is exercised by the
positive control below, not by the real docs, which hedge everything).  Two
deliberate under-approximations keep it from firing on things that are not
claims:

  * **headings** (``#…``) are labels, not claims — the claim lives in the body
    (``# PLAYABLE-TODAY — …能玩到…吗？`` is a question, not an assertion);
  * the English tokens are matched as **standalone words**: ``playable`` /
    ``verified`` inside a filename (``PLAYABLE-TODAY.md``), a dotted field
    (``level.verified``) or a camelCase field (``officialPlaytestVerified``) is a
    *mention*, not a claim.

and fenced code blocks (JSON receipts, shell transcripts) are skipped outright:
a ``"verified": true`` in an expected-response example is not a claim about this
repo, it is the shape of a receipt.

The negative controls prove the guard still bites: a synthetic unhedged
playability claim and a synthetic unhedged verification claim must both be
flagged, and the real failure shape — an unhedged claim spliced into a *real*
demo doc — must be caught in the real text.  :meth:`…test_scan_is_not_vacuous`
pins a floor on the claim count so a gutted :data:`_CLAIM` cannot report a hollow
green.

The inverse — a manual step may not be called automatic
-------------------------------------------------------
:data:`_CLAIM` guards "the demo works" against over-claiming.  The mirror image
is "this step is done for you".  The whole slice stops on three things a
**human** must do in the official editor (build the templates, add the
collision/trigger components, start the playtest); ``MANUAL-STEPS.md`` is the
authority that marks them human-only (its §5 literally says **加组件只能人工**,
§6 gives 试玩 no tool path).  A doc that quietly calls one of those steps
**automatic** (全自动 / 无人值守 / 自动建模板 / 自动加组件 / 自动试玩 …)
contradicts that authority.
:class:`AutomaticStepClaimsDoNotContradictManualSteps` scans every
``docs/gameplan/*.md`` line for an auto token (:data:`_AUTO`) near a step subject
(:data:`_STEP`) that lacks any manual qualifier (:data:`_MANUAL_HEDGE`) and
reports it; it never edits the docs.  Today it flags 0 and pins a non-vacuity
floor so a gutted vocabulary cannot report a hollow green.

Three more over-claim shapes (added 2026-10-12)
----------------------------------------------
The 2026-10-11 session shipped several over-claims that only an adversary
caught, each in a *different* disguise.  Three of those disguises leave a
mechanically checkable residue in the prose and are guarded here; the other
three do not, and stay prose (see the closing note).

  * :class:`ArtefactIndependenceContradictsTheOwnPullLog` — a doc that calls its
    captured artefacts "N 份互不依赖" while *the same doc elsewhere* says two of
    them are outputs of ONE debug-log pull (近似 1:1).  Independence comes from
    an axis the doc can point at (the "two legs"), not from counting files.
  * :class:`MarkerExecutionClaimsNeedFreshness` — a captured marker said to
    prove a graph executed, with neither a freshness argument (mint time vs the
    artefact's own timestamp; ``GRAPH-RUNTIME-EVIDENCE.md`` §二) nor a hedge.
  * :class:`ComponentKindEqualityNeedsAnchor` — a component *kind* equated to a
    front-end enum value ("kind = 8 = Collision") with neither a hedge (假设/待
    真机) nor an anchor citation.  The enum member value is a static fact; the
    cross-layer identity is an inference with a named 软肋.

Each is demonstrated *both ways*: a synthetic offender (and the offender
spliced into a real doc) must be flagged, and a hedged / anchored / legs-only
passage must not be.  Each also pins a non-vacuity floor, so a gutted vocabulary
cannot report a hollow green.

Left to prose on purpose
------------------------
Three of the session's disguises are *operational* — they live in the act of
searching, not in a document's prose — so a text guard cannot be honest about
them, and none is faked here:

  * **a zero trusted with a zero positive control** (``SEARCH-AND-AUDIT-
    DISCIPLINE.md`` L1) — whether an instrument returned non-zero on a known
    target is a fact about a run, not about a sentence;
  * **a case-sensitive instrument over uppercase data** (L8) — likewise a
    property of the search, not of the text; the discipline (decode first, run
    the positive control, report the layer) is the only honest form;
  * **a negative scoped to one corpus presented as scoped to all** (L5) — partly
    detectable, but the boundary between "one corpus" and "all corpora" is a
    semantic one (which corpora count as independent axes) that a regex cannot
    draw without firing on the honest scope statements the docs are full of.

Read-only: this module reads docs and stats paths.  No bridge, no native call, no
game/editor contact, nothing written.

Run::

    python -B -m unittest tools.gameplan.tests.test_demo_claims
"""

from __future__ import annotations

import os
import re
import unittest
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GAMEPLAN = "docs/gameplan"

# The demo docs that describe the vertical slice / the demo / playability.  These
# are the guard's primary targets: if they vanish, the scan would be hollow, so
# they must be present.  (Any *other* ``docs/gameplan/*.md`` is scanned too, so a
# new DEMO-* doc is covered automatically and a missing one is not a failure.)
REQUIRED_DOCS = (
    "docs/gameplan/VERTICAL-SLICE.md",
    "docs/gameplan/DEMO-GAP.md",
    "docs/gameplan/DEMO-CHAIN-FINAL.md",
    "docs/gameplan/DEMO-NEXT-STEP.md",
    "docs/gameplan/PLAYABLE-TODAY.md",
)
# Filename patterns that make a doc part of the demo surface even if it is new.
DEMO_PATTERNS = ("DEMO-*.md", "PLAYABLE-*.md", "VERTICAL-SLICE*.md")

# The claim vocabulary — the words that assert "this is playable" / "this is
# verified".  Chinese tokens are substring-matched (``可以玩`` is listed
# separately because it does not contain ``可玩`` as a substring); the English
# terms are standalone words: a filename (``…PLAYABLE-…``), a dotted field
# (``level.verified``) or a camelCase field (``…Verified``) is a mention, not a
# claim, and is deliberately not matched.
_CLAIM = re.compile(
    r"能玩|可玩|可以玩|试玩通过|已验证|跑通|正常触发|"
    r"(?<![A-Za-z0-9_\-.])playable(?![A-Za-z0-9_\-])|"
    r"(?<![A-Za-z0-9_\-.])verified(?![A-Za-z0-9_\-])",
    re.IGNORECASE,
)

# An explicit hedge — the line says it is a candidate / not run / blocked /
# conditional / *prospective*, so it is not a claim that the demo works.  Kept to
# compounds and doctrine words (不能 / 尚未 / 离线 / blocked / OFFLINE / 只有…才算 /
# ≠ …); a bare 未 / 无 would swallow the very negation the honest docs rely on.
# The prospective markers (``unblocks`` / ``going`` / 目标 / will …) matter because
# a handoff that says an op is *going* "compiled → real-machine verified" is
# stating a goal, not claiming the verified state holds today.
_HEDGE = re.compile(
    r"候选|未真机|未验证|未证|未跑|未编译|未接线|未上机|未连|未落|未读回|未|"
    r"只离线|离线|OFFLINE|unknown|unverified|missing|research|blocked|unblocks?|"
    r"待办|待|缺|不能|不是|不等于|不算|不会|不到|不了|没有|并非|非|无|没|"
    r"只有|才算|离|想|差|做不到|不存在|无法|尚未|悬空|否|≠|"
    r"going|would|will|goal|target|计划|打算|将要|目标|吗|？|\?",
    re.IGNORECASE,
)

# --- the inverse guard's vocabulary (a manual step may not be called automatic) --

# The authority that marks the slice's stalled steps human-only.
MANUAL_STEPS = "docs/gameplan/MANUAL-STEPS.md"

# The words that assert a step happens *without* a human.  Grounded in the tree: on
# 2026-10-10 only ``自动`` / ``自动化`` occur alongside a step subject in
# ``docs/gameplan``, but the set is kept wide enough that a re-wording (``全自动`` /
# ``无人值守`` / ``无需人工`` / ``automatically``) is still caught.
_AUTO = re.compile(
    r"全自动|自动化|自动|无人值守|无需人工|不用人工|免人工|"
    r"(?<![A-Za-z0-9_\-])auto(?:matic(?:ally)?)?(?![A-Za-z0-9_\-])",
    re.IGNORECASE,
)
# The manual-step subjects MANUAL-STEPS.md enumerates (§1–§6): the currency / item /
# shop *templates*, the collision-trigger / shop / bag *components*, and the
# *playtest* itself — the three things the slice stops on.
_STEP = re.compile(r"组件|模板|试玩|碰撞触发器|商店|背包|货币|道具")
# An honest qualifier: a manual actor, or an explicit negation of the auto verb
# (``一条都自动化不了``).  Broad negations (``无`` / ``没`` / ``未``) count because in
# these docs they sit *on* the auto claim (``本工程无写入原语``); a bare ``自动`` with
# no qualifier anywhere in the unit is exactly the thing that must not pass silently.
_MANUAL_HEDGE = re.compile(
    r"手工|人工|人眼|人手|由人|人来做|人必须|需要人|要人|请人|"
    r"不自动|不能自动|无法自动|不可自动|未自动|没有自动|不得自动|"
    r"自动化不了|自动不了|不能自动化|无法自动化|不可能自动|"
    r"未|没有|无|没|非|仅|只有|只能|才算|不了|"
    r"(?<![A-Za-z0-9_\-])(?:not|never|no|blocked)(?![A-Za-z0-9_\-])",
    re.IGNORECASE,
)

# A directory-qualified path token: ≥1 ``/``, segments of ``[.A-Za-z0-9_-]``.
_PATH_TOKEN = re.compile(r"[.A-Za-z0-9_\-]+(?:/[.A-Za-z0-9_\-]+)+")
# A trailing ``:LINE`` or ``:A-B`` source suffix on a reference.
_LINE_SUFFIX = re.compile(r":\d{1,5}(?:-\d{1,5})?$")
# A path's last segment looks like a filename (has a short extension).
_EXT = re.compile(r"\.[A-Za-z0-9]{1,6}$")
# Repo top-level directories that make a slash-token unambiguously a repo path.
_KNOWN_TOPS = (
    "docs/", "tools/", "data/", "config/", "backend/", "bridge/",
    "plugins/", "mvp/", "scripts/", "vendor/", ".runtime/", ".task-manifest/",
)
# A drive-qualified or absolute path — out of scope (its target is the live save).
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|/|\\)")
# A placeholder segment (``<levelId>``, ``{before,after}`` …) truncates a path.
_PLACEHOLDER = re.compile(r"[<>{}$]")

# Markdown structure that starts a *new* logical line rather than continuing one.
_STRUCT = re.compile(r"^\s*(?:\||#|>|[-*+]\s|\d+\.\s)")
_FENCE = "```"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def units(text: str) -> list[tuple[int, list[str], bool]]:
    """Split ``text`` into logical lines as ``(1-based start, [lines], in_fence)``.

    Mirrors ``test_evidence_discipline.units``: a table row / heading / blockquote
    / bullet is its own unit, any other non-blank line continues the unit above it
    so a claim and its wrapped hedge/citation stay together.  Fenced code blocks
    are emitted with ``in_fence=True`` (calls skip them — receipts are not claims).
    """
    out: list[tuple[int, list[str], bool]] = []
    cur: list[str] = []
    start: int | None = None
    fence = False

    def flush() -> None:
        nonlocal cur, start
        if cur:
            assert start is not None
            out.append((start, cur, False))
            cur = []
            start = None

    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.rstrip()
        if s.lstrip().startswith(_FENCE):
            flush()
            fence = not fence
            out.append((i, [s], True))
            continue
        if fence:
            out.append((i, [s], True))
            continue
        if not s.strip():
            flush()
            continue
        if _STRUCT.match(s):
            flush()
            out.append((i, [s], False))
            continue
        if not cur:
            start = i
        cur.append(s)
    flush()
    return out


def is_path_reference(tok: str) -> bool:
    """True iff ``tok`` is a directory-qualified repo path worth resolving."""
    if _ABSOLUTE.match(tok):
        return False
    if _PLACEHOLDER.search(tok):
        return False
    if tok.startswith(_KNOWN_TOPS):
        return True
    return bool(_EXT.search(tok.rsplit("/", 1)[-1]))


def references(blob: str) -> list[str]:
    """Directory-qualified path references in ``blob``, de-duplicated, in order."""
    seen: dict[str, None] = {}
    for m in _PATH_TOKEN.finditer(blob):
        tok = _LINE_SUFFIX.sub("", m.group(0))
        if is_path_reference(tok):
            seen.setdefault(tok, None)
    return list(seen)


def target_exists(rel: str) -> bool:
    """Resolve a repo-relative reference against the checkout.

    ``.runtime/`` is git-ignored but present on this disk, so existence is checked
    with :func:`os.path.exists` (same convention as ``test_verification_claims``).
    """
    rel = rel.replace("\\", "/")
    return os.path.exists(os.path.join(REPO, *rel.split("/")))


@dataclass(frozen=True)
class Claim:
    """One playability / verification claim and how it is qualified."""

    doc: str
    line: int
    text: str
    token: str
    hedged: bool
    refs: tuple[str, ...]

    @property
    def backed(self) -> bool:
        """True iff at least one cited artefact exists on disk."""
        return any(target_exists(r) for r in self.refs)

    @property
    def violation(self) -> bool:
        """A claim with neither a hedge nor a real cited artefact."""
        return not self.hedged and not self.backed

    def report(self) -> str:
        return f"{self.doc}:{self.line}: {self.token!r} in {self.text[:80]!r}"


def claims_in(doc: str, text: str) -> list[Claim]:
    """Every playability / verification claim in ``text`` (hedged or not)."""
    found: list[Claim] = []
    for line_no, lines, in_fence in units(text):
        if in_fence:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            # A heading is a label; the claim lives in the body it heads.
            continue
        blob = "\n".join(lines)
        m = _CLAIM.search(blob)
        if not m:
            continue
        found.append(
            Claim(
                doc=doc,
                line=line_no,
                text=first,
                token=m.group(0),
                hedged=bool(_HEDGE.search(blob)),
                refs=tuple(references(blob)),
            )
        )
    return found


def violations_in(doc: str, text: str) -> list[Claim]:
    return [c for c in claims_in(doc, text) if c.violation]


def scanned_docs() -> list[str]:
    """Every present ``docs/gameplan/*.md``, as repo-relative posix paths."""
    d = REPO / GAMEPLAN
    if not d.is_dir():
        return []
    return [f"{GAMEPLAN}/{p.name}" for p in sorted(d.glob("*.md"))]


def is_demo_doc(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch(name, pat) for pat in DEMO_PATTERNS)


def scan_all() -> tuple[list[Claim], list[Claim]]:
    """Scan every gameplan doc; return ``(all claims, violating claims)``."""
    claims: list[Claim] = []
    for rel in scanned_docs():
        claims.extend(claims_in(rel, _read(REPO / rel)))
    return claims, [c for c in claims if c.violation]


# --------------------------------------------------------------------------- #
# The inverse: a doc may not call a human-only step automatic.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AutoStepClaim:
    """One "this step is automatic" claim and whether it carries a manual qualifier."""

    doc: str
    line: int
    text: str
    token: str
    hedged: bool

    @property
    def violation(self) -> bool:
        """An automatic-step claim with no manual qualifier — contradicts MANUAL-STEPS."""
        return not self.hedged

    def report(self) -> str:
        return f"{self.doc}:{self.line}: {self.token!r} in {self.text[:80]!r}"


def auto_step_claims(doc: str, text: str) -> list[AutoStepClaim]:
    """Every "step is automatic" claim in ``text`` (qualified or not)."""
    found: list[AutoStepClaim] = []
    for line_no, lines, in_fence in units(text):
        if in_fence:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            # A heading is a label, not a claim.
            continue
        blob = "\n".join(lines)
        if not _STEP.search(blob):
            continue
        m = _AUTO.search(blob)
        if not m:
            continue
        found.append(
            AutoStepClaim(
                doc=doc,
                line=line_no,
                text=first,
                token=m.group(0),
                hedged=bool(_MANUAL_HEDGE.search(blob)),
            )
        )
    return found


def scan_auto_steps() -> tuple[list[AutoStepClaim], list[AutoStepClaim]]:
    """Scan every gameplan doc; return ``(all auto-step claims, violating ones)``."""
    claims: list[AutoStepClaim] = []
    for rel in scanned_docs():
        claims.extend(auto_step_claims(rel, _read(REPO / rel)))
    return claims, [c for c in claims if c.violation]


# --------------------------------------------------------------------------- #
# The check itself, plus the guards that make its green meaningful.
# --------------------------------------------------------------------------- #

class DemoDocsDoNotOverclaim(unittest.TestCase):
    def test_required_demo_docs_exist(self):
        """A missing demo doc must not be a silent pass — the scan would be hollow."""
        missing = [d for d in REQUIRED_DOCS if not (REPO / d).is_file()]
        self.assertEqual(missing, [], f"demo docs named in the task are absent: {missing}")

    def test_every_gameplan_doc_is_scanned(self):
        """The scan really covers the whole ``docs/gameplan/*.md`` surface."""
        scanned = set(scanned_docs())
        for d in REQUIRED_DOCS:
            self.assertIn(d, scanned, f"{d} is present but fell out of the scan set")

    def test_no_unbacked_playability_or_verification_claim(self):
        """DRIFT DETECTOR — the real check over ``docs/gameplan/*.md``.

        Flags any logical line that claims the demo is playable / verified while
        giving neither an explicit hedge nor a cited artefact that exists.  Today
        it flags 0 (the docs are honest); a *new* over-claiming line turns this
        red and names ``doc:line -> claim``.  Fix by hedging the line or citing a
        real receipt — **not** by editing this test to ignore it.
        """
        claims, bad = scan_all()
        report = [c.report() for c in bad]
        self.assertEqual(
            report,
            [],
            f"{len(bad)} of {len(claims)} playability/verification claims in "
            f"docs/gameplan/*.md are neither hedged nor backed by an artefact "
            f"that exists:\n  " + "\n  ".join(report),
        )

    def test_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty scan.

        Pins a floor on the number of claims the vocabulary finds across the real
        docs, and requires them to land in the demo docs specifically, so a gutted
        :data:`_CLAIM` (0 claims) fails here instead of reporting a hollow green.
        """
        claims, _ = scan_all()
        total = len(claims)
        demo = {c.doc for c in claims if is_demo_doc(c.doc)}
        self.assertGreaterEqual(
            total, 10,
            f"only {total} playability/verification claims found across "
            f"docs/gameplan/*.md — the vocabulary has gone blind",
        )
        self.assertGreaterEqual(
            len(demo), 3,
            f"claims resolved in only {len(demo)} demo docs ({sorted(demo)}) — the "
            f"scan is no longer touching the demo surface",
        )

    def test_claim_vocabulary_matches_every_token(self):
        """Each canonical token is a claim word — or ``_CLAIM`` is not what we think."""
        for tok in (
            "能玩", "可玩", "可以玩", "试玩通过", "playable",
            "已验证", "verified", "跑通", "正常触发",
        ):
            with self.subTest(token=tok):
                self.assertIsNotNone(_CLAIM.search(tok), f"{tok!r} is not a claim word")

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible.

        Reports ``checked / hedged / backed / failing`` for this checkout; the
        non-vacuity floors live in :meth:`test_scan_is_not_vacuous`.
        """
        claims, bad = scan_all()
        hedged = sum(1 for c in claims if c.hedged)
        backed = sum(1 for c in claims if c.backed and not c.hedged)
        print(
            f"\ndemo docs claim-scan: {len(claims)} playability/verification "
            f"claims across {len(scanned_docs())} docs; hedged: {hedged}; "
            f"artefact-backed (unhedged): {backed}; FAILING: {len(bad)}"
        )
        for c in bad:
            print(f"  FAIL  {c.report()}")


class AutomaticStepClaimsDoNotContradictManualSteps(unittest.TestCase):
    """The inverse guard: no gameplan doc may call a human-only step automatic.

    ``MANUAL-STEPS.md`` is the authority: §1–§4 (templates), §5/§5b (components)
    and §6 (playtest) are all steps a **human** must perform in the official
    editor — §5 literally reads **加组件只能人工**.  A doc that says such a step
    is 自动 / 全自动 / 无人值守 / auto contradicts it and is flagged here.
    """

    def test_manual_steps_authority_exists(self):
        """A missing authority would make the contradiction check vacuous."""
        p = REPO / MANUAL_STEPS
        self.assertTrue(p.is_file(), f"{MANUAL_STEPS} (the manual/auto authority) is missing")
        text = _read(p)
        self.assertIn("只能人工", text, "MANUAL-STEPS no longer declares a manual-only step")
        for step in ("组件", "模板", "试玩"):
            self.assertRegex(
                text, step, f"MANUAL-STEPS no longer covers the {step!r} step"
            )

    def test_no_unhedged_automatic_step_claim(self):
        """DRIFT DETECTOR — the inverse of the playability check.

        Flags any logical line in ``docs/gameplan/*.md`` that calls one of
        ``MANUAL-STEPS.md``'s human-only steps (template / component / playtest)
        **automatic** while carrying no manual qualifier.  Today it flags 0; a
        line that quietly claims the slice's manual half is automated turns this
        red and names ``doc:line -> token``.  Fix by qualifying the line — **not**
        by editing this test to ignore it.
        """
        claims, bad = scan_auto_steps()
        report = [c.report() for c in bad]
        self.assertEqual(
            report,
            [],
            f"{len(bad)} of {len(claims)} \"step is automatic\" claims in "
            f"docs/gameplan/*.md carry no manual qualifier and so contradict "
            f"{MANUAL_STEPS}:\n  " + "\n  ".join(report),
        )

    def test_auto_step_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty scan.

        Pins a floor on the number of auto+step units the vocabulary finds across
        the real docs, and requires them to land in MANUAL-STEPS.md itself, so a
        gutted :data:`_AUTO` / :data:`_STEP` fails here instead of reporting a
        hollow green.
        """
        claims, _ = scan_auto_steps()
        self.assertGreaterEqual(
            len(claims), 3,
            f"only {len(claims)} \"step is automatic\" claims found across "
            f"docs/gameplan/*.md — the inverse vocabulary has gone blind",
        )
        self.assertTrue(
            any(c.doc == MANUAL_STEPS for c in claims),
            f"no auto-step claim resolved in {MANUAL_STEPS} — the authority is "
            f"no longer in the scan",
        )

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible."""
        claims, bad = scan_auto_steps()
        hedged = sum(1 for c in claims if c.hedged)
        print(
            f"\nauto-step claim-scan: {len(claims)} \"step is automatic\" claims "
            f"across {len(scanned_docs())} docs; manually-qualified: {hedged}; "
            f"FAILING: {len(bad)}"
        )
        for c in bad:
            print(f"  FAIL  {c.report()}")


class AutomaticStepControlsProveTheGuardBites(unittest.TestCase):
    """The inverse guard, tested against what it must catch and let pass."""

    def test_synthetic_unhedged_automatic_step_claim_fails(self):
        """Negative control: calling a manual step automatic must be flagged."""
        for text, token in (
            ("加碰撞触发器组件这一步已全自动完成。\n", "全自动"),
            ("商店模板由工具自动创建。\n", "自动"),
            ("试玩现在会自动跑起来。\n", "自动"),
        ):
            with self.subTest(text=text):
                bad = [c for c in auto_step_claims("(synthetic)", text) if c.violation]
                self.assertEqual(
                    len(bad), 1, f"an unhedged automatic-step claim was NOT flagged: {text!r}"
                )
                self.assertIn(token, bad[0].token, f"flagged token {bad[0].token!r} is not the auto word")

    def test_hedged_automatic_step_claims_are_not_flagged(self):
        """Positive control — a manual qualifier must suppress, or the check is noise."""
        for text in (
            "加组件只能人工，不能自动化。\n",
            "模板今天无法自动创建（手工建）。\n",
            "试玩没有后台入口，工程一条都自动化不了。\n",
            "组件写入原语不存在，本工程无自动加组件能力。\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    [c for c in auto_step_claims("(synthetic)", text) if c.violation], [],
                    f"a qualified line was treated as an over-claim: {text}",
                )

    def test_automatic_step_claim_in_a_real_doc_is_flagged(self):
        """The actual failure shape: an over-claim spliced into a real doc."""
        real = _read(REPO / "docs/gameplan/VERTICAL-SLICE.md")
        claim = "加碰撞触发器组件这一步已能全自动完成。"
        spliced = real + "\n\n" + claim + "\n"
        flagged = [c.text for c in auto_step_claims("VERTICAL-SLICE.md", spliced) if c.violation]
        self.assertIn(
            claim, flagged,
            "an automatic-step over-claim spliced into the real demo doc went unflagged",
        )

    def test_auto_step_mentions_are_not_claims(self):
        """A step word with no auto token, or an auto token with no step subject, is not a claim."""
        for text in (
            "本工程无写入原语，建模板只能人工。\n",           # step word, no auto token
            "Get-AllowedOps 会自动跟随 ValidateSet。\n",        # auto token, no step subject
            "`--run-id` 缺省自动取最新活租约。\n",              # auto token, no step subject
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    auto_step_claims("(synthetic)", text), [],
                    f"a mention was treated as an automatic-step claim: {text}",
                )



    def test_synthetic_unhedged_playability_claim_fails(self):
        """Negative control (task #4): an unhedged playability claim must fail."""
        text = "这条种菜 demo 今天能玩了，玩家走进去地块就会响应。\n"
        bad = violations_in("(synthetic)", text)
        self.assertEqual(len(bad), 1, "an unhedged playability claim was NOT flagged")
        self.assertEqual(bad[0].token, "能玩")
        self.assertEqual(bad[0].line, 1)

    def test_synthetic_unhedged_verification_claim_fails(self):
        """Negative control: an unhedged runtime-verification claim must fail."""
        for text in (
            "图触发已验证，走进去就有反应。\n",
            "这条链路已跑通。\n",
            "The demo is verified playable today.\n",
        ):
            with self.subTest(text=text):
                bad = violations_in("(synthetic)", text)
                self.assertEqual(len(bad), 1, f"unhedged claim not flagged: {text!r}")
                self.assertRegex(
                    bad[0].token.lower(), r"^(?:已验证|跑通|verified|playable)$",
                    f"the flagged token is not a claim word: {bad[0].token!r}",
                )

    def test_new_playability_tokens_are_flagged(self):
        """Negative control: the vocabulary added for task #5 bites too."""
        for text, token in (
            ("这条 demo 今天可以玩了。\n", "可以玩"),
            ("这次改动已试玩通过。\n", "试玩通过"),
        ):
            with self.subTest(text=text):
                bad = violations_in("(synthetic)", text)
                self.assertEqual(len(bad), 1, f"unhedged claim not flagged: {text!r}")
                self.assertEqual(bad[0].token, token)

    def test_new_claim_in_a_real_demo_doc_is_flagged(self):
        """The actual failure shape: a fresh over-claim spliced into a real doc.

        Takes the real ``docs/gameplan/PLAYABLE-TODAY.md`` and appends an unhedged
        playability claim; the scanner must catch it in the real text, not a toy
        string.
        """
        real = _read(REPO / "docs/gameplan/PLAYABLE-TODAY.md")
        claim = "这条 demo 今天能玩了。"
        spliced = real + "\n" + claim + "\n"
        flagged = [c.text for c in violations_in("PLAYABLE-TODAY.md", spliced)]
        self.assertIn(claim, flagged, "an over-claim spliced into the real demo doc went unflagged")

    def test_hedged_lines_are_not_flagged(self):
        """Positive control — a hedge must suppress, or the check is noise."""
        for text in (
            "这条 demo 今天还不能玩。",
            "图触发尚未验证。",
            "demo 能玩只是候选，未真机。",
            "离能玩还差三步。",
            "只有试玩里被观察到才算能玩。",
            "**离线 ≠ 能玩**。",
            "`actionStatus 0` 单独不证落盘。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    violations_in("(synthetic)", text), [],
                    f"a hedged line was treated as an over-claim: {text}",
                )

    def test_artefact_backed_claim_is_not_flagged(self):
        """Positive control — a real cited artefact must suppress."""
        for text in (
            "这条链已跑通（原件 `docs/gameplan/VERTICAL-SLICE.md`）。",
            "图触发已验证，回执 `tools/gameplan/tests/test_demo_claims.py`。",
        ):
            with self.subTest(text=text):
                bad = violations_in("(synthetic)", text)
                self.assertEqual(bad, [], f"an artefact-backed claim was flagged: {text}")

        # ... and a claim citing a path that does NOT exist is flagged (not backed).
        bogus = violations_in(
            "(synthetic)",
            "这条链已跑通，原件 `.runtime/authoring/requests/"
            "00000000000000000000000000000000/result.json`。",
        )
        self.assertEqual(len(bogus), 1, "a claim citing a missing path was treated as backed")

    def test_mentions_are_not_claims(self):
        """Filenames, dotted fields, camelCase fields, headings and fences are not claims."""
        for text in (
            "见 `docs/gameplan/PLAYABLE-TODAY.md:54`。",          # filename mention
            "回执字段 `level.verified:true` 由 `live.py` 填。",   # dotted field
            "`runtimeVerified:false` / `officialPlaytestVerified:false`。",  # camelCase
            "# PLAYABLE-TODAY — 一个人今天能玩到这条 demo 吗？",  # heading (question label)
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    claims_in("(synthetic)", text), [],
                    f"a mention was treated as a claim: {text}",
                )

        fenced = "```\n\"verified\": true\n能玩 playable\n```\n"
        self.assertEqual(
            claims_in("(synthetic)", fenced), [],
            "a fenced code block (receipt shape) was scanned as a claim",
        )

    def test_claim_and_hedge_across_a_wrap_stay_together(self):
        """A wrap must not split a claim from its hedge on the next line."""
        text = (
            "**今天一个人不能玩到这条 demo**，第一道门是第 4 步 `92 进入碰撞触发器时`\n"
            "永远不会触发；它身后每一步都缺一个已证不存在的写入原语。\n"
        )
        self.assertEqual(
            violations_in("(synthetic)", text), [],
            "a hedged claim was split by a wrap and wrongly flagged",
        )


# --------------------------------------------------------------------------- #
# Three more over-claim shapes the 2026-10-11 session produced.
#
# Each was caught only by an adversary, and each wore a *different* disguise of
# the same sin — a claim stated more strongly than the evidence carries.  A
# guard is worth adding only where the disguise leaves a mechanically checkable
# residue in the prose; where it does not, the rule stays prose (see the module
# docstring's closing section).  A guard that cannot fail is worse than none.
# --------------------------------------------------------------------------- #

# --- (i) independence of artefacts, refuted by the same doc's own pull log ---
#
# The session counted its captured artefacts and called them "N 份互不依赖",
# while *another section of the same doc* said two of them are outputs of ONE
# debug-log pull (近似 1:1).  Independence is not a property you get by counting
# files; it must come from an axis the doc can point at.
#
# The claim is scoped to *artefacts* (产物/文件/回执/记录/日志/证据/证物/份/输出).
# The doctrine's legitimate independent axis is "两条腿" — the minted-string
# freshness leg vs the pre-registered-prediction leg — and a count of *legs* is
# exactly what the honest docs give ("独立性只来自腿 A 与腿 B"), so 腿 is
# deliberately NOT an artefact noun and a legs-only line cannot fire.
_INDEP_MUTUAL = re.compile(r"互不依赖|互相独立|彼此独立|相互独立|(?<![A-Za-z])independent", re.IGNORECASE)
_INDEP_ARTIFACT = re.compile(r"份|产物|文件|回执|记录|日志|证据|证物|输出")
# The artefact and the independence word must be *near* each other, not merely
# co-present in a wrapped unit: the same-pull sentence ("同一会话的两份产物…")
# is itself artefact-laden, so a whole-unit test would fire on the doc's own
# correction.  A claim is «N 份 <artefact> 互不依赖», within one sentence.
_INDEP_WINDOW = 24
_INDEP_CLAIM = re.compile(
    r"(?:份|产物|文件|回执|记录|日志|证据|证物|输出)[^\n]{0,%d}(?:互不依赖|互相独立|彼此独立|相互独立)"
    r"|(?:互不依赖|互相独立|彼此独立|相互独立)[^\n]{0,%d}(?:份|产物|文件|回执|记录|日志|证据|证物|输出)"
    r"|(?:[0-9]+|[两三四五六七八九十])\s*份\s*(?:互不依赖|互相独立|彼此独立|相互独立)"
    % (_INDEP_WINDOW, _INDEP_WINDOW),
    re.IGNORECASE,
)
# ... the same document, *elsewhere*, saying the artefacts share one source.
_SAME_PULL = re.compile(
    r"同一会话|同一次拉取|同一拉取|同一个拉取|一次拉取|两份产物|"
    r"同一次调试日志|同一调试日志|同一次调试日志拉取",
    re.IGNORECASE,
)
# A hedge turns the unit into a correction, not a claim — the honest docs write
# 「不写『三份互不依赖』」 / 「互相不独立」, where the negation is the point.
_INDEP_HEDGE = re.compile(r"不|非|≠|只|仅|不是|不能|无|没|未|并|更正|已改|口径|not|never", re.IGNORECASE)


def is_independence_claim(blob: str) -> bool:
    """True iff ``blob`` calls two or more *artefacts* mutually independent."""
    return bool(_INDEP_CLAIM.search(blob))


@dataclass(frozen=True)
class IndependenceClaim:
    """An artefact-independence claim and whether the doc refutes it elsewhere."""

    doc: str
    line: int
    text: str
    hedged: bool
    doc_has_same_pull: bool

    @property
    def violation(self) -> bool:
        """Artefacts called independent in a doc that elsewhere names one pull."""
        return self.doc_has_same_pull and not self.hedged

    def report(self) -> str:
        return (
            f"{self.doc}:{self.line}: artefacts called independent while the same "
            f"doc names a shared pull -- {self.text[:80]!r}"
        )


def independence_claims(doc: str, text: str) -> list[IndependenceClaim]:
    """Every artefact-independence claim in ``text`` (hedged or not).

    ``doc_has_same_pull`` is a whole-document property: the rule is
    «the same document *elsewhere* says they come from one pull», not «nearby».
    """
    same_pull = bool(_SAME_PULL.search(text))
    found: list[IndependenceClaim] = []
    for line_no, lines, in_fence in units(text):
        if in_fence:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            continue
        blob = "\n".join(lines)
        if is_independence_claim(blob):
            # The claim word itself carries a 不 («互不依赖»); the hedge must be a
            # negation *about* the claim, so test it on the blob with the claim
            # phrases removed — otherwise «互不依赖» would hedge itself.
            residue = _INDEP_MUTUAL.sub("", blob)
            found.append(
                IndependenceClaim(
                    doc=doc,
                    line=line_no,
                    text=first,
                    hedged=bool(_INDEP_HEDGE.search(residue)),
                    doc_has_same_pull=same_pull,
                )
            )
    return found


def scan_independence() -> tuple[list[IndependenceClaim], list[IndependenceClaim]]:
    """Scan every gameplan doc; return ``(all claims, violating claims)``."""
    claims: list[IndependenceClaim] = []
    for rel in scanned_docs():
        claims.extend(independence_claims(rel, _read(REPO / rel)))
    return claims, [c for c in claims if c.violation]


# --- (ii) a captured marker claimed to prove execution, with no freshness ----
#
# A captured string proves a RECORD was received — never that the graph ran
# *now*.  ``GRAPH-RUNTIME-EVIDENCE.md`` §二 puts the whole burden on freshness:
# the string was minted after the last historical artefact (铸串 22:09) and the
# artefact's own timestamp post-dates the mint.  A unit that links a captured
# marker to execution while carrying neither that argument nor a hedge is the
# over-claim the session made ("the marker proves it ran").
_MARKER = re.compile(r"标记|串|捕获|captur|marker|记录|回执|日志|\.gia|record", re.IGNORECASE)
_PROVES = re.compile(r"证明|证实|说明|表明|proves?|proven", re.IGNORECASE)
_EXECUTES = re.compile(
    r"执行|跑过|跑起来|运行|触发|execut|(?<![A-Za-z])ran(?![A-Za-z])|fired|点火", re.IGNORECASE
)
_FRESHNESS = re.compile(
    r"新鲜度|freshness|铸|时间戳|mtime|晚于|早于|先于运行|预注册|时间序|timestamp|时序",
    re.IGNORECASE,
)
_EXEC_HEDGE = re.compile(r"不|没|未|非|只|仅|不能|无法|≠|not|never", re.IGNORECASE)


def is_execution_marker_claim(blob: str) -> bool:
    """True iff ``blob`` links a captured marker to execution."""
    return bool(_MARKER.search(blob) and _PROVES.search(blob) and _EXECUTES.search(blob))


@dataclass(frozen=True)
class MarkerExecutionClaim:
    """A marker→execution claim and whether it survives the freshness test."""

    doc: str
    line: int
    text: str
    hedged: bool
    freshness: bool

    @property
    def violation(self) -> bool:
        """A marker said to prove execution with neither a hedge nor freshness."""
        return not self.hedged and not self.freshness

    def report(self) -> str:
        return (
            f"{self.doc}:{self.line}: a captured marker claimed to prove execution "
            f"with no freshness argument -- {self.text[:80]!r}"
        )


def marker_execution_claims(doc: str, text: str) -> list[MarkerExecutionClaim]:
    """Every marker→execution claim in ``text`` (qualified or not)."""
    found: list[MarkerExecutionClaim] = []
    for line_no, lines, in_fence in units(text):
        if in_fence:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            continue
        blob = "\n".join(lines)
        if is_execution_marker_claim(blob):
            found.append(
                MarkerExecutionClaim(
                    doc=doc,
                    line=line_no,
                    text=first,
                    hedged=bool(_EXEC_HEDGE.search(blob)),
                    freshness=bool(_FRESHNESS.search(blob)),
                )
            )
    return found


def scan_marker_execution() -> tuple[list[MarkerExecutionClaim], list[MarkerExecutionClaim]]:
    """Scan every gameplan doc; return ``(all claims, violating claims)``."""
    claims: list[MarkerExecutionClaim] = []
    for rel in scanned_docs():
        claims.extend(marker_execution_claims(rel, _read(REPO / rel)))
    return claims, [c for c in claims if c.violation]


# --- (iii) a component kind equated to a front-end enum value, unanchored ----
#
# "kind == 8 (Collision)" is the cross-layer identity the session asserted as
# fact.  That the enum member ``Collision`` has value 8 is a static fact of the
# decompiled source; that a *kind* (a native/save-side field, or the front-end
# `componentId` numbering) *equals* it is an inference — ``COLLISION-COMPONENT-
# ID.md`` §2.5/§3.1 keeps it a 假设 with a named 软肋.  Such a line needs either
# a hedge (假设/待真机/推断) or an anchor (a file:line, a § ref, 原件).
_KIND_NUM = r"(?:0x[0-9a-fA-F]+|\d+)"
_KIND_NAME = (
    r"(?:BeyondCompType\w+|Collision|ClientTrigger|CursorCollision|"
    r"StuffBag|EquipStuffBag|Shop|PopUp|HitDetection)"
)
_KIND_IDENTITY = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + _KIND_NAME + r")\s*[=＝]{1,2}\s*" + _KIND_NUM
    + r"|" + _KIND_NUM + r"\s*[=＝]{1,2}\s*(?:" + _KIND_NAME + r")(?![A-Za-z0-9_])"
)
_KIND_FIELD = re.compile(
    r"(?:组件.{0,4}kind|组件id|组件编号|component[_ ]?id|comp\+0x34)\s*[=＝:：]{1,2}\s*" + _KIND_NUM,
    re.IGNORECASE,
)
_KIND_ANCHOR = re.compile(r":\d{1,5}\b|§\s*\d|原件|枚举定义|回执|\.md\b|\.cs\b|sha256")
_KIND_HEDGE = re.compile(r"假设|待|推断|未证|候选|hypothesis|不宣称|不等于|不是|≠|不|未")


def is_kind_equality_claim(blob: str) -> bool:
    """True iff ``blob`` equates a component kind/id with a number or enum name."""
    return bool(_KIND_IDENTITY.search(blob) or _KIND_FIELD.search(blob))


@dataclass(frozen=True)
class KindEqualityClaim:
    """A kind↔enum-value identity and how it is qualified."""

    doc: str
    line: int
    text: str
    hedged: bool
    anchored: bool

    @property
    def violation(self) -> bool:
        """A kind equated to an enum value with neither a hedge nor an anchor."""
        return not self.hedged and not self.anchored

    def report(self) -> str:
        return (
            f"{self.doc}:{self.line}: a component kind equated to an enum value "
            f"with no anchor citation -- {self.text[:80]!r}"
        )


def kind_equality_claims(doc: str, text: str) -> list[KindEqualityClaim]:
    """Every kind↔enum-value identity in ``text`` (qualified or not)."""
    found: list[KindEqualityClaim] = []
    for line_no, lines, in_fence in units(text):
        if in_fence:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            continue
        blob = "\n".join(lines)
        if is_kind_equality_claim(blob):
            found.append(
                KindEqualityClaim(
                    doc=doc,
                    line=line_no,
                    text=first,
                    hedged=bool(_KIND_HEDGE.search(blob)),
                    anchored=bool(_KIND_ANCHOR.search(blob)),
                )
            )
    return found


def scan_kind_equality() -> tuple[list[KindEqualityClaim], list[KindEqualityClaim]]:
    """Scan every gameplan doc; return ``(all claims, violating claims)``."""
    claims: list[KindEqualityClaim] = []
    for rel in scanned_docs():
        claims.extend(kind_equality_claims(rel, _read(REPO / rel)))
    return claims, [c for c in claims if c.violation]


# --------------------------------------------------------------------------- #
# The checks themselves, each tested against what it must catch and let pass.
# --------------------------------------------------------------------------- #

class ArtefactIndependenceContradictsTheOwnPullLog(unittest.TestCase):
    """No doc may call its artefacts independent while itself naming one pull.

    The failure shape (2026-10-11): «三份互不依赖的物证» in a doc whose §五
    says the ``.gia`` and the log-observer row are the *same* debug-log pull.
    Counting artefacts does not manufacture independence; only the two legs do.
    """

    def test_same_pull_docs_exist(self):
        """If no doc names a shared pull, the scan could never fire — so pin one.

        ``GRAPH-RUNTIME-EVIDENCE.md`` is the authority (近似 1:1 ⇒ 同一会话的两份
        产物); a gutted :data:`_SAME_PULL` must fail here, not report a hollow 0.
        """
        docs = [d for d in scanned_docs() if _SAME_PULL.search(_read(REPO / d))]
        self.assertGreaterEqual(
            len(docs), 1,
            f"no gameplan doc states a shared pull ({_SAME_PULL.pattern!r}) — the "
            f"contradiction can never be detected",
        )

    def test_no_unhedged_artefact_independence_claim(self):
        """DRIFT DETECTOR — the real check over ``docs/gameplan/*.md``.

        Flags any logical line that calls artefacts mutually independent while
        the same doc elsewhere says they are outputs of one pull, unless the
        line is hedged.  Today it flags 0; a fresh «N 份互不依赖» turns it red and
        names ``doc:line``.  Fix by hedging or by grounding independence in the
        two legs — **not** by editing this test to ignore it.
        """
        claims, bad = scan_independence()
        report = [c.report() for c in bad]
        self.assertEqual(
            report, [],
            f"{len(bad)} of {len(claims)} artefact-independence claims are stated "
            f"in a doc that itself names a shared pull and carry no hedge:\n  "
            + "\n  ".join(report),
        )

    def test_independence_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty scan."""
        claims, _ = scan_independence()
        self.assertGreaterEqual(
            len(claims), 2,
            f"only {len(claims)} artefact-independence claims found across "
            f"docs/gameplan/*.md — the vocabulary has gone blind",
        )

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible."""
        claims, bad = scan_independence()
        hedged = sum(1 for c in claims if c.hedged)
        print(
            f"\nindependence claim-scan: {len(claims)} artefact-independence claims "
            f"across {len(scanned_docs())} docs; hedged: {hedged}; FAILING: {len(bad)}"
        )
        for c in bad:
            print(f"  FAIL  {c.report()}")

    def test_synthetic_unhedged_independence_claim_fails(self):
        """Negative control: «N 份互不依赖» in a same-pull doc must be flagged."""
        doc = "同一会话的两份产物是一次调试日志拉取。\n\n三份产物互不依赖，各自独立。\n"
        bad = [c for c in independence_claims("(synthetic)", doc) if c.violation]
        self.assertEqual(len(bad), 1, "an unhedged artefact-independence claim was NOT flagged")
        self.assertEqual(bad[0].line, 3)

    def test_hedged_or_legs_only_independence_is_not_flagged(self):
        """Positive control — a hedge, or the legitimate two legs, must suppress.

        Including the real corrected phrasings: 「互相不独立」 (the negation is
        the point) and 「独立性只来自腿 A 与腿 B」 (腿 is not an artefact noun).
        """
        same_pull = "同一会话的两份产物是一次调试日志拉取。\n\n"
        for tail in (
            "产物 1 与产物 2 互相不独立。\n",
            "「产物多」不增高独立性；独立性只来自腿 A 与腿 B。\n",
            "三份产物是否互不依赖尚未判定。\n",
            "两条腿互不依赖（铸串新鲜度 / 预注册预测）。\n",
        ):
            with self.subTest(tail=tail):
                self.assertEqual(
                    [c for c in independence_claims("(synthetic)", same_pull + tail) if c.violation],
                    [],
                    f"a qualified line was treated as an over-claim: {tail!r}",
                )

    def test_independence_claim_spliced_into_a_real_doc_is_flagged(self):
        """The actual failure shape: the over-claim spliced into the authority doc."""
        real = _read(REPO / "docs/gameplan/GRAPH-RUNTIME-EVIDENCE.md")
        claim = "三份捕捉到的产物互不依赖，各自独立证明这次运行。"
        spliced = real + "\n\n" + claim + "\n"
        flagged = [c.text for c in independence_claims("GRAPH-RUNTIME-EVIDENCE.md", spliced) if c.violation]
        self.assertIn(
            claim, flagged,
            "an artefact-independence over-claim spliced into the real doc went unflagged",
        )


class MarkerExecutionClaimsNeedFreshness(unittest.TestCase):
    """No doc may say a captured marker proves execution without freshness."""

    def test_no_execution_marker_claim_without_freshness(self):
        """DRIFT DETECTOR — the real check over ``docs/gameplan/*.md``.

        Flags any logical line that links a captured marker to execution while
        giving neither a freshness argument nor a hedge.  Today it flags 0; a
        fresh «捕获到的串证明这次真的跑了» turns it red.  Fix by adding the
        freshness test (`GRAPH-RUNTIME-EVIDENCE.md` §二) or the hedge.
        """
        claims, bad = scan_marker_execution()
        report = [c.report() for c in bad]
        self.assertEqual(
            report, [],
            f"{len(bad)} of {len(claims)} marker→execution claims carry neither a "
            f"freshness argument nor a hedge:\n  " + "\n  ".join(report),
        )

    def test_marker_execution_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty scan."""
        claims, _ = scan_marker_execution()
        self.assertGreaterEqual(
            len(claims), 3,
            f"only {len(claims)} marker→execution claims found across "
            f"docs/gameplan/*.md — the vocabulary has gone blind",
        )

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible."""
        claims, bad = scan_marker_execution()
        fresh = sum(1 for c in claims if c.freshness)
        print(
            f"\nmarker→execution claim-scan: {len(claims)} claims across "
            f"{len(scanned_docs())} docs; freshness-qualified: {fresh}; FAILING: {len(bad)}"
        )
        for c in bad:
            print(f"  FAIL  {c.report()}")

    def test_synthetic_unhedged_marker_claim_fails(self):
        """Negative control: marker + prove + execute, no freshness, must flag."""
        for text in (
            "捕获到的「四号图入口已触发」证明这张图本次真的执行了。\n",
            "the captured marker proves our graph ran.\n",
        ):
            with self.subTest(text=text):
                bad = [c for c in marker_execution_claims("(synthetic)", text) if c.violation]
                self.assertEqual(len(bad), 1, f"unhedged marker claim not flagged: {text!r}")

    def test_hedged_or_fresh_marker_claims_are_not_flagged(self):
        """Positive control — a hedge, or a freshness argument, must suppress."""
        for text in (
            "一条标记只证明记录被收到，不证明本会话执行。\n",
            "捕获的串证明本次执行——串铸于 22:09、产物时间戳晚于它。\n",
            "The captured row proves the record was received; it does not prove a graph ran.\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    [c for c in marker_execution_claims("(synthetic)", text) if c.violation],
                    [],
                    f"a qualified marker claim was treated as an over-claim: {text}",
                )

    def test_marker_mentions_are_not_claims(self):
        """A marker with no prove verb, or a prove verb with no exec term, is not a claim."""
        for text in (
            "日志里出现「作物不足」×4。\n",      # marker, no prove
            "`.gil` 的 sha256 证明文件被改过。\n",  # prove, no execution
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    marker_execution_claims("(synthetic)", text), [],
                    f"a mention was treated as a marker→execution claim: {text}",
                )

    def test_marker_claim_spliced_into_a_real_doc_is_flagged(self):
        """The actual failure shape: the over-claim spliced into a real doc."""
        real = _read(REPO / "docs/gameplan/PLAYABLE-TODAY.md")
        claim = "捕获到的「四号图入口已触发」证明这张图本次已经执行。"
        spliced = real + "\n\n" + claim + "\n"
        flagged = [c.text for c in marker_execution_claims("PLAYABLE-TODAY.md", spliced) if c.violation]
        self.assertIn(
            claim, flagged,
            "a marker→execution over-claim spliced into a real doc went unflagged",
        )


class ComponentKindEqualityNeedsAnchor(unittest.TestCase):
    """No doc may equate a component kind to an enum value with no anchor."""

    def test_no_unanchored_kind_equality(self):
        """DRIFT DETECTOR — the real check over ``docs/gameplan/*.md``.

        Flags any logical line that equates a component kind/id with a number or
        a front-end enum member value while giving neither a hedge nor an anchor
        (a file:line, a § ref, 原件).  Today it flags 0; a fresh bare
        «组件 kind = 8（Collision）» turns it red.  Fix by hedging (假设/待真机) or
        by anchoring the identity — **not** by editing this test to ignore it.
        """
        claims, bad = scan_kind_equality()
        report = [c.report() for c in bad]
        self.assertEqual(
            report, [],
            f"{len(bad)} of {len(claims)} kind↔enum-value identities carry neither "
            f"a hedge nor an anchor citation:\n  " + "\n  ".join(report),
        )

    def test_kind_equality_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty scan."""
        claims, _ = scan_kind_equality()
        self.assertGreaterEqual(
            len(claims), 2,
            f"only {len(claims)} kind↔enum-value identities found across "
            f"docs/gameplan/*.md — the vocabulary has gone blind",
        )

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible."""
        claims, bad = scan_kind_equality()
        anchored = sum(1 for c in claims if c.anchored)
        print(
            f"\nkind-equality claim-scan: {len(claims)} kind↔enum identities across "
            f"{len(scanned_docs())} docs; anchored: {anchored}; FAILING: {len(bad)}"
        )
        for c in bad:
            print(f"  FAIL  {c.report()}")

    def test_synthetic_unanchored_kind_equality_fails(self):
        """Negative control: a bare kind↔enum identity with no anchor must flag."""
        for text in (
            "实体上组件的 kind = 8，即 Collision（碰撞触发器）。\n",
            "componentId == 8\n",
        ):
            with self.subTest(text=text):
                bad = [c for c in kind_equality_claims("(synthetic)", text) if c.violation]
                self.assertEqual(len(bad), 1, f"unanchored kind identity not flagged: {text!r}")

    def test_hedged_or_anchored_kind_equality_is_not_flagged(self):
        """Positive control — a hedge or an anchor citation must suppress."""
        for text in (
            "假设：碰撞触发器组件的读回 id = 8（待真机读回证实/证伪）。\n",
            "`BeyondCompTypeCollision = 8`（`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:12`）。\n",
            "组件 kind 与前端枚举值的对齐尚未真机证实（`COLLISION-COMPONENT-ID.md` §2.5）。\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    [c for c in kind_equality_claims("(synthetic)", text) if c.violation],
                    [],
                    f"a qualified kind identity was treated as an over-claim: {text}",
                )

    def test_kind_equality_spliced_into_a_real_doc_is_flagged(self):
        """The actual failure shape: the over-claim spliced into a real doc."""
        real = _read(REPO / "docs/gameplan/COMPONENT-DATA-SIDE.md")
        claim = "所以我们实体上那个组件的 kind = 8（Collision）。"
        spliced = real + "\n\n" + claim + "\n"
        flagged = [c.text for c in kind_equality_claims("COMPONENT-DATA-SIDE.md", spliced) if c.violation]
        self.assertIn(
            claim, flagged,
            "a kind↔enum-value over-claim spliced into a real doc went unflagged",
        )


if __name__ == "__main__":
    unittest.main()
