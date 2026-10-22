> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# INSTALLED-TEXTMAP-KEYS

Read-only extraction of the **live installed** BeyondAssistEditor TextMap (CHS) into a full
key -> label table, plus the key-name subsets relevant to the item / bag / currency / shop /
template / component UI panels. These KEY NAMES are the search literals for the 7.1 corpus.

## 0. TL;DR for the parent

- Installed CHS TextMap decodes to **8267 entries**, every one carrying a string KEY.
- The installed table is a strict SUPERSET of the 7.0 corpus table
  (`.runtime/editor-catalog/textmap-chs.json`, 7743 keys): 524 keys exist only in the installed
  (7.1) file, 0 keys exist only in the 7.0 file -> the installed table IS the 7.1 table.
- **No key carries the literal titles `背包与货币` or `商店模板管理`.** Those two exact strings
  occur NOWHERE in the whole install (`D:/games/.../BeyondAssets`, rg over all files = 0 hits)
  and nowhere in the 7.1 decomp corpus. The closest real keys are the node-category folders
  `..._subFolders_38_name` = `道具与背包` (EN: Items and Inventory) and
  `..._subFolders_36_name` = `商店` (EN: Shop), plus the node-config keys 681-733.
- No key name contains CURRENCY / BAG / SHOP. Exactly one carries STUFF:
  `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_STUFF_BP` = `道具节点图`.

## 1. Decode provenance (not guessed)

- Source (READ-ONLY): `C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\Resource\Json\TextMap\CHS\17720714722766726369.mihoyobin`
- source sha256: `b50ba993dbc156314f5594a13e1abbd499b6a5ea3b92af8d4bf9746a138449dd`
- transform: single-byte XOR 0xE5 (229) then protobuf wire
  - matches the editor's own loader: `.runtime/verification/resource-file-loader/file-loader.cs:250`
    (`for (int i = 0; i < array.Length; i++) array[i] ^= 229;`), payload merges as a protobuf message
  - same proven chain documented in `tools/editor-catalog/decode-mihoyobin.py` and
    `scripts/research/mihoyobin_schema.py` (XOR_KEY = 0xE5)
- decoded sha256: `9ae3dc81b999e92f1499308b52cae5ddfe251605ef62d2019eb6159b2b872d54`
- wire schema (inferred from the bytes, stable across all 8267 entries):
  `field 1 = version (varint, = 2)`; `field 2 = repeated Entry` where
  `Entry.field 1 = key (string)`, `Entry.field 2 = hash (uint32)`, `Entry.field 3 = text (string, optional)`
- NOTE on wire ambiguity: some key bytes (e.g. `BeyondEditorInstructionNodeConfig_name_1`) also
  parse as a legal nested message. This is the standard protobuf string-vs-submessage tie; the
  string interpretation is the correct one for field 1/3 and was preferred for every entry.
- full table emitted to `.runtime/scratch/installed-ui-keys.json` (8267 entries;
  6655 carry a non-null label, 1612 are key-only).

## 2. Which 7.1 artifact carries the key literals

The 7.1 `.cs` files do NOT inline string literals; strings live in the assembly string heap and are
referenced via folded XOR constants (e.g. `0x46DF9D65 ^ 0x46DEEAFF`). The extracted 7.1 string
heap is `.runtime/verification/update-repair-20260925/strings/string-table-7.1.json` (2985 strings).
Verified present there as literals:
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_WINDOW_TITLE`
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_STUFF_BP`
- `UI_BEYOND_ASSIST_EDITOR_NODE_MANAGER_NEW_COMPOSITE_NODE`
(The `BeyondEditorInstructionNodeConfig_*` and `BeyondAssistantEditorConfigGlobal_*` keys are NOT
bare string literals in the assembly; the node/config system reaches them by hash, not by name.
Grep the UI_* keys above in `string-table-7.1.json` / the 7.1 corpus; do not expect the node-config
key text to appear verbatim in the 7.1 `.cs`.)

## 3. Grouped extracts

