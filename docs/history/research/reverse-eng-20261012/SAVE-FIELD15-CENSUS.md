> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# SAVE `field 15` CENSUS — is it "template records" or "环境配置"?

**Wave:** M2/M3/M4/M5 · **Date:** 2026-10-12 · **Method:** read-only decode of every real `.gil`
via the in-repo `tools/beyond-save/gil_container.py` (`parse_fields`, schema-free protobuf walker).
**Nothing was written. No bridge/native dispatch. No save.** Census script: `.runtime/scratch/f15_census.py`.

Read root: `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/*/Beyond_Local_Save_Level/`

---

## 0. VERDICT (one line)

`field 15` is **neither** "asset/template records" **nor** "环境配置". It is a **per-level typed
config-object table** holding **exactly four families** — `背包模板`(type 11), `环境配置`(type 27),
`自定义职业`(type 4), `自定义成长曲线`(type 5). The "field 15 = 环境配置" claim is a
**partial generalization**: 环境配置 is one of the four rows, not the table. And the answer to
Q5 is **YES** — a genuine **economy (inventory) template** exists on disk: type **11 = 道具背包**,
name **`背包模板`**, id **1119879169**, present in **every one of the 14 real levels**.

---

## 1. SCOPE — what was actually read (Q1)

- `find` over `Beyond_Local_Save_Level/**` → **19 `.gil` files** (18 level dirs + 1 `UpgradeBackup/` copy).
- **15** files carry a top-level `field 15`; **4** do not (`1073741826/1827/1836/1837` = empty placeholders).
- **40 `field 15` records** read in total (14 distinct levels contribute 38; the `UpgradeBackup` copy 2).
  Distinct-level breakdown: 9 levels × 2 rows + 5 levels × 4 rows = 38.

Top-level field histogram (files carrying each field, of 19): `1`×10, `2`×19, `3..33,35..49`×15,
`34`×4, `39/40/41`×19, `42`×13, `50`×6, `52/53`×7. Only `field 15` carries config-typed records.

## 2. POSITIVE CONTROLS (Q4) — the decoder reads three knowns correctly

| control | reader | result |
|---|---|---|
| level name (f2) | `gil_container.parse_level` | `1073741831` → `newdemo_存档`; all 19 decode to the editor-displayed names |
| creator uid (f39) | `gil_container` | `100000001` in all 19 = the parent directory name exactly |
| terrain (f7) | `terrain.read_terrain_fields` | `1073741831` → `TerrainFields(name='地形01', terrain_id=1073741825, cells={...})` |

## 3. HISTOGRAM of record ids + the derivation rule (Q2) — **verified, not assumed**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


This is checked **against the official chapter** `docs/official-docs/chapters/mhsd6lrx3voe.json`
(`facts[kind=="type-taxonomy"]`), whose "配置ID 类型表" is an **independent** source (it names
`11 = 道具背包`, `27 = 环境`, `4 = 职业` without reference to our saves). Band width = 1<<22.

| id | hex | `(>>22)-256` | official range for that type | in-range? | official type name | n | save name string |
|---|---|---|---|---|---|---|---|
| 1119879169 | 0x42C00001 | **11** | 1119879168~1124073471 | ✓ | 道具背包 | 15 | `背包模板` |
| 1186988033 | 0x46C00001 | **27** | 1186988032~1191182335 | ✓ | 环境 | 15 | `环境配置` |
| 1090519041 | 0x41000001 | **4** | 1090519040~1094713343 | ✓ | 职业 | 5 | `自定义职业` |
| 1094713345 | 0x41400001 | **5** | *(skipped in the official table)* | — | *(unnamed; band 1094713344~1098907647 = entity "关卡")* | 5 | `自定义成长曲线` |

Only **4** distinct ids exist. The record's own second varint (`f2` = 12 / 26 / 4 / 5) is
**NOT** the type: it equals the type for 4/5 but is off by 1 for 11/27 → semantics **unresolved**;
report raw. (Do not mistake `f2` for a type tag.)

## 4. EACH FAMILY'S STRUCTURE + NAME FROM LOCAL EVIDENCE (Q3)

Record shape: `f1 = configId(varint)`, `f2 = ?varint`, `repeated f4 = { f1: kind, <fKind>: payload }`
(the `f4[0]` entry is always `{f1:1, f11:{f1:<name>}}` — the name block).


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**Name provenance (the honest instrument list).** Files searched:

