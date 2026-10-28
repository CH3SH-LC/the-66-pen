# AI 工具路由与知识库

入口：[AI-START-HERE.md](../../AI-START-HERE.md)。
先 `python -B ai.py describe 工具名`，再使用严格 JSON 参数调用。
`build.py` 从当前公开源码捕获 schema，缺少的私人工具不登记。
`build_knowledge.py` 只索引公开源文件；缺少的原始素材明确列出。
`validate_workbench.py` 使用离线样本，不启动游戏或 helper。
