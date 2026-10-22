> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 实体创建的名称规则：templateId → 保存后的实体名

范围：`entity.create` 组的必备前置——`tools/game-executor/verify-created-save.py` 的 `--name`（expectedName）必须**在创建之前**从预先核实的目录/规则得到，不能创建后再从待验 GIL 里反抄（那样名称断言恒真，验证器退化成自证）。

判定日期：2026-09-29（离线，无游戏进程、无提权、无 UAC）。本轮 runId `f87472fb0a5cc2b77e1446124787e05d`。

---

## 0. 三选一结论

**选 (a)：创建出来的实体名 = 预制目录里该 templateId 的 `name` 字段。**

限定的条件是「创建时不传名字、且之后没有改名」。这是本项目实际使用的创建路径的形状：

* 原生工厂 `ge::scene::place_builtin` 的入参 `struct PlacementInput` 只有 `template_id / world_position / context_origin / rotation_degrees / scale` 五项，**没有名字**（`tools/game-executor/native/scene_calls.h:30-36`）；它调用的原生工厂 ABI（同文件 16-20 行的 `PlacementFactory`）也没有名字参数，且唯一的自由指针 `optional_data` 实际传 `nullptr`（`scene_calls.cpp:33`：`factory(context, template_id, 1, &position, &rotation, &scale, 0, 1, nullptr, 0, 0)`）——即创建时不存在传入名字的通道。
* CLI 的 create 只有 `--template-id/--position/--rotation/--scale`（`tools/game-executor/scene_cli.py:614-618`），组装 `PlacementInput` 时同样只有这五样（`tools/game-executor/native/game_scene_action.cpp:186-190`、`258-270`）。
* 名字是游戏在保存时按模板写进去的，等于编辑器物化预制注册表（只读桥操作 `prefab-catalog`，`tools/editor-bridge/Adapter/SceneCatalog.cs:105-125`）里同一 registryId 的 `name`。

**不是 (b) 固定模式。** 反例见第 4 节：同一次战役里 template 20001875 的实体在存档里叫 `MW_Static_P0_Tile3`，而那批实体是本项目**离线移植工具自己写名字**的结果（`tools/editor-bridge/build-static-level-draft.py:163-180` 的 `make_entry` 显式写 `MW_Static_P{n}_Tile{k}`）；改名（编辑器改名、CRUD 探针改名）也会覆盖它。

**不是 (c) undecidable**，因为 (a) 有实测样本支撑（第 3 节：40/40 战役样本 + 真实存档 36,188 条一致记录），(b) 有正面反证。

---

## 1. verify-created-save.py 里 name 的编码与比对语义

源码：`tools/game-executor/verify-created-save.py`。

| 项 | 实测事实（源码位置） |
| --- | --- |
| CLI 形状 | `--name` 必填（`parser.add_argument('--name', required=True)`，第 225 行） |
| 非空 | `if not args.name or ... parser.error('Name must be nonempty; ...')`（第 235-236 行） |
| 记录内位置 | root5 → 实体记录 → field 5（重复的 name 组件），筛 `field1 == 1`（NAME 类型）；其 field 11 → field 1 = UTF-8 字节串（第 174-177 行） |
| 比对方式 1（解析器） | `require(entity.name == args.name, 'Target name mismatch')`（第 165 行），`entity` 来自 `miliastra_agent.parsers.entities.parse_payload` |
| 比对方式 2（原始字节） | `one(one(names[0], 11), 1).decode('utf-8') == args.name`（第 176 行） |
| 「唯一且不歧义」的含义 | 要求该记录里 `field1==1` 的 name 组件**恰好 1 个**、其 `field11` **恰好 1 个**、`field11.field1` 恰好 1 个；否则报 `'Target name is missing or ambiguous'`。源码注释（第 166 行）：`Do not allow parser defaults or ambiguous duplicate identity/name fields to pass.` |
| 精确性 | **精确相等**：不做大小写折叠、不做空白裁剪、不做 Unicode 归一化；名字**没有容差**（容差只用于几何，`max(--abs-tolerance, 2 ULP)`，第 104-122 行） |
| 非法 UTF-8 | `.decode('utf-8')` 抛 `UnicodeDecodeError`，它是 `ValueError` 子类，被主循环捕获成 `report['error']`，退出码 1（第 248-251 行） |
| 负例 | 历史隔离负例 `wrong-name` 实测 `returncode=1`、`error='Target name mismatch'`（`.runtime/game-executor/host-route-20260921/save-verifier/root-independent/wrong-name.json`） |

**「唯一」不是指名字在全局唯一。** 目录里 1097 个非空名字中 421 个被 ≥2 个 templateId 共用（`乔木` 覆盖 72 个 id、`灌木` 58、`山石` 40、`岩石` 35；`20001200` 与 `20001001` 都叫 `乔木`）。所以名字永远不能单独证明 templateId，必须与 `--template-id` 一起断言——这也是验证器把 template 与 name 分成两条独立断言的原因。

