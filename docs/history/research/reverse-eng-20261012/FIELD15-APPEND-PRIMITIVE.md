> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# field-15 append/replace primitive — reusable, tested, in-memory only

**Wave:** M5 (JOB 1) · **Date:** 2026-10-12 · **Method:** pure offline, read-only.
**No bridge, no dispatch, no native call, no helper, no UAC, no save, no entity/graph/template mutation,
no playtest.** `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` is **read (`read_bytes`) only, not one byte
written**. All new code is in-memory and returns `bytes`; every fixture is under the project. Did not
touch `GOAL.md`, `CLAUDE.md`, or any pinned file.

**Three layers, labelled:** **PROVEN** (read from real bytes / executed this checkout) ·
**INFERRED** (advanced from a proven fact, not directly observed) · **UNKNOWN**.

Deliverables: `tools/beyond-save/field15_edit.py` (the primitive),
`tools/beyond-save/test_field15_edit.py` (26 tests, all green),
`.runtime/scratch/mutation_field15.py` (the mutation harness). Sister docs (do not re-derive):
`FIELD15-IS-THE-TEMPLATE-STORE.md`, `SAVE-FIELD15-CENSUS.md`, `SHOP-TEMPLATE-SCHEMA.md`.

---

## 0. VERDICT (one line)

The field-15 store now has a **reusable, byte-exact, tested primitive** — append (refusing duplicate
ids with `template_edit`'s own guard) and **replace-a-payload-in-place** (preserving the record's
index, which the prior composition route did not) — plus a no-op re-serialiser. It is a **library +
tests** only: it is wired to **no** dispatch, bridge op, or save path, and there is **no evidence the
game accepts bytes we produce**.

---

## 1. What was already measured (the basis, not re-derived here)

From `.runtime/scratch/SHOP-INPLACE-VS-APPEND.md` (2026-10-12, offline/read-only) and
`FIELD15-IS-THE-TEMPLATE-STORE.md`:

- **Editor session = tail append** (PROVEN, per-record sha256 across three independent BEFORE copies):
  one editor session took level `1073741842` field 15 from **4 records to 8**, changed **none** of the
  4 pre-existing ones, and left every top-level field count unchanged.
- **Record shape** (PROVEN): `{1: <typed id>, 2: <f2>, 4*: <component block>}`; a block is
  `{1: <kind>, <P>: <payload>}`; the first block is always the **name block** (kind 1 → payload field
  11 → `f1` = UTF-8). `f2` is "type-stable" but its semantics are **UNRESOLVED**.
- **The one real shop record** (PROVEN): level `1073741842`, field-15 index 4, id `1136656385`,
  band `(id>>22)-256 = 15` = 商店模板, **54 B**:
  `088180809e04 1011 221508015a110a0fe887aae5ae9ae4b989e6a8a1e69dbf
   22150830d203100a0e 080120012a0032003a0050015801`
  = `{f1=1136656385, f2=17, f4{name 自定义模板}, f4{f1=48, f58{ f1{ f1=1 f4=1 f5={} f6={} f7={} f10=1 f11=1 } }}}`.
  `payload_field_for(48) == 58`.
- **The missing piece** (PROVEN): `template_edit` had append (`add_template`, with a duplicate guard)
  and excise (`remove_template`) but **no replace-in-place**. Changing a payload was done by
  *composition* (`remove`+`add`), and that route **moves the record to the tail** (shop index 4→7 on
  the real file). The +3 B / 54→57 B demo was that composition route.

---

## 2. The API (`tools/beyond-save/field15_edit.py`)

Every function takes `bytes` and returns `bytes` (or plain data); **nothing takes or returns a path**,
nothing opens a file for writing. Persisting the returned bytes is **a separate, deliberate step the
caller owns** — the same convention `terrain.py` documents for its writer half.

| function | what it does |
|---|---|
| `read_records(blob) -> list[Record]` | decode every store record (id / f2 / raw body / index) |
| `record_digests(blob) -> dict[int, str]` | `{id: sha256(body)}` — the per-record unit the tests compare on |
| `record_index(blob, id) -> int` | a record's table position |
| `field15_value(blob) -> bytes` | the raw field-15 body |
| `reserialise_field15(blob) -> bytes` | re-encode **just** the store body (byte-exact) |
| `reserialise_level(blob) -> bytes` | re-encode the **whole** container with no change (byte-exact) |
| `append_record(blob, id, f2=None, payload=b"", *, component_kind, name, payload_field, blocks, entry) -> Field15Edit` | append one record `{1: id, 2: f2, 4*: blocks}` at the tail |
| `replace_record_payload(blob, id, payload, *, block_index=-1, payload_field=None) -> Field15Edit` | replace the payload of **one block of an existing record, in place** |

`Field15Edit` carries `blob` (the new bytes, written nowhere) plus the exact diff facts
(`byte_delta`, `record_delta`, `table_delta`, `added_bytes`, `old_payload_bytes`/`new_payload_bytes`,
index, before/after counts).

**The duplicate guard is `template_edit.add_template`'s, reused verbatim** — `append_record` delegates
to it, so there is exactly one guard and one message:
`template id <id> already present -- refusing to duplicate`. `field15_edit.Field15Error` **is**
`template_edit.TemplateEditError` (aliased), so `except field15_edit.Field15Error` catches every failure.

