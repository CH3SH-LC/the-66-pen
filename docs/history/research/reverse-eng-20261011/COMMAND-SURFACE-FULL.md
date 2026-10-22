> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# COMMAND-SURFACE-FULL — the whole FNV command surface of `YuanShen.exe`, and the three answers

Date: 2026-10-11. Read-only. No process touched, no save written, no helper restarted, no UAC.
Bytes read from the image only. Outputs under `.runtime/scratch/` and this file.

This closes the hole an adversary flagged: the prior claim "there is no AddComponent command" rested on
a name-guess dictionary over a *subset* of keys. This document re-runs the question against the **full
enumerated FNV dispatcher surface** — every `switch`-over-string in the image, found by *shape*, not by
a name list — and states the exact bound.

---

## 0. TL;DR

* The editor's command dispatcher is an **FNV-1a-32 string switch compiled into `YuanShen.exe`**
  (the game engine the editor drives). A command string is hashed; the command *name* is never in the binary.
* Whole-image shape scan finds **332 FNV dispatchers / 11,859 key-instances / 10,004 distinct keys**
  (sections `.text .rdata .data .pdata .00cfg .retplne .tls .voltbl _RDATA il2cpp .upx0 .reloc .rsrc`;
  `.pdata` RUNTIME_FUNCTIONs = 1,177,402).
* Exactly **two** of the 332 carry real `command_route` command names:
  **`0xcba3130` (27/27 named)** and **`0xf03eb40` (9/9 named)**. The other **330 contain zero** command names.
* The two dispatchers an adversary flagged as "extra" are **not** command dispatchers:
  `0xa33ded0` is a **Unity `KeyCode` name resolver**; `0xa37be00` is an **input / UI action-event resolver**.
  Neither writes.
* **Q-A / Q-B / Q-C answers:**
  - **Q-A. Add a component to an entity — NO command, anywhere.** The only component commands in the whole
    enumerated surface are **two deletes** (`DeleteComponentForEditObj`, `DeleteComponentForPrefab`).
    ⚠️ **But the command layer is NOT the only write surface** — see §4.
  - **Q-B. Create a template/asset (currency/item/inventory/shop/any) — NO command.**
  - **Q-C. Write terrain — NO command.** ("Terrain" appears only as an object-kind *enum value*.)
* `Insert` (in `0xa33ded0`) is the **`Insert` keyboard key** (KeyCode value 277), **not an entity command** (§3).

---

## 1. Method (same-method discipline)

The scanner, `tools/editor-catalog/fnv_dispatchers.py`, is **offline and read-only**. It finds each
dispatcher by **shape**, never from a name list:

1. locate the FNV seed `mov r32, 0x811c9dc5` and the FNV prime `imul ACC, r/m32, 0x1000193`
   in the same `.pdata` function body — **ACC is taken from the imul's destination register**;
2. the tree ROOT = the first reachable `cmp ACC, imm32` (imm >= 0x10000) after the last prime-imul;
3. walk the binary-search tree (`cmp ACC,imm` + `ja/je/jne`; both the 2-way and 3-way forms) and collect
   every reached `imm32` — these ARE `fnv1a(case-label)`.

False positives are bounded by: (a) the compared register must be the one the FNV multiply writes,
(b) imm >= 0x10000, (c) the node must be **reachable** from the loop-exit root (a coincidental
`cmp ACC,imm` inside a case body is never reached).

**Positive controls (MUST reproduce — all PASS):**

| control | value |
|---|---|
| `fnv1a("DeleteComponentForEditObj")` | `0x0b69f28d` @ `0xcba3428` (main) |
| `fnv1a("AddInstructionGraphForEditObj")` | `0xa8a12ee8` @ `0xcba34fb` (main) |
| `DoImport` / `DoExport` | `0xc9824659` / `0xd8aae5e2` @ `0xf03eb40` (export) |

**Round-trip discipline:** every one of the **890 accepted name-instances** satisfies
`fnv1a(name)==key` (checked this run: **0 failures**). Of 10,004 keys, **617 distinct** are named
(890 instances), **0** are ambiguous, **9,387 distinct** remain unnamed.

---

## 2. Full dispatcher inventory (all 332; sorted by key count)

Columns: begin RVA / end RVA / file offset of begin / distinct keys / named keys / how many of the
editor's 38 `command_route` command names land in this dispatcher.


