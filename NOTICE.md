# 来源与许可

MIT 授权仅覆盖本项目作者编写的工具、适配器、文档和组织结构。来源是同一作者维护的千星编辑器研究工程及其中 AI 辅助编写的成果，导出来源与 SHA-256 见 `catalog/SOURCES.json`。

原神、千星奇域、HoYoverse、miHoYo 及其商标属于各自权利人；本项目与官方无关联。接口名称、数值编号、类型签名和必要兼容指纹是互操作性研究元数据，不构成对第三方游戏内容的再许可。

不分发官方游戏 DLL/EXE、游戏存档、图片音频、原始资源表、官方教程全文或整份反编译源码。读者需自行合法取得相关软件。历史研究中的原始代码段已移除，指向未公开本机证据的路径仅为历史来源标签。

基础 `pen.py` 与节点查询仅使用 Python 标准库。可选组件的依赖由用户另行安装：

| 组件 | 来源 | 许可证/说明 |
|---|---|---|
| Python | https://www.python.org/ | PSF License |
| .NET / Windows Desktop | https://github.com/dotnet/runtime | MIT；Windows 桌面依赖适用相应平台条款 |
| Visual C++ / Windows SDK | https://visualstudio.microsoft.com/visual-cpp-build-tools/ | Microsoft 工具链条款；本包不分发 |
| Snoop 6.1.1 | https://github.com/snoopwpf/snoopwpf | 上游 MS-PL；自行取得其签名发行包，本包不含二进制 |
| Python MCP SDK 1.27.0 | https://github.com/modelcontextprotocol/python-sdk | MIT；只用于可选旧 backend 服务 |
| ICSharpCode.Decompiler | https://github.com/icsharpcode/ILSpy | MIT；只用于可选本机元数据研究 |
| DeepSeek DSH / Cordis / Schemastery | npm 包，见 plugins/miliastra/package.json | 依赖未随包分发；安装前以各包附带 LICENSE 为准 |

`plugins/miliastra` 是自有的适配插件源码；DSH 主程序、上游依赖、私人 preset/会话与密钥均不包含。

`third_party/auto-miliastra/src` 包含 marcos0318/auto-miliastra 的 MIT 源码依赖，固定提交 `4de39f33f10d63c9e024a905cd802feae82bf82c`，保留完整 LICENSE；它不是游戏反编译源码。

`third_party/UGC-File-Generate-Utils/config/block_config.py` 是 luern0313/UGC-File-Generate-Utils 的 Apache-2.0 模板声明表，固定提交 `fba7c267a3752d3f0108b30020c46868d56acdd5`，保留 LICENSE；工具只做 AST 读取，不执行该上游文件。

MVP 容器编码器的字段依据来自 [UGC-Gia-Gil-ProtoBuf](https://github.com/luern0313/UGC-Gia-Gil-ProtoBuf) 的 MIT 格式研究，相关许可证保留在 `third_party/licenses/`。mvp 中的六实体示例仅为离线工具样本，不是此次验收的游戏内容。