`replace_record_payload` targets the `block_index`-th `field 4` (negative counts from the end; default
`-1` = the last block, i.e. the settings/payload block in the measured shape). Its payload child is the
first length-delimited child that is not the `{1: kind}` tag; those bytes are replaced. If the block has
no payload child, `payload_field` (or the measured `payload_field_for(kind)`) supplies the new field.
A `payload_field` that disagrees with the block's actual payload field is refused (wrong-block guard).

`replace_record_payload` is what "add a shop's goods" needs: build the new settings payload (e.g. fill
the empty `f5{}` submessage) and hand it in. The primitive **never guesses** which of `f5/f6/f7` carries
goods — the caller supplies the bytes.

---

## 3. Byte-exactness (the bar — PROVEN)

The prior wave measured that "append changes none of the other records". The tests hold the same bar and
compare **per-record sha256, not total length**:

- **no-op re-serialise is byte-identical** — on the real 33 KB / 45-root-field level `1073741842` and on
  `1073741825`, `reserialise_level(blob) == blob` and `reserialise_field15(blob) == field15_value(blob)`.
- **append leaves every other record byte-identical** — `record_digests` before/after differ only in the
  new id (synthetic and both real fixtures).
- **replace leaves every other record byte-identical and keeps the index** — the target record's digest
  changes, all others identical, `record_count` unchanged, index preserved (real: index 4 stays 4). The
  +3 B payload edit gives `record_delta == 3` and `byte_delta == 3` (54→57 B, matching the demo).
- **replace with the identical payload is byte-exact** (`byte_delta == 0`, `blob == input`) — the replace
  path introduces **zero** perturbation when nothing changes.

---

## 4. Mutation tests — the assertions are load-bearing

"A guard you have not tried to defeat is not a guard." `.runtime/scratch/mutation_field15.py` compiles
mutated copies of the module in memory and re-runs the relevant tests. All three mutations are **KILLED**;
the unmutated baseline **SURVIVES**:

| mutation | test that fails |
|---|---|
| **A** — replace re-appends at the TAIL (the composition route) | `test_replace_grows_the_record_and_keeps_the_index`, `test_replace_shop_payload_in_place` |
| **B** — replace also clobbers another record | `test_replace_grows_the_record_and_keeps_the_index` |
| **C** — append skips the duplicate guard | `test_duplicate_id_is_refused_with_the_established_message` |

`TestDuplicateGuardIsLoadBearing` additionally performs the append **without** the guard and asserts the
duplicate really materialises (2 records with the same id) — so the guard, not some incidental property,
is what refuses.

---

## 5. Fixtures — one is gitignored, and the tests say so

- **Synthetic** (`synthetic_level()`): a 3-record level built to the measured shape — a name block and a
  kind-48 settings block whose payload carries the three empty `f5/f6/f7` submessages. **Always runs**;
  covers append, replace, round-trip and the mutation test with no save on disk.
- **Real** (`.runtime/beyond-save/fixtures/1073741842/1073741842.gil`, `.../1073741825.gil`): repo
  **copies** (the live `LocalLow` path is never touched). `.gitignore` has `/.runtime/`, and **no `.gil`
  is tracked anywhere in this repo** (`git ls-files "*.gil"` = empty) ⇒ on a clean checkout these tests
  **SKIP**, and the skip reason **says so**. The synthetic tests are what always run.

---

## 6. EXPLICIT LIMIT (the honest ceiling)

1. **No evidence the game accepts bytes we produce.** The **editor** is the only proven writer of field
   15 (the tail-append event). Whether the engine would *load* a field-15 table we synthesised is
   **untested** and **not claimed**.
2. **No persistent write path from our side.** This module writes nothing; `gil_container.write_bytes`
   is the repo's only writer and **no caller writes field 15**. Even a hand-written `.gil` would be
   futile: the owner process re-serialises from its own memory, so a file-level edit is overwritten.
   Our job is to **shape bytes** (and show the exact delta), not to persist them.
3. **`replace_record_payload` is not the editor's own edit.** It reproduces the byte *delta* the editor
   would produce, at the record's own position. It is **not** the editor's code path, and the engine has
   never been shown to accept an in-place field-15 rewrite from anyone but itself.
4. **Which of `f5/f6/f7` is the goods (出售) table is UNKNOWN** — there is no goods-bearing sample on
   this machine (see `SHOP-TEMPLATE-SCHEMA.md` §5). The primitive takes the new payload from the caller
   and never guesses.
5. **`f2` semantics remain UNRESOLVED** (`SAVE-FIELD15-CENSUS.md` §2).

---

## 7. Files

- `tools/beyond-save/field15_edit.py` — the primitive (new)
- `tools/beyond-save/test_field15_edit.py` — 26 tests (new)
- `.runtime/scratch/mutation_field15.py` — mutation harness (new)
- `.runtime/scratch/field15_probe.py` — the read-only layout probe (new)
- `.runtime/scratch/SHOP-INPLACE-VS-APPEND.md`, `shop_inplace_demo.py` — the measured basis (prior)
