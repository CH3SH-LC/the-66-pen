> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 旧命令与7.1比较指令对应

这是指定候选的静态定位，不是可执行接口清单。function是函数边界，at是cmp/mov位置，不冒充已验证handler。完整反汇编见机器证据（历史来源：`../../../.runtime/verification/docs-71-20260926/native-command-rescan-all38.json`）。

| 名称 | 旧状态 | 新函数 | 指令位置 | 当前结论 |
| --- | --- | --- | --- | --- |
| `AddInstructionGraphForEditObj` | matched | 0xcba3130 | 0xcba34fb, 0xcba3a9f | static-match；业务未验 |
| `AddInstructionGraphForPrefab` | matched | 0xcba3130 | 0xcba341c, 0xcba3440 | static-match；业务未验 |
| `ApplyPrefabInstanceChange` | matched | 0xcba3130 | 0xcba3882, 0xcba389a | static-match；业务未验 |
| `DeleteComponentForEditObj` | matched | 0xcba3130 | 0xcba3428 | static-match；业务未验 |
| `DeleteComponentForPrefab` | matched | 0xcba3130 | 0xcba388e | static-match；业务未验 |
| `DeleteDebugLog` | matched | 0xf03eb40 | 0xf03ed92 | static-match；业务未验 |
| `DeleteEditObj` | matched | 0xcba3130 | 0xcba3b7d | static-match；业务未验 |
| `DeletePCGInstance` | undecidable |  |  | 此口径未命中；不代表不存在 |
| `DeletePrefab` | matched | 0xcba3130 | 0xcba3513 | static-match；业务未验 |
| `DoExport` | matched | 0xf03eb40 | 0xf03ef48 | static-match；业务未验 |
| `DoExportClientScript` | 新增候选 | 0xf03eb40 | 0xf03ecf4, 0xf03eea1 | static-match；业务未验 |
| `DoImport` | matched | 0xf03eb40 | 0xf03ef30 | static-match；业务未验 |
| `EndLoadAllDebugLog` | disproved |  |  | 此口径未命中；不代表不存在 |
| `FocusBeyondTileMap` | matched | 0xcba3130 | 0xcba352b | static-match；业务未验 |
| `FocusCharacter` | matched | 0xcba3130 | 0xcba359c | static-match；业务未验 |
| `FocusDropGather` | matched | 0xcba3130 | 0xcba3911 | static-match；业务未验 |
| `FocusEditObj` | matched | 0xcba3130 | 0xcba3404, 0xcba3b89 | static-match；业务未验 |
| `FocusEsp` | matched | 0xcba3130 | 0xcba3a93 | static-match；业务未验 |
| `FocusLight` | matched | 0xcba3130 | 0xcba3c00 | static-match；业务未验 |
| `FocusLocalBullet` | matched | 0xcba3130 | 0xcba3434 | static-match；业务未验 |
| `FocusPCGInstance` | undecidable |  |  | 此口径未命中；不代表不存在 |
| `FocusPrefabInstance` | matched | 0xcba3130 | 0xcba3653 | static-match；业务未验 |
| `FocusScreenshot` | matched | 0xcba3130 | 0xcba3905, 0xcba391d | static-match；业务未验 |
| `ImportAllDebugLog` | matched | 0xf03eb40 | 0xf03ee95 | static-match；业务未验 |
| `ImportDebugLog` | matched | 0xf03eb40 | 0xf03ed0c | static-match；业务未验 |
| `ImportPerformanceReport` | matched | 0xf03eb40 | 0xf03ef3c | static-match；业务未验 |
| `JumpCombatSetting` | matched | 0xcba3130 | 0xcba3507, 0xcba351f | static-match；业务未验 |
| `ModifyEditObjName` | matched | 0xcba3130 | 0xcba37dd, 0xcba37f5 | static-match；业务未验 |
| `ModifyEditobjTag` | matched | 0xcba3130 | 0xcba3647, 0xcba366b | static-match；业务未验 |
| `ModifyFactionForEditObj` | matched | 0xcba3130 | 0xcba3721 | static-match；业务未验 |
| `ModifyFactionForPrefab` | matched | 0xcba3130 | 0xcba3715 | static-match；业务未验 |
| `ModifyPCGInstanceName` | undecidable |  |  | 此口径未命中；不代表不存在 |
| `ModifyPrefabName` | matched | 0xcba3130 | 0xcba365f | static-match；业务未验 |
| `ModifyPrefabTag` | matched | 0xcba3130 | 0xcba35a8 | static-match；业务未验 |
| `ModifySuite` | matched | 0xcba3130 | 0xcba3bf4 | static-match；业务未验 |
| `PlayMusic` | undecidable |  |  | 此口径未命中；不代表不存在 |
| `PlaySoundEffect` | undecidable |  |  | 此口径未命中；不代表不存在 |
| `RefreshExistDebugLogReport` | matched | 0xf03eb40 | 0xf03ed86, 0xf03ed9e | static-match；业务未验 |
| `RequestPrefabInstance` | matched | 0xcba3130 | 0xcba37e9 | static-match；业务未验 |
| `batchcreate` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `batchdelete` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `beyondClientScriptService` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `deleteNodeConfig` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `deleteSignal` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `modify` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `modifyNodeConfig` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `modifySignal` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `modifypath` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `sendScriptPath` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `wpfClientScriptService` | 新增候选 |  |  | 此口径未命中；不代表不存在 |
| `wpfColEditService` | 新增候选 |  |  | 此口径未命中；不代表不存在 |

旧38条中32条matched全部重定位，另6条未命中；新增13候选仅DoExportClientScript命中。当前主表33比较、导出表10比较，共43处对应33个名字，不是43条独立命令。