| # | begin RVA | end RVA | file offset | keys | named | cmd_route hits |
|---|---|---|---|---|---|---|
| 1 | `0xa364d30` | `0xa372de4` | 0x9B1A930 | 750 | 16 | 0 |
| 2 | `0xc7e8000` | `0xc7f58ea` | 0xBF9DC00 | 726 | 1 | 0 |
| 3 | `0x95f6410` | `0x9607cca` | 0x8DAC010 | 691 | 0 | 0 |
| 4 | `0xa780990` | `0xa78b0c0` | 0x9F36590 | 563 | 1 | 0 |
| 5 | `0xa37be00` | `0xa385b99` | 0x9B31A00 | 479 | 51 | 0 |
| 6 | `0xa344250` | `0xa34c4ae` | 0x9AF9E50 | 423 | 27 | 0 |
| 7 | `0xa3316f0` | `0xa339041` | 0x9AE72F0 | 421 | 11 | 0 |
| 8 | `0xa763b60` | `0xa76ba65` | 0x9F19760 | 402 | 0 | 0 |
| 9 | `0xa33ded0` | `0xa3436c8` | 0x9AF3AD0 | 319 | 287 | 0 |
| 10 | `0xa75c860` | `0xa760eb3` | 0x9F12460 | 255 | 1 | 0 |
| 11 | `0xa658c90` | `0xa661766` | 0x9E0E890 | 247 | 0 | 0 |
| 12 | `0xc7e23a0` | `0xc7e5c65` | 0xBF97FA0 | 218 | 0 | 0 |
| 13 | `0xa771790` | `0xa7749cc` | 0x9F27390 | 195 | 0 | 0 |
| 14 | `0xa38ff90` | `0xa393294` | 0x9B45B90 | 189 | 1 | 0 |
| 15 | `0xa35ede0` | `0xa360bb5` | 0x9B149E0 | 133 | 1 | 0 |
| 16 | `0xa356930` | `0xa358678` | 0x9B0C530 | 131 | 0 | 0 |
| 17 | `0xc7e6030` | `0xc7e7a21` | 0xBF9BC30 | 126 | 0 | 0 |
| 18 | `0xa38b390` | `0xa38cb29` | 0x9B40F90 | 117 | 1 | 0 |
| 19 | `0xa779200` | `0xa77a8b6` | 0x9F2EE00 | 114 | 0 | 0 |
| 20 | `0x13aec700` | `0x13aef651` | 0x132A2300 | 98 | 0 | 0 |
| 21 | `0x1962fca0` | `0x19630ee7` | 0x18DE58A0 | 96 | 1 | 0 |
| 22 | `0xa794700` | `0xa7956c4` | 0x9F4A300 | 95 | 9 | 0 |
| 23 | `0xa792ab0` | `0xa79398b` | 0x9F486B0 | 88 | 8 | 0 |
| 24 | `0xa791ce0` | `0xa792aae` | 0x9F478E0 | 80 | 18 | 0 |
| 25 | `0xa33ca70` | `0xa33d77b` | 0x9AF2670 | 74 | 0 | 0 |
| 26 | `0x10f57110` | `0x10f5a1b6` | 0x1070CD10 | 73 | 0 | 0 |
| 27 | `0xa389050` | `0xa389d15` | 0x9B3EC50 | 72 | 1 | 0 |
| 28 | `0xa75aed0` | `0xa75baba` | 0x9F10AD0 | 65 | 0 | 0 |
| 29 | `0xa3741b0` | `0xa374d71` | 0x9B29DB0 | 64 | 0 | 0 |
| 30 | `0xa359850` | `0xa35a36a` | 0x9B0F450 | 60 | 0 | 0 |
| 31 | `0xa76d8e0` | `0xa76e31a` | 0x9F234E0 | 55 | 3 | 0 |
| 32 | `0xa4afa10` | `0xa4b0a93` | 0x9C65610 | 53 | 0 | 0 |
| 33 | `0xbf4fdc0` | `0xbf50e65` | 0xB7059C0 | 51 | 0 | 0 |
| 34 | `0xa35b5f0` | `0xa35bf2b` | 0x9B111F0 | 49 | 6 | 0 |
| 35 | `0xa38dce0` | `0xa38e61b` | 0x9B438E0 | 49 | 10 | 0 |
| 36 | `0x19cd3c00` | `0x19cd5116` | 0x19489800 | 49 | 23 | 0 |
| 37 | `0x1967fee0` | `0x196804e1` | 0x18E35AE0 | 48 | 0 | 0 |
| 38 | `0xab65100` | `0xab657bd` | 0xA31AD00 | 41 | 0 | 0 |
| 39 | `0xa387a90` | `0xa388133` | 0x9B3D690 | 40 | 1 | 0 |
| 40 | `0xa35a370` | `0xa35a9da` | 0x9B0FF70 | 38 | 1 | 0 |
| 41 | `0xa7956d0` | `0xa795d2d` | 0x9F4B2D0 | 38 | 9 | 0 |
| 42 | `0xa351b60` | `0xa3521a3` | 0x9B07760 | 37 | 5 | 0 |
| 43 | `0xa78d470` | `0xa78dab3` | 0x9F43070 | 37 | 4 | 0 |
| 44 | `0x19bbac50` | `0x19bbb2f6` | 0x19370850 | 36 | 0 | 0 |
| 45 | `0xa77fcd0` | `0xa7802d3` | 0x9F358D0 | 35 | 8 | 0 |
| 46 | `0xa796d10` | `0xa797313` | 0x9F4C910 | 35 | 7 | 0 |
| 47 | `0xab63c30` | `0xab6420d` | 0xA319830 | 34 | 1 | 0 |
| 48 | `0xa3778a0` | `0xa377e63` | 0x9B2D4A0 | 33 | 4 | 0 |
| 49 | `0xab621a0` | `0xab6275d` | 0xA317DA0 | 33 | 1 | 0 |
| 50 | `0xa352e40` | `0xa3533d9` | 0x9B08A40 | 32 | 0 | 0 |
| 51 | `0xa774cc0` | `0xa775263` | 0x9F2A8C0 | 32 | 1 | 0 |
| 52 | `0xa78b0c0` | `0xa78b663` | 0x9F40CC0 | 32 | 4 | 0 |
| 53 | `0xa78c840` | `0xa78cde3` | 0x9F42440 | 32 | 2 | 0 |
| 54 | `0x199fa8e0` | `0x199faf6a` | 0x191B04E0 | 32 | 0 | 0 |
| 55 | `0x19bbb300` | `0x19bbb98a` | 0x19370F00 | 32 | 1 | 0 |
| 56 | `0xa343880` | `0xa343d9b` | 0x9AF9480 | 30 | 8 | 0 |
| 57 | `0xa776be0` | `0xa77712b` | 0x9F2C7E0 | 30 | 7 | 0 |
| 58 | `0x19630f90` | `0x19631663` | 0x18DE6B90 | 30 | 1 | 0 |
| 59 | `0xa77ace0` | `0xa77b1f9` | 0x9F308E0 | 29 | 6 | 0 |
| 60 | `0xc700190` | `0xc701f4d` | 0xBEB5D90 | 29 | 6 | 0 |
| 61 | `0xa339910` | `0xa339e03` | 0x9AEF510 | 28 | 1 | 0 |
| 62 | `0xa76c840` | `0xa76cd33` | 0x9F22440 | 28 | 1 | 0 |
| 63 | `0xa76cd40` | `0xa76d22d` | 0x9F22940 | 28 | 1 | 0 |
| 64 | `0x10187a70` | `0x101889aa` | 0xF93D670 | 28 | 0 | 0 |
| 65 | `0xa355a10` | `0xa355ed7` | 0x9B0B610 | 27 | 0 | 0 |
| 66 | `0xa761e00` | `0xa7622c7` | 0x9F17A00 | 27 | 1 | 0 |
| 67 | `0xcba3130` | `0xcba43d7` | 0xC358D30 | 27 | 27 | 25 |
| 68 | `0xa34e840` | `0xa34ecd0` | 0x9B04440 | 26 | 0 | 0 |
| 69 | `0xa352760` | `0xa352bf3` | 0x9B08360 | 26 | 2 | 0 |
| 70 | `0xa38a6a0` | `0xa38ab33` | 0x9B402A0 | 26 | 1 | 0 |
| 71 | `0xa3933e0` | `0xa393873` | 0x9B48FE0 | 26 | 1 | 0 |
| 72 | `0xa78bf70` | `0xa78c403` | 0x9F41B70 | 26 | 0 | 0 |
| 73 | `0xa78dbd0` | `0xa78e063` | 0x9F437D0 | 26 | 0 | 0 |
| 74 | `0xa35c3f0` | `0xa35c855` | 0x9B11FF0 | 25 | 0 | 0 |
| 75 | `0xa77d970` | `0xa77dddb` | 0x9F33570 | 25 | 0 | 0 |
| 76 | `0xa355fb0` | `0xa3563ed` | 0x9B0BBB0 | 24 | 0 | 0 |
| 77 | `0xa7760e0` | `0xa776523` | 0x9F2BCE0 | 24 | 3 | 0 |
| 78 | `0xa4a28c0` | `0xa4a388d` | 0x9C584C0 | 23 | 0 | 0 |
| 79 | `0xf7f49e0` | `0xf7f51c9` | 0xEFAA5E0 | 23 | 23 | 0 |
| 80 | `0xa37b2f0` | `0xa37b6e5` | 0x9B30EF0 | 22 | 2 | 0 |
| 81 | `0xa3865e0` | `0xa3869d5` | 0x9B3C1E0 | 22 | 2 | 0 |
| 82 | `0xa75bac0` | `0xa75bebb` | 0x9F116C0 | 22 | 2 | 0 |
| 83 | `0xa762b30` | `0xa762f2b` | 0x9F18730 | 22 | 1 | 0 |
| 84 | `0xa7775c0` | `0xa7779bb` | 0x9F2D1C0 | 22 | 1 | 0 |
| 85 | `0xa77c160` | `0xa77c55b` | 0x9F31D60 | 22 | 0 | 0 |
| 86 | `0x12472f70` | `0x12473366` | 0x11C28B70 | 22 | 0 | 0 |
| 87 | `0xa75a270` | `0xa75a64b` | 0x9F0FE70 | 21 | 0 | 0 |
| 88 | `0xebb30b0` | `0xebb3489` | 0xE368CB0 | 21 | 0 | 0 |
| 89 | `0x12677a20` | `0x12677df9` | 0x11E2D620 | 21 | 0 | 0 |
| 90 | `0xa32f0b0` | `0xa32f46b` | 0x9AE4CB0 | 20 | 2 | 0 |
| 91 | `0xa33c080` | `0xa33c43b` | 0x9AF1C80 | 20 | 2 | 0 |
| 92 | `0xa33c6b0` | `0xa33ca6b` | 0x9AF22B0 | 20 | 2 | 0 |
| 93 | `0xa38cb30` | `0xa38ceeb` | 0x9B42730 | 20 | 4 | 0 |
| 94 | `0xa38ed90` | `0xa38f14b` | 0x9B44990 | 20 | 0 | 0 |
| 95 | `0xa77b880` | `0xa77bc7c` | 0x9F31480 | 20 | 7 | 0 |
| 96 | `0xc7e5c70` | `0xc7e6025` | 0xBF9B870 | 20 | 1 | 0 |
| 97 | `0xa34cef0` | `0xa34d285` | 0x9B02AF0 | 19 | 2 | 0 |
| 98 | `0xa350f20` | `0xa3512bb` | 0x9B06B20 | 19 | 7 | 0 |
| 99 | `0xa3549e0` | `0xa354d7b` | 0x9B0A5E0 | 19 | 0 | 0 |
| 100 | `0xa361c50` | `0xa361feb` | 0x9B17850 | 19 | 2 | 0 |
| 101 | `0xab63890` | `0xab63c25` | 0xA319490 | 19 | 0 | 0 |
| 102 | `0x13adcf00` | `0x13addd4e` | 0x13292B00 | 19 | 0 | 0 |
| 103 | `0x19e01e30` | `0x19e028a8` | 0x195B7A30 | 19 | 9 | 0 |
| 104 | `0x9c494b0` | `0x9c49dcc` | 0x93FF0B0 | 18 | 0 | 0 |
| 105 | `0xa330750` | `0xa330acb` | 0x9AE6350 | 18 | 0 | 0 |
| 106 | `0xa35cb40` | `0xa35cebb` | 0x9B12740 | 18 | 0 | 0 |
| 107 | `0xa35e120` | `0xa35e49b` | 0x9B13D20 | 18 | 0 | 0 |
| 108 | `0xd03a7f0` | `0xd03b3e4` | 0xC7F03F0 | 18 | 1 | 0 |
| 109 | `0x10324250` | `0x10324768` | 0xFAD9E50 | 18 | 4 | 0 |
| 110 | `0xa32e980` | `0xa32ecc7` | 0x9AE4580 | 17 | 3 | 0 |
| 111 | `0xa330400` | `0xa330741` | 0x9AE6000 | 17 | 0 | 0 |
| 112 | `0xa33a8e0` | `0xa33ac27` | 0x9AF04E0 | 17 | 0 | 0 |
| 113 | `0xc7e7cb0` | `0xc7e7ff7` | 0xBF9D8B0 | 17 | 0 | 0 |
| 114 | `0x116fdc30` | `0x116fdf95` | 0x10EB3830 | 17 | 0 | 0 |
| 115 | `0x73e1ce0` | `0x73e2021` | 0x6B978E0 | 16 | 0 | 0 |
| 116 | `0x868f6f0` | `0x868fa31` | 0x7E452F0 | 16 | 0 | 0 |
| 117 | `0x9250f50` | `0x9251291` | 0x8A06B50 | 16 | 0 | 0 |
| 118 | `0xa34d720` | `0xa34da42` | 0x9B03320 | 16 | 0 | 0 |
| 119 | `0xa34f3f0` | `0xa34f718` | 0x9B04FF0 | 16 | 0 | 0 |
| 120 | `0xa3882b0` | `0xa3885d2` | 0x9B3DEB0 | 16 | 3 | 0 |
| 121 | `0xa38ea60` | `0xa38ed82` | 0x9B44660 | 16 | 0 | 0 |
| 122 | `0xa7940d0` | `0xa7943f8` | 0x9F49CD0 | 16 | 2 | 0 |
| 123 | `0xa797ff0` | `0xa798318` | 0x9F4DBF0 | 16 | 0 | 0 |
| 124 | `0xb29e840` | `0xb29eb81` | 0xAA54440 | 16 | 0 | 0 |
| 125 | `0xc6b5360` | `0xc6b56a1` | 0xBE6AF60 | 16 | 0 | 0 |
| 126 | `0x10fafcd0` | `0x10fb0011` | 0x107658D0 | 16 | 0 | 0 |
| 127 | `0x12a5bfe0` | `0x12a5c321` | 0x12211BE0 | 16 | 0 | 0 |
| 128 | `0x1408e290` | `0x1408e5d1` | 0x13843E90 | 16 | 0 | 0 |
| 129 | `0x733f430` | `0x733f716` | 0x6AF5030 | 15 | 0 | 0 |
| 130 | `0xa3391a0` | `0xa33949d` | 0x9AEEDA0 | 15 | 0 | 0 |
| 131 | `0xa33a5e0` | `0xa33a8dd` | 0x9AF01E0 | 15 | 1 | 0 |
| 132 | `0xa34fea0` | `0xa350199` | 0x9B05AA0 | 15 | 1 | 0 |
| 133 | `0xa759e60` | `0xa75a159` | 0x9F0FA60 | 15 | 1 | 0 |
| 134 | `0xa761890` | `0xa761b8d` | 0x9F17490 | 15 | 0 | 0 |
| 135 | `0xa77d000` | `0xa77d2fd` | 0x9F32C00 | 15 | 1 | 0 |
| 136 | `0xa78d170` | `0xa78d46d` | 0x9F42D70 | 15 | 1 | 0 |
| 137 | `0xa331070` | `0xa33133a` | 0x9AE6C70 | 14 | 1 | 0 |
| 138 | `0xa350b10` | `0xa350dd4` | 0x9B06710 | 14 | 0 | 0 |
| 139 | `0xa374d80` | `0xa37504a` | 0x9B2A980 | 14 | 2 | 0 |
| 140 | `0xa379fa0` | `0xa37a26a` | 0x9B2FBA0 | 14 | 1 | 0 |
| 141 | `0xa38e790` | `0xa38ea54` | 0x9B44390 | 14 | 3 | 0 |
| 142 | `0xa38fa40` | `0xa38fd0d` | 0x9B45640 | 14 | 0 | 0 |
| 143 | `0xa78b7b0` | `0xa78ba7a` | 0x9F413B0 | 14 | 0 | 0 |
| 144 | `0x6d81120` | `0x6d815e8` | 0x6536D20 | 13 | 2 | 0 |
| 145 | `0x734f510` | `0x734f7cf` | 0x6B05110 | 13 | 0 | 0 |
| 146 | `0xa32fea0` | `0xa33013d` | 0x9AE5AA0 | 13 | 1 | 0 |
| 147 | `0xa35ea60` | `0xa35ed03` | 0x9B14660 | 13 | 0 | 0 |
| 148 | `0xa361800` | `0xa361aa3` | 0x9B17400 | 13 | 3 | 0 |
| 149 | `0xa375230` | `0xa3754cd` | 0x9B2AE30 | 13 | 2 | 0 |
| 150 | `0xa4a5380` | `0xa4a582a` | 0x9C5AF80 | 13 | 0 | 0 |
| 151 | `0xa762fb0` | `0xa763253` | 0x9F18BB0 | 13 | 0 | 0 |
| 152 | `0xa775600` | `0xa7758a3` | 0x9F2B200 | 13 | 2 | 0 |
| 153 | `0xa77c8b0` | `0xa77cb53` | 0x9F324B0 | 13 | 0 | 0 |
| 154 | `0xa77e130` | `0xa77e3d3` | 0x9F33D30 | 13 | 0 | 0 |
| 155 | `0xa791790` | `0xa791a2d` | 0x9F47390 | 13 | 0 | 0 |
| 156 | `0xa799a10` | `0xa799cb3` | 0x9F4F610 | 13 | 3 | 0 |
| 157 | `0x19447fa0` | `0x19448ca4` | 0x18BFDBA0 | 13 | 2 | 0 |
| 158 | `0xa362fd0` | `0xa36324c` | 0x9B18BD0 | 12 | 1 | 0 |
| 159 | `0xa373270` | `0xa3734ec` | 0x9B28E70 | 12 | 0 | 0 |
| 160 | `0xa375740` | `0xa3759bc` | 0x9B2B340 | 12 | 0 | 0 |
| 161 | `0xa386cf0` | `0xa386f6c` | 0x9B3C8F0 | 12 | 2 | 0 |
| 162 | `0xa389d20` | `0xa389f9c` | 0x9B3F920 | 12 | 1 | 0 |
| 163 | `0xa38d4f0` | `0xa38d76c` | 0x9B430F0 | 12 | 0 | 0 |
| 164 | `0xa63d120` | `0xa63d946` | 0x9DF2D20 | 12 | 0 | 0 |
| 165 | `0xa76ee50` | `0xa76f0cc` | 0x9F24A50 | 12 | 0 | 0 |
| 166 | `0xa770f10` | `0xa77118c` | 0x9F26B10 | 12 | 1 | 0 |
| 167 | `0xa77d6f0` | `0xa77d96c` | 0x9F332F0 | 12 | 0 | 0 |
| 168 | `0xa77deb0` | `0xa77e126` | 0x9F33AB0 | 12 | 1 | 0 |
| 169 | `0xa78e360` | `0xa78e5dc` | 0x9F43F60 | 12 | 0 | 0 |
| 170 | `0xa78ec50` | `0xa78eecc` | 0x9F44850 | 12 | 4 | 0 |
| 171 | `0xa793e50` | `0xa7940c6` | 0x9F49A50 | 12 | 0 | 0 |
| 172 | `0xab61e80` | `0xab620fc` | 0xA317A80 | 12 | 2 | 0 |
| 173 | `0xfb48540` | `0xfb48a9a` | 0xF2FE140 | 12 | 2 | 0 |
| 174 | `0x11521b10` | `0x11522278` | 0x10CD7710 | 12 | 0 | 0 |
| 175 | `0x13f23ea0` | `0x13f2441e` | 0x136D9AA0 | 12 | 0 | 0 |
| 176 | `0x19507390` | `0x19507a2f` | 0x18CBCF90 | 12 | 0 | 0 |
| 177 | `0x1966aea0` | `0x1966b75d` | 0x18E20AA0 | 12 | 0 | 0 |
| 178 | `0x19c3fb40` | `0x19c40169` | 0x193F5740 | 12 | 1 | 0 |
| 179 | `0x8b343a0` | `0x8b34880` | 0x82E9FA0 | 11 | 0 | 0 |
| 180 | `0xa0a7460` | `0xa0a7997` | 0x985D060 | 11 | 1 | 0 |
| 181 | `0xa33b5b0` | `0xa33b808` | 0x9AF11B0 | 11 | 0 | 0 |
| 182 | `0xa352500` | `0xa352752` | 0x9B08100 | 11 | 1 | 0 |
| 183 | `0xa358750` | `0xa3589a8` | 0x9B0E350 | 11 | 0 | 0 |
| 184 | `0xa358e10` | `0xa359062` | 0x9B0EA10 | 11 | 0 | 0 |
| 185 | `0xa35d4a0` | `0xa35d6f8` | 0x9B130A0 | 11 | 0 | 0 |
| 186 | `0xa362760` | `0xa3629b2` | 0x9B18360 | 11 | 1 | 0 |
| 187 | `0xa362d70` | `0xa362fc8` | 0x9B18970 | 11 | 0 | 0 |
| 188 | `0xa3644c0` | `0xa364718` | 0x9B1A0C0 | 11 | 5 | 0 |
| 189 | `0xa379b70` | `0xa379dc2` | 0x9B2F770 | 11 | 1 | 0 |
| 190 | `0xa387040` | `0xa387292` | 0x9B3CC40 | 11 | 1 | 0 |
| 191 | `0xa38f150` | `0xa38f3a8` | 0x9B44D50 | 11 | 0 | 0 |
| 192 | `0xa76c030` | `0xa76c288` | 0x9F21C30 | 11 | 0 | 0 |
| 193 | `0xa76d230` | `0xa76d488` | 0x9F22E30 | 11 | 3 | 0 |
| 194 | `0xa770070` | `0xa7702c8` | 0x9F25C70 | 11 | 2 | 0 |
| 195 | `0xa7901e0` | `0xa790438` | 0x9F45DE0 | 11 | 0 | 0 |
| 196 | `0xaaaeaf0` | `0xaaaf1e9` | 0xA2646F0 | 11 | 0 | 0 |
| 197 | `0xc658f00` | `0xc65962c` | 0xBE0EB00 | 11 | 0 | 0 |
| 198 | `0x13415bc0` | `0x13416095` | 0x12BCB7C0 | 11 | 2 | 0 |
| 199 | `0xa32f9c0` | `0xa32fbf4` | 0x9AE55C0 | 10 | 0 | 0 |
| 200 | `0xa33be40` | `0xa33c074` | 0x9AF1A40 | 10 | 2 | 0 |
| 201 | `0xa35ddb0` | `0xa35dfde` | 0x9B139B0 | 10 | 1 | 0 |
| 202 | `0xa37a560` | `0xa37a794` | 0x9B30160 | 10 | 2 | 0 |
| 203 | `0xa385cb0` | `0xa385ee4` | 0x9B3B8B0 | 10 | 0 | 0 |
| 204 | `0xa3863b0` | `0xa3865de` | 0x9B3BFB0 | 10 | 0 | 0 |
| 205 | `0xa38d9d0` | `0xa38dc04` | 0x9B435D0 | 10 | 2 | 0 |
| 206 | `0xa75c470` | `0xa75c6a4` | 0x9F12070 | 10 | 5 | 0 |
| 207 | `0xa762780` | `0xa7629b4` | 0x9F18380 | 10 | 2 | 0 |
| 208 | `0xa76ba70` | `0xa76bc9e` | 0x9F21670 | 10 | 0 | 0 |
| 209 | `0xa77f260` | `0xa77f494` | 0x9F34E60 | 10 | 0 | 0 |
| 210 | `0xa78f070` | `0xa78f2a4` | 0x9F44C70 | 10 | 2 | 0 |
| 211 | `0xa7905b0` | `0xa7907e4` | 0x9F461B0 | 10 | 2 | 0 |
| 212 | `0xb0a07d0` | `0xb0a0e10` | 0xA8563D0 | 10 | 0 | 0 |
| 213 | `0xd415600` | `0xd415a02` | 0xCBCB200 | 10 | 4 | 0 |
| 214 | `0x126e3540` | `0x126e3b83` | 0x11E99140 | 10 | 0 | 0 |
| 215 | `0x194f8610` | `0x194f887f` | 0x18CAE210 | 10 | 0 | 0 |
| 216 | `0x19511ca0` | `0x1951215f` | 0x18CC78A0 | 10 | 0 | 0 |
| 217 | `0x8a21ae0` | `0x8a21f85` | 0x81D76E0 | 9 | 0 | 0 |
| 218 | `0x93f9150` | `0x93fa7b8` | 0x8BAED50 | 9 | 2 | 0 |
| 219 | `0x956ca70` | `0x956d211` | 0x8D22670 | 9 | 0 | 0 |
| 220 | `0xa33a180` | `0xa33a391` | 0x9AEFD80 | 9 | 0 | 0 |
| 221 | `0xa34e620` | `0xa34e831` | 0x9B04220 | 9 | 1 | 0 |
| 222 | `0xa355060` | `0xa355271` | 0x9B0AC60 | 9 | 2 | 0 |
| 223 | `0xa35b3d0` | `0xa35b5e4` | 0x9B10FD0 | 9 | 0 | 0 |
| 224 | `0xa35d700` | `0xa35d911` | 0x9B13300 | 9 | 0 | 0 |
| 225 | `0xa361400` | `0xa3615ea` | 0x9B17000 | 9 | 1 | 0 |
| 226 | `0xa373920` | `0xa373b2b` | 0x9B29520 | 9 | 0 | 0 |
| 227 | `0xa373d70` | `0xa373f81` | 0x9B29970 | 9 | 0 | 0 |
| 228 | `0xa375b50` | `0xa375d5b` | 0x9B2B750 | 9 | 1 | 0 |
| 229 | `0xa375d60` | `0xa375f6b` | 0x9B2B960 | 9 | 0 | 0 |
| 230 | `0xa38b170` | `0xa38b381` | 0x9B40D70 | 9 | 0 | 0 |
| 231 | `0xa76f8e0` | `0xa76faf1` | 0x9F254E0 | 9 | 1 | 0 |
| 232 | `0xa76fb00` | `0xa76fd11` | 0x9F25700 | 9 | 7 | 0 |
| 233 | `0xa7705c0` | `0xa7707d1` | 0x9F261C0 | 9 | 1 | 0 |
| 234 | `0xa777d10` | `0xa777f21` | 0x9F2D910 | 9 | 0 | 0 |
| 235 | `0xa77c6a0` | `0xa77c8ae` | 0x9F322A0 | 9 | 0 | 0 |
| 236 | `0xa7802e0` | `0xa7804f1` | 0x9F35EE0 | 9 | 0 | 0 |
| 237 | `0xa78c4b0` | `0xa78c6c1` | 0x9F420B0 | 9 | 0 | 0 |
| 238 | `0xa794400` | `0xa794614` | 0x9F4A000 | 9 | 2 | 0 |
| 239 | `0xa7973c0` | `0xa7975d1` | 0x9F4CFC0 | 9 | 1 | 0 |
| 240 | `0xa797890` | `0xa797aa1` | 0x9F4D490 | 9 | 1 | 0 |
| 241 | `0xab64ef0` | `0xab650fb` | 0xA31AAF0 | 9 | 4 | 0 |
| 242 | `0xab65fb0` | `0xab661c1` | 0xA31BBB0 | 9 | 1 | 0 |
| 243 | `0xb194980` | `0xb194d8b` | 0xA94A580 | 9 | 0 | 0 |
| 244 | `0xf03eb40` | `0xf03f396` | 0xE7F4740 | 9 | 9 | 7 |
| 245 | `0xf85c540` | `0xf85c885` | 0xF012140 | 9 | 0 | 0 |
| 246 | `0x10013ae0` | `0x10013f8e` | 0xF7C96E0 | 9 | 0 | 0 |
| 247 | `0x1007d5d0` | `0x1007f29e` | 0xF8331D0 | 9 | 3 | 0 |
| 248 | `0x106e4230` | `0x106e464b` | 0xFE99E30 | 9 | 1 | 0 |
| 249 | `0x125dbbf0` | `0x125dc06b` | 0x11D917F0 | 9 | 0 | 0 |
| 250 | `0x889f020` | `0x889f5a5` | 0x8054C20 | 8 | 0 | 0 |
| 251 | `0xa32e2a0` | `0xa32e496` | 0x9AE3EA0 | 8 | 0 | 0 |
| 252 | `0xa32fc00` | `0xa32fdf9` | 0x9AE5800 | 8 | 3 | 0 |
| 253 | `0xa339f80` | `0xa33a173` | 0x9AEFB80 | 8 | 3 | 0 |
| 254 | `0xa33d960` | `0xa33db50` | 0x9AF3560 | 8 | 1 | 0 |
| 255 | `0xa34da50` | `0xa34dc4c` | 0x9B03650 | 8 | 0 | 0 |
| 256 | `0xa34ee80` | `0xa34f073` | 0x9B04A80 | 8 | 2 | 0 |
| 257 | `0xa34f080` | `0xa34f276` | 0x9B04C80 | 8 | 2 | 0 |
| 258 | `0xa350440` | `0xa350639` | 0x9B06040 | 8 | 1 | 0 |
| 259 | `0xa353950` | `0xa353b46` | 0x9B09550 | 8 | 2 | 0 |
| 260 | `0xa353b50` | `0xa353d46` | 0x9B09750 | 8 | 2 | 0 |
| 261 | `0xa3544d0` | `0xa3546c9` | 0x9B0A0D0 | 8 | 0 | 0 |
| 262 | `0xa355390` | `0xa355586` | 0x9B0AF90 | 8 | 1 | 0 |
| 263 | `0xa35aeb0` | `0xa35b0a9` | 0x9B10AB0 | 8 | 2 | 0 |
| 264 | `0xa35d2a0` | `0xa35d496` | 0x9B12EA0 | 8 | 0 | 0 |
| 265 | `0xa360bc0` | `0xa360db3` | 0x9B167C0 | 8 | 4 | 0 |
| 266 | `0xa3629c0` | `0xa362bb9` | 0x9B185C0 | 8 | 0 | 0 |
| 267 | `0xa3773c0` | `0xa3775b9` | 0x9B2CFC0 | 8 | 0 | 0 |
| 268 | `0xa37bc00` | `0xa37bdf9` | 0x9B31800 | 8 | 0 | 0 |
| 269 | `0xa3885e0` | `0xa3887d6` | 0x9B3E1E0 | 8 | 1 | 0 |
| 270 | `0xa38cef0` | `0xa38d0e6` | 0x9B42AF0 | 8 | 0 | 0 |
| 271 | `0xa38f3b0` | `0xa38f5a6` | 0x9B44FB0 | 8 | 0 | 0 |
| 272 | `0xa393890` | `0xa393a89` | 0x9B49490 | 8 | 2 | 0 |
| 273 | `0xa762580` | `0xa762776` | 0x9F18180 | 8 | 4 | 0 |
| 274 | `0xa775dd0` | `0xa775fc6` | 0x9F2B9D0 | 8 | 2 | 0 |
| 275 | `0xa778250` | `0xa778449` | 0x9F2DE50 | 8 | 3 | 0 |
| 276 | `0xa77a9d0` | `0xa77abc9` | 0x9F305D0 | 8 | 0 | 0 |
| 277 | `0xa77d4f0` | `0xa77d6e6` | 0x9F330F0 | 8 | 0 | 0 |
| 278 | `0xa77fa00` | `0xa77fbf6` | 0x9F35600 | 8 | 1 | 0 |
| 279 | `0xa796b10` | `0xa796d06` | 0x9F4C710 | 8 | 0 | 0 |
| 280 | `0xa798a00` | `0xa798bf0` | 0x9F4E600 | 8 | 1 | 0 |
| 281 | `0xa798bf0` | `0xa798de6` | 0x9F4E7F0 | 8 | 4 | 0 |
| 282 | `0xab62d20` | `0xab62f16` | 0xA318920 | 8 | 0 | 0 |
| 283 | `0xab66270` | `0xab66466` | 0xA31BE70 | 8 | 1 | 0 |
| 284 | `0xf759e10` | `0xf75a03b` | 0xEF0FA10 | 8 | 2 | 0 |
| 285 | `0x194f88e0` | `0x194f8cf4` | 0x18CAE4E0 | 8 | 3 | 0 |
| 286 | `0x1951c790` | `0x1951c90d` | 0x18CD2390 | 8 | 3 | 0 |
| 287 | `0x195f5220` | `0x195f5611` | 0x18DAAE20 | 8 | 3 | 0 |
| 288 | `0xa32f7f0` | `0xa32f9be` | 0x9AE53F0 | 7 | 1 | 0 |
| 289 | `0xa330c10` | `0xa330de1` | 0x9AE6810 | 7 | 0 | 0 |
| 290 | `0xa343ee0` | `0xa3440ae` | 0x9AF9AE0 | 7 | 2 | 0 |
| 291 | `0xa34c4b0` | `0xa34c67e` | 0x9B020B0 | 7 | 0 | 0 |
| 292 | `0xa3501a0` | `0xa35036e` | 0x9B05DA0 | 7 | 0 | 0 |
| 293 | `0xa3591b0` | `0xa35937e` | 0x9B0EDB0 | 7 | 2 | 0 |
| 294 | `0xa35c040` | `0xa35c208` | 0x9B11C40 | 7 | 0 | 0 |
| 295 | `0xa360dc0` | `0xa360f8b` | 0x9B169C0 | 7 | 4 | 0 |
| 296 | `0xa362240` | `0xa36240e` | 0x9B17E40 | 7 | 4 | 0 |
| 297 | `0xa363250` | `0xa363418` | 0x9B18E50 | 7 | 3 | 0 |
| 298 | `0xa363880` | `0xa363a48` | 0x9B19480 | 7 | 1 | 0 |
| 299 | `0xa3754d0` | `0xa37569e` | 0x9B2B0D0 | 7 | 0 | 0 |
| 300 | `0xa3765b0` | `0xa37677e` | 0x9B2C1B0 | 7 | 3 | 0 |
| 301 | `0xa378340` | `0xa37850e` | 0x9B2DF40 | 7 | 0 | 0 |
| 302 | `0xa3795b0` | `0xa379778` | 0x9B2F1B0 | 7 | 1 | 0 |
| 303 | `0xa379dd0` | `0xa379f98` | 0x9B2F9D0 | 7 | 3 | 0 |
| 304 | `0xa37a910` | `0xa37aad8` | 0x9B30510 | 7 | 2 | 0 |
| 305 | `0xa37aea0` | `0xa37b06e` | 0x9B30AA0 | 7 | 0 | 0 |
| 306 | `0xa386a80` | `0xa386c1f` | 0x9B3C680 | 7 | 0 | 0 |
| 307 | `0xa3888b0` | `0xa388a7e` | 0x9B3E4B0 | 7 | 0 | 0 |
| 308 | `0xa51bc90` | `0xa51bfec` | 0x9CD1890 | 7 | 1 | 0 |
| 309 | `0xa75a890` | `0xa75aa58` | 0x9F10490 | 7 | 0 | 0 |
| 310 | `0xa76eac0` | `0xa76ec91` | 0x9F246C0 | 7 | 0 | 0 |
| 311 | `0xa775c00` | `0xa775dce` | 0x9F2B800 | 7 | 1 | 0 |
| 312 | `0xa77ed10` | `0xa77eede` | 0x9F34910 | 7 | 0 | 0 |
| 313 | `0xa77f7c0` | `0xa77f98e` | 0x9F353C0 | 7 | 1 | 0 |
| 314 | `0xab659a0` | `0xab65b68` | 0xA31B5A0 | 7 | 0 | 0 |
| 315 | `0xab66470` | `0xab6663e` | 0xA31C070 | 7 | 2 | 0 |
| 316 | `0xb3984d0` | `0xb3988d4` | 0xAB4E0D0 | 7 | 0 | 0 |
| 317 | `0xb399130` | `0xb3997a1` | 0xAB4ED30 | 7 | 0 | 0 |
| 318 | `0xc1ac7a0` | `0xc1acaf4` | 0xB9623A0 | 7 | 0 | 0 |
| 319 | `0xc818ab0` | `0xc818ca6` | 0xBFCE6B0 | 7 | 7 | 0 |
| 320 | `0xca2e760` | `0xca2eaed` | 0xC1E4360 | 7 | 2 | 0 |
| 321 | `0xd519140` | `0xd519acc` | 0xCCCED40 | 7 | 0 | 0 |
| 322 | `0xe6f2550` | `0xe6f8f42` | 0xDEA8150 | 7 | 0 | 0 |
| 323 | `0xe8937d0` | `0xe893cb9` | 0xE0493D0 | 7 | 0 | 0 |
| 324 | `0xf37f800` | `0xf380183` | 0xEB35400 | 7 | 1 | 0 |
| 325 | `0xfb640f0` | `0xfb64332` | 0xF319CF0 | 7 | 1 | 0 |
| 326 | `0x106a71e0` | `0x106a75cd` | 0xFE5CDE0 | 7 | 1 | 0 |
| 327 | `0x11e7cdb0` | `0x11e7d30b` | 0x116329B0 | 7 | 0 | 0 |
| 328 | `0x13ed5740` | `0x13ed5b9f` | 0x1368B340 | 7 | 0 | 0 |
| 329 | `0x13ed9590` | `0x13ed9a13` | 0x1368F190 | 7 | 0 | 0 |
| 330 | `0x14069c50` | `0x14069ea8` | 0x1381F850 | 7 | 0 | 0 |
| 331 | `0x195aa490` | `0x195aa94d` | 0x18D60090 | 7 | 1 | 0 |
| 332 | `0x109a38b0` | `0x109a3cb6` | 0x101594B0 | 3 | 0 | 0 |