---

## 2. 名字的真实来源

`prefab-catalog` 是只读桥操作，读编辑器**物化注册表**，每条输出 `{registryId, name, iconPath, nativeKind}`（`SceneCatalog.cs:105-125`；`PrefabCatalogLimit = 4000`，`total` 报告实际条数）。

两次**独立采集**的目录：

| 采集 | 时间（本地） | 文件 | sha256 | 条数 |
| --- | --- | --- | --- | --- |
| p02 | 2026-09-26 23:18 | `.runtime/editor-bridge/elevated-interfaces-p02-571b9f753bb0467aa39fc7f71951a52f/2dfcea43f9904b71b6b6ccc42c94f47e.response.json`（op 见同名 `.submission.json`：`{"kind":"call","op":"prefab-catalog"}`） | `c9d22bf4d56420974ff6dcdaedeef641bed4147e48d85e5a1bd402542e3f2c61` | 2722 |
| geometry-fix R219 | 2026-09-28 20:02 | `.runtime/verification/interface-experiments-20260928/geometry-fix/prefab-catalog-r219.json` | `46faaa35cdd58c38cb513b865e06e48ef9bc8b865e11927ea5db0ab5698726f3` | 2722 |

**两次相隔 38.7 小时的采集完全一致**：registryId 集合相同（2722 = 2722，`truncated=false`），2722 个名字逐一相同，差异 0 条。

**第三层稳定性核对**：`.runtime` 下 `catalog-*.json`（桥操作 `catalog`，含 84 条 `prefabCandidates`，覆盖 2026-09-19 → 2026-09-26）共扫到 224 个含候选列表的采集文件、18,156 行、84 个不同 registryId，与冻结目录**逐条比对 0 条差异**（84 个 id 全部收录）。命令与输出见第 6 节尾部。

第三条独立证据线是**编辑器运行时观察**（不是存档、不是预制目录）：`.runtime/editor-bridge/elevated-interfaces-p02-571b9f753bb0467aa39fc7f71951a52f/24092650bc7442fea8e3d578300d5c01.response.json` 与 `.runtime/verification/interface-experiments-20260926/catalog-001.json` 的 `scene.entities` 报告实体 1077936129/130/131 `templateId=20001034` 名字 `石质元素立方体`——与预制目录、与保存后的 GIL 三处一致。

创建路径不传名字的证据（源码）：`scene_calls.h:16`、`scene_calls.cpp:11-32`、`scene_cli.py:614-618`、`game_scene_action.cpp:186-190` 与 `258-270`。

---

## 3. 实测证据（带路径与样本）

### 3.1 本轮战役：40 个模板全部一致

`CATALOGUE_SAMPLE_20260928` 的 40 个 id，逐个「创建 → 保存 → 从正式 GIL 读回」，读回名字与目录名字 **40/40 全等**（比对脚本：本轮 `catalog-vs-gil-names` 逻辑，见第 6 节工具）。

| templateId | 保存后实体 id | GIL 名字 | 目录名字 | 判定 |
| --- | --- | --- | --- | --- |
| 20001002 | 1077936132 | 乔木 | 乔木 | 一致 |
| 10005018 | 1077936133 | 空模型 | 空模型 | 一致 |
| 10009001 | 1077936136 | 长方体 | 长方体 | 一致 |
| 20001137 | 1077936144 | 木质鸟居 | 木质鸟居 | 一致 |
| 20003455 | 1077936171 | 香肠 | 香肠 | 一致 |

证据：`.runtime/verification/interface-experiments-20260928/template-coverage/formal-diff-batch16.json`（`placedNames`，17 条）、`RESULT-ADDENDUM-BATCH23.json` 的 `secondBatch.formalGilDiff.placedNames`（23 条）、`RESULT.json`。

### 3.2 真实存档的批量独立核对

用本轮的独立只读扫描器（自写 protobuf span walker，不依赖 `miliastra_agent`）遍历 `.runtime` 下全部 `.gil`：

* 扫描 2603 个 GIL 文件（4 个故意破坏容器的负例被解析器拒收，2599 个成功），93,328 条实体记录，93,287 条同时有可解码名字与 templateId。
* 与目录比对：**80,584 条一致**，12,703 条不一致。
* 12,703 条不一致中：12,512 条是 `MW_` 前缀（本项目离线移植工具显式写的名字），190 条是 `RT_Probe_Tree`（改名），1 条来自第三方样例文件；**没有第 4 类**。
* 真实游戏存档子集（路径含 `Beyond_Local_Save_Level`，741 个文件、40,605 条记录）：**36,188 条一致 / 4,417 条不一致**，不一致全部是 `MW_`（4,352）与 `RT_`（65），其余为 0。
* 93,328 条记录中只有 8 条读不出名字，全部是 `authoring-api-20260923/saved-fixtures/` 的手工合成负例（entity_id 200、template 300）；**真实存档里没有一条缺名字**。

