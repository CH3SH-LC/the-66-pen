# 后台视觉采集与参考

`visual.window` 是可复用 Windows 窗口像素工具：
`pid`、`expected_image`、新的 `out_dir` 为必填。使用操作系统窗口和进程身份 API，
不读游戏内存、不发键鼠、不聚焦、不还原窗口。默认 1 帧，可显式设 1–120 帧、
0.5–30 秒间隔；每帧带 SHA 和真实路径。进程名称不符或窗口不唯一就拒绝。
输出目录必须在 `.runtime`，不覆盖已有帧。Pillow 仅用于保存采集像素。

图像结果要实际打开检查；`PrintWindow` 成功不等于镜头对准、全部物体入镜或视觉通过。
最小化、空白图、部分像素返回明确失败，不循环重试。窗口不可截图与后台编辑 API
是否可用是两回事，不能要求用户仅因某截图失败而退出重进编辑器。

引擎取图用已有 `playtest.prepare` 的 `scene-frame` 或 `render-frame`，明确当前 session、
target-level，再通过 helper 派发。旧 scene-overview 的 avenue/knights 等命名视角
是蒙德专用，不是跨地图通用坐标。固定视角失败必须读取清理回执和 cameraRestored；
不盲目再次启动摄像机操作。

原版视觉扫描历史素材由 `knowledge.search kind=file` 查 reference/walk/capture 等。
新参考采集若需要人物移动，应仅使用用户当前允许的正常输入方式；
本工作台没有增加直接修改角色内存、网络包或战斗数据的入口。
离线网格/草图/几何预览必须标注为离线，不能放进游戏截图验收栏。