TOTAL dispatchers=332  key_instances=11859  named_instances=890

**Reading the table.** `cmd_route hits` is the discriminator: only `0xcba3130` (25 hits) and
`0xf03eb40` (7 hits) carry editor command names; summed with the 6 non-hashed `command_route` rows
(audio / PCG / WPF, which are not on the FNV surface) that is the complete editor command face.
Everything else is an enum/table resolver. The biggest of them —
`0xa364d30` (750 keys, `*Event` ids), `0xc7e8000` (726), `0x95f6410` (691), `0xa780990` (563),
`0xa37be00` (479, input/actor events), `0xa344250` (423), `0xa3316f0` (421, `*Event` ids),
`0xa33ded0` (319, Unity `KeyCode`) — are **not** command surfaces.

### 2.1 The seven "extra" single-key functions (bound check)

Lowering the key-count floor from 3 to **1** adds only **7** functions, each with **one** key
(`0x8568fbde`, `0x811c9dc5`, `0x6c967a58`, `0x758fe4ff`, `0x81224900`, `0x811c9dc5`, `0x8568fbde`).
Two of them compare against the **FNV seed itself** (`0x811c9dc5`) — a harness false positive.
**None** carries a `command_route` name. So the "every dispatcher" bound is not hiding a command surface.

*Bound on "every dispatcher":* bounded by (a) function bodies per `.pdata`, (b) seed + prime in the
**same** body, (c) a reachable tree with >= 1 distinct accumulator key. Stated, not hidden: a function
that legitimately owns BOTH an FNV loop and an unrelated string switch elsewhere could anchor on the
wrong list; each entry records its root RVA so any row can be re-checked by hand.