汇总产物：`.runtime/verification/entity-create-full-run/f87472fb0a5cc2b77e1446124787e05d/catalog-vs-gil-names.json`（逐条 mismatch 清单）、`scan-all.stdout.txt`。

单文件样本（`recovery.gil` = 战役前关卡 1073741839 的 14 条，全部一致）：

| 实体 id | templateId | GIL 名字 | 目录名字 |
| --- | --- | --- | --- |
| 1077936129 | 20001034 | 石质元素立方体 | 石质元素立方体 |
| 1077936130 | 20001034 | 石质元素立方体 | 石质元素立方体 |
| 1094713345 | 10003004 | 关卡实体 | 关卡实体 |
| 1086324737 | 1086324737 | 默认模版 | 默认模版 |
| 1090519041 | 1090519041 | 默认模版(角色编辑) | 默认模版(角色编辑) |

路径：`.runtime/verification/interface-experiments-20260928/template-coverage/reviews/save-t2/recovery.gil`（14/14 一致）。另：`.runtime/editor-bridge/backups/20260928T102824Z-pre-interface-campaign-20260928/files/Beyond_Local_Save_Level/1073741835/1073741835.gil` 235/235 一致；`.../1073741829.gil` 12/12；`.../1073741828.gil` 11/11。

**覆盖度诚实说明**：真实存档里出现的 templateId 只有 15 个（都是同一批关卡对象），战役样本 40 个，合计可核对的一致模板不到 2722 的 2%。这是样本，不是全量证明。

---

## 4. 反例与边界（为什么不能写成固定模式，也不能只靠名字）

1. **创建方自己写名字会覆盖它。** `tools/editor-bridge/build-static-level-draft.py:163-180` 的 `make_entry(entity_id, template_id, name, position)` 把调用方给的名字写进 `Property.Name`；离线移植出来的 34 个格子在存档里是 `MW_Static_P0_Tile0`…`MW_Static_P5_Tile8`，而 templateId 仍是 20001875/20001876/20001877/20001878/20001224（目录名字分别是 通常立方体/坚固立方体/冰质立方体/火质立方体/木质箱子）。这一类在扫描里占 12,512 条。
2. **改名会覆盖它。** CRUD 探针把 20001200（目录名 `乔木`）的实体改名成 `RT_Probe_Tree`（190 条），保存后存档里就是新名字。
3. **第三方文件里存在一处不一致**：`.runtime/research-sources/ecosystem/Ayaya_Miliastra_Editor/.../ugc_file_tools/builtin_resources/seeds/template_instance_exemplars.gil` 中 templateId 20001240 的名字是 `武器管理`，目录里是 `拐杖糖果`。该文件是外部工具的种子样例（不是本工程产出的存档），本工程真实存档里没有出现同类偏差。**这一条我没有解释清楚，见 notVerified。**
4. **3 个 registryId 的目录名字为空**：1000000、1000001、10003001。若对它们走这条验证路线，`verify-created-save.py` 会以「`--name` 不能为空」直接拒绝（第 235 行），即这 3 个 id 无法用名字断言验收。
5. **名字不唯一**：421 个名字被 ≥2 个 id 共用（第 1 节），名字只能作为辅助断言。
6. **版本相关**：以上是 7.1.0 CN 客户端。换客户端版本必须重新采集、重新冻结，不能沿用。

---

## 5. 若要对「目录里存在、但从未实测过」的模板做判定，唯一能判定的实验

残余未决量：2722 个 id 里只有 40 个（战役）+ 十几个（历史存档）被实测过；**「任意给定 templateId 都按目录名字落盘」这件事没有被证明**，只是被 40/40 与 36,188 条真实记录高度支持。判定它对某个具体 id 成立的唯一实验（需要在允许实机的窗口里做，本轮硬约束下没做）：

1. **先冻结期望值（顺序是关键，防止自证）**：
   `python -B tools/game-executor/entity_name_rule.py show --template-id <T>` → 记录 `expectedName` 与 `directorySha256`，写进 intent 后再执行任何创建。
