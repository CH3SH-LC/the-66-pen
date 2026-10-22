> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# UI-HUD-FINAL — `ui.hud` 的收口：编辑器里有没有任何东西能写进去让玩家看见？

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/UI-HUD-FINAL.md`。
> **本轮零执行**：全程离线只读。未连接 bridge、未发送任何 native/graph 请求、未启动或触碰游戏/编辑器、
> 未请求 UAC、未起 helper（正有一笔重启在挂），未读写 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 下任何文件。
> 所有「能/不能」均为**静态阅读（仓内源码 + 离线语料 + 离线合同）**，`runtime_verified=false`。
> 凡未给出 `file:line` 或离线证据者，一律降级标注。
>
> 前置：`CLAUDE.md`（§三 提权 helper / §六 不对称边界）、
> `docs/research/reverse-eng-20261010/EDITOR-REGISTRY-MINE.md`（下称 **REG**）、
> `docs/research/reverse-eng-20261010/VISIBLE-NO-ASSET.md`（下称 **VNA**）、
> `docs/research/game-b-systems-20261009/F5-visible-feedback.md`（下称 **F5**）、
> `docs/research/reverse-eng-20261010/UI-CONTROL-WRITE-MINE.md`（下称 **UWM**）。
>
> **来源纪律（硬拷贝）**：本轮只认**一份**权威源 —— `tools/editor-bridge/Adapter/FrontendCommands.cs`
> 与 `tools/editor-bridge/Adapter/PanelOpen.cs`（UWM/F5 引用的也是这一份）。
> 全仓内有约 40 份同名拷贝在 `.runtime/editor-build/r*/before/Adapter/` 下（历史「编辑前」快照）。
> 本轮核对：live 两份与 **`r214/before`** 逐字节相同
> （`md5 20c537d577a689dc1ed16b26a9101e85` / `0cb5af3296ec780903d5f5a9574296eb`）。
> **`.runtime` 下的全部快照一律未动**（它们不是权威源，只是历史留档）。行号均按本次 checkout 实测。

---

## 0. 一句话结论

1. **编辑器侧：没有任何 op 能把一个值写进 UI 元素。** 全部 7 个「面板/UI 相关」op
   （`BridgeServer.cs:521-527` 派发，`:599-605` 落点）只做三件事：**开面板** / **调编辑器自己的原生
   导航·加载·聚焦方法**（改变的是「编辑器里选中了什么、把哪份已存在资源加载进列表」） / **只读回显**。
   **没有任何一处 setter 写控件的文本、属性或可见性**（见 §1，逐 op）。
2. **注册表侧：不存在「UI 资产 Kind」。** REG §6.1 的精确负面：25 个资源 Kind（1、5–27）里没有一个是
   「界面/控件/布局/HUD」；编辑器资源树里确有「界面控件组」类目（`menu-tree.json`），但**没有反射符号
   能走到它**。⇒ **ui.hud 连一个可寻址的写对象都还没有**（§2）。
3. **运行期节点侧：`308 激活/关闭模型显示` 是唯一「零资产 + 落在已通真机管线上 + 反馈二元不可误读」的
   玩家可见通道**（VNA §5 冠军）。但它**不是文字/UI 通道**，且**未真机验证**（§3）。
4. **总判决：今天没有任何「玩家可见的文字/UI 通道」可达。** 能到的只有**几何层**（308/266/835），
   而那要走**节点图**，不是 `ui.hud`；且其运行时语义仍为 CANDIDATE。
   要打开文字/UI 这条路，**只需要一个原语：编辑器侧「界面控件组」资源的建/改符号**
   （见 §4）——它一旦存在，UI 家族的所有节点（383/384/833/631…）立刻从「缺资产」升级为「可建资产」。

---

## 1. 编辑器侧逐条清点：`FrontendCommands.cs` 与 `PanelOpen.cs`

### 1.1 先分清「op」和「方法」

桥的 op 名（小写连字符）→ 处理器方法，映射在 `tools/editor-bridge/ManagedBridge/BridgeServer.cs`：

| op 名 | 前端 case | 处理器落点 | 实现文件 |
|---|---|---|---|
| `open-editor-panel` | `BridgeServer.cs:521` | `:599` `OpenEditorPanel()` | `PanelOpen.cs:38` |
| `open-resource-manager` | `:525` | `:603` `OpenEditorPanel(resourceManager:true)` | `PanelOpen.cs:38` |
| `open-scene-resource-folder` | `:526` | `:604` `OpenSceneResourceFolder()` | `FrontendCommands.cs:137` |
| `load-scene-resource-model` | `:524` | `:602` `LoadSceneResourceModel()` | `FrontendCommands.cs:153` |
| `load-lab-cube-resource-model` | `:523` | `:601` `LoadSceneResourceModel(labCube:true)` | `FrontendCommands.cs:153` |
| `focus-lab-cube-from-frontend` | `:522` | `:600` `FocusLabCubeFromFrontend()` | `FrontendCommands.cs:199` |
| `inspect-frontend-commands` | `:527` | `:605` `InspectFrontendCommands()` | `FrontendCommands.cs:231` |

> 口径更正：F5 §4 与 UWM §2.3 写「桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）」。**本次现值（见 tools/gameplan/tests/test_doctrine.py）
> （`grep -oE 'case "[a-z0-9-]+"' …/BridgeServer.cs | sort -u | wc -l`），
> 与 `CLAUDE.md` §五的 137（136 + `inspect-entity-components`）一致。F5/UWM 的「136」**旧了一位**。
> 且下表比 UWM 多一条 `load-lab-cube-resource-model`（`BridgeServer.cs:523`）——UWM 漏了它。**UI 命中数仍为 0**
> （`grep -niE "界面控件|控件组|HUD|Widget|UiControl|提示" …/BridgeServer.cs` → **0**）。

### 1.2 逐 op：能改什么 / 不能改什么

#### (A) `PanelOpen.cs` —— 只能「开面板」，不能「改控件」

| 事实 | 证据（file:line） |
|---|---|
| 目标面板是**写死的 2 元素白名单** `{ "节点管理器", "资源管理器" }` | `PanelOpen.cs:36` |
| 读菜单项的 **label 字段** `MMGKX5coQC4` | `PanelOpen.cs:31` |
| 读菜单项的 **Action 字段** `Te1KXhuGxBC` | `PanelOpen.cs:32` |
| 做法：遍历编辑器对象图，**精确等值匹配** label 后 `action?.DynamicInvoke()` | `PanelOpen.cs:51`（walk）、`:86`（匹配）、`:90`（invoke） |
| 唯一「可见副作用」= 把编辑器的面板**显示出来**；文件头自述「Opening a panel changes what is on screen. Nothing else.」 | `PanelOpen.cs:25-27` |
| 开完只能**读回窗口标题/屏幕文本**，**不证明面板内容** | `PanelOpen.cs:108-109`（`CurrentCaptions()`）；实现 `ArchiveModel.cs:303`（注释 `:301-302`「Every caption currently on screen … to read back what a panel shows」） |

**判定**：`OpenEditorPanel` **不是写入口**。它 invoke 的是**编辑器自己的菜单回调**，效果上限是「把
节点管理器/资源管理器画到屏幕上」。**没有一行 setter**——`grep -nE "SetValue|\.set_|SetValue\(" PanelOpen.cs`
= **0 命中**（本次实测）。

#### (B) `FrontendCommands.cs` —— 走资源树 + 原生导航/加载/聚焦 + 只读回显

| 方法 | 做了什么 | **改不了什么** | 证据（file:line） |
|---|---|---|---|
| `OpenSceneResourceFolder()` | 解析**场景资源文件夹**（注册表 tag 路径 `[40000,40003,41101,40004]`），对选中节点调一次原生**导航**方法 `SyTKwRXfIBP` | 不改任何字段；返回体自带 `notice = "Invocation only; requires independent frontend readback."` | 路径常量 `:23`；方法 `:137`；取原生方法 `:144`；invoke `:145`；`pendingSelection` 回读 `:149`；notice `:150` |
| `LoadSceneResourceModel()` | 对 `containerType==3` 的场景文件夹（或历史 lab-cube `313584`）调原生**加载**方法 `vF1Yj4iJnve`，把资源模型装进管理器 | 只处理**已存在**的场景文件夹/lab-cube；不改资源字段；`notice = "Requires independent resource-path readback."` | 方法 `:153`；lab-cube id `313584` `:156`；取原生方法 `:192-193`；invoke `:194`；notice `:196` |
| `FocusLabCubeFromFrontend()` | 对**固定 lab-cube 资源**（entityId `1077936130`）调原生**聚焦**方法 `sM5KBF555gu` | 聚焦是「看/选中」，不是「改」；`notice` 明说「no transform or save requested」 | 方法 `:199`；取原生方法 `:222`；invoke `:223`；notice `:226` |
| `InspectFrontendCommands()` | **纯只读**：反射读前端命令元数据（delegate / ICommand / 菜单 label），**显式不 invoke、不写**；还**读**了一个 WPF 控件 `Selector` 的 `SelectedIndex` | 方法头自述 `Observation only: no delegate invocation, command execution, CanExecute, application property getters, RPC, or model field writes.`；返回 `scope` 明写「no command/delegate invoked and no game request sent」 | 方法 `:231`；自述注释 `:229-230`；读 `Selector.SelectedIndex` `:375-380`（`selectedIndex` 值在 `:377`）；返回 `scope` `:431-433` |
| `ResolveSceneFolderCore()` / `ResolveSceneResourceFolder()` | 纯只读地**解析**场景文件夹节点（读 `pIxYiE5REC8` / `JkmYibSuDZr` 等字段，按 tag 路径下钻） | 只读字段，无写 | `:31`、`:105` |

**判定**：`FrontendCommands.cs` 是「**资源树导航 + 原生加载/聚焦 + 只读回显**」，**不是写入口**。
唯一沾到 UI 元素的代码是 **`Selector.SelectedIndex` 的读取**（`:377`）——**它是读，不是写**。
`grep -nE "SetValue|\.set_|SetValue\(" FrontendCommands.cs` = **0 命中**（本次实测）。

### 1.3 回答第 1 问：「有没有任何 op 把值写进 UI 元素（不只是开面板）？」

**没有。** 7 个 op 可归为三类，逐个都不是「向 UI 元素写值」：

1. **开面板**（presentation）：`open-editor-panel` / `open-resource-manager` → invoke 编辑器自己的菜单 Action
   （`PanelOpen.cs:90`）。效果 = 面板出现；**不写任何控件字段**。
2. **调编辑器自己的原生导航/加载/聚焦方法**：`open-scene-resource-folder`（`:145`）、
   `load-scene-resource-model` / `load-lab-cube-resource-model`（`:194`）、
   `focus-lab-cube-from-frontend`（`:223`）。它们**改变的是「编辑器里选中了谁 / 哪份已存在资源被装进列表」**——
   **仍然是「在已有对象之间挪动选择」，不是「给一个控件赋一个新值」**；且各自都带「需独立回读」的 notice。
3. **只读**：`inspect-frontend-commands`（`:231`，显式零 invoke）＋ 两处回读（`CurrentCaptions()` `PanelOpen.cs:109`；
   `Selector.SelectedIndex` `FrontendCommands.cs:377`）。

> 「最接近写」的一条是 `LoadSceneResourceModel`：它把一份已存在的资源模型**加载进**资源管理器，
> 从而改变**编辑器资源面板显示的内容**（`:192-194`）。但这仍**不是**「写一个 UI 元素的值」——
> 它只认 `containerType==3` 的场景文件夹或固定的 lab-cube，**选择的是已存在的资源**，且**不碰任何
> 控件的文本/属性/可见性**。把它当写入口是**过度概括**，本文不这么写。

**副产物（对第 4 问有用）**：这也把「ui.hud 的**读**半边」钉死了——能读到的 UI 面只有
**窗口标题文本**（`ArchiveModel.cs:303`）与**控件选中索引**（`FrontendCommands.cs:377`），
**读不到任何「界面控件组/控件」的字段**。

---

## 2. 第 2 问：编辑器注册表里有没有「UI 资产 Kind」？

**结论 = 没有。** 依 REG（`docs/research/reverse-eng-20261010/EDITOR-REGISTRY-MINE.md`）：

- **Kind 来源**：每个资源模型 override `RG6YRkRQud0()`，返回枚举 `QD5e7QiwC7ij9WZWqtx3` 的一个常量；
  枚举被混淆器抹到只剩 `None`，**编号只能逐模型读**（REG §1）。
- **全量台账 = 25 个 Kind（编号 1、5–27）**（REG §3）。其中：
  - **节点定义 = 6**（真机已证读）、**节点图 = 9**（建+删）、**预制/元件 = 7**、**关卡实体实例 = 8**、
    **标签 = 23**——**没有一个与 UI 沾边**；
  - 其余 12/13/17–22/24–27 全是「继承 11、字段名全混淆」的未知项，**无 UI 标签、无控件模板**
    （REG §5 UNKNOWN）。
- **精确负面**（REG §6.1）：25 个编号里，`resourceItemTextType` 命中「界面标签」的只有
  1（NEW_FOLDER）/10（FILTER_FOLDER）/11（COSTLOAD_*）/14（BP_VARIABLES）/15（EXTERNAL_ASSETS_*）/
  16（CUSTOM_ROLESTATUS）——**全是「文件夹/变量/外部资产/角色状态」，没有一个是「界面控件/布局/HUD」**。
  Bash 在 `…resolved/`（12375 个 `.cs`）里搜 `界面`、`控件组`、`HUD`、`UI_BEYOND_ASSIST_EDITOR_HUD`
  均无「控件资源模型」命中。
- **编外旁证**：编辑器资源树里**确有「界面控件组」类目**
  （`docs/research/beyondeditor-frontend/db/raw/menu-tree.json:1276` 等 6 处），
  但那是**文件系统/菜单层**，**不是注册表 Kind**；且**没有任何反射符号指向这个类目**
  （UWM §8.1：`EditorBindingProfile.Generated.cs` 307 个 legacy 符号里未见 UI 类 owner）。
- **「组件」也不是资源 Kind**：真正的组件模型 `LudM06iCRNk4iFkwqKIW` **不 override Kind**，
  是挂在实体/预制/关卡上的**字段**（REG §6.2）——与 `CLAUDE.md` §六(a)「组件读得懂、删得掉、加不了」一致。

**⇒ REG 的判决**：`ui.hud` 的**读半边**在当前逆向水平下**没有一个注册表 Kind 能对上**；
**写半边**更无从谈起（连可寻址对象都不存在）。此为**本检索范围内的精确负面**
（范围＝`…resolved/` 12375 个 `.cs` + §2.2 列出的工程 `.cs`），**「搜不到」≠「不存在」**。

---

## 3. 第 3 问：运行期节点侧，`VISIBLE-NO-ASSET.md` 的冠军是哪条？凭什么是它？

**冠军 = `308 激活/关闭模型显示`（definitionId 308）。** 依 VNA §5（`:194-209`）的排位表，
第 1 名即 308，理由四条：零资产 / 只须一个已能建的动态实体 / 反馈二元不可误读 / 触发现成。

**「它不需要任何编辑器手工资产」的证据**（VNA §3.1 `:112-119`）：

- **入参只有两个**：`目标实体`（实体引用）+ `是否激活`（布尔）。**没有一个是资产/配置ID/索引/格式约定**。
  - `目标实体` pin：`data/node-contracts/variants/server/bucket-06.json:3268`；
  - `是否激活` pin：同文件 `:3304`，其 `valueTypeNameRaw:"6"`（VNA 判为布尔/枚举，见 `:3287`）。
- **离线目录**：`docs/editor-catalog/NODE-CATALOG.md:831` 记它 `入×1，出×1`、参数 `是否激活、目标实体`、类别码 4。
- **实体引用靠连线供给、不用字面量**：已通真机的 demo 图里所有实体/玩家引用都是**边**
  （`.runtime/scratch/MW_API_FARM_DEMO-plan.json` 的 `edges` 段；同文件 `values` 段只有 `int`/`string` 槽）。
  所以 308 的 `目标实体` 可由上游事件节点（如 `71 实体创建时`）的实体输出口连线供给。
- **触发现成**：`71 实体创建时`（`data/node-contracts/variants/server/bucket-07.json:1169`）驱动一次即可，无需任何 UI。
- **语义是弱证据**：官方知识库**没有任何一章**点名 308 本身（VNA §3.1）。其语义是**由节点名 + pin 名逆推**，
  唯一的官方旁证是同族的「模型可见性仅影响模型显示，不影响实体上的其他逻辑」
  （`docs/official-docs/chapters/mhnffmieeqbg.json:161`）。⇒ 属②层弱证据。

**为什么不是别的**：21 个题给词命中里，「零资产 + 自身直接产生可见效果」的**只有 308**；
`266 激活屏幕震动`（bulk-05.json:2230）与 `835 修改模型颜色和材质`（bulk-03.json:14173）同为零资产，
但 308 的反馈**二元且不可误读**（模型有/无），比「震动」更硬、比「改色」少一个颜色码格式缺口（VNA §3.1）。

**唯一的「文字反例」**：`631 切换生效的文本气泡`（`bulk-02.json:7283`）需要
**`文本气泡配置ID` + 实体上先挂文本气泡组件**；组件加不了 ⇒ **零资产文字通道不存在**（VNA §3.2、§6.4）。

---

## 4. 第 4 问：综合判决

### 4.1 今天有没有任何玩家可见通道可达？

**分两层，结论不同：**

- **文字 / UI 层（`ui.hud`）：不可达。** 三条独立证据同时为负：
  1. **编辑器侧无写 op**（§1：7 个 op 无一写 UI 元素值）；
  2. **注册表无可寻址的 UI 资产 Kind**（§2：25 个 Kind 里没有 UI 类）；
  3. **运行期文字节点全要预置资产**（§3：631/833/383/384/613… 全部吃「界面控件组索引 / 文本气泡配置ID」，
     而这些资产**编辑器手工建、桥建不了**）。
  ⇒ **今天要让玩家看见一句自定义文字，本仓没有原语。** 这与 F5 §5、UWM §0.5、VNA §6.4 一致。

- **几何层（presentation 家族）：有 CANDIDATE，但不算「已可达」。**
  `308`（隐藏/显示模型）、`266`（屏幕震动）、`835`（改色/材质）**零资产**，
  且走**已通真机的「建实体→绑图→原生 save」管线**。但它们：
  ① 是**节点图**路径，不是 `ui.hud`；
  ② **运行时语义未真机验证**（`docs/gameplan/README.md:98-99` 的 `runtimeVerified:false` 一直保留）；
  ③ 还欠一次「这条 server 节点能被桥加进图」的 `build-plan` + 独立 `inspect`
     （UWM §5.2 E1）。
  ⇒ 严格写：**308 是「离线可行的候选」，不是「已证真机可见的通道」**。三层口径里它停在②层，③层为 0。

### 4.2 要打开文字/UI 这条路，需要的一个原语是什么？

**唯一缺的原语 = 编辑器侧「界面控件组」资源（UI 资产）的建/改符号。**

- **为什么是它**：UI 家族的一切（界面控件组、控件模板、文本框、消息队列、悬浮交互页）在编辑器资源树里
  是**一个真实存在的类目**（`menu-tree.json:1276` 等），但**没有任何反射符号/命令能走到它**（§2、UWM §5.1）。
  一旦有了「建 UI 控件组资源 + 存为模板（生成索引）」的符号，运行期节点（383/384/521/833/631…）
  就立刻从「缺资产」升级为「可建资产」——**它们是通用的 server 节点，加节点规则不写死白名单**
  （`AuthoringGraph.cs:322` 按 `Kind==6 && Id==definitionId && Category.SequenceEqual` 解析；
  `AuthorGraphKinds={20000,20001,20002,20007}` `:17`；UI 四节点 category 正是 `[10001,20000,22000,0]`，
  落在受理集内）。**卡点不在运行期侧，全在编辑器资源侧。**
- **同族、次选的原语 = 组件写入口（AddComponent / 写组件字段）**：它解锁的是**实体挂载型**的
  文字/小地图通道（`631 文本气泡组件` `mhwtz297kp6a`、`640 小地图标识组件` `mh0pppib5eyc`），
  而不是界面布局型。命令面目前只有 `DeleteComponentForEditObj`/`DeleteComponentForPrefab`，
  **无 AddComponent**（`CLAUDE.md` §六(a)；UWM §4.1）。
  ⇒ 若只能挖一个，**先挖「界面控件组资源建/改符号」**（它是**资源**，与已打通的客户端脚本资源
  `ClientScriptCrudProbe.cs:114/125/136` 同类，挖法最像）；AddComponent 作为第二条。
- **两条原语的共同点**（`CLAUDE.md` §六的纪律）：**读/导航/开面板都有，写/建没有**——
  **不对称边界**。`ui.hud` 正卡在这条边界上，且比组件/地形/变换那三条**更靠里**：
  连「可寻址对象」都还只存在于菜单树的名字符串里。

### 4.3 不许越界的三条（诚实边界）

1. **三层分开**：本文全部是 ① 文档写了什么（官方章）＋ ② 工具/源码能做什么（源码、离线合同、注册表台账）。
   **③ 真机「玩家真的看到了」= 0 条**。308/266/835 无一条经过真机目视。
2. **「进了模型 ≠ 看得见 ≠ 能玩」**：§3 只论证了 308 的**参数面不需要资产**，**没有**论证它真能被求值、
   求值后真产生可见帧。它的语义是**逆推**的（无官方章）。
3. **负结论要带范围**：§2 的「无 UI Kind」是**本次检索范围内的精确负面**
   （`…resolved/` 12375 个 `.cs` + 工程 `.cs`），按 doctrine「搜不到 ≠ 不存在」。

---

## 5. 复跑命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 6. 本轮未找到的（写明搜过哪里、用什么命令）

1. **任何「向 UI 元素写值」的桥 op**：未找到。搜过 `tools/editor-bridge/Adapter/FrontendCommands.cs`、
   `PanelOpen.cs`（全文无 setter），以及 `BridgeServer.cs` 的全部 op 名（UI 词 0 命中；op 数见 tools/gameplan/tests/test_doctrine.py）。
2. **任何「UI 资产 Kind」**：未找到（REG §6.1；`…resolved/` 12375 个 `.cs` 搜 `界面`/`控件组`/`HUD` 无控件资源模型）。
3. **「界面控件组」类目的反射符号 / 注册表 tag 路径 / 建资源命令**：未找到（UWM §8.1 同）。
4. **`AddComponent` / 组件字段写**：未找到（命令面只有 `DeleteComponentFor*`；`CLAUDE.md` §六(a)）。
5. **「文本直投玩家」的零资产节点**：不存在（VNA §6.4；UWM §8.4：全 810 定义名按
   `字幕/旁白/对话/飘字/弹窗/公告/广播/通知` 搜，仅得权限开关与图间信号）。

> 说明：`.runtime/editor-build/*/before/` 下约 40 份 `FrontendCommands.cs` / `PanelOpen.cs` 历史快照
> **本轮未逐一 diff**（只核对了最新的 `r214/before` 与 live 一致）。若下游要改这两份源文件，
> 按 `CLAUDE.md` §四「改一处硬拷贝，必须 grep 出全部同份」——那些快照是**历史留档，不应被当权威源编辑**。

---

*本文件由 2026-10-10 会话离线整理；全程未连接桥、未发送任何请求、未触碰游戏/编辑器/存档/helper，
未请求 UAC。所有引用行号为本次 checkout 实测。凡只到「离线可行」的条目一律标 CANDIDATE，未写「已验证」。*