---

## 3. `Insert` — what it actually is (and it is not entity-related)

The adversary singled out `Insert` appearing as a "real verb" in dispatcher `0xa33ded0`. It is a key name.

**`0xa33ded0` (keys=319, named=287) is the Unity `KeyCode` name resolver.** Each leaf sets an immediate
into `ebx` and returns — a pure string->enum resolver (the only call in a body is the IL2CPP
string-equality helper `0x19537450`; there is no store). Instruction-level verification:

| input | leaf body | returns | = Unity KeyCode |
|---|---|---|---|
| `"Question"` | `0xa340a7c` `mov ebx, 0x3f` | `63` | `KeyCode.Question` = 63 ✔ |
| `"Insert"`   | `0xa342662` `mov ebx, 0x115` | `277` | `KeyCode.Insert` = 277 ✔ |

A wider automatic leaf check over 31 Unity `KeyCode` members reproduces the exact value for **24/31**
(the 7 misses are the walker mis-following a shared leaf block, not a different semantics).
So in `0xa33ded0`, **`Insert` = the Insert key** — not a command, not entity-related, writes nothing.

**`0xa37be00` (keys=479, named=51) is an input / UI action-event resolver** (named members:
`Save / Undo / Move / Pause / OpenCharacter / ResetCamera / ChangeView / Hide / MenuConfirm / …`).
Its `Insert` leaf sets `mov ebx, 0x1b6` (= 438) — an action-enum value, again a pure resolver.

Neither dispatcher contains a `command_route` name; neither writes memory.

---

## 4. The three answers, with exact scope

### Q-A. Does ANY command in ANY dispatcher add a component to an entity?

**NO — on the full enumerated command surface.** The only component commands that exist anywhere in the
10,004 keys are the **two deletes**:

| key | command | dispatcher |
|---|---|---|
| `0x0b69f28d` | `DeleteComponentForEditObj` | `0xcba3130` |
| `0x5c27df0e` | `DeleteComponentForPrefab` | `0xcba3130` |

The only `Add*` commands are `AddInstructionGraphFor{EditObj,Prefab}` — they bind a **node graph** to an
object, not a component. Re-test across ALL 10,004 keys with a **40,800-candidate** additive-verb space
(`Add|Create|Attach|Insert|New|Make|Instantiate|Register|Apply|Set|Push|Append|Mount|Equip|Enable|Spawn|Build|Generate|Compose|Assemble|Construct|Init|Initialize|Link|Connect`
× ~48 nouns × ~19 tails) yields exactly the authentic hits
`AddInstructionGraphForEditObj`, `AddInstructionGraphForPrefab`, plus one new candidate below.

**New candidate surfaced this run:** `fnv1a("SpawnMonster") = 0xfd80b2ce` lands in dispatcher
`0xc700190` (29 keys; named siblings `Reset / Stop / DoSkill / Manual`). This is a game-side
ability/state dispatcher, **not** in `command_route`; `SpawnMonster` is corroborated by no corpus literal
(it is a generator combination, and the expected random-hit count over 40,800×10,004/2³² is ≈ 0.1, so a
coincidence is entirely plausible). Even if genuine it is an **entity spawn**, not a component add.
Reported for honesty; it does not move Q-A.

**⚠️ The command layer is NOT the only write surface — say it explicitly.** A parallel wave found the
editor adds a component by **mutating the entity model directly**, bypassing commands entirely:
the entity's local component collection `rgfCjhijuAbCoKxWU8Lu<T>` exposes an **ADD** method
`X66ijdVvJ0k(T, bool withCallback)` (7.1 name `G2GXLQZkPlk`), reached via the accessor `WlJiSPfnM3R()`;
the loader itself calls it at `UofGwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587` (see
`docs/gameplan/ADD-COMPONENT-MODEL-PATH.md` and `ADD-COMPONENT-OP-DESIGN.md`).

**⇒ Q-A's command-layer NO does NOT decide whether components can be added.** It decides only that no
*command string* routes to an add. The actual add capability lives in the model layer, not the command layer.

### Q-B. Does ANY command create a template/asset (currency / item / inventory / shop / any)?

**NO — on the enumerated command surface.** No `Create*` / `New*` / `Make*` / `Instantiate*` /
`Register*` command name exists among the 10,004 keys (the full additive sweep above runs those verbs
against `Template / Asset / Item / Shop / Currency / Prefab / Entity / Resource / …`). The two command
dispatchers are 100% named and contain no creator; the editor's `command_route` (38 rows) and its frontend
`operation` table (44 rows) contain **no** create command either (verified row-by-row this run).

**Scope / honesty:** this is a negative on the *surfaces enumerated* (the FNV dispatcher keys + the two
editor DBs). It is **not** a negative on the editor's un-reversed "system menu" panel: per
`TEMPLATE-CREATE-TRACE.md §0/§6`, the currency / item / shop-template management panel was **never
reverse-engineered** ("not a hidden button — the panel was never reversed"), so a create command that
lives only in that un-reversed managed UI would be invisible to this scan. That is an OPEN, not a proof.

### Q-C. Does ANY command write terrain?

**NO — on the enumerated command surface.** No terrain-write verb (`Set/Paint/Write/Add/Create/Modify/
Apply/Sculpt/Raise/Lower Terrain`, `SetCell/SetTile/SetHeight/PaintCell/CreateTile`) is a key anywhere
in the 10,004. `"Terrain"` (`0xa7ff0cae`) does appear, but only as an **object-kind enum value** in the
entity-type tables `0xa78b0c0` / `0xa78c840` / `0xa77ace0` (siblings `Water / Camera / Character /
Particle / Default / HitBox`), i.e. "this object is a Terrain", not "write terrain".

**Scope / honesty:** separately and independently, **no terrain persistence writer exists in this repo**
either: `tools/beyond-save/terrain.py`'s write-half (`set_cell` / `add_terrain` / `apply_terrain_fields` /
`to_level_bytes`) takes in-memory objects only and performs no file write. "Read" and "write" are two
different things here.

---

## 5. Honest bound on the unnamed remainder

**9,387 distinct keys (10,969 instances) are unnamed.** The bound is
**"unnamed against a 2,151,316-candidate dictionary (2,135,017 corpus + 16,299 auxiliary) plus a
40,800-candidate additive sweep" — never "does not exist".**

Collision discipline: the dictionary has **534 internal colliding buckets** (2+ candidate names hashing to
the same value); **0** of the 10,004 keys land on such a bucket, so **0 names are ambiguous** — that is
checked, not assumed. (Residual caveat, stated: a *single* wrong dictionary name that happens to hash to a
key is not caught by bucket-collision discipline; with 2.135M corpus names × 10,004 keys / 2³² ≈ 5
birthday coincidences are expected across the 617 names, so treat the named set as ~99% precise.)

**What the unnamed keys ARE.** Every large unnamed dispatcher's *named* members are enum labels —
input actions, `KeyCode` names, `*Event` ids (`0xa364d30`, `0xa3316f0`, `0xa38dce0`), entity/object
kinds (`0xa791ce0`, `0xa77ace0`, `0xa343880`), UI panel ids (`0xa7956d0`), type names (`0xf7f49e0`),
menu/undo verbs (`0xa794700` = `NEW/COPY/PASTE/RENAME/DELETE/RESET/…`). Decisive check: the corpus
dictionary **includes the editor's own recovered strings**, yet the single largest unnamed table
(`0xc7e8000`, 726 keys) lights up for only **1** key. If these were command tables, the editor-string
corpus would light them up wholesale. They are not.

**Root cause of the remainder:** `global-metadata.dat` is mhy-obfuscated (magic `0x0059484D`; only ~218 KB
ASCII in 82 MB), so the `case`-label strings are **not byte-readable**. That is *why* 9,387 stay unnamed —
the keys are real, the labels are encrypted.

**Three structurally different ways to name the remainder** (none required to keep the three answers,
which are already closed on the command surface):
1. Reverse `global-metadata.dat`'s string-literal offset table (mhy-obfuscated format).
2. Live process — read the cached `Il2CppString*` at each body's `[rip-X]` slot after il2cpp init
   (out of scope here: no process/UAC/save allowed).
3. Widen the offline corpus with the editor's own config/asset enum labels (input map, element/entity
   enum sheets, toolbar/menu tables) and re-hash.

---

## 6. Full named-key list (617 distinct / 890 instances; every line satisfies `fnv1a(name)==key`)


### Full named-key list (per dispatcher; every line satisfies fnv1a(name)==key)