### 3a. Values containing 货币 (29)
- `BeyondEditorInstructionNodeConfig_name_684` = 背包货币数量变化时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_684` = 货币持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_684` = 货币持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_684` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_684` = 货币变化值
- `BeyondEditorInstructionNodeConfig_name_687` = 设置背包掉落道具/货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_687` = 道具/货币配置ID
- `BeyondEditorInstructionNodeConfig_name_688` = 增加背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_688` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_name_691` = 获取背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_691` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_4_name_704` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_706` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_707` = 收购货币字典
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_708` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_709` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_710` = 收购货币字典
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_717` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_718` = 出售货币字典
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_719` = 收购货币字典
- `BeyondEditorInstructionNodeConfig_name_722` = 获取背包所有货币
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_722` = 货币字典
- `BeyondEditorInstructionNodeConfig_name_727` = 增加掉落物组件货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_727` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_name_729` = 获取掉落物组件货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_729` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_729` = 货币数量
- `BeyondEditorInstructionNodeConfig_name_731` = 获取掉落物组件所有货币
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_731` = 货币字典

### 3b. Values containing 背包 (40)
- `BeyondEditorInstructionNodeConfig_name_681` = 背包道具新增时
- `BeyondEditorInstructionNodeConfig_name_682` = 背包道具失去时
- `BeyondEditorInstructionNodeConfig_name_683` = 背包道具数量变化时
- `BeyondEditorInstructionNodeConfig_name_684` = 背包货币数量变化时
- `BeyondEditorInstructionNodeConfig_name_685` = 增加背包最大容量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_685` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_686` = 增加背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_686` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_687` = 设置背包掉落道具/货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_687` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_688` = 增加背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_688` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_689` = 获取背包容量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_689` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_689` = 背包容量
- `BeyondEditorInstructionNodeConfig_name_690` = 获取背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_690` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_691` = 获取背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_691` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_701` = 商店出售背包物品时
- `BeyondEditorInstructionNodeConfig_name_706` = 设置背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_709` = 向背包商店出售表中新增商品
- `BeyondEditorInstructionNodeConfig_name_712` = 从背包商店出售表中移除商品
- `BeyondEditorInstructionNodeConfig_name_715` = 查询背包商店物品出售列表
- `BeyondEditorInstructionNodeConfig_name_718` = 查询背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_720` = 设置背包道具掉落内容
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_720` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_721` = 获取背包所有基础道具
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_721` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_722` = 获取背包所有货币
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_722` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_723` = 获取背包所有装备
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_723` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_name_733` = 背包内道具被使用时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_820` = 买入的背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_820` = 买入的背包持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_821` = 卖出的背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_821` = 卖出的背包持有者GUID
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_38_name` = 道具与背包
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_32_name` = 道具与背包

### 3c. Values containing 商店 (65)
- `BeyondEditorInstructionNodeConfig_name_700` = 商店出售自定义商品时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_700` = 商店持有者
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_700` = 商店持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_700` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_701` = 商店出售背包物品时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_701` = 商店持有者
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_701` = 商店持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_701` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_702` = 打开商店
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_702` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_702` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_703` = 关闭商店
- `BeyondEditorInstructionNodeConfig_name_704` = 设置自定义商店商品出售信息
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_704` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_704` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_705` = 商店收购道具时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_705` = 商店持有者
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_705` = 商店持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_705` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_706` = 设置背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_706` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_706` = 商店序号
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_707` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_707` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_708` = 向自定义商店出售表中新增商品
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_708` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_708` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_709` = 向背包商店出售表中新增商品
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_709` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_709` = 商店序号
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_710` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_710` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_711` = 从自定义商店出售表中移除商品
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_711` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_711` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_712` = 从背包商店出售表中移除商品
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_712` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_712` = 商店序号
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_713` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_713` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_714` = 查询自定义商店商品出售列表
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_714` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_714` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_715` = 查询背包商店物品出售列表
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_715` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_715` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_716` = 查询商店收购物品列表
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_716` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_716` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_717` = 查询自定义商店商品出售信息
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_717` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_717` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_718` = 查询背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_718` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_718` = 商店序号
- `BeyondEditorInstructionNodeConfig_name_719` = 查询商店物品收购信息
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_719` = 商店归属者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_719` = 商店序号
- `BeyondAssistantEditorConfigGlobal_configEnum_maps_35_map_4_textMapId_36` = 商店交易
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_36_name` = 商店
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_1_subFolders_22_name` = 商店
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_3_subFolders_22_name` = 商店
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_30_name` = 商店
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_1_subFolders_18_name` = 商店
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_3_subFolders_19_name` = 商店

