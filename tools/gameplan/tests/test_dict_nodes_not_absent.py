"""Guard: a FINITE, enumerated set of retracted "no dictionary node" phrasings.

Read this before "improving" the detector
=========================================
The claim *"the dictionary node family is absent"* was retracted on 2026-10-12;
it was one of **our own false negatives**.  This guard keeps the retracted
wording out of the live prose.  It has been **defeated three times**, each time
by re-wording the same false claim (running record:
``.runtime/scratch/PROSE-GUARD-DESIGN.md``):

  * **round 1** -- the scan ``rglob``\\ d only ``*.py`` (the claim lived in
    ``.md``) and the banned list was a single exact sentence;
  * **round 2** -- the scan widened to ``.md`` and the detector was re-keyed on a
    *shape*, but every CJK shape hard-coded the word order (quantifier before
    predicate) and the measure word 条, and the English side was one template;
  * **round 3** -- four re-wordings were planted in every covered root and all
    four stayed **inert**: ``字典构造节点并不存在`` (order reversed),
    ``无字典构造节点`` (no measure word), ``0 个节点构造字典`` (measure word 个,
    predicate last), ``there is no dictionary-building node`` (English, verb
    inside the compound noun).

**Detecting "does this natural-language sentence restate a retracted negative" by
regex is not solvable, and three rounds prove it.**  So this guard does **not**
claim to be general.  It does exactly two honest, finite things:

1.  It checks a **finite, enumerated set of literal forms** -- the ten listed
    under "The forms checked" below and implemented in :data:`_CLAIM_SHAPES`.
    **A novel phrasing of the same false claim is OUT OF SCOPE and will NOT be
    caught.**  When you meet one, add its literal form to :data:`_CLAIM_SHAPES`,
    add a sample to :data:`BANNED_SAMPLES`, and add a mutation test.  Do **not**
    assume the guard already covers it -- it does not, and it says so.

2.  It waives a hit **only** on an exact-line match against a checked-in
    allowlist (:data:`_ALLOWLIST_PATH`).  The allowlist names the handful of
    lines that legitimately *quote* the retracted claim in order to refute it.
    A new quote-to-refute line therefore **FIRES by default** and must be added
    to the allowlist by a human, with a reason.  There is **no vocabulary window
    and no proximity heuristic**: the round-2 waiver ("a refutation cue within
    six lines") was a marker, and the project's L7 discipline forbids keying a
    detector on a marker -- a bare re-assertion sitting next to an unrelated cue
    (``本表已更正过多次。``) was swallowed by it.

What is TRUE, and must survive
==============================
Re-derived read-only from ``data/node-contracts`` (the editor's own node store;
no bridge, no game, no save):

  * **constructors** -- ``1088 建立字典`` and ``1788 拼装字典`` (server), the
    in-place ``948 对字典设置或新增键值对``, and the client mirrors ``200153`` /
    ``200229`` (建立字典) and ``200152`` / ``200228`` (拼装字典);
  * **accessor** -- ``1158 以键查询字典值`` (with the rest of the family: 1298 /
    1368 / 1438 / 1508 / 1578 / 1648 / 1718 / 1928 / 1938).

The correcting sentence must not swing the other way either:

  * a dict **constant** still cannot be written -- ``SLOT_FOR_TYPE[27] is None``
    and ``AuthorWriteScalar`` has no dict branch, so a type-27 value cannot be
    serialised into a pin at all;
  * every one of the 8 ``serverParamType == 27`` OUTPUT pins in the 500-definition
    server store (705 / 717 / 718 / 719 / 721 / 722 / 730 / 731) is a bag/store
    READ or an event -- **none is a constructor**; the constructors declare their
    dict pins as **Generics** (``serverParamType == 0``), NOT as concrete 27;
  * the shop price pin (``704`` / ``706`` / ``709`` input 出售货币字典) is concrete
    type 27, and whether a generic constructor specialises to it is UNPROVEN.

Scope of the scan
=================
Every live ``.py`` and ``.md`` under ``tools/gameplan/``, every ``.md`` under
``docs/``, and the repo-root ``*.md`` -- **except** two categories that are
deliberately OUT, each for a stated reason:

  * ``__pycache__`` / ``.pytest_cache`` -- generated, not prose;
  * ``docs/**/archive/**`` -- **frozen snapshots** of superseded files (the
    doctrine "过期就地标注、不替换" governs *live* docs, not archived copies;
    the record is kept, not edited).  Dated *research* directories such as
    ``docs/research/reverse-eng-20261010/`` are NOT archives -- they are live
    notes we do annotate in place, so they stay in scope.

The forms checked (this is the whole list)
==========================================
  * **F1**  CJK absence quantifier (没有/无/不存在/尚无) + optional 一条 + <=2
    filler + 构造|建立|拼装字典 -- e.g. ``没有一条构造字典``.
  * **F2**  CJK numeric/``N`` count + 条 + 构造字典 (or 构造或取元素) -- e.g.
    ``500 条定义中 0 条构造字典``.
  * **F3**  CJK absence quantifier + dict-*accessor* absence (取/查/读字典 ... 节点|元素).
  * **F4**  English ``no <x> constructs/builds/creates a dict``.
  * **F5**  English ``no (dict )constructor``.
  * **F6**  English ``no dict-access node``.
  * **F7**  CJK ``字典构造节点/器`` + trailing absence predicate -- e.g.
    ``字典构造节点并不存在`` (round-3 evasion 1: word order reversed).
  * **F8**  CJK absence quantifier + ``字典构造`` + 节点/器 -- e.g.
    ``无字典构造节点`` (round-3 evasion 2: no measure word).
  * **F9**  CJK numeric/``N`` count + 个 + <=6 filler + 构造|建立|拼装字典 --
    e.g. ``0 个节点构造字典`` (round-3 evasion 3: measure word 个, predicate last).
  * **F10** English ``no dictionary-<build|construct|creat>... node`` -- e.g.
    ``there is no dictionary-building node`` (round-3 evasion 4).

What is OUT OF SCOPE (provably)
===============================
Anything not in F1..F10.  Concretely, all of these sail straight through and are
*known* to: a synonym for 构造 we have not written down; a phrasing that puts the
measure word somewhere none of F1..F9 allows; an English sentence whose verb is a
word outside ``build/construct/create``; a claim expressed as a table cell with no
verb.  **This is a fact about the guard, not a bug to file.**  A guard that admits
its boundary is useful; one that claims generality it was never mutation-tested
for is a false-confidence machine.

A maintainer who meets a new phrasing should: (i) confirm it is the same false
claim; (ii) add its literal to :data:`_CLAIM_SHAPES`; (iii) add the exact string
to :data:`BANNED_SAMPLES`; (iv) confirm the new mutation test fires.  If it is a
legitimate *refutation* line, add the line to the allowlist instead (see
:data:`_ALLOWLIST_PATH`), with a reason.
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, default_store

_REPO = Path(__file__).resolve().parents[3]
_GAMEPLAN = _REPO / "tools" / "gameplan"

#: The corrected marker each formerly-wrong file must carry -- the fact, not the
#: retraction.  (These three were the round-1 false-negative homes.)
#: ``(path, substring)``; a substring that only appears once the fix is in place.
_CORRECTED_MARKERS = (
    (_GAMEPLAN / "modules" / "shop.py", "1088"),
    (_GAMEPLAN / "modules" / "shop.py", "1788"),
    (_GAMEPLAN / "modules" / "inventory.py", "1158"),
    (_GAMEPLAN / "demo" / "farming_m4.py", "1158"),
)

# --------------------------------------------------------------------------- #
# The detector: the FINITE enumerated set of retracted literal forms (F1..F10).
# --------------------------------------------------------------------------- #
#
# Every pattern below is one *form we have seen* -- nothing here is claimed to
# cover a form we have not seen.  Add to this tuple, never "generalise" it.
_CLAIM_SHAPES = (
    # F1 -- CJK: absence quantifier + optional "一条" + <=2 filler + 构造/建立/拼装字典.
    re.compile(
        r"(?:没有|沒有|无|無|不存在|尚无)\s*(?:任何|一条|一條|一条都|一条也)?"
        r"\s*条?\s*[^\n。；;]{0,2}(?:构造|建立|拼装)字典"
    ),
    # F2 -- CJK: numeric (or metavariable "N") count directly bound to the predicate.
    re.compile(r"(?:\d+|[Nn])\s*条\s*(?:构造字典|构造或取元素|构造[^\n。；;]{0,2}字典)"),
    # F3 -- CJK: absence quantifier + dict *accessor* absence (the round-1 inventory claim).
    re.compile(
        r"(?:没有|沒有|无|無|尚无)[^\n。；;]{0,8}(?:取|查|读)字典[^\n。；;]{0,4}(?:节点|元素)"
    ),
    # F4 -- English: "no <x> constructs/builds/creates a dict".
    re.compile(
        r"\bno\b[^\n.;]{0,40}\b(?:construct|build|create)\w*\b[^\n.;]{0,25}\bdict(?:ionary)?\b",
        re.IGNORECASE,
    ),
    # F5 -- English: "no dict constructor" / "no dictionary constructor".
    re.compile(r"\bno\s+(?:dict(?:ionary)?\s+)?constructor\b", re.IGNORECASE),
    # F6 -- English: "no dict-access node" / "no dictionary accessor node".
    re.compile(
        r"\bno\s+(?:dict|dictionary)[-\s]?(?:access|accessor)\s+node\b", re.IGNORECASE
    ),
    # F7 -- CJK, round-3 evasion 1: 字典构造节点/器 + a TRAILING absence predicate
    # (word order reversed -- the predicate follows the noun).
    re.compile(r"字典构造(?:节点|器)[^\n。；;]{0,4}(?:并不存在|不存在|是没有的|没有)"),
    # F8 -- CJK, round-3 evasion 2: absence quantifier BEFORE 字典构造, no measure
    # word at all.  The 0..4 gap deliberately excludes 的: a 的 before the noun
    # marks a *modifier*, i.e. a scoped subset ("64-bit 有而 uint32 没有的字典构造器"
    # is a true, scoped statement -- F8 must not fire on it), whereas the retracted
    # claim puts the quantifier straight onto the family noun ("无字典构造节点").
    re.compile(
        r"(?:没有|沒有|无|無|不存在|尚无|并不存在)\s*[^\n。；;的]{0,4}字典构造[^\n。；;]{0,4}(?:节点|器)"
    ),
    # F9 -- CJK, round-3 evasion 3: count + 个 (measure word, not 条) + filler + predicate.
    re.compile(r"(?:\d+|[Nn])\s*个\s*[^\n。；;]{0,6}(?:构造|建立|拼装)字典"),
    # F10 -- English, round-3 evasion 4: "no dictionary-building node" (the verb sits
    # inside the compound noun, so F4/F5/F6 all miss it).
    re.compile(
        r"\bno\s+(?:dict|dictionary)[-\s]?(?:build|construct|creat)\w*\s+node\b",
        re.IGNORECASE,
    ),
)

#: One human description per pattern, same order as :data:`_CLAIM_SHAPES`.
#: A test asserts the two stay the same length -- the documentation cannot rot away
#: from the code without the suite noticing.
_FORM_NOTES = (
    "F1  CJK absence quantifier + <=2 filler + 构造/建立/拼装字典",
    "F2  CJK numeric/N count + 条 + 构造字典 / 构造或取元素",
    "F3  CJK absence quantifier + dict-accessor absence",
    "F4  EN 'no <x> constructs/builds/creates a dict'",
    "F5  EN 'no (dict )constructor'",
    "F6  EN 'no dict-access node'",
    "F7  CJK '字典构造节点/器' + trailing absence predicate (round-3 #1)",
    "F8  CJK absence quantifier + '字典构造' + 节点/器 (round-3 #2; gap excludes 的)",
    "F9  CJK numeric/N count + 个 + filler + 构造字典 (round-3 #3)",
    "F10 EN 'no dictionary-building node' (round-3 #4)",
)

#: The banned literals, kept as *data* so every mutation test plants a real one.
#: ``F1..F10`` above must each catch at least one of these (see the tests).
BANNED_SAMPLES = (
    "没有一条构造字典",
    "无一条构造字典",
    "0 条构造字典",
    "500 条定义中 0 条构造字典",
    "N 条构造字典",
    "无任何节点构造字典",
    '本工程尚无经证明的"取字典元素"节点',
    "no server node builds a dict",
    "no server node constructs a dict",
    "there is no dictionary constructor",
    "no dict-access node",
    "no dict accessor node",
    "0 条构造或取元素",
    # --- round-3 evasions: planted inert in every root before the rebuild ---
    "字典构造节点并不存在",          # F7  order reversed
    "无字典构造节点",                # F8  no measure word
    "0 个节点构造字典",              # F9  measure word 个
    "there is no dictionary-building node",  # F10 English, verb in the compound
)

#: Correctly-worded prose that must NOT trip any form (negative control).
CORRECT_PROSE_SAMPLES = (
    "建立字典 1088 与取元素 1158 都在；构造器为泛型引脚 spt 0",
    "字典构造器 1088/1788/948 存在，缺的是把字典写成常量",
    "这 8 条里没有一条是从输入构造字典",  # true of the 8 type-27 OUTPUT pins
    "- 「64-bit 有而 uint32 没有的字典构造器」→ **无**。",  # scoped-true subset negative
)

#: Prose that QUOTES the claim to refute it.  Under the fail-closed design these
#: FIRE unless the exact line is on the allowlist -- which is the point: only an
#: allowlisted *line in the repo* is waived, never a cue beside a bare claim.
#: Kept as data so a test can plant each and prove it still fires.
REFUTATION_SAMPLES_THAT_FIRE = (
    "旧句「500 条定义里没有一条构造字典」是过度概括",
    "this module used to assert that the server side had no dict constructor at all; "
    "that was a false negative",
    "500 条定义中 0 条构造字典 —— 该说法已被推翻",
)


# --------------------------------------------------------------------------- #
# The fail-closed waiver: an exact-line allowlist.  No vocabulary, no proximity.
# --------------------------------------------------------------------------- #
_ALLOWLIST_PATH = Path(__file__).with_name("dict_claim_allowlist.json")


def _normalise(line: str) -> str:
    """Collapse runs of whitespace and strip -- the unit the allowlist hashes.

    Two lines that differ only in spacing are the same prose; collapsing makes
    the allowlist stable against column re-padding without letting a *content*
    change (an added claim on the same line) slip through.
    """
    return re.sub(r"\s+", " ", line).strip()


def _line_digest(line: str) -> str:
    return hashlib.sha256(_normalise(line).encode("utf-8")).hexdigest()


def _load_allowlist() -> dict[tuple[str, str], dict]:
    """``{(rel_path, line_digest): entry}`` read from the checked-in JSON."""
    raw = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    table: dict[tuple[str, str], dict] = {}
    for entry in raw["allow"]:
        table[(entry["file"], entry["sha256"])] = entry
    return table


_ALLOWLIST_CACHE: dict[tuple[str, str], dict] | None = None


def _allowlist() -> dict[tuple[str, str], dict]:
    """The allowlist, parsed once per process."""
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is None:
        _ALLOWLIST_CACHE = _load_allowlist()
    return _ALLOWLIST_CACHE


def _rel_of(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return path.name


def _is_waived(rel: str, line: str) -> bool:
    """True iff this exact ``(rel, normalised line)`` is on the allowlist.

    The *only* waiver.  A hit whose line is not byte-for-byte (modulo whitespace)
    an allowlist entry is an assertion and FIRES -- even if an allowlisted line
    sits directly above it.  That is the fail-closed property the round-2
    vocabulary window destroyed.
    """
    return (rel, _line_digest(line)) in _allowlist()


def _claim_hits(text: str) -> list[str]:
    """Raw form hits in *text*, ignoring the allowlist (used for controls)."""
    return [m.group(0) for pat in _CLAIM_SHAPES if (m := pat.search(text))]


def _hits_in_lines(rel: str, lines: list[str], *, waive: bool) -> list[tuple[int, str]]:
    """``(1-based line number, matched text)`` for every line that fires.

    With ``waive=True`` a line is skipped only when :func:`_is_waived` accepts it
    *exactly*.  Exposed (rather than inlined) so a test can hand it a synthetic
    ``(rel, lines)`` and prove the line granularity.
    """
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        for pat in _CLAIM_SHAPES:
            match = pat.search(line)
            if match:
                if waive and _is_waived(rel, line):
                    break
                out.append((i + 1, match.group(0)))
                break
    return out


def _asserting_hits(path: Path) -> list[str]:
    """Form hits in *path* that are NOT waived by an exact allowlist entry."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rel = _rel_of(path)
    return [f"{rel}:{ln}: {txt!r}" for ln, txt in _hits_in_lines(rel, lines, waive=True)]