**`0xa33ded0`–`0xa3436c8`** (keys=319, named=287)
  - `0x00a70065` = `Question`
  - `0x00c6075a` = `Menu`
  - `0x00cacf6e` = `Joystick1Button8`
  - `0x01cad101` = `Joystick1Button9`
  - `0x04797f6b` = `LeftAlt`
  - `0x04a57fc2` = `Clear`
  - `0x09aa5b8c` = `Joystick7Button8`
  - `0x0aaa5d1f` = `Joystick7Button9`
  - `0x0bab33c4` = `LeftParen`
  - `0x0bd2af00` = `F9`
  - `0x0c9761e8` = `KeypadPeriod`
  - `0x0cbecc20` = `Joystick8Button10`
  - `0x0cd2b093` = `F8`
  - `0x0daa61d8` = `Joystick7Button4`
  - `0x0dbecdb3` = `Joystick8Button11`
  - `0x0eaa636b` = `Joystick7Button5`
  - `0x0ebecf46` = `Joystick8Button12`
  - `0x0f317948` = `Insert`
  - `0x0f5670be` = `Semicolon`
  - `0x0faa64fe` = `Joystick7Button6`
  - `0x0fbed0d9` = `Joystick8Button13`
  - `0x103ebca4` = `Ampersand`
  - `0x10aa6691` = `Joystick7Button7`
  - `0x10bed26c` = `Joystick8Button14`
  - `0x11aa6824` = `Joystick7Button0`
  - `0x11bed3ff` = `Joystick8Button15`
  - `0x12aa69b7` = `Joystick7Button1`
  - `0x12bed592` = `Joystick8Button16`
  - `0x13aa6b4a` = `Joystick7Button2`
  - `0x13bed725` = `Joystick8Button17`
  - `0x13d2bb98` = `F1`
  - `0x14aa6cdd` = `Joystick7Button3`
  - `0x14bed8b8` = `Joystick8Button18`
  - `0x15beda4b` = `Joystick8Button19`
  - `0x15d2bebe` = `F3`
  - `0x15da4f6d` = `LeftWindows`
  - `0x16d2c051` = `F2`
  - `0x17d2c1e4` = `F5`
  - `0x18d2c377` = `F4`
  - `0x19d2c50a` = `F7`
  - `0x1ad2c69d` = `F6`
  - `0x2324f148` = `Caret`
  - `0x23ca9260` = `Joystick6Button16`
  - `0x24ca93f3` = `Joystick6Button17`
  - `0x25ca9586` = `Joystick6Button14`
  - `0x26ca9719` = `Joystick6Button15`
  - `0x26ce0dd3` = `RightBracket`
  - `0x27ca98ac` = `Joystick6Button12`
  - `0x28ca9a3f` = `Joystick6Button13`
  - `0x29ca9bd2` = `Joystick6Button10`
  - `0x29e468a0` = `Joystick3Button0`
  - `0x2a107e00` = `Keypad1`
  - `0x2aca9d65` = `Joystick6Button11`
  - `0x2ae46a33` = `Joystick3Button1`
  - `0x2b107f93` = `Keypad0`
  - `0x2b8d5d95` = `Plus`
  - `0x2be46bc6` = `Joystick3Button2`
  - `0x2c108126` = `Keypad3`
  - `0x2ce46d59` = `Joystick3Button3`
  - `0x2d1082b9` = `Keypad2`
  - `0x2de46eec` = `Joystick3Button4`
  - `0x2e10844c` = `Keypad5`
  - `0x2ee4707f` = `Joystick3Button5`
  - `0x2f1085df` = `Keypad4`
  - `0x2f9b7ef0` = `Mouse4`
  - `0x2fe47212` = `Joystick3Button6`
  - `0x30108772` = `Keypad7`
  - `0x304ff7fb` = `None`
  - `0x309b8083` = `Mouse5`
  - `0x30e473a5` = `Joystick3Button7`
  - `0x31108905` = `Keypad6`
  - `0x319b8216` = `Mouse6`
  - `0x31caa86a` = `Joystick6Button18`
  - `0x31e47538` = `Joystick3Button8`
  - `0x32108a98` = `Keypad9`
  - `0x32b3d1e6` = `RightArrow`
  - `0x32caa9fd` = `Joystick6Button19`
  - `0x32e476cb` = `Joystick3Button9`
  - `0x33108c2b` = `Keypad8`
  - `0x339b853c` = `Mouse0`
  - `0x349b86cf` = `Mouse1`
  - `0x359b8862` = `Mouse2`
  - `0x369b89f5` = `Mouse3`
  - `0x373e2abb` = `RightParen`
  - `0x3e3d06ab` = `PageUp`
  - `0x3e995db4` = `Equals`
  - `0x44f9bf2d` = `Pause`
  - `0x4963d1fe` = `RightControl`
  - `0x4afdfe17` = `Backslash`
  - `0x4ef356f1` = `Hash`
  - `0x52f50eae` = `Home`
  - `0x5520c194` = `LeftShift`
  - `0x56d563a8` = `At`
  - `0x5797ea6a` = `Delete`
  - `0x5abe5677` = `Quote`
  - `0x5d509316` = `DownArrow`
  - `0x5ea0cddd` = `Underscore`
  - `0x6063da59` = `LeftCommand`
  - `0x6120d7cc` = `Backspace`
  - `0x65b5f718` = `Comma`
  - `0x6735b040` = `Joystick2Button7`
  - `0x6749394c` = `LeftBracket`
  - `0x6835b1d3` = `Joystick2Button6`
  - `0x6935b366` = `Joystick2Button5`
  - `0x693e1750` = `Joystick8Button1`
  - `0x6a35b4f9` = `Joystick2Button4`
  - `0x6a3e18e3` = `Joystick8Button0`
  - `0x6b35b68c` = `Joystick2Button3`
  - `0x6b3e1a76` = `Joystick8Button3`
  - `0x6b930480` = `Joystick2Button12`
  - `0x6c35b81f` = `Joystick2Button2`
  - `0x6c3e1c09` = `Joystick8Button2`
  - `0x6c930613` = `Joystick2Button13`
  - `0x6d35b9b2` = `Joystick2Button1`
  - `0x6d3e1d9c` = `Joystick8Button5`
  - `0x6d9307a6` = `Joystick2Button10`
  - `0x6e35bb45` = `Joystick2Button0`
  - `0x6e3e1f2f` = `Joystick8Button4`
  - `0x6e930939` = `Joystick2Button11`
  - `0x6f3e20c2` = `Joystick8Button7`
  - `0x6f930acc` = `Joystick2Button16`
  - `0x703e2255` = `Joystick8Button6`
  - `0x70930c5f` = `Joystick2Button17`
  - `0x712f5a8a` = `Slash`
  - `0x713e23e8` = `Joystick8Button9`
  - `0x71930df2` = `Joystick2Button14`
  - `0x723e257b` = `Joystick8Button8`
  - `0x72930f85` = `Joystick2Button15`
  - `0x7535c64a` = `Joystick2Button9`
  - `0x7593143e` = `Joystick2Button18`
  - `0x7635c7dd` = `Joystick2Button8`
  - `0x769315d1` = `Joystick2Button19`
  - `0x8592de00` = `Joystick3Button13`
  - `0x85d25976` = `JoystickButton18`
  - `0x8692df93` = `Joystick3Button12`
  - `0x86d25b09` = `JoystickButton19`
  - `0x87248424` = `Period`
  - `0x872d506c` = `KeypadDivide`
  - `0x8792e126` = `Joystick3Button11`
  - `0x8892e2b9` = `Joystick3Button10`
  - `0x8992e44c` = `Joystick3Button17`
  - `0x8a3309f0` = `Joystick1Button19`
  - `0x8a92e5df` = `Joystick3Button16`
  - `0x8b081cf0` = `Joystick6Button3`
  - `0x8b330b83` = `Joystick1Button18`
  - `0x8b92e772` = `Joystick3Button15`
  - `0x8bd262e8` = `JoystickButton12`
  - `0x8c081e83` = `Joystick6Button2`
  - `0x8c92e905` = `Joystick3Button14`
  - `0x8c98a212` = `RightCommand`
  - `0x8cd2647b` = `JoystickButton13`
  - `0x8d082016` = `Joystick6Button1`
  - `0x8dd2660e` = `JoystickButton10`
  - `0x8e0821a9` = `Joystick6Button0`
  - `0x8ed267a1` = `JoystickButton11`
  - `0x8f08233c` = `Joystick6Button7`
  - `0x8f92edbe` = `Joystick3Button19`
  - `0x8fd26934` = `JoystickButton16`
  - `0x900824cf` = `Joystick6Button6`
  - `0x9092ef51` = `Joystick3Button18`
  - `0x90a50ea1` = `Asterisk`
  - `0x90d26ac7` = `JoystickButton17`
  - `0x91082662` = `Joystick6Button5`
  - `0x911756bc` = `RightAlt`
  - `0x91d26c5a` = `JoystickButton14`
  - `0x920827f5` = `Joystick6Button4`
  - `0x92331688` = `Joystick1Button11`
  - `0x92d26ded` = `JoystickButton15`
  - `0x9333181b` = `Joystick1Button10`
  - `0x943319ae` = `Joystick1Button13`
  - `0x95082cae` = `Joystick6Button9`
  - `0x95331b41` = `Joystick1Button12`
  - `0x96082e41` = `Joystick6Button8`
  - `0x96331cd4` = `Joystick1Button15`
  - `0x96ddac39` = `Greater`
  - `0x97331e67` = `Joystick1Button14`
  - `0x98331ffa` = `Joystick1Button17`
  - `0x9933218d` = `Joystick1Button16`
  - `0x9aff15ab` = `KeypadMinus`
  - `0x9d0c2976` = `Alpha9`
  - `0x9d472e79` = `KeypadMultiply`
  - `0x9e0c2b09` = `Alpha8`
  - `0x9edbaba4` = `Exclaim`
  - `0xa06b9f02` = `Joystick5Button8`
  - `0xa16ba095` = `Joystick5Button9`
  - `0xa197a3d8` = `Less`
  - `0xa26ba228` = `Joystick5Button6`
  - `0xa30c32e8` = `Alpha3`
  - `0xa36ba3bb` = `Joystick5Button7`
  - `0xa40c347b` = `Alpha2`
  - `0xa46ba54e` = `Joystick5Button4`
  - `0xa50c360e` = `Alpha1`
  - `0xa56ba6e1` = `Joystick5Button5`
  - `0xa60c37a1` = `Alpha0`
  - `0xa66ba874` = `Joystick5Button2`
  - `0xa70c3934` = `Alpha7`
  - `0xa76baa07` = `Joystick5Button3`
  - `0xa80c3ac7` = `Alpha6`
  - `0xa86bab9a` = `Joystick5Button0`
  - `0xa90c3c5a` = `Alpha5`
  - `0xa96bad2d` = `Joystick5Button1`
  - `0xa9cdcf49` = `LeftArrow`
  - `0xaa0c3ded` = `Alpha4`
  - `0xada10ac0` = `Joystick4Button5`
  - `0xaea10c53` = `Joystick4Button4`
  - `0xafa10de6` = `Joystick4Button7`
  - `0xb0a10f79` = `Joystick4Button6`
  - `0xb1a1110c` = `Joystick4Button1`
  - `0xb2a1129f` = `Joystick4Button0`
  - `0xb3a11432` = `Joystick4Button3`
  - `0xb4a115c5` = `Joystick4Button2`
  - `0xb4ff45f5` = `LeftControl`
  - `0xb7bb7226` = `Escape`
  - `0xb89df01a` = `Help`
  - `0xb9a11da4` = `Joystick4Button9`
  - `0xbaa11f37` = `Joystick4Button8`
  - `0xbabc0b5c` = `DoubleQuote`
  - `0xc13511be` = `PageDown`
  - `0xc1c43225` = `Space`
  - `0xc773455f` = `Dollar`
  - `0xc881767c` = `Joystick5Button19`
  - `0xc981780f` = `Joystick5Button18`
  - `0xc9f4c04f` = `Minus`
  - `0xcc01b1df` = `Return`
  - `0xcc817cc8` = `Joystick5Button15`
  - `0xcd817e5b` = `Joystick5Button14`
  - `0xce817fee` = `Joystick5Button17`
  - `0xcf818181` = `Joystick5Button16`
  - `0xcf93764a` = `End`
  - `0xd00775b2` = `JoystickButton9`
  - `0xd0818314` = `Joystick5Button11`
  - `0xd1077745` = `JoystickButton8`
  - `0xd18184a7` = `Joystick5Button10`
  - `0xd20778d8` = `JoystickButton7`
  - `0xd281863a` = `Joystick5Button13`
  - `0xd3077a6b` = `JoystickButton6`
  - `0xd38187cd` = `Joystick5Button12`
  - `0xd4077bfe` = `JoystickButton5`
  - `0xd48204d1` = `KeypadEnter`
  - `0xd48e14dc` = `Joystick4Button18`
  - `0xd5077d91` = `JoystickButton4`
  - `0xd5625101` = `KeypadPlus`
  - `0xd58e166f` = `Joystick4Button19`
  - `0xd59266b9` = `UpArrow`
  - `0xd6077f24` = `JoystickButton3`
  - `0xd6209aa7` = `RightShift`
  - `0xd70780b7` = `JoystickButton2`
  - `0xd807824a` = `JoystickButton1`
  - `0xd88e1b28` = `Joystick4Button14`
  - `0xd90783dd` = `JoystickButton0`
  - `0xd98e1cbb` = `Joystick4Button15`
  - `0xda8e1e4e` = `Joystick4Button16`
  - `0xdb8e1fe1` = `Joystick4Button17`
  - `0xdc8e2174` = `Joystick4Button10`
  - `0xdcbd6978` = `F10`
  - `0xdd8e2307` = `Joystick4Button11`
  - `0xddbd6b0b` = `F11`
  - `0xde8e249a` = `Joystick4Button12`
  - `0xdebd6c9e` = `F12`
  - `0xdf8e262d` = `Joystick4Button13`
  - `0xdfbd6e31` = `F13`
  - `0xe0bd6fc4` = `F14`
  - `0xe1bd7157` = `F15`
  - `0xe2441480` = `Joystick7Button17`
  - `0xe3441613` = `Joystick7Button16`
  - `0xe397241e` = `BackQuote`
  - `0xe44417a6` = `Joystick7Button15`
  - `0xe4871888` = `KeypadEquals`
  - `0xe5441939` = `Joystick7Button14`
  - `0xe6441acc` = `Joystick7Button13`
  - `0xe7441c5f` = `Joystick7Button12`
  - `0xe823334a` = `RightWindows`
  - `0xe8320d28` = `Print`
  - `0xe8441df2` = `Joystick7Button11`
  - `0xe9441f85` = `Joystick7Button10`
  - `0xf0442a8a` = `Joystick7Button19`
  - `0xf1442c1d` = `Joystick7Button18`
  - `0xf1b44fdc` = `Colon`
  - `0xf6cabfb0` = `Joystick1Button2`
  - `0xf7cac143` = `Joystick1Button3`
  - `0xf8cac2d6` = `Joystick1Button0`
  - `0xf9cac469` = `Joystick1Button1`
  - `0xfacac5fc` = `Joystick1Button6`
  - `0xfb8358ec` = `Tab`
  - `0xfbcac78f` = `Joystick1Button7`
  - `0xfccac922` = `Joystick1Button4`
  - `0xfdcacab5` = `Joystick1Button5`