### 3d. Values containing 道具 (59)
- `BeyondEditorInstructionNodeConfig_name_681` = 背包道具新增时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_681` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_681` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_681` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_682` = 背包道具失去时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_682` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_682` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_682` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_683` = 背包道具数量变化时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_683` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_683` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_683` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_686` = 增加背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_686` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_687` = 设置背包掉落道具/货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_687` = 道具/货币配置ID
- `BeyondEditorInstructionNodeConfig_name_690` = 获取背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_690` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_690` = 道具数量
- `BeyondEditorInstructionNodeConfig_outParamList_4_name_701` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_704` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_705` = 商店收购道具时
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_706` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_707` = 设置物品收购表中道具收购信息
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_707` = 商品道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_708` = 商品道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_709` = 商品道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_710` = 商品道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_712` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_713` = 商品道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_715` = 道具配置ID列表
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_716` = 道具配置ID列表
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_717` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_718` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_719` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_720` = 设置背包道具掉落内容
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_720` = 道具掉落字典
- `BeyondEditorInstructionNodeConfig_name_721` = 获取背包所有基础道具
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_721` = 基础道具字典
- `BeyondEditorInstructionNodeConfig_name_726` = 增加掉落物组件道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_726` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_name_728` = 获取掉落物组件道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_728` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_728` = 道具数量
- `BeyondEditorInstructionNodeConfig_name_730` = 获取掉落物组件所有道具
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_730` = 道具字典
- `BeyondEditorInstructionNodeConfig_name_733` = 背包内道具被使用时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_733` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_733` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_733` = 道具配置ID
- `BeyondAssistantEditorConfigGlobal_configEnum_maps_35_mapTitle` = 道具变化原因
- `BeyondAssistantEditorConfigGlobal_configEnum_maps_36_mapTitle` = 道具掉落类型
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_38_name` = 道具与背包
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_1_subFolders_24_name` = 道具
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_3_subFolders_24_name` = 道具
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_32_name` = 道具与背包
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_1_subFolders_20_name` = 道具
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_3_subFolders_21_name` = 道具
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_STUFF_BP` = 道具节点图

### 3e. Values containing 模板 (24)
- `BeyondEditorInstructionNodeConfig_name_261` = 切换主镜头模板
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_261` = 镜头模板名称
- `BeyondEditorInstructionNodeConfig_name_618` = 切换造物巡逻模板
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_618` = 巡逻模板序号
- `BeyondEditorInstructionNodeConfig_name_619` = 获取当前造物的巡逻模板
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_619` = 巡逻模板序号
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_620` = 当前巡逻模板序号
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_818` = 镜头模板名称
- `BeyondEditorInstructionNodeConfig_name_200036` = 获取当前镜头模板
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_200036` = 镜头模板
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_200141` = 巡逻模板序号
- `UI_BEYOND_EDITOR_UI_MONSTER_V2_BLUEPRINT_DEBUG_LOG_CHANGE_STATE` = ;状态节点图ID切换为{0};AI参数模板序号为{1}
- `UI_BEYOND_ASSIST_EDITOR_PCG_WPF_TYPE_NAME` = 场景生成模板
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_SERVER` = 服务器控件模板
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_CLIENT` = 客户端控件模板
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_MODELREFERENCE` = 模板引用控件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_MODELREFERENCE_REFERENCESETTING` = 模板引用
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_MODELREFERENCE_REFERENCESETTING_REFERENCE` = 引用控件模板
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_MODELREFERENCE_REFERENCESETTING_EDIT` = 前往模板编辑
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_TO_PREFAB_TIP` = 向客户端控件容器中添加客户端控件模板时，被添加的控件将断开与模板的连接，是否继续？
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_MODELREFERENCE_NONE_TIP` = 点击选择控件模板
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_ADD_TEMPLATE_LIST` = 客户端控件模板列表
- `UI_BEYOND_EDITOR_UIEDITOR_UI_PREFAB_CLIENT_SAVE_AS` = 另存为模板
- `UI_BEYOND_EDITOR_UIEDITOR_UI_PREFAB_SAVE_AS_SUCCESS_TIP` = 成功保存至客户端控件模板库