# --------------------------------------------------------------------------- #
# The scan surface -- the live prose, with only generated/frozen paths excluded.
# --------------------------------------------------------------------------- #

#: Directory-name parts whose files are OUT of scope (see the module docstring).
_EXCLUDED_PARTS = ("__pycache__", ".pytest_cache", "archive")


def _scan_files() -> list[Path]:
    """Every live prose file in scope: gameplan (py+md), docs (**/*.md), root *.md."""
    me = Path(__file__).resolve()
    seen: set[Path] = set()
    out: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or resolved == me:
            return
        try:
            rel = resolved.relative_to(_REPO).as_posix()
        except ValueError:
            rel = resolved.as_posix()
        if any(part in rel.split("/") for part in _EXCLUDED_PARTS):
            return
        seen.add(resolved)
        out.append(path)

    for ext in ("*.py", "*.md"):
        for path in sorted(_GAMEPLAN.rglob(ext)):
            add(path)
    for path in sorted((_REPO / "docs").rglob("*.md")):
        add(path)
    for path in sorted(_REPO.glob("*.md")):
        add(path)
    return out


# --------------------------------------------------------------------------- #
# Positive evidence: the dict nodes really are in the contract store.
# --------------------------------------------------------------------------- #

class DictNodesExistInTheContractStore(unittest.TestCase):
    """The counter-evidence, read straight from ``data/node-contracts`` (read-only)."""

    def test_constructors_and_accessor_are_present(self):
        store = default_store()
        for nid, name in (
            (1088, "建立字典"),
            (1788, "拼装字典"),
            (948, "对字典设置或新增键值对"),
            (1158, "以键查询字典值"),
        ):
            definition = store.get(nid)
            self.assertIsNotNone(
                definition,
                f"defId {nid} is missing from the server contract store -- either the "
                f"store was pruned or this guard's premise broke",
            )
            self.assertEqual(definition.name, name)

    def test_constructor_dict_pins_are_generic_not_concrete_27(self):
        for nid in (1088, 1788):
            definition = default_store().require(nid)
            dict_out = [
                p for p in definition.ports
                if p.kind == DATA_OUTPUT and p.name == "字典"
            ]
            self.assertTrue(dict_out, f"defId {nid} has no 字典 output pin")
            # Generic (serverParamType 0) -- NOT the shop's concrete type 27.
            self.assertEqual(dict_out[0].server_param_type, 0)

    def test_shop_price_pin_is_concrete_type_27(self):
        definition = default_store().require(704)
        pin = definition.port(DATA_INPUT, 4)
        self.assertIsNotNone(pin, "704 input 3:4 (出售货币字典) is gone")
        self.assertEqual(pin.name, "出售货币字典")
        self.assertEqual(pin.server_param_type, 27)

    def test_no_type27_output_is_a_constructor(self):
        store = default_store()
        pins = sorted(
            (nid, p.index)
            for nid in store
            for p in store.require(nid).ports
            if p.kind == DATA_OUTPUT and p.server_param_type == 27
        )
        self.assertEqual(
            pins,
            [(705, 4), (717, 1), (718, 0), (719, 0), (721, 0), (722, 0), (730, 0), (731, 0)],
            "the set of serverParamType==27 OUTPUT pins changed; re-check the "
            "'every type-27 output is a read/event, none is a constructor' claim",
        )
        self.assertFalse(
            {nid for nid, _ in pins} & {1088, 1788, 948},
            "a dict constructor grew a type-27 output -- the narrow truth changed",
        )

    def test_client_side_mirrors_exist(self):
        # ``load_store`` rejects the client dir (it carries a ``200009`` duplicate with
        # differing content), so read the buckets directly -- a plain presence check.
        client = _REPO / "data" / "node-contracts" / "variants" / "client"
        names: dict[int, str] = {}
        for bucket in sorted(client.glob("bucket-*.json")):
            for rec in json.loads(bucket.read_text(encoding="utf-8")):
                names[rec["stableKey"]["definitionId"]] = rec.get("name")
        self.assertEqual(names.get(200153), "建立字典")
        self.assertEqual(names.get(200152), "拼装字典")
        self.assertIn(200229, names)
        self.assertIn(200228, names)