**`0xa37be00`–`0xa385b99`** (keys=479, named=51)
  - `0x00c6075a` = `Menu`
  - `0x04797f6b` = `LeftAlt`
  - `0x06148492` = `MenuConfirm`
  - `0x0bd2af00` = `F9`
  - `0x0cd2b093` = `F8`
  - `0x0f317948` = `Insert`
  - `0x0f5670be` = `Semicolon`
  - `0x13d2bb98` = `F1`
  - `0x15d2bebe` = `F3`
  - `0x16d2c051` = `F2`
  - `0x17d2c1e4` = `F5`
  - `0x18d2c377` = `F4`
  - `0x19d2c50a` = `F7`
  - `0x1ad2c69d` = `F6`
  - `0x26ce0dd3` = `RightBracket`
  - `0x3be05547` = `KeyDelete`
  - `0x3e995db4` = `Equals`
  - `0x3f7fe50b` = `MouseWheel`
  - `0x44f9bf2d` = `Pause`
  - `0x4963d1fe` = `RightControl`
  - `0x4d2d5d68` = `Save`
  - `0x52f50eae` = `Home`
  - `0x5520c194` = `LeftShift`
  - `0x580a6cc5` = `OpenMap`
  - `0x5abe5677` = `Quote`
  - `0x5b53b9b5` = `OpenBag`
  - `0x6120d7cc` = `Backspace`
  - `0x65b5f718` = `Comma`
  - `0x6749394c` = `LeftBracket`
  - `0x6c2c9a40` = `ChangeView`
  - `0x712f5a8a` = `Slash`
  - `0x718e870f` = `ResetCamera`
  - `0x71fd4acf` = `Undo`
  - `0x7f2c2a34` = `Move`
  - `0x911756bc` = `RightAlt`
  - `0xb4ff45f5` = `LeftControl`
  - `0xb76fd571` = `ZoomCamera`
  - `0xb89df01a` = `Help`
  - `0xc1c43225` = `Space`
  - `0xc9f4c04f` = `Minus`
  - `0xcc01b1df` = `Return`
  - `0xcf93764a` = `End`
  - `0xd6209aa7` = `RightShift`
  - `0xdcbd6978` = `F10`
  - `0xddbd6b0b` = `F11`
  - `0xdebd6c9e` = `F12`
  - `0xe10c7bcd` = `Hide`
  - `0xe397241e` = `BackQuote`
  - `0xea50bade` = `ESC`
  - `0xf08906bc` = `OpenCharacter`
  - `0xf092cb97` = `MenuNext`

**`0xa344250`–`0xa34c4ae`** (keys=423, named=27)
  - `0x04797f6b` = `LeftAlt`
  - `0x06148492` = `MenuConfirm`
  - `0x13d2bb98` = `F1`
  - `0x15d2bebe` = `F3`
  - `0x16d2c051` = `F2`
  - `0x17d2c1e4` = `F5`
  - `0x18d2c377` = `F4`
  - `0x3be05547` = `KeyDelete`
  - `0x3f7fe50b` = `MouseWheel`
  - `0x4d2d5d68` = `Save`
  - `0x5520c194` = `LeftShift`
  - `0x580a6cc5` = `OpenMap`
  - `0x5b53b9b5` = `OpenBag`
  - `0x6c2c9a40` = `ChangeView`
  - `0x718e870f` = `ResetCamera`
  - `0x71fd4acf` = `Undo`
  - `0x7f2c2a34` = `Move`
  - `0xb4ff45f5` = `LeftControl`
  - `0xb76fd571` = `ZoomCamera`
  - `0xb89df01a` = `Help`
  - `0xc1c43225` = `Space`
  - `0xcc01b1df` = `Return`
  - `0xcf93764a` = `End`
  - `0xe10c7bcd` = `Hide`
  - `0xea50bade` = `ESC`
  - `0xf08906bc` = `OpenCharacter`
  - `0xf092cb97` = `MenuNext`

**`0xcba3130`–`0xcba43d7`** (keys=27, named=27)
  - `0x0b69f28d` = `DeleteComponentForEditObj`
  - `0x1880a8de` = `FocusLocalBullet`
  - `0x1a33f6f9` = `AddInstructionGraphForPrefab`
  - `0x1f56cd02` = `ModifyFactionForPrefab`
  - `0x25139089` = `ModifyFactionForEditObj`
  - `0x2c4eda76` = `DeleteInstructionGraphForEditObj`
  - `0x3f5d30b2` = `FocusCharacter`
  - `0x460c83db` = `ModifyPrefabTag`
  - `0x5a1a25f3` = `DeleteInstructionGraphForPrefab`
  - `0x5c27df0e` = `DeleteComponentForPrefab`
  - `0x68677bd6` = `ApplyPrefabInstanceChange`
  - `0x755a10f3` = `DeleteEditObj`
  - `0x78eb3304` = `FocusEditObj`
  - `0x7ca8b102` = `FocusBeyondTileMap`
  - `0x83668ec8` = `DeletePrefab`
  - `0x89cf06af` = `JumpCombatSetting`
  - `0x9f65756b` = `RequestPrefabInstance`
  - `0x9fe1144f` = `ModifyEditObjName`
  - `0x9ffa4fa9` = `FocusEsp`
  - `0xa8a12ee8` = `AddInstructionGraphForEditObj`
  - `0xb202598a` = `FocusPrefabInstance`
  - `0xb7f550fe` = `ModifyPrefabName`
  - `0xbd40da3c` = `ModifyEditobjTag`
  - `0xbf0390c9` = `FocusDropGather`
  - `0xc7280e4f` = `FocusScreenshot`
  - `0xd807fbc5` = `ModifySuite`
  - `0xe703f83d` = `FocusLight`

**`0x19cd3c00`–`0x19cd5116`** (keys=49, named=23)
  - `0x0c2260e0` = `f9`
  - `0x0d226273` = `f8`
  - `0x14226d78` = `f1`
  - `0x1622709e` = `f3`
  - `0x17227231` = `f2`
  - `0x182273c4` = `f5`
  - `0x19227557` = `f4`
  - `0x1a2276ea` = `f7`
  - `0x1b22787d` = `f6`
  - `0x3553e285` = `space`
  - `0x67c2444a` = `delete`
  - `0x6a8e75aa` = `end`
  - `0x853c682c` = `backspace`
  - `0x85ee37bf` = `return`
  - `0x98f72e4c` = `tab`
  - `0xc6a39628` = `insert`
  - `0xd2c8c28e` = `home`
  - `0xfa320858` = `f10`
  - `0xfb3209eb` = `f11`
  - `0xfc320b7e` = `f12`
  - `0xfd320d11` = `f13`
  - `0xfe320ea4` = `f14`
  - `0xff321037` = `f15`

**`0xf7f49e0`–`0xf7f51c9`** (keys=23, named=23)
  - `0x109de396` = `EntityList`
  - `0x25a25b44` = `Army`
  - `0x2bd0ae97` = `EntityReferenceList`
  - `0x2f742c5d` = `Bool`
  - `0x38f5c80c` = `ArmyList`
  - `0x39fc01c1` = `FloatList`
  - `0x3ddc116f` = `EntityReference`
  - `0x4aae1ffc` = `ConfigReferenceList`
  - `0x4c816225` = `Float`
  - `0x4cf61574` = `GuidList`
  - `0x4e889aa8` = `StructList`
  - `0x604f4858` = `String`
  - `0x77acc3c0` = `StringList`
  - `0x82b7d7d9` = `BoolList`
  - `0x840071c3` = `Vector3`
  - `0xa19a545f` = `Int32`
  - `0xacc7cb2c` = `Guid`
  - `0xb5933c59` = `Dict`
  - `0xc09b32fa` = `Entity`
  - `0xd3b26c47` = `Int32List`
  - `0xd3c26ceb` = `Vector3List`
  - `0xdb50a140` = `Struct`
  - `0xdbdde4f4` = `ConfigReference`

**`0xa791ce0`–`0xa792aae`** (keys=80, named=18)
  - `0x0fb83d07` = `Field`
  - `0x13bcde7d` = `Gadget`
  - `0x2329c92c` = `Team`
  - `0x304ff7fb` = `None`
  - `0x30d783f6` = `Timeline`
  - `0x4155597d` = `Level`
  - `0x582b1e1d` = `Grass`
  - `0x611f5e31` = `Monster`
  - `0x66a677f0` = `NPC`
  - `0x6847c3e4` = `Avatar`
  - `0x9bd8c631` = `Screen`
  - `0xa27663cf` = `Vehicle`
  - `0xca766ea3` = `DropItem`
  - `0xd5efe099` = `Bullet`
  - `0xd63556b0` = `Water`
  - `0xde2a09aa` = `PlayTeam`
  - `0xe74c7b6e` = `Camera`
  - `0xedb780f5` = `Tree`

**`0xa364d30`–`0xa372de4`** (keys=750, named=16)
  - `0x1a045ef0` = `SaveEvent`
  - `0x2235b4ec` = `MoveEvent`
  - `0x444e07cf` = `OpenBagEvent`
  - `0x4e16d5e8` = `ChangeViewEvent`
  - `0x576c8254` = `OpenCharacterEvent`
  - `0x60b29c6d` = `ResetCameraEvent`
  - `0x6649c207` = `HideEvent`
  - `0x6ffa642d` = `UndoEvent`
  - `0x7d4361b5` = `MenuNextEvent`
  - `0x84b9003f` = `OpenMapEvent`
  - `0x9fcb772a` = `OpenMenuEvent`
  - `0xba4fb04e` = `MenuConfirmEvent`
  - `0xdcd9508b` = `ZoomCameraEvent`
  - `0xe385acdd` = `ReturnEvent`
  - `0xe71ac32b` = `F2Event`
  - `0xfc7c63d0` = `Invalid`

**`0xa3316f0`–`0xa339041`** (keys=421, named=11)
  - `0x1a045ef0` = `SaveEvent`
  - `0x2170468d` = `ConfirmEvent`
  - `0x431da231` = `MaterialAddEvent`
  - `0x6649c207` = `HideEvent`
  - `0x6767e193` = `WeaponModifyForEditObj`
  - `0x6ffa642d` = `UndoEvent`
  - `0x729449db` = `DialogSelectEvent`
  - `0x9fcb772a` = `OpenMenuEvent`
  - `0xf32949d1` = `CloseEvent`
  - `0xfc5d0f52` = `MoveCursorEvent`
  - `0xfc7c63d0` = `Invalid`

**`0xa38dce0`–`0xa38e61b`** (keys=49, named=10)
  - `0x0d72541b` = `QuestPlay`
  - `0x19dc307e` = `Default`
  - `0x611f5e31` = `Monster`
  - `0x76ef3d8c` = `Task`
  - `0x9525b78e` = `Custom`
  - `0x96d3996f` = `Talk`
  - `0x9e75940c` = `Activity`
  - `0xa27663cf` = `Vehicle`
  - `0xaf8c40dd` = `Quest`
  - `0xef953925` = `Widget`

**`0xa794700`–`0xa7956c4`** (keys=95, named=9)
  - `0x0d76d520` = `RESET`
  - `0x203bf453` = `RENAME`
  - `0x22b51f44` = `COPY`
  - `0x732a0f1b` = `NONE`
  - `0x75b29508` = `PASTE`
  - `0xa5822da3` = `Revert`
  - `0xaad4ae31` = `NEW`
  - `0xafa89985` = `CHECK_REFERENCE`
  - `0xf8718eca` = `DELETE`

**`0xa7956d0`–`0xa795d2d`** (keys=38, named=9)
  - `0x0120cdf8` = `Achievement`
  - `0x2329c92c` = `Team`
  - `0x28742cc9` = `Shop`
  - `0x44a7f051` = `Map`
  - `0x889f754b` = `Setting`
  - `0x9e75940c` = `Activity`
  - `0xaf8c40dd` = `Quest`
  - `0xc8bc5fd1` = `Bag`
  - `0xec7340b0` = `Character`

**`0x19e01e30`–`0x19e028a8`** (keys=19, named=9)
  - `0x67c2444a` = `delete`
  - `0x6a8e75aa` = `end`
  - `0x853c682c` = `backspace`
  - `0xc6a39628` = `insert`
  - `0xd2c8c28e` = `home`
  - `0xe562ea44` = `copy`
  - `0xf1d0feaf` = `undo`
  - `0xf3e699c9` = `redo`
  - `0xf6562dc3` = `cut`

**`0xf03eb40`–`0xf03f396`** (keys=9, named=9)
  - `0x07724773` = `ImportDebugLog`
  - `0x08aee119` = `DoImportClientScript`
  - `0x0a2d8704` = `ImportAllDebugLog`
  - `0x26e623fe` = `DoExportClientScript`
  - `0x5986b6f9` = `DeleteDebugLog`
  - `0x6e900256` = `RefreshExistDebugLogReport`
  - `0xc9824659` = `DoImport`
  - `0xd19570b8` = `ImportPerformanceReport`
  - `0xd8aae5e2` = `DoExport`

**`0xa792ab0`–`0xa79398b`** (keys=88, named=8)
  - `0x4b642118` = `IconSelect`
  - `0x6cf1ba25` = `Toggle`
  - `0x7490124d` = `GadgetInfo`
  - `0x840071c3` = `Vector3`
  - `0x9808f547` = `Line`
  - `0xafa771d6` = `SearchValue`
  - `0xee04d1ad` = `InstructionGraph`
  - `0xfb8358ec` = `Tab`

**`0xa77fcd0`–`0xa7802d3`** (keys=35, named=8)
  - `0x19dc307e` = `Default`
  - `0x1db5d664` = `Area`
  - `0x304ff7fb` = `None`
  - `0x572b11b7` = `QuestEvent`
  - `0x611f5e31` = `Monster`
  - `0x9525b78e` = `Custom`
  - `0x9e75940c` = `Activity`
  - `0xa27663cf` = `Vehicle`

**`0xa343880`–`0xa343d9b`** (keys=30, named=8)
  - `0x3e40cd83` = `Sand`
  - `0x582b1e1d` = `Grass`
  - `0xba4796d4` = `Rock`
  - `0xd56d2320` = `Ice`
  - `0xd63556b0` = `Water`
  - `0xedb780f5` = `Tree`
  - `0xf3e131e9` = `Tile`
  - `0xfc7c63d0` = `Invalid`

**`0xa796d10`–`0xa797313`** (keys=35, named=7)
  - `0x304ff7fb` = `None`
  - `0x3e2f2134` = `BuffList`
  - `0x53573f1f` = `ProgressBar`
  - `0x590ca79a` = `Image`
  - `0x6fd141d6` = `Skill`
  - `0xcd013a7e` = `WindowFrame`
  - `0xeb53a5c2` = `Timer`