| file | `背包模板` | `环境配置` | `自定义职业` | `自定义成长曲线` | `道具背包` |
|---|---|---|---|---|---|
| `.runtime/editor-catalog/textmap-chs.json` (7743 rows / 13931 strings) | 0 | **3 exact / 9 substr** | 0 | 0 | 0 |
| `.runtime/editor-catalog/string-table.json` | 0 | 0 | 0 | 0 | 0 — **void: instrument has no Chinese at all** |
| `docs/official-docs/chapters/mhsd6lrx3voe.json` | — | — | — | — | `11 = 道具背包` (type table) |
| `docs/official-docs/chapters/mh5y5001vqd4.json` | **term used** ("背包组件将直接引用背包模板") | — | — | — | — |

- `环境配置` is an **editor UI string**: `textmap-chs.json` has `环境配置名称 / 环境配置所属分类 /
  环境配置索引 / 新建环境配置 / 是否删除{0}？\n删除后当前存档的环境配置引用将丢失`, and
  `INSTALLED-TEXTMAP-KEYS.md:437` gives `UI_BEYOND_EDITOR_ESP_PROFILE_TAB_TABNAME = 环境配置`.
  The *"…当前存档的环境配置引用将丢失"* string literally ties this asset to the save's reference.
- **`背包模板` is a real official term** — `mh5y5001vqd4.json` (`背包组件将直接引用背包模板`,
  `仅支持同时选择一个背包模板`). Type 11 is **independently** named `道具背包` by the official
  type table. So `1119879169` is a genuine bag template, not a guess.
- `自定义职业` / `自定义成长曲线` have **no** textmap key — they are user-authored custom names
  (自定义 = "custom"); their types 4 (职业) / 5 are read off the id band.
- ⚠ **instrument note**: `string-table.json` returned 0 for `背包模板` **and** for the control `环境` —
  a *false zero* from a file with no Chinese. The load-bearing catalogue is `textmap-chs.json`
  (control `环境配置` = non-zero through the same instrument).

## 5. ANSWER — does any real save hold an ECONOMY template? (Q5)

**YES — exactly one, and it is M4's.** A structured recursive walk (`depth<=9`) over **all 19 files**
classifies every varint value by its config band:

| band | occurrences | distinct values |
|---|---|---|
| 4 职业 | 105 | `{1090519041}` |
| 11 道具背包 | 30 | `{1119879169}` |
| 27 环境 | 30 | `{1186988033}` |
| **8 普通道具 / 10 资源货币 / 15 商店模板** | **0 / 0 / 0** | **∅** |

So the only **economy-family** record in any real save is:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


There is **no** currency (10), **no** item (8) and **no** shop (15) template anywhere in any save.

### Implication for M2-M5

- **M4 背包** — its template **already exists on disk** (type 11 `背包模板`), auto-added per level.
  This is *not* "blocked for lack of a template"; it is blocked only in that (a) the tooling has
  no primitive to **create a new** one or edit this one, and (b) the bag's stored form here is a
  stub — so "the default bag is referenceable" ≠ "we can provision a farming bag".
- **M2 货币 / M3 道具 / M5 商店** — confirmed still **template-less**: bands 8/10/15 are empty across
  every real save. The demo's `货币配置ID` / `道具配置ID` remain **dangling references**. Nothing in
  this census unblocks them; it *re-confirms* the block with a wider net (19 files, not 18).
- **The "field 15 = 环境配置" reading is wrong as a whole.** `环境配置` (type 27) is a **lighting/
  environment profile**, co-resident with the bag template. The prior `TEMPLATE-CREATION-MINE.md`
  table stands and is now independently corroborated by the official type table + decoded floats.

## 6. FILES

- `tools/beyond-save/gil_container.py` (reused read-only: `decode_container/parse_fields/parse_level`)
- `tools/beyond-save/terrain.py` (reused read-only: `read_terrain_fields`)
- `.runtime/scratch/f15_census.py` (this census)
- `docs/official-docs/chapters/mhsd6lrx3voe.json` (config-ID type table)
- `docs/official-docs/chapters/mh5y5001vqd4.json` (背包模板 / 背包组件)
- `.runtime/editor-catalog/textmap-chs.json`; `.runtime/editor-catalog/string-table.json` (void)
- prior: `docs/research/reverse-eng-20261010/TEMPLATE-STORAGE.md`, `CONFIG-ID-RESOLUTION-MINE.md`,
  `docs/research/reverse-eng-20261010/INSTALLED-TEXTMAP-KEYS.md`

## 7. OPEN

- `f2` semantics (12/26/4/5) — unresolved; not the type.
- `f4[*].f1` kind ids (1,42,70,8,9,10,11,25,26,27,101,102) and their `f<K>` payload field numbers —
  not mapped to an editor enum yet.
- Whether `1094713345` (type 5) is a config type the official table omitted, or an entity-band id
  — the doc warns the two namespaces overlap at 5 (`关卡`).
