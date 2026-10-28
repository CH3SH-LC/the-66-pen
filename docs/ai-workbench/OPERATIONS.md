# 操作合同

所有调用通过 `ai.py`/MCP 的统一入口，错误返回 JSON，非零退出不重试。
原有 CLI 仍为生产实现，schema 从实际 argparse 捕获，源码和依赖 SHA 不一致即拒绝。
未审阅脚本只登记为 source，不在检索时导入。`script-coverage.json` 给出未登记清单。

| 操作域 | 工具族 | 必须具备的当前数据 |
|---|---|---|
| 当前关卡发现 | live.discover | 当前会话/明确传输；默认 UAC 路线会弹窗，优先显式 queue_dir |
| 操作系统会话发现、版本核验 | runtime | 当前安装路径与 profile；discover 只查询窗口/进程/线程身份 |
| helper 启动、状态、正常停止 | helper | 明确 queue/config/PowerShell host；start 需绝对 deadline_utc 和 operation_id |
| 场景检查、实体/生物创建、保存、重开 | scene | session、level_id、review（写入）、当前基线 |
| 完整批量排布 | scene.apply | 已启用 context、已有 helper、placements、operation_id |
| 位置/旋转/缩放/静态状态/拼接 | transform | baseline、inspection/request、正式 save、ownership（通用拼接） |
| 材质 | material | 原值/目标值、目标实例和当前基线 |
| 地形、水、环境选项 | terrain/water/native_tabs | 块/层/选项的当前 ID 和范围 |
| 节点图和绑定 | author/node/node_api | 当前桥 run_id、图 ID、真实 slots、完整配方 |
| 资源检查、模板属性、图标、外观 | asset/template/template_v2/icons/npc | 明确模板/资源类型，动态数据另需当前会话 |
| 试玩与截图 | playtest/visual | 当前编辑关卡和该操作授权；禁止沿用大世界控制授权 |
| 参考提取、配准 | reference/world_frame | 明确源锁、哈希、坐标锚点 |
| 存档解析与比较 | saved/context.readback | 实际正式文件，绝不写回 GIL |

`context.plan` 自动绑定该 context 的 level/session/save/queue。传入冲突值拒绝。
`context.call` 单次派发并保留日志；已知结果才释放本工作台写者锁，未知结果保留。
下层 helper 还有正式在途锁，禁止删除或绕过。桥图操作必须绑定当前桥会话，
缺桥身份时通用 context 拒绝执行，改用明确 author 参数与原生产守卫。

`scene.apply` 先全量校验输入，串行执行每步，失败立即停：

1. 保存上下文快照已建立。
2. 只读场景检查；生成本次创建 review 与恢复副本。
3. 一次创建批量；记录返回 ID。
4. 新检查；生成保存 review；一次原生 save。
5. 重新解析正式 GIL，逐个核对 ID、模板、位置、旋转、缩放及新增集合。

保存回执和正式内容吻合才 `nativeSaveVerified=true`。视觉、碰撞、通行和试玩保留单独状态。
如果创建后保存失败，报告 `sceneMayHaveChanges`；不自动重建或恢复文件。

截止时间不够完成操作时拒绝启动，context 有界（最多 24 小时）；当前用户授权更短时以用户为准。
没有运行 helper 时准备/索引可以离线做，执行不能伪称成功。
helper.start 包装既有启动器，只响应明确调用；延期 UAC 也受传给 runner 的绝对截止时间约束。
helper.stop 写 STOP，等待当前操作正常结束；不能把 stopRequested 当作已经退出。
helper.status 的新鲜心跳不等于已核验进程，返回 processVerified=false。
注册、UAC 和版本探针仍遵守 `docs/kb/ENTRIES/01-native-channel.md` 的真实流程；
本工作台不会自行重启游戏、编辑器或后台助手。