**`0xa776be0`–`0xa77712b`** (keys=30, named=7)
  - `0x2329c92c` = `Team`
  - `0x304ff7fb` = `None`
  - `0x9e75940c` = `Activity`
  - `0xaf8c40dd` = `Quest`
  - `0xc8bc5fd1` = `Bag`
  - `0xdfe4e404` = `Time`
  - `0xec7340b0` = `Character`

**`0xa77b880`–`0xa77bc7c`** (keys=20, named=7)
  - `0x2f7cc682` = `QuestEnd`
  - `0x304ff7fb` = `None`
  - `0x4ddb965e` = `DialogEnd`
  - `0x74755cc2` = `MenuOpen`
  - `0x75b95032` = `DialogBegin`
  - `0xca7b6766` = `QuestBegin`
  - `0xdafd0e86` = `MenuClose`

**`0xa350f20`–`0xa3512bb`** (keys=19, named=7)
  - `0x0ed762f9` = `Fire`
  - `0x304ff7fb` = `None`
  - `0x582b1e1d` = `Grass`
  - `0x94413d27` = `Wind`
  - `0xba4796d4` = `Rock`
  - `0xd56d2320` = `Ice`
  - `0xd63556b0` = `Water`

**`0xa76fb00`–`0xa76fd11`** (keys=9, named=7)
  - `0x0ed762f9` = `Fire`
  - `0x304ff7fb` = `None`
  - `0x582b1e1d` = `Grass`
  - `0x94413d27` = `Wind`
  - `0xba4796d4` = `Rock`
  - `0xd56d2320` = `Ice`
  - `0xd63556b0` = `Water`

**`0xc818ab0`–`0xc818ca6`** (keys=7, named=7)
  - `0x509eec9e` = `DefCur`
  - `0x6e31ac79` = `HpMax`
  - `0x92e50095` = `HpCur`
  - `0xb18f624b` = `LvCur`
  - `0xc0f613ac` = `PName`
  - `0xc246ece9` = `AtkCur`
  - `0xf1262baf` = `PDist`

**`0xa35b5f0`–`0xa35bf2b`** (keys=49, named=6)
  - `0x0ed762f9` = `Fire`
  - `0x304ff7fb` = `None`
  - `0x89ce70c2` = `Freeze`
  - `0x94413d27` = `Wind`
  - `0xa582e785` = `Stream`
  - `0xba4796d4` = `Rock`

**`0xa77ace0`–`0xa77b1f9`** (keys=29, named=6)
  - `0x19dc307e` = `Default`
  - `0xa7ff0cae` = `Terrain`
  - `0xbb673857` = `HitBox`
  - `0xd63556b0` = `Water`
  - `0xe74c7b6e` = `Camera`
  - `0xec7340b0` = `Character`

**`0xc700190`–`0xc701f4d`** (keys=29, named=6)
  - `0x0ac8a560` = `Reset`
  - `0x0e1ef32d` = `Jump`
  - `0x4b7f7705` = `Stop`
  - `0xf0e8b0f9` = `DoSkill`
  - `0xf819f303` = `Manual`
  - `0xfd80b2ce` = `SpawnMonster`

**`0xa351b60`–`0xa3521a3`** (keys=37, named=5)
  - `0x2329c92c` = `Team`
  - `0x8b67f168` = `Target`
  - `0x9b22be74` = `Owner`
  - `0xa27663cf` = `Vehicle`
  - `0xe4898197` = `Self`

**`0xa3644c0`–`0xa364718`** (keys=11, named=5)
  - `0x0ed762f9` = `Fire`
  - `0x19dc307e` = `Default`
  - `0x94413d27` = `Wind`
  - `0xd56d2320` = `Ice`
  - `0xd63556b0` = `Water`

**`0xa75c470`–`0xa75c6a4`** (keys=10, named=5)
  - `0x0e0011c9` = `AreaId`
  - `0x2ac6135e` = `SceneId`
  - `0x304ff7fb` = `None`
  - `0x4115d182` = `Random`
  - `0xdfe4e404` = `Time`

**`0xa78d470`–`0xa78dab3`** (keys=37, named=4)
  - `0x0e1ef32d` = `Jump`
  - `0x108524ac` = `Drop`
  - `0x7f2c2a34` = `Move`
  - `0xa27663cf` = `Vehicle`

**`0xa3778a0`–`0xa377e63`** (keys=33, named=4)
  - `0x2329c92c` = `Team`
  - `0x4155597d` = `Level`
  - `0x65715141` = `Combat`
  - `0xff93d931` = `Ability`

**`0xa78b0c0`–`0xa78b663`** (keys=32, named=4)
  - `0x304ff7fb` = `None`
  - `0x80fd59df` = `Particle`
  - `0xa7ff0cae` = `Terrain`
  - `0xd9f1c8db` = `BeginTriggerForPrefab`

**`0xa38cb30`–`0xa38ceeb`** (keys=20, named=4)
  - `0x27d1a499` = `Voice`
  - `0x304ff7fb` = `None`
  - `0x6146f2f0` = `TeamInfo`
  - `0xd2c92744` = `MiniMap`

**`0x10324250`–`0x10324768`** (keys=18, named=4)
  - `0x14c8d3ca` = `offset`
  - `0x83d03615` = `length`
  - `0x95876e1f` = `width`
  - `0xd5bdbb42` = `height`

**`0xa78ec50`–`0xa78eecc`** (keys=12, named=4)
  - `0x24d4c1d7` = `EnterVehicle`
  - `0x304ff7fb` = `None`
  - `0x587a9cdb` = `EnterScene`
  - `0xfcaf5c24` = `QuestExec`

**`0xd415600`–`0xd415a02`** (keys=10, named=4)
  - `0x0ed762f9` = `Fire`
  - `0x94413d27` = `Wind`
  - `0xa582e785` = `Stream`
  - `0xd63556b0` = `Water`

**`0xab64ef0`–`0xab650fb`** (keys=9, named=4)
  - `0x19dc307e` = `Default`
  - `0xbb673857` = `HitBox`
  - `0xc89b38b3` = `Scene`
  - `0xd63556b0` = `Water`

**`0xa360bc0`–`0xa360db3`** (keys=8, named=4)
  - `0x304ff7fb` = `None`
  - `0x428a1095` = `Body`
  - `0x75afe364` = `All`
  - `0xb7c10361` = `Weapon`

**`0xa762580`–`0xa762776`** (keys=8, named=4)
  - `0x126befb6` = `Auto`
  - `0x304ff7fb` = `None`
  - `0x3e892b4d` = `Select`
  - `0x611f5e31` = `Monster`

**`0xa798bf0`–`0xa798de6`** (keys=8, named=4)
  - `0x1e9e9f85` = `Right`
  - `0x304ff7fb` = `None`
  - `0x92773890` = `Left`
  - `0xa4995035` = `Down`

**`0xa360dc0`–`0xa360f8b`** (keys=7, named=4)
  - `0x2fb366b1` = `Grid`
  - `0x34ce44a5` = `Exit`
  - `0xdbbc7dba` = `Bar`
  - `0xdfe4e404` = `Time`

**`0xa362240`–`0xa36240e`** (keys=7, named=4)
  - `0x304ff7fb` = `None`
  - `0x3ac6ffba` = `Gray`
  - `0x727b390b` = `Orange`
  - `0xa953c75c` = `Green`

**`0xa76d8e0`–`0xa76e31a`** (keys=55, named=3)
  - `0x58de2772` = `Normal`
  - `0xb1546073` = `Effigy`
  - `0xfa82b602` = `Tower`

**`0xa7760e0`–`0xa776523`** (keys=24, named=3)
  - `0x304ff7fb` = `None`
  - `0x4e586f89` = `Mask`
  - `0x75afe364` = `All`

**`0xa32e980`–`0xa32ecc7`** (keys=17, named=3)
  - `0x4b822fa6` = `SkillInfo`
  - `0x58de2772` = `Normal`
  - `0xc52300d9` = `WeaponSelect`

**`0xa3882b0`–`0xa3885d2`** (keys=16, named=3)
  - `0x304ff7fb` = `None`
  - `0xc8907069` = `MoveControl`
  - `0xd2c92744` = `MiniMap`

**`0xa38e790`–`0xa38ea54`** (keys=14, named=3)
  - `0x33881a91` = `Button`
  - `0x58de2772` = `Normal`
  - `0xf0c19391` = `Slot`

**`0xa361800`–`0xa361aa3`** (keys=13, named=3)
  - `0x00c6075a` = `Menu`
  - `0x75afe364` = `All`
  - `0x98fedd56` = `Beyond`

**`0xa799a10`–`0xa799cb3`** (keys=13, named=3)
  - `0x21a5901d` = `Remove`
  - `0x6fd141d6` = `Skill`
  - `0x718e870f` = `ResetCamera`

**`0xa76d230`–`0xa76d488`** (keys=11, named=3)
  - `0x0640028a` = `Windows`
  - `0x4968bf98` = `Editor`
  - `0xcc200e59` = `Unknown`

**`0x1007d5d0`–`0x1007f29e`** (keys=9, named=3)
  - `0x0736dd56` = `Padding`
  - `0x28528e11` = `Scale`
  - `0xeb66e456` = `Path`

**`0xa32fc00`–`0xa32fdf9`** (keys=8, named=3)
  - `0x304ff7fb` = `None`
  - `0x6ceb2d06` = `White`
  - `0xa953c75c` = `Green`

**`0xa339f80`–`0xa33a173`** (keys=8, named=3)
  - `0x3c2510a9` = `CPU`
  - `0x58f879ce` = `Memory`
  - `0xfc7c63d0` = `Invalid`

**`0xa778250`–`0xa778449`** (keys=8, named=3)
  - `0x304ff7fb` = `None`
  - `0x75afe364` = `All`
  - `0xe4898197` = `Self`

**`0x194f88e0`–`0x194f8cf4`** (keys=8, named=3)
  - `0x18bcf834` = `SHA1`
  - `0xb0b2f99a` = `SHA256`
  - `0xb6141476` = `SHA384`

**`0x1951c790`–`0x1951c90d`** (keys=8, named=3)
  - `0xaaea5743` = `file`
  - `0xc96448a5` = `http`
  - `0xdedea8e2` = `https`

**`0x195f5220`–`0x195f5611`** (keys=8, named=3)
  - `0x18bcf834` = `SHA1`
  - `0xb0b2f99a` = `SHA256`
  - `0xb6141476` = `SHA384`

**`0xa363250`–`0xa363418`** (keys=7, named=3)
  - `0x035f1f67` = `Best`
  - `0x611f5e31` = `Monster`
  - `0xe1e7b894` = `Count`

**`0xa3765b0`–`0xa37677e`** (keys=7, named=3)
  - `0x37c4fc8f` = `Warning`
  - `0x58de2772` = `Normal`
  - `0xfc7c63d0` = `Invalid`

**`0xa379dd0`–`0xa379f98`** (keys=7, named=3)
  - `0x304ff7fb` = `None`
  - `0x6ebc2674` = `Effect`
  - `0xec8015df` = `ProcessMaterial`

**`0xa78c840`–`0xa78cde3`** (keys=32, named=2)
  - `0xa7ff0cae` = `Terrain`
  - `0xd9f1c8db` = `BeginTriggerForPrefab`

**`0xa352760`–`0xa352bf3`** (keys=26, named=2)
  - `0x19dc307e` = `Default`
  - `0xa9b587f6` = `DestroyState`

**`0xa37b2f0`–`0xa37b6e5`** (keys=22, named=2)
  - `0x971574c4` = `Reflection`
  - `0xfc7c63d0` = `Invalid`

**`0xa3865e0`–`0xa3869d5`** (keys=22, named=2)
  - `0x19dc307e` = `Default`
  - `0x304ff7fb` = `None`

**`0xa75bac0`–`0xa75bebb`** (keys=22, named=2)
  - `0x582b1e1d` = `Grass`
  - `0xfc7c63d0` = `Invalid`

**`0xa32f0b0`–`0xa32f46b`** (keys=20, named=2)
  - `0x304ff7fb` = `None`
  - `0xe1e7b894` = `Count`

**`0xa33c080`–`0xa33c43b`** (keys=20, named=2)
  - `0x304ff7fb` = `None`
  - `0xf8d9e32a` = `QuestFinish`

**`0xa33c6b0`–`0xa33ca6b`** (keys=20, named=2)
  - `0xa0bb64e0` = `Slot1`
  - `0xa3bb6999` = `Slot2`

**`0xa34cef0`–`0xa34d285`** (keys=19, named=2)
  - `0x094fcecb` = `NotifyCamera`
  - `0x304ff7fb` = `None`

**`0xa361c50`–`0xa361feb`** (keys=19, named=2)
  - `0x304ff7fb` = `None`
  - `0xc0f57250` = `TestIcon`

**`0xa7940d0`–`0xa7943f8`** (keys=16, named=2)
  - `0x58de2772` = `Normal`
  - `0xe1e7b894` = `Count`

**`0xa374d80`–`0xa37504a`** (keys=14, named=2)
  - `0x0e1ef32d` = `Jump`
  - `0xd0a88c3e` = `SkillJump`

**`0x6d81120`–`0x6d815e8`** (keys=13, named=2)
  - `0x37386ae0` = `id`
  - `0x5c1ccea2` = `de`

**`0xa375230`–`0xa3754cd`** (keys=13, named=2)
  - `0x0e1ef32d` = `Jump`
  - `0x58de2772` = `Normal`

**`0xa775600`–`0xa7758a3`** (keys=13, named=2)
  - `0x7d7558d4` = `ADD`
  - `0x91666dc6` = `AND`