2. **取完整前后基线 + 恢复副本**：按 `docs/ds-handoff/07-ENTITY-CREATE-FULL-RUN.md` S02 的基线/备份步骤（`backup-account-saves.py create` + `verify`）。
3. **走已审核创建**：`scene_cli.py create --elevated-queue <queue> --review <review> --level-id <本关真实 id> --template-id <T> --position x y z --rotation 0 0 0 --scale 1 1 1`，拿到 `entityId`。
4. **保存**：`scene_cli.py save ...`（新 review、新 requestId）。
5. **差分**：`verify-created-save.py <before.gil> <after.gil> --entity-id <id> --template-id <T> --name "<第 1 步冻结的 expectedName>" --position ... --out <.runtime/game-executor/... 新文件>`。
   * 退出码 0 且 `ok=true` → 对该 id 支持 (a)。
   * 退出码 1 且 `error='Target name mismatch'` → (a) 不成立；此时**另做一次只读取回**，把实际名字与目录名字并列比较：若实际名字是规则化的（如带编号/前缀的固定模式），记 (b) 并给出式样；若实际名字与目录名无任何关系且每次不同，记 undecidable。
6. **判 (b) 的附加条件**：同一 templateId 创建两次，若两个实体名字不同 → 说明名字含 id/序号，是 (b)；若两次相同且都 ≠ 目录名 → 说明来源是另一个名字表，需要重新找来源（(c)，并记录该名字表的位置）。

判据必须是「先冻结、后创建」，否则第 5 步就是自证。

---

## 6. 可复用工具

### 6.1 冻结目录

`docs/research/entity-create/prefab-name-directory.json`
sha256 `44d6afedc4eda2a123cf119b3c9e71fe9d36e794f97d6d6fa5f7ef920f0fefc8`，2722 条 `templateId → name`，`derivedFrom` 记录上面两次原始采集的路径与 sha256（两次采集必须一致才允许冻结）。

### 6.2 查表工具（纯离线，不碰实机）

`tools/game-executor/entity_name_rule.py`


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


可 import：`name_for(template_id)` / `require_name(template_id)`（空名与未收录 id 会抛错）。

实测（本会话）：

* `show --template-id 20001002` → `expectedName = "乔木"`，退出码 0。
* `show --template-id 1000000` → `expectedName = ""`、`nameIsEmpty=true`（即该 id 不能走名字验收）。
* `show --template-id 9999999` → 退出码 1、`template id 9999999 is not in the prefab name directory`。
* `verify` → `digestOk=true`、`total=2722`、`emptyNames=[1000000,1000001,10003001]`、`namesSharedByMultipleIds=421`、`widestDuplicateGroup={"name":"乔木","count":72}`、两份原始采集 sha256 均与 pin 相符。
* 51 个允许模板 id **全部收录、无一为空**（本轮实测）。

`verify-created-save.py` 的预期值应当由 `entity_name_rule.require_name(template_id)` 生成，或按第 5 节的顺序先冻结再创建；**任何情况下不要在创建后从待验 GIL 抄名字**。

### 6.3 本轮实际跑过的命令（离线只读，退出码为实测）

| 命令 | 退出码 / 结果 |
| --- | --- |
| `python -B .runtime/.../scan_gil_names.py --all --json .runtime/.../catalog-vs-gil-names.json` | 0；2603 文件、93,328 记录、80,584 一致 |
| `python -B tools/game-executor/entity_name_rule.py verify` | 0；`digestOk=true`、`total=2722` |
| `python -B tools/game-executor/entity_name_rule.py show --template-id 20001002` | 0；`expectedName="乔木"` |
| `python -B tools/game-executor/entity_name_rule.py show --template-id 1000000` | 0；`expectedName=""`、`nameIsEmpty=true` |
| `python -B tools/game-executor/entity_name_rule.py show --template-id 9999999` | 1；`template id 9999999 is not in the prefab name directory` |
| `python -B tools/game-executor/entity_name_rule.py list --duplicates --limit 4` | 0；`namesSharedByMultipleIds=421`，乔木 72 / 灌木 58 / 山石 40 / 岩石 35 |
| 内联脚本：224 个 `catalog-*.json` 的 `prefabCandidates` × 冻结目录 | 0；18,156 行、0 差异 |
| 内联脚本：遍历全部 GIL 找「读不出名字」的记录 | 0；8 条，全在 `authoring-api-20260923/saved-fixtures/`（entity_id 200、template 300） |

本轮扫描脚本本身在证据目录里：`.runtime/verification/entity-create-full-run/f87472fb0a5cc2b77e1446124787e05d/scan_gil_names.py`。

---

## 7. 本轮没有验证的（不要当成已验证）

* 没有跑任何实机创建/保存；第 5 节的实验是**方案**，不是结果。
* 没有证明 2722 个 id 全部满足 (a)：只测到 40 个战役样本 + 真实存档里出现的 15 个 templateId。
* 没有解释外部样例文件里 20001240 的 `武器管理` vs 目录 `拐杖糖果`（可能是外部工具自造样例，未查证）。
* 没有验证「同一次创建里名字的字节是否可能被游戏做本地化替换」（不同语言客户端未采集）。
* 没有验证空名 id 被创建时游戏是否会写入名字组件（无样本）。
