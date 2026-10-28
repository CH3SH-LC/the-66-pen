# 通用拼接

旧 reparent 和 semantic-assembly 依赖蒙德 `current-state.json`、固定计划和 1073741846。
现在两者支持显式 `--ownership`，从当前正式存档绑定目标关卡、SHA、实体和操作对。
未传该参数时保留旧合同；旧脚本不能当作通用安装器直接运行。

## 输入与顺序

1. `context.open` → `context.instances`，获得当前对象。
2. 明确完整 host/child 清单及配对；不要从模板 ID 推断实例 ID。
3. `context.ownership` 输入 `entity_ids`、`accessory_ids`、`reparent`、`convert`。
4. `scene.inspect` 获取新基线。request 是
   `{"schemaVersion":1,"levelId":当前关卡,"pairs":[...]}`。
5. 读 `transform.reparent_prepare` / `transform.semantic_assembly_prepare` schema，
   传 `mode=set`、`baseline`、`request`、`save`、`ownership`；prepare 不执行。
6. 单次 dispatch → 解码 → 原生保存 → 独立比较附件父子关系、世界姿态、材质和数量。

转挂对：`accessoryId/oldHostId/hostId` 三者不同，附件不能重复、不能形成嵌套环。
实体转换对：`sourceId/hostId`；源不能已有附件。
原生卡最多 64 对，父对象最多 128 个；host 容量 999；宿主缩放必须均匀且正数；
源是内建静态场景模型，无逻辑；继承材质一致。转换空间上限水平 200/垂直 100，
实际卡使用本批实际跨度收紧，不能为了通过而放宽上限。

清单中的 levelId 同时进入原生编译卡；回执绑定 prepared SHA、代码指纹和本次关卡，
不会把“支持跨存档”解释为取消关卡检查。保护关卡仍不可写。

## 批量策略

整栋、整段墙、整段道路连装饰按语义分组；保持原世界姿态、材质和碰撞。
先安排转挂再转换宿主，避免转换仍有附件的实体。近期原生回调需自适应 1–4 件，
目标 1800ms，保留原硬预算及停止条件；完整卡的成功前缀必须先保存/审计。
计划数量、内存已完成数量、正式已保存数量分别记录，不能合并成一个“完成”数。

换存档只换当前上下文/清单/基线，不修改代码里的关卡常量。
换游戏版本必须重新确认 runtime profile；跨存档可用不代表跨版本无需适配。
本次新增通用分支有离线合同和编译验证；不继承旧蒙德分支的真机验收结论。

旧 `reference-refinement-20261026/contract-staging` 会覆盖生产合同；现只作历史材料。
不得运行旧 apply_reference_contract 来覆盖本次通用版本。