### 3f. Values containing 组件 (29)
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_365` = 组件类型
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_366` = 组件类型
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_367` = 组件类型
- `BeyondEditorInstructionNodeConfig_outParamList_8_name_373` = 自定义变量组件快照
- `BeyondEditorInstructionNodeConfig_name_726` = 增加掉落物组件道具数量
- `BeyondEditorInstructionNodeConfig_name_727` = 增加掉落物组件货币数量
- `BeyondEditorInstructionNodeConfig_name_728` = 获取掉落物组件道具数量
- `BeyondEditorInstructionNodeConfig_name_729` = 获取掉落物组件货币数量
- `BeyondEditorInstructionNodeConfig_name_730` = 获取掉落物组件所有道具
- `BeyondEditorInstructionNodeConfig_name_731` = 获取掉落物组件所有货币
- `BeyondEditorInstructionNodeConfig_name_732` = 获取掉落物组件所有装备
- `BeyondEditorInstructionNodeConfig_name_736` = 设置扫描组件的生效扫描标签序号
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_789` = 组件类型
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_790` = 组件（不可见）
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_854` = 组件（不可见）
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_3360` = 自定义变量组件快照
- `BeyondEditorInstructionNodeConfig_name_200118` = 获取扫描组件当前扫描到的实体
- `BeyondEditorInstructionNodeConfig_name_200119` = 获取扫描组件可扫描的所有合法对象
- `BeyondAssistantEditorConfigGlobal_configEnum_maps_98_mapTitle` = 组件功能
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_33_name` = 光源组件
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_39_name` = 小地图标识组件
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_49_name` = 光标碰撞盒组件
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_3_subFolders_26_name` = 小地图标识组件
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_27_name` = 光源组件
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_33_name` = 小地图标识组件
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_3_subFolders_23_name` = 小地图标识组件
- `UI_BEYOND_ASSIST_EDITOR_VAR_TYPE_COMPTYPE` = 组件类型
- `UI_BEYOND_COSTLOAD_SERVERMEMORY_PERFORMANCE_LIMIT_SANDBOX_MEMORY` = 服务端内存超出上限，请减少逻辑功能（例如组件功能、节点图功能等）的使用，减少实体的创建使用。例如组件功能、节点图功能等
- `UI_BEYOND_EDITOR_ESP_LUTNAME_CAMPOVERLIMIT` = 组件数量达到上限

### 3g. Key names containing STUFF / TEMPLATE / COMPONENT (case-insensitive)
- **CURRENCY** (0): none
- **BAG** (0): none
- **SHOP** (0): none
- **STUFF** (1): `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_STUFF_BP`
- **TEMPLATE** (4): `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_SERVER`, `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_CLIENT`, `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_TEMPLATE_LIST`, `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_ADD_TEMPLATE_LIST`
- **COMPONENT** (1): `UI_BEYOND_EDITOR_UI_COMPONENT_CONFIG_CURSOR_COLLISION`

## 4. Candidate keys for the two panels