**`0x19447fa0`–`0x19448ca4`** (keys=13, named=2)
  - `0x37386ae0` = `id`
  - `0x5c1ccea2` = `de`

**`0xa386cf0`–`0xa386f6c`** (keys=12, named=2)
  - `0x0815aad4` = `Refresh`
  - `0xbb34f8e1` = `Multiple`

**`0xab61e80`–`0xab620fc`** (keys=12, named=2)
  - `0x304ff7fb` = `None`
  - `0xaf18b613` = `JumpBoard`

**`0xfb48540`–`0xfb48a9a`** (keys=12, named=2)
  - `0x14c8d3ca` = `offset`
  - `0x23a0d95c` = `size`

**`0xa770070`–`0xa7702c8`** (keys=11, named=2)
  - `0x58de2772` = `Normal`
  - `0x58e25863` = `Cut`

**`0x13415bc0`–`0x13416095`** (keys=11, named=2)
  - `0x2c96ccf4` = `Wave`
  - `0x4b822fa6` = `SkillInfo`

**`0xa33be40`–`0xa33c074`** (keys=10, named=2)
  - `0x304ff7fb` = `None`
  - `0x401da918` = `Prop`

**`0xa37a560`–`0xa37a794`** (keys=10, named=2)
  - `0x58de2772` = `Normal`
  - `0x7f2c2a34` = `Move`

**`0xa38d9d0`–`0xa38dc04`** (keys=10, named=2)
  - `0x19dc307e` = `Default`
  - `0x4115d182` = `Random`

**`0xa762780`–`0xa7629b4`** (keys=10, named=2)
  - `0x26be3ad9` = `Dialog`
  - `0xfc7c63d0` = `Invalid`

**`0xa78f070`–`0xa78f2a4`** (keys=10, named=2)
  - `0x2ffcbe05` = `Test`
  - `0x304ff7fb` = `None`

**`0xa7905b0`–`0xa7907e4`** (keys=10, named=2)
  - `0x1c70fc20` = `Player`
  - `0x7e84b35e` = `SavePoint`

**`0x93f9150`–`0x93fa7b8`** (keys=9, named=2)
  - `0x32608848` = `target`
  - `0xfe30d09f` = `event`

**`0xa355060`–`0xa355271`** (keys=9, named=2)
  - `0x304ff7fb` = `None`
  - `0xdd60ed33` = `World`

**`0xa794400`–`0xa794614`** (keys=9, named=2)
  - `0x29742e5c` = `Show`
  - `0x2c96ccf4` = `Wave`

**`0xa34ee80`–`0xa34f073`** (keys=8, named=2)
  - `0x304ff7fb` = `None`
  - `0x9810e8f3` = `ButtonCheck`

**`0xa34f080`–`0xa34f276`** (keys=8, named=2)
  - `0x70e72f55` = `OTHER`
  - `0x732a0f1b` = `NONE`

**`0xa353950`–`0xa353b46`** (keys=8, named=2)
  - `0x55619224` = `ALL`
  - `0x732a0f1b` = `NONE`

**`0xa353b50`–`0xa353d46`** (keys=8, named=2)
  - `0x28742cc9` = `Shop`
  - `0xd6aab198` = `ShopRefresh`

**`0xa35aeb0`–`0xa35b0a9`** (keys=8, named=2)
  - `0x304ff7fb` = `None`
  - `0xcd013a7e` = `WindowFrame`

**`0xa393890`–`0xa393a89`** (keys=8, named=2)
  - `0x304ff7fb` = `None`
  - `0xea87109e` = `Pull`

**`0xa775dd0`–`0xa775fc6`** (keys=8, named=2)
  - `0x727b390b` = `Orange`
  - `0xa953c75c` = `Green`

**`0xf759e10`–`0xf75a03b`** (keys=8, named=2)
  - `0x07e055dc` = `Mesh`
  - `0xcbd54f80` = `Material`

**`0xa343ee0`–`0xa3440ae`** (keys=7, named=2)
  - `0x0dc6b4aa` = `Off`
  - `0x19dc307e` = `Default`

**`0xa3591b0`–`0xa35937e`** (keys=7, named=2)
  - `0x304ff7fb` = `None`
  - `0xbe990ac3` = `TogglePrefab`

**`0xa37a910`–`0xa37aad8`** (keys=7, named=2)
  - `0x5ea410bd` = `Floor`
  - `0xfc7c63d0` = `Invalid`

**`0xab66470`–`0xab6663e`** (keys=7, named=2)
  - `0x304ff7fb` = `None`
  - `0x401da918` = `Prop`

**`0xca2e760`–`0xca2eaed`** (keys=7, named=2)
  - `0x5b55aa06` = `alive`
  - `0xd22f9095` = `score`

**`0xc7e8000`–`0xc7f58ea`** (keys=726, named=1)
  - `0xebc1674d` = `UndoComponentsHandler`

**`0xa780990`–`0xa78b0c0`** (keys=563, named=1)
  - `0x19dc307e` = `Default`

**`0xa75c860`–`0xa760eb3`** (keys=255, named=1)
  - `0x304ff7fb` = `None`

**`0xa38ff90`–`0xa393294`** (keys=189, named=1)
  - `0x32ac9537` = `TableCheckHandler`

**`0xa35ede0`–`0xa360bb5`** (keys=133, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa38b390`–`0xa38cb29`** (keys=117, named=1)
  - `0x58de2772` = `Normal`

**`0x1962fca0`–`0x19630ee7`** (keys=96, named=1)
  - `0x9cd435fa` = `sha256`

**`0xa389050`–`0xa389d15`** (keys=72, named=1)
  - `0x304ff7fb` = `None`

**`0xa387a90`–`0xa388133`** (keys=40, named=1)
  - `0x0e1ef32d` = `Jump`

**`0xa35a370`–`0xa35a9da`** (keys=38, named=1)
  - `0x304ff7fb` = `None`

**`0xab63c30`–`0xab6420d`** (keys=34, named=1)
  - `0x732a0f1b` = `NONE`

**`0xab621a0`–`0xab6275d`** (keys=33, named=1)
  - `0x36d11e29` = `SEARCH`

**`0xa774cc0`–`0xa775263`** (keys=32, named=1)
  - `0x304ff7fb` = `None`

**`0x19bbb300`–`0x19bbb98a`** (keys=32, named=1)
  - `0x9cd435fa` = `sha256`

**`0x19630f90`–`0x19631663`** (keys=30, named=1)
  - `0x9cd435fa` = `sha256`

**`0xa339910`–`0xa339e03`** (keys=28, named=1)
  - `0x19dc307e` = `Default`

**`0xa76c840`–`0xa76cd33`** (keys=28, named=1)
  - `0x304ff7fb` = `None`

**`0xa76cd40`–`0xa76d22d`** (keys=28, named=1)
  - `0x304ff7fb` = `None`

**`0xa761e00`–`0xa7622c7`** (keys=27, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa38a6a0`–`0xa38ab33`** (keys=26, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa3933e0`–`0xa393873`** (keys=26, named=1)
  - `0xfc7c63d0` = `Invalid`

**`0xa762b30`–`0xa762f2b`** (keys=22, named=1)
  - `0x304ff7fb` = `None`

**`0xa7775c0`–`0xa7779bb`** (keys=22, named=1)
  - `0x304ff7fb` = `None`

**`0xc7e5c70`–`0xc7e6025`** (keys=20, named=1)
  - `0x66a677f0` = `NPC`

**`0xd03a7f0`–`0xd03b3e4`** (keys=18, named=1)
  - `0x14c8d3ca` = `offset`

**`0xa33a5e0`–`0xa33a8dd`** (keys=15, named=1)
  - `0x572b11b7` = `QuestEvent`

**`0xa34fea0`–`0xa350199`** (keys=15, named=1)
  - `0x304ff7fb` = `None`

**`0xa759e60`–`0xa75a159`** (keys=15, named=1)
  - `0x283352d2` = `COMMAND`

**`0xa77d000`–`0xa77d2fd`** (keys=15, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa78d170`–`0xa78d46d`** (keys=15, named=1)
  - `0x304ff7fb` = `None`

**`0xa331070`–`0xa33133a`** (keys=14, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa379fa0`–`0xa37a26a`** (keys=14, named=1)
  - `0x1ca5a7a6` = `MaxValue`

**`0xa32fea0`–`0xa33013d`** (keys=13, named=1)
  - `0xfc7c63d0` = `Invalid`

**`0xa362fd0`–`0xa36324c`** (keys=12, named=1)
  - `0x58de2772` = `Normal`

**`0xa389d20`–`0xa389f9c`** (keys=12, named=1)
  - `0x8eb61aed` = `Any`

**`0xa770f10`–`0xa77118c`** (keys=12, named=1)
  - `0x6cf1ba25` = `Toggle`

**`0xa77deb0`–`0xa77e126`** (keys=12, named=1)
  - `0x13bcde7d` = `Gadget`

**`0x19c3fb40`–`0x19c40169`** (keys=12, named=1)
  - `0x203bf453` = `RENAME`

**`0xa0a7460`–`0xa0a7997`** (keys=11, named=1)
  - `0x84e9f1ae` = `memory`

**`0xa352500`–`0xa352752`** (keys=11, named=1)
  - `0x19dc307e` = `Default`

**`0xa362760`–`0xa3629b2`** (keys=11, named=1)
  - `0xe1e7b894` = `Count`

**`0xa379b70`–`0xa379dc2`** (keys=11, named=1)
  - `0xaf8c40dd` = `Quest`

**`0xa387040`–`0xa387292`** (keys=11, named=1)
  - `0x65715141` = `Combat`

**`0xa35ddb0`–`0xa35dfde`** (keys=10, named=1)
  - `0x13254bc4` = `all`

**`0xa34e620`–`0xa34e831`** (keys=9, named=1)
  - `0x304ff7fb` = `None`

**`0xa361400`–`0xa3615ea`** (keys=9, named=1)
  - `0x8ad2f8cf` = `Light`

**`0xa375b50`–`0xa375d5b`** (keys=9, named=1)
  - `0x304ff7fb` = `None`

**`0xa76f8e0`–`0xa76faf1`** (keys=9, named=1)
  - `0x7ce203fe` = `DEFAULT`

**`0xa7705c0`–`0xa7707d1`** (keys=9, named=1)
  - `0xd63556b0` = `Water`

**`0xa7973c0`–`0xa7975d1`** (keys=9, named=1)
  - `0x304ff7fb` = `None`

**`0xa797890`–`0xa797aa1`** (keys=9, named=1)
  - `0x304ff7fb` = `None`

**`0xab65fb0`–`0xab661c1`** (keys=9, named=1)
  - `0x6fd141d6` = `Skill`

**`0x106e4230`–`0x106e464b`** (keys=9, named=1)
  - `0x25f53d4d` = `LevelInfo`

**`0xa33d960`–`0xa33db50`** (keys=8, named=1)
  - `0xaf8c40dd` = `Quest`

**`0xa350440`–`0xa350639`** (keys=8, named=1)
  - `0x58de2772` = `Normal`

**`0xa355390`–`0xa355586`** (keys=8, named=1)
  - `0x7d376697` = `Element`

**`0xa3885e0`–`0xa3887d6`** (keys=8, named=1)
  - `0xfc7c63d0` = `Invalid`

**`0xa77fa00`–`0xa77fbf6`** (keys=8, named=1)
  - `0x304ff7fb` = `None`

**`0xa798a00`–`0xa798bf0`** (keys=8, named=1)
  - `0xaf8c40dd` = `Quest`

**`0xab66270`–`0xab66466`** (keys=8, named=1)
  - `0x23a5c9f2` = `others`

**`0xa32f7f0`–`0xa32f9be`** (keys=7, named=1)
  - `0x58de2772` = `Normal`

**`0xa363880`–`0xa363a48`** (keys=7, named=1)
  - `0x304ff7fb` = `None`

**`0xa3795b0`–`0xa379778`** (keys=7, named=1)
  - `0xfc7c63d0` = `Invalid`

**`0xa51bc90`–`0xa51bfec`** (keys=7, named=1)
  - `0x77eb0235` = `Score`

**`0xa775c00`–`0xa775dce`** (keys=7, named=1)
  - `0x732a0f1b` = `NONE`

**`0xa77f7c0`–`0xa77f98e`** (keys=7, named=1)
  - `0x126befb6` = `Auto`

**`0xf37f800`–`0xf380183`** (keys=7, named=1)
  - `0x3e61e3c0` = `LastWave`

**`0xfb640f0`–`0xfb64332`** (keys=7, named=1)
  - `0x23a0d95c` = `size`

**`0x106a71e0`–`0x106a75cd`** (keys=7, named=1)
  - `0xd5bdbb42` = `height`

**`0x195aa490`–`0x195aa94d`** (keys=7, named=1)
  - `0x5d7aced6` = `HKEY_CURRENT_USER`

named instances total = 890

---

## 7. Reproduce


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


Artifacts: `.runtime/scratch/FNV-DISPATCHERS-FULL.json` (scan + 332 dispatchers + keys + offsets + controls),
`.runtime/scratch/FNV-CRACK-FINAL.json`, `.runtime/scratch/FNV-NAMED-FINAL.txt`,
`.runtime/scratch/FNV-DICT-AUX.txt`. Tests: `tools/editor-catalog/tests/test_fnv_dispatchers.py` (24 tests, all pass).

## 8. OPEN

* 9,387 distinct keys unnamed (§5) — all in enum/table dispatchers; **0** in the 2 command dispatchers.
* The editor "system menu" panel (currency/item/shop template management) was never reversed — Q-B's
  negative does not cover it (§4 Q-B).
* `SpawnMonster` (`0xfd80b2ce`, dispatcher `0xc700190`) — candidate, uncorroborated, likely a generator
  coincidence; not a component add regardless (§4 Q-A).
* The component **add** capability is proven at the **entity-model** layer, not the command layer (§4 Q-A).
