# 给接手 AI 的执行顺序

## 1. 安装与启动

首次克隆先执行 `python -B -X utf8 ai.py build`，从公开源码生成本地 SQLite 索引。
源码更新后重建一次；日常搜索不重复构建。数据库不存入 Git 历史。

在已有工程运行 Python 3.11+。核心索引/CLI 仅用标准库；GIL/图解析沿用工程内
`backend/miliastra_agent` 及 protobuf 依赖；参考网格需要 numpy，窗口截图需要 Pillow，
原生编译需要本工程现有 Windows C++ 工具链。不要盲目全局安装或升级包。

读取存档或运行 `ai.py verify` 前，在当前 Python 环境执行
`python -m pip install "protobuf>=5,<8"`。查询与构建索引不需要此依赖。

`python -B -X utf8 ai.py configure` 生成本机绝对路径的 `data/ai-workbench/mcp.local.json`。
把其中 `mcpServers.miliastra` 导入支持 stdio MCP 的客户端；命令是 `ai.py serve`。
生成配置不代表已经替用户修改客户端。换机器必须重新 configure。

## 2. 只查所需信息

1. `ai.py status` 看覆盖、缺失库、未知节点字段。
2. `ai.py route 任务关键词` 得到工具顺序及必要输入。
3. `ai.py search 关键词` 默认返回 20 条摘要。结果含精确 id/source。
4. `knowledge.get` 取记录；`knowledge.read` 取源码最多 200 行。
5. `ai.py describe 工具名` 给出完整 schema、副作用与登记指纹。

禁止每轮调用 `catalog.verify_sources` 或重新构建整个库。只有源码变化或报漂移才更新。
默认搜索是各词同时匹配，中文无需分词。`offset/limit` 翻页，不能凭第一页推断不存在。

## 3. 绑定当前存档

创建 JSON 文件（尖括号是待填值，不可原样执行）：

```json
{"save":"<实际正式存档绝对路径.gil>","level_id":1234567890,"valid_minutes":60}
```

运行 `ai.py call context.open --file 参数.json`。记录返回的 `context`，后续传这个句柄。
先用 `context.instances` 查看真实 entityId/templateId；图 ID 也必须来自此档。
文件有内部关卡 ID 时必须吻合；无内部 ID 时必须保留正式 `save数字.gil` 文件名，
返回 `identityEvidence=formal-filename-no-embedded-id`，不会伪称内部验证。

默认离线。确实要制作且用户已授权时，在新 context 显式传
`native_enabled=true`、新鲜 `session` 文件、已有 `queue`。上下文只记录范围，
不创造授权；下层每次执行仍核对进程创建时间、版本、回执、过期和保存证据。

## 4. 执行和收尾

普通排布优先 `scene.apply`，一次批量最多 256 件。它包含检查→review→创建→检查→
review→保存→读回。其他操作用 `context.plan` 看完整命令，再 `context.call` 执行一项。
`operation_id` 必须唯一且稳定，结果不明不能换 ID 重试。

成功只按返回证据描述：`nativeSaveVerified`、`runtimeVerified`、`visualVerified`、
`passageVerified` 分开看。保存改变后旧 context 拒绝继续写；先 `context.readback`，
确认结果后显式创建新 context。失败用 `ai.py error 精确错误码`。

## 5. 不要踩的细节

- 所有 ID 都是 JSON 整数，不是浮点字符串；布尔值必须是 `true/false`。
- Windows 路径在 JSON 中用 `/` 或双反斜杠；优先 `--file`，不要多层转义命令。
- 向量是恰好 3 个有限数；缩放必须符合对应工具的正值/均匀限制。
- 模板同名不等于同物；节点同 definitionId 不等于同 graphKind。
- 动态端口先读实例槽位；配方里的占位符不是已有图/实体 ID。
- 活跃 helper 登记了代码指纹；改生产工具后先正常结束旧 helper 再登记新版本。
- 原授权截止不能通过新建 context 延长。当前工程已停止的作者任务不会自动恢复。