### 4a. items+bag+currency panel (parent's "背包与货币")
The umbrella display title literally does not exist. The functional umbrella keys are the node
category folders (the ONLY keys whose value names the bag/item grouping):
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_38_name` = 道具与背包 (EN "Items and Inventory")  <- node-category panel holding the bag/currency nodes
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_32_name` = 道具与背包 (EN "Items and Inventory")  <- node-category panel holding the bag/currency nodes
Node-config keys under it (these resolve to the bag/currency node labels):
- `BeyondEditorInstructionNodeConfig_name_681` = 背包道具新增时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_681` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_681` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_681` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_681` = 获得数量
- `BeyondEditorInstructionNodeConfig_name_682` = 背包道具失去时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_682` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_682` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_682` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_682` = 失去数量
- `BeyondEditorInstructionNodeConfig_name_683` = 背包道具数量变化时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_683` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_683` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_683` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_683` = 变化前数量
- `BeyondEditorInstructionNodeConfig_outParamList_4_name_683` = 变化后数量
- `BeyondEditorInstructionNodeConfig_outParamList_5_name_683` = 变化原因
- `BeyondEditorInstructionNodeConfig_name_684` = 背包货币数量变化时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_684` = 货币持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_684` = 货币持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_684` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_684` = 货币变化值
- `BeyondEditorInstructionNodeConfig_name_685` = 增加背包最大容量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_685` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_685` = 增加容量
- `BeyondEditorInstructionNodeConfig_name_686` = 增加背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_686` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_686` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_686` = 增加值
- `BeyondEditorInstructionNodeConfig_name_687` = 设置背包掉落道具/货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_687` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_687` = 道具/货币配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_687` = 掉落数量
- `BeyondEditorInstructionNodeConfig_inParamList_3_name_687` = 掉落类型
- `BeyondEditorInstructionNodeConfig_name_688` = 增加背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_688` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_688` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_688` = 增加值
- `BeyondEditorInstructionNodeConfig_name_689` = 获取背包容量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_689` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_689` = 背包容量
- `BeyondEditorInstructionNodeConfig_name_690` = 获取背包道具数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_690` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_690` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_690` = 道具数量
- `BeyondEditorInstructionNodeConfig_name_691` = 获取背包货币数量
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_691` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_691` = 货币配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_691` = 资源数量
- `BeyondEditorInstructionNodeConfig_name_720` = 设置背包道具掉落内容
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_720` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_inParamList_1_name_720` = 道具掉落字典
- `BeyondEditorInstructionNodeConfig_inParamList_2_name_720` = 掉落类型
- `BeyondEditorInstructionNodeConfig_name_721` = 获取背包所有基础道具
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_721` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_721` = 基础道具字典
- `BeyondEditorInstructionNodeConfig_name_722` = 获取背包所有货币
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_722` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_722` = 货币字典
- `BeyondEditorInstructionNodeConfig_name_723` = 获取背包所有装备
- `BeyondEditorInstructionNodeConfig_inParamList_0_name_723` = 背包持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_723` = 装备索引列表
- `BeyondEditorInstructionNodeConfig_name_733` = 背包内道具被使用时
- `BeyondEditorInstructionNodeConfig_outParamList_0_name_733` = 道具持有者实体
- `BeyondEditorInstructionNodeConfig_outParamList_1_name_733` = 道具持有者GUID
- `BeyondEditorInstructionNodeConfig_outParamList_2_name_733` = 道具配置ID
- `BeyondEditorInstructionNodeConfig_outParamList_3_name_733` = 使用数量

