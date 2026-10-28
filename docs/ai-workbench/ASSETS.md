# 素材、原件和参考的使用

`data/ai-workbench/asset-libraries.json` 列出期望库、实际存在状态和源集合。
`knowledge.search kind=library` 查域；`kind=asset` 查模板；
`kind=file` 可检索 geometry、mesh、material、reference、截图、GLB/OBJ 等具体文件。

| 层次 | 真实内容 | 使用限制 |
|---|---|---|
| 模板目录 | `data/m2/assets/prefab-catalog.json` | 模板 ID、中文名、族、原生类型、图标路径；不是放置成功证明 |
| 预制体原件 | `official-prefab-index.json` 及旁边 decoded 原件 | 来源和结构，不是可直接实例化的自定义网格 |
| 几何库 | `data/mondstadt/reference3d/template-geometry-v1` 和近期 resource-audit | 只覆盖实际提取的模板；未知尺寸保留未知 |
| 图标库 | `assets.dec` 容器及 icons 工具 | 容器存在、某图标存在、可渲染三者分开 |
| 玩法参考包 | `data/m2/reference-pack` | 道具/生物/地形/水/地图等源范围，不能混用模板 ID 与道具 ID |
| 原版参考 | reference3d、codex-main-street 下图像和网格 | 每份的来源、坐标系和配准证据都需保留 |
| 材质/地形/水/NPC | 对应工具目录及被索引 JSON | 参数范围取实际 schema；外观相似不是物理等价 |

操作路线：精确模板解析 → 查看 nativeKind → 查询尺寸/碰撞/枢轴 → 读取当前世界坐标原点 →
按位置/旋转/缩放生成 scene.plan → 当前场景预检 → 原生创建 → 保存读回 → 真机视觉。
不能为了填“全覆盖”而给未测模板统一尺寸、统一碰撞或统一可创建状态。

所有源文件只保留一份；索引记录路径和哈希，查询不重新解码。大文件不重复复制到知识库。
公开版只附模板技术目录、节点与自有研究文档。下表列出的原件、几何、图标和私人参考包
不随 GitHub 分发；`distribution.json` 与 `status` 明确标记缺失，不能视为现成可用。
不能用离线模型渲染替代游戏截图。
