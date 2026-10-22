# 使用接口与工具

## 查接口

```powershell
python -X utf8 -B pen.py catalog component --limit 15
python -X utf8 -B pen.py catalog --family editor-bridge --offset 0 --limit 20
python -X utf8 -B pen.py catalog DoExport --static
python -X utf8 -B pen.py tools
```

结果中的 `source`、`line`、`sourceSha256` 对应本发行源码；`tool` 是调用入口，`args` 为可检查的帮助命令或参数模板。桥调用的 `<queue>`、`<run-id>` 需要自己建立的本机运行环境。完整字段和先决条件以 CLI `--help` 和实现为准。

`callTransportListed` 仅说明操作在 PowerShell 白名单；其他参数还要经过 runner 的字段检查。`callable=unknown` 的静态记录只提供研究工具，不能直接给游戏发送。动态生成的 CLI 子命令可能不在静态 AST 参数摘要里；源码是最终依据。

## 查节点

```powershell
python -X utf8 -B pen.py nodes search 商店 --graph-kind 20000
python -X utf8 -B pen.py nodes route "靠近 NPC 打开商店"
python -X utf8 -B pen.py nodes cluster interaction --graph-kind 20000
python -X utf8 -B pen.py nodes explain 307 --graph-kind 20000
python -X utf8 -B pen.py nodes recipe 307 --graph-kind 20000
python -X utf8 -B pen.py nodes enum 2
python -X utf8 -B pen.py nodes edge --graph-kind 20000 --from-id 307 --from-port 4:3 --to-id 259 --to-port 3:0
```

必须区分 graphKind 和 definitionId。输出的 create/add/wire 模板应填入真实图与节点标识；常量必须先读 live slots。`dynamicPorts.rawExcludedFromDistribution` 表示本发行包没有分发原始资源字段，`presentInSource` 表示历史元数据中是否有此类记录。

本包已移除官方教程全文，目录保留来源链接与技术参数。`nodes build` 是研究人员从自己采集的语料重建目录的入口，需要本机输入数据；普通用户直接用随包目录即可。

## 文件读写

```powershell
python -X utf8 -B pen.py inspect "你的副本.gil"
python -X utf8 -B pen.py inspect "你的导出.gia"
python -X utf8 -B pen.py diff "保存前副本.gil" "保存后副本.gil"
```

基础 Python 库位于 `tools/beyond-save/`：`gil_container.py` 提供容器与 protobuf 字段读写；`gia.py` 解析图、客户端脚本及实体导出；`terrain.py`、`component_edit.py`、`field15_edit.py`、`template_edit.py` 提供相应模型操作。未知字段保留，不能用当前已知 schema 重建并丢弃其余字段。

`pen.py inspect` 只读，`demo` 只在指定新文件里生成原创样本。离线文件编辑不会自动进入游戏，任何真实存档变更需要另外的版本与保存流程。

## MCP

支持 JSON lines 的 MCP stdio。配置示例（路径按自己系统填写）：

```json
{
  "mcpServers": {
    "the-66-pen": {
      "command": "python",
      "args": ["-X", "utf8", "-B", "/absolute/path/the-66-pen/pen.py", "mcp"]
    }
  }
}
```

可调用工具：

| 名称 | 参数 | 效果 |
|---|---|---|
| pen_catalog | query、family、offset、limit、static | 查询接口与来源 |
| pen_nodes | definition_id、graph_kind | 返回端口与建图配方 |
| pen_inspect | path | 只读解析用户明确指定的文件 |
| pen_doctor | 无 | 离线环境诊断 |

本 MCP 服务不提供任意 shell 或游戏写入端点。本地执行工具可用 `pen.py tool <别名> --help` 查看。更完整的历史业务 MCP 服务在 `backend/`，需要 `requirements-runtime.txt`、运行时会话及其各自 review/幂等/账本合同。

## 研究入口

原生消息/命令与 UI 候选在 `catalog/native-commands.json`、`catalog/user-operations.json`。工具 `tools/editor-catalog/fnv_dispatchers.py`、`fnv_command_surface.py`、`symbol-map-71.py`、`string_table.py`、`decode-mihoyobin.py` 可以分析使用者自行提供的文件；需要的可选反汇编库或 .NET 工具见各源码 import 与构建目录。符号/地址跨版本无效，字符串检索零命中也不是能力不存在的证明。

历史调研经 [调研索引](RESEARCH.md) 进入。错误码、地形/组件与实机证据判断见 [能力边界](BOUNDARIES.md)。

## 历史模板名称

`python -X utf8 -B tools/game-executor/entity_name_rule.py search 石 --limit 3` 可离线查找 2722 条冻结名称；115 条生物候选事实表见 `docs/research/entity-create/creature-template-candidates.json`。这些是历史 7.1 元数据，不是当前视觉或放置验收。`verify` 会报告原始私人回执未分发；查找只校验随包目录哈希。历史研究脚本中的调查输入、样例、证据路径并不保证随包齐备；受支持发行入口以 README、pen.py 的13个工具别名和本次验证记录为准。