### 4b. shop panel (parent's "商店模板管理")
- `BeyondAssistantEditorConfigGlobal_folders_0_data_subFolders_0_subFolders_36_name` = 商店 (EN "Shop")  <- node-category panel holding the shop nodes
- `BeyondAssistantEditorConfigGlobal_folders_6_data_subFolders_0_subFolders_30_name` = 商店 (EN "Shop")  <- node-category panel holding the shop nodes
Shop node-config keys (700-719):
- `BeyondEditorInstructionNodeConfig_name_700` = 商店出售自定义商品时
- `BeyondEditorInstructionNodeConfig_name_701` = 商店出售背包物品时
- `BeyondEditorInstructionNodeConfig_name_702` = 打开商店
- `BeyondEditorInstructionNodeConfig_name_703` = 关闭商店
- `BeyondEditorInstructionNodeConfig_name_704` = 设置自定义商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_705` = 商店收购道具时
- `BeyondEditorInstructionNodeConfig_name_706` = 设置背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_707` = 设置物品收购表中道具收购信息
- `BeyondEditorInstructionNodeConfig_name_708` = 向自定义商店出售表中新增商品
- `BeyondEditorInstructionNodeConfig_name_709` = 向背包商店出售表中新增商品
- `BeyondEditorInstructionNodeConfig_name_710` = 向物品收购表中新增物品
- `BeyondEditorInstructionNodeConfig_name_711` = 从自定义商店出售表中移除商品
- `BeyondEditorInstructionNodeConfig_name_712` = 从背包商店出售表中移除商品
- `BeyondEditorInstructionNodeConfig_name_713` = 从物品收购表中移除物品
- `BeyondEditorInstructionNodeConfig_name_714` = 查询自定义商店商品出售列表
- `BeyondEditorInstructionNodeConfig_name_715` = 查询背包商店物品出售列表
- `BeyondEditorInstructionNodeConfig_name_716` = 查询商店收购物品列表
- `BeyondEditorInstructionNodeConfig_name_717` = 查询自定义商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_718` = 查询背包商店商品出售信息
- `BeyondEditorInstructionNodeConfig_name_719` = 查询商店物品收购信息

### 4c. Window titles / tabs / NEW-CREATE buttons (the literal forms to grep)
Window titles:
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_WINDOW_TITLE` = 千星沙箱
- `UI_BEYOND_ASSIST_EDITOR_RESOURCE_MANAGER_WINDOW_TITLE` = 资源管理器
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_MENU_TITLE` = 服务器节点图
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_MANAGER_MENU_TITLE` = 客户端节点图
- `UI_BEYOND_EDITOR_ESP_LIGHTING_TITLE` = 光源管理
Tabs:
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_UNCLASSIFIED_TAB` = 未分类页签
- `UI_BEYOND_ASSIST_EDITOR_RESOURCE_MANAGER_OFFICIAL_TAB` = 预制分类
- `UI_BEYOND_ASSIST_EDITOR_RESOURCE_MANAGER_CUSTOM_TAB` = 自定义分类
- `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_SAVE_AS_NEW_TAB` = 新节点图页签
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_TABS` = 默认页签
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_IMPORT_ASSET_TAB` = 导入资产页签
- `UI_BEYOND_EDITOR_ESP_PROFILE_TAB_TABNAME` = 环境配置
- `UI_BEYOND_EDITOR_ESP_PROFILE_TAB_DEFAULTTAB` = 默认
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_TAB_BASE` = 基础
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_TAB_SCRIPT` = 脚本
NEW / CREATE / ADD buttons (UI_*, short labels):
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_FOLDER` = 新建文件夹
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_BP` = 创建节点图
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_SERVER_BP` = 新建节点图
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_FILTER_BP` = 新建过滤器节点图
- `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_SKILL_BP` = 新建技能节点图
- `UI_BEYOND_ASSIST_EDITOR_NODE_MANAGER_NEW_COMPOSITE_NODE` = 创建复合节点
- `UI_BEYOND_ASSIST_EDITOR_ADD_PINS` = 添加引脚
- `UI_BEYOND_ASSIST_EDITOR_BP_VAR_CREATE` = 新增变量
- `UI_BEYOND_ASSIST_EDITOR_SIGNAL_ADD_NEW_SIGNAL` = 添加信号
- `UI_BEYOND_ASSIST_EDITOR_SIGNAL_ADD_NEW_VARIABLE` = 添加参数
- `UI_BEYOND_ASSIST_EDITOR_SIGNAL_CLICK_PLUS_BELOW_TO_CREATE_PARAMETER` = 点击加号创建参数
- `UI_BEYOND_ASSIST_EDITOR_SIGNAL_GO_TO_INTERFACE_TO_CREATE` = 前往创建信号
- `UI_BEYOND_EDITOR_WPF_HISTORY_NODE_NEW` = 新建节点: {0}
- `UI_BEYOND_EDITOR_WPF_HISTORY_CV_NEW` = 新建节点图变量
- `UI_BEYOND_EDITOR_WPF_HISTORY_MENTION_NEW` = 新建注释
- `UI_BEYOND_EDITOR_ATTACKTAG_STRINGLIST_LIMIT` = 可添加数量达到上限
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_MONSTER_SKILL_NEW` = 新建造物技能节点图
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_MONSTER_POSE_NEW` = 新建造物状态节点图
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_MONSTER_AI_NEW` = 新建造物状态决策节点图
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_AVATAR_SKILL_NEW` = 新建角色技能节点图
- `UI_BEYOND_ASSIST_EDITOR_CLIENT_BLUEPRINT_CONTROL_NEW` = 新建角色操控技能节点图
- `UI_BEYOND_EDITOR_ESP_LIGHTING_NEW` = 新建光源
- `UI_BEYOND_EDITOR_ESP_PROFILE_NEWPROFILE` = 新建环境
- `UI_BEYOND_EDITOR_ESP_PROFILE_NEW_TITLE` = 新建环境配置
- `UI_BEYOND_EDITOR_ESP_PROFILE_LIGHT_ADD` = 添加光源
- `UI_BEYOND_EDITOR_ESP_PROFILE_LIGHT_ADD_TITLE` = 添加光源
- `UI_BEYOND_EDITOR_ESP_PROFILE_LIGHT_ADD_ADD` = 点击下方按钮前往创建
- `UI_BEYOND_EDITOR_ESP_LIGHTING_CREATEOVERLIMITS` = 创建环境光源数量到达上限
- `UI_BEYOND_EDITOR_ESP_LIGHTCAMP_ADDLIGHT` = 添加光源
- `UI_BEYOND_LOG_TIPS_DISPLAYLOGOVERLIMITS` = 可添加数量达到上限
- `UI_BEYOND_EDITOR_VFXEDITOR_NEWVFXEDITOR` = 新建特效器
- `UI_BEYOND_EDITOR_VFXEDITOR_NEW_MTITE` = 添加特效器
- `UI_BEYOND_EDITOR_VFXEDITOR_SUBTITLE1` = 新建特效器名称
- `UI_BEYOND_EDITOR_VFXEDITOR_SUBTITLE2` = 新建特效器分类
- `UI_BEYOND_EDITOR_VFXEDITOR_CONFIRM` = 确认创建
- `UI_BEYOND_EDITOR_VFXEDITOR_EDITOR_RIGHTKEY_ADDEVENT` = 从蓝线处添加事件
- `UI_BEYOND_EDITOR_VFXEDITOR_EX3_NEW` = 新建轨道
- `UI_BEYOND_EDITOR_VFXEDITOR_EX4_ADDTRACK` = 新建普通轨道
- `UI_BEYOND_EDITOR_VFXEDITOR_EX4_ADDLOOPTRACK` = 新建循环节轨道
- `UI_BEYOND_EDITOR_VFXEDITOR_EX4_TRACKDEFAULTNAME` = 新建轨道
- `UI_BEYOND_EDITOR_VFXEDITOR_EX4_ADDEVENTATLINE` = 添加事件
- `UI_BEYOND_EDITOR_PROTOTYPE_LINE_ADDMEASUREMENTLINES` = 添加测距线
- `UI_BEYOND_EDITOR_PROTOTYPE_ARRAY_CONFIRMCREATION` = 确认创建
- `UI_BEYOND_EDITOR_CURSOR_COLLISION_ADD` = 添加光标碰撞
- `UI_BEYOND_EDITOR_COOP_CREATEASACOLLABORATIVEARCHIVE` = 创建为协作存档
- `UI_BEYOND_EDITOR_COOP_EXPORTFAILED` = 创建协作模式存档
- `UI_BEYOND_EDITOR_COOP_CREATETITLE` = 创建协作模式存档
- `UI_BEYOND_EDITOR_COOP_TIPSFORCHANGE4` = 创建协作模式存档
- `UI_BEYOND_EDITOR_COOP_CONFIRMCREATION` = 确认创建
- `UI_BEYOND_EDITOR_COOP_CREATE_SUCCESS` = 协作模式存档创建成功！
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_CLIENT_UI_CONTROL` = 添加客户端界面控件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_CONTROL` = 添加控件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_EMPTY_NODE` = 添加空节点
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CREATE_EMPTY_NODE_AND_PLACE` = 创建空节点并置入
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_NEW_CLIENT_SCRIPT` = 新建客户端脚本
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_SCRIPT_FILE` = 添加脚本文件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_EXISTING_SCRIPT_AND_MAPPING` = 批量添加脚本文件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_NEW_SCRIPT_MAPPING` = 新建脚本映射
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_VARIABLE` = 新增变量
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_ADD_TEXT_VARIABLE` = 新增文本变量
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_BLANK_BASE_CREATESETTING` = 创建设置
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_BLANK_SCRIPT_ADDSCRIPT` = 添加脚本
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_SCRIPT_ADD_FILE` = 按文件添加
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_SCRIPT_ADD_FOLDER` = 按文件夹添加
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_SCRIPT_CREATE_FILE_TITLE` = 创建脚本文件
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_SCRIPT_TIP_CREATE_FAIL` = 创建失败
- `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_MODEL_ADD_CLIENT_UI_CONTROL` = 添加客户端控件

## 5. The 7.1 vs 7.0 question (a second TextMap?)

There is **no second TextMap directory**. The install has exactly one TextMap root
(`D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/TextMap/`) with 15
language subdirs, one `.mihoyobin` each:

| lang | file |
|---|---|
| CHS | 17720714722766726369.mihoyobin |
| CHT | 11284457730017061111.mihoyobin |
| DE | 5187829705972667115.mihoyobin |
| EN | 6246370240741975437.mihoyobin |
| ES | 7128657974210431668.mihoyobin |
| FR | 12617692037789508847.mihoyobin |
| ID | 165995757088611046.mihoyobin |
| IT | 14937131906817476398.mihoyobin |
| JP | 10834242066387198875.mihoyobin |
| KR | 501195674224062945.mihoyobin |
| PT | 8208247846030159950.mihoyobin |
| RU | 15901364795405250954.mihoyobin |
| TH | 13420409649441522412.mihoyobin |
| TR | 16787395788866970016.mihoyobin |
| VI | 16094592205117128184.mihoyobin |

The installed (7.1) CHS table is emitted above. Its 7.0 counterpart already exists in-repo at
`.runtime/editor-catalog/decoded/TextMap__CHS__17720714722766726369.mihoyobin.json` (7743 entries;
same numeric resource id, different content/size -> the id is NOT a content hash, so 7.0 and 7.1
share the filename but differ). EN values were decoded for the panel keys in 4a/4b.

Keys present in 7.1 only (524 total); first 60:
`BeyondAssistantEditorConfigGlobal_configEnum_maps_100_map_13_textMapId_200051`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_100_map_14_textMapId_200051`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_100_map_15_textMapId_200051`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_100_map_16_textMapId_200051`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_100_map_17_textMapId_200051`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_102_mapTitle`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_102_map_0_textMapId_200053`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_102_map_1_textMapId_200053`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_102_map_2_textMapId_200053`, `BeyondAssistantEditorConfigGlobal_configEnum_maps_30_map_21_textMapId_31`, `BeyondAssistantEditorConfigGlobal_folders_11_data_subFolders_0_subFolders_4_name`, `BeyondAssistantEditorConfigGlobal_folders_3_data_subFolders_0_subFolders_4_name`, `BeyondAssistantEditorConfigGlobal_folders_4_data_subFolders_0_subFolders_4_name`, `BeyondAssistantEditorConfigGlobal_folders_9_data_subFolders_0_subFolders_4_name`, `BeyondEditorInstructionNodeConfig_desc_200301`, `BeyondEditorInstructionNodeConfig_desc_200302`, `BeyondEditorInstructionNodeConfig_desc_200303`, `BeyondEditorInstructionNodeConfig_desc_200307`, `BeyondEditorInstructionNodeConfig_desc_200308`, `BeyondEditorInstructionNodeConfig_desc_200309`, `BeyondEditorInstructionNodeConfig_desc_200310`, `BeyondEditorInstructionNodeConfig_desc_200311`, `BeyondEditorInstructionNodeConfig_desc_200312`, `BeyondEditorInstructionNodeConfig_desc_300005`, `BeyondEditorInstructionNodeConfig_desc_856`, `BeyondEditorInstructionNodeConfig_extraParamList_0_name_300005`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200301`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200302`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200303`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200307`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200311`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_200312`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_300005`, `BeyondEditorInstructionNodeConfig_inParamList_0_name_856`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200302`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200311`, `BeyondEditorInstructionNodeConfig_inParamList_10_name_200312`, `BeyondEditorInstructionNodeConfig_inParamList_11_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_11_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_11_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_11_name_200311`, `BeyondEditorInstructionNodeConfig_inParamList_12_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_12_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_12_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_12_name_200311`, `BeyondEditorInstructionNodeConfig_inParamList_13_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_13_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_13_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_13_name_200311`, `BeyondEditorInstructionNodeConfig_inParamList_14_name_200308`, `BeyondEditorInstructionNodeConfig_inParamList_14_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_14_name_200310`, `BeyondEditorInstructionNodeConfig_inParamList_15_name_200309`, `BeyondEditorInstructionNodeConfig_inParamList_15_name_200310`