# --------------------------------------------------------------------------- #
# The prose guard: no live file re-asserts the absence.
# --------------------------------------------------------------------------- #

class NoLiveProseReassertsTheAbsence(unittest.TestCase):
    def test_every_enumerated_form_has_a_documented_note(self):
        """The docstring list and the code stay the same length."""
        self.assertEqual(
            len(_CLAIM_SHAPES), len(_FORM_NOTES),
            "a form was added/removed without a matching entry in _FORM_NOTES "
            "(and therefore in the module docstring)",
        )

    def test_the_detector_fires_on_every_banned_spelling(self):
        """Positive control: the instrument FIREs on each enumerated literal."""
        for sample in BANNED_SAMPLES:
            self.assertTrue(
                _claim_hits(sample),
                f"the form detector misses the banned spelling {sample!r} -- if this "
                f"is a NEW phrasing, it is out of scope by design; add it explicitly",
            )

    def test_the_round3_evasions_fire_on_their_named_forms(self):
        """The four round-3 evasions are caught -- by the form named for each."""
        named = {
            6: "字典构造节点并不存在",              # F7
            7: "无字典构造节点",                    # F8
            8: "0 个节点构造字典",                  # F9
            9: "there is no dictionary-building node",  # F10
        }
        for index, sample in named.items():
            self.assertTrue(
                _CLAIM_SHAPES[index].search(sample),
                f"{_FORM_NOTES[index]} does not catch its own round-3 evasion {sample!r}",
            )

    def test_the_detector_stays_silent_on_correct_prose(self):
        """Negative control: correctly-worded prose must NOT trip any form."""
        for sample in CORRECT_PROSE_SAMPLES:
            self.assertEqual(
                _claim_hits(sample), [],
                f"the detector false-positives on correct prose {sample!r}",
            )

    def test_each_form_is_distinct_from_its_neighbours(self):
        """A crude sanity check that no form was pasted twice."""
        sources = [p.pattern for p in _CLAIM_SHAPES]
        self.assertEqual(len(sources), len(set(sources)), "a form pattern is duplicated")

    def test_an_out_of_allowlist_refutation_still_fires(self):
        """Fail-closed: quoting the claim to refute it is NOT enough -- it fires.

        Only an exact allowlist line is waived.  Prose that merely *reads* like a
        refutation (cue words and all) is treated as an assertion, because the
        round-2 waiver that accepted cue words was the second defect.
        """
        for sample in REFUTATION_SAMPLES_THAT_FIRE:
            hits = _hits_in_lines("some/nowhere.md", [sample], waive=True)
            self.assertTrue(
                hits,
                f"an un-allowlisted refutation was silently waived: {sample!r}",
            )

    def test_the_allowlist_does_not_rot(self):
        """(a) Every allowlist entry still matches a real line in the repo.

        If the line was edited, this fails and a human must regenerate the entry
        *and* confirm the new wording still refutes rather than asserts.
        """
        for (rel, digest), entry in _load_allowlist().items():
            path = _REPO / rel
            self.assertTrue(path.is_file(), f"allowlist names a missing file: {rel}")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            matching = [ln for ln in lines if _line_digest(ln) == digest]
            self.assertTrue(
                matching,
                f"allowlist entry for {rel}:{entry.get('line')} ({entry.get('reason')}) "
                f"no longer matches any line -- the line was edited or removed. "
                f"Regenerate the entry and confirm the new wording still REFUTES.",
            )
            excerpt = _normalise(entry.get("excerpt", ""))
            if excerpt:
                self.assertTrue(
                    any(_normalise(ln).startswith(excerpt) for ln in matching),
                    f"allowlist excerpt for {rel}:{entry.get('line')} no longer matches "
                    f"the allowlisted line",
                )

    def test_a_bare_claim_next_to_an_allowlisted_line_fires(self):
        """(b) Proximity does NOT waive: a bare claim beside an allowed line fires.

        This is the exact defect the round-2 vocabulary window produced: a bare
        re-assertion was swallowed when an unrelated cue sat within six lines.
        """
        table = _load_allowlist()
        # Pick a real allowlist entry and recover the raw line it matches.
        rel, digest = sorted(table)[0]
        lines = (_REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        allowed_raw = next(ln for ln in lines if _line_digest(ln) == digest)
        bare = "0 个节点构造字典"  # a known form, NOT an allowlist entry

        # Same file, adjacent lines: allowed line first, bare claim second.
        hits = _hits_in_lines(rel, [allowed_raw, bare], waive=True)
        self.assertEqual(
            [ln for ln, _ in hits], [2],
            f"a bare claim adjacent to an allowlisted line in {rel} must fire (got {hits})",
        )

    def test_the_scan_surface_is_not_vacuous(self):
        """Prove the widened scan really reaches docs/ and the repo root."""
        rels = {
            p.resolve().relative_to(_REPO).as_posix()
            for p in _scan_files()
            if p.resolve().is_relative_to(_REPO)
        }
        for must in (
            "CLAUDE.md",
            "PROGRESS.md",
            "PROGRESS-LITE.md",
            "README.md",
            "docs/gameplan/README.md",
            "docs/gameplan/STATUS-AUDIT.md",
            "docs/research/reverse-eng-20261010/NATIVE-MEMORY-MAP.md",
            "tools/gameplan/modules/shop.py",
        ):
            self.assertIn(must, rels, f"the scan surface dropped {must}")
        # And nothing frozen is in scope.
        self.assertFalse(
            [r for r in rels if "/archive/" in r],
            "an archived snapshot slipped into the live scan",
        )

    def test_no_live_file_asserts_the_absence(self):
        offenders: list[str] = []
        for path in _scan_files():
            offenders.extend(_asserting_hits(path))
        self.assertEqual(
            offenders, [],
            "a live file re-asserts the refuted dictionary absence:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_corrected_marker_is_present(self):
        """A retraction alone is not enough -- the fact must be stated too."""
        for path, marker in _CORRECTED_MARKERS:
            self.assertIn(
                marker, path.read_text(encoding="utf-8"),
                f"{path.relative_to(_REPO)} no longer names {marker!r} -- the "
                f"correction was gutted",
            )


# --------------------------------------------------------------------------- #
# The mutation test: a guard you have not tried to defeat is not a guard.
# --------------------------------------------------------------------------- #

class MutationTestTheGuardIsNotInert(unittest.TestCase):
    """Plant each banned literal into each covered ROOT and prove the scan fires.

    Round-1 was defeated because the scan rooted only ``*.py`` and the wordlist
    held one spelling; round-3 because the *forms* were word-order specific.
    Here every literal (round-2 and round-3 alike) is planted under every root,
    including a ``.md``, and every root is proved to be in ``_scan_files()``.
    """

    #: (root dir, suffix) pairs -- one live file is planted in each covered root.
    _ROOTS = (
        (_REPO, ".md"),
        (_REPO / "docs", ".md"),
        (_REPO / "tools" / "gameplan", ".md"),
        (_REPO / "tools" / "gameplan", ".py"),
    )

    def _plant(self, root: Path, suffix: str, text: str) -> Path:
        self.assertTrue(root.is_dir(), f"scan root missing: {root}")
        path = root / f"_mut_dict_claim_probe{suffix}"
        path.write_text(text + "\n", encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_each_banned_spelling_is_caught_in_each_root(self):
        for index, sample in enumerate(BANNED_SAMPLES):
            for root, suffix in self._ROOTS:
                path = self._plant(root, suffix, f"# mutation {index}\n\n{sample}\n")
                rel = path.relative_to(_REPO).as_posix()
                self.assertIn(
                    rel, {h.split(":", 1)[0] for h in _asserting_hits(path)},
                    f"the guard failed to fire on {sample!r} planted in {rel}",
                )

    def test_the_planted_claim_reaches_the_whole_scan(self):
        """The planted file is in ``_scan_files()`` -- the scan is not skipping roots."""
        for root, suffix in self._ROOTS:
            path = self._plant(root, suffix, "没有一条构造字典\n")
            self.assertIn(
                path.resolve(),
                {p.resolve() for p in _scan_files()},
                f"the scan surface did not pick up a planted file in {root}",
            )

    def test_correct_prose_planted_in_each_root_does_not_fire(self):
        """Negative control at the whole-scan level: correct prose stays silent."""
        for root, suffix in self._ROOTS:
            path = self._plant(
                root, suffix,
                "字典构造器 1088/1788/948 与取元素 1158 都在，只是泛型引脚。\n",
            )
            self.assertEqual(
                _asserting_hits(path), [],
                f"the guard false-fired on correct prose planted in "
                f"{path.relative_to(_REPO)}",
            )


if __name__ == "__main__":
    unittest.main()
