"""Build the evidence-only closeout inventory. Never imports or calls live tools."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/research/7.1-experiment-plan/closeout'
SOURCE = '.runtime/verification/interface-experiments-20260926/source-registry.jsonl'
PLAN = 'docs/research/7.1-experiment-plan/coverage.json'
BRIDGE = 'tools/editor-bridge/ManagedBridge/BridgeServer.cs'
CALL = 'tools/editor-bridge/call-bridge.ps1'
SCENE = 'tools/game-executor/scene_cli.py'
AUTHOR = 'tools/authoring/author.py'
META7 = '.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json'
RESCAN = '.runtime/verification/docs-71-20260926/native-command-rescan-all38.json'
VM_INDEX = '.runtime/verification/interface-experiments-20260928/interface-discovery/vm-index-7.1.json'
UI_MATCH = '.runtime/verification/interface-experiments-20260928/interface-discovery/ui-owner-matching.json'
TPL_INDEX = '.runtime/verification/interface-experiments-20260928/interface-discovery/template-index.json'
TEXTMAP = '.runtime/verification/docs-71-20260926/textmap-decoded-71.json'

SHORTCUT_LABEL_7_1 = {
    'BEYOND_EDITOR_SHORTCUT_KEY_ASSIST_COMMON': '通用',
    'BEYOND_EDITOR_SHORTCUT_KEY_CANVAS': '画布',
    'BEYOND_EDITOR_SHORTCUT_KEY_CATALOG': '目录',
    'BEYOND_EDITOR_SHORTCUT_KEY_CHANGE_CANVAS': '放大/缩小画布',
    'BEYOND_EDITOR_SHORTCUT_KEY_CHOOSE_ALLCONTENT': '全选输入内容',
    'BEYOND_EDITOR_SHORTCUT_KEY_CHOOSE_ALL_NODE': '全选节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_CHOOSE_MULT_NODE': '多选节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_CHOOSE_UP_OR_DOWN': '选择上一个/下一个',
    'BEYOND_EDITOR_SHORTCUT_KEY_CREATE_CHOOSE_NODE': '创建所选节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_CREATE_MULT_NODE': '生成复合节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_DELETE_LINE': '断开所选连线',
    'BEYOND_EDITOR_SHORTCUT_KEY_DELETE_NODE': '删除选中的节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_DISBAND_MULT_NODE': '解散复合节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_EDIT_FLODER': '文件/文件夹',
    'BEYOND_EDITOR_SHORTCUT_KEY_MOVE_CANVAS': '平移画布',
    'BEYOND_EDITOR_SHORTCUT_KEY_MOVE_MOUSE': '左/右移动光标',
    'BEYOND_EDITOR_SHORTCUT_KEY_MOVE_MOUSE_LEFT': '光标移至最左',
    'BEYOND_EDITOR_SHORTCUT_KEY_MOVE_MOUSE_RIGHT': '光标移至最右',
    'BEYOND_EDITOR_SHORTCUT_KEY_MOVE_NODE': '移动选中的节点',
    'BEYOND_EDITOR_SHORTCUT_KEY_OPEN_FLODER': '打开选中文件/文件夹',
    'BEYOND_EDITOR_SHORTCUT_KEY_OPEN_NODESTORE': '打开节点库（鼠标位于画布空白处）',
    'BEYOND_EDITOR_SHORTCUT_KEY_REVERT': '还原',
    'BEYOND_EDITOR_SHORTCUT_KEY_TAB_SWITCH': '页签展开/收起',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_A': 'A',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_C': 'C',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_CREATCOPY': '创建副本',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Ctrl': 'Ctrl',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_D': 'D',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_DOWN_ARROW': '↓',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Delete': 'Delete',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_ENTER': None,
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_End': 'End',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_F': 'F',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_G': 'G',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Home': 'Home',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_LEFT_ALT': 'Alt',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_LEFT_ARROW': '←',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_RIGHT_ARROW': '→',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_S': 'S',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_SHIFT': 'Shift',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_UP_ARROW': '↑',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_V': 'V',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Y': 'Y',
    'BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Z': 'Z',
    'BEYOND_EDITOR_SHORTCUT_KEY_TO_BOTTOM': '返回底部',
    'BEYOND_EDITOR_SHORTCUT_KEY_TO_TOP': '返回顶部',
    'BEYOND_EDITOR_SHORTCUT_KEY_UNFLOD_OR_CLOSE': '展开/收起',
}
USER_OP_DISPATCH = {
    'audio.preview_music': ['beyondAudioService (boGLyQBJv9p)', None, 'undecidable'],
    'audio.preview_sfx': ['beyondAudioService (boGLyQBJv9p)', None, 'undecidable'],
    'cost.focus_screenshot': ['beyondEditObjService', 3341291087, 'matched'],
    'cost.import_performance_report': ['beyondExportService', 3516231864, 'matched'],
    'debuglog.delete': ['beyondExportService', 1502000889, 'matched'],
    'debuglog.import_all': ['beyondExportService', 170755844, 'matched'],
    'debuglog.import_log': ['beyondExportService', 124929907, 'matched'],
    'debuglog.refresh_report': ['beyondExportService', 1854931542, 'matched'],
    'entity.apply': [None, 1751612374, 'matched'],
    'entity.change_faction': ['beyondEditObjService', 622039177, 'matched'],
    'entity.delete': ['beyondEditObjService', 1968836851, 'matched'],
    'entity.export': ['beyondExportService', 3635078626, 'matched'],
    'entity.focus_in_game': ['beyondEditObjService', 2028679940, 'matched'],
    'entity.import': ['beyondExportService', 3380758105, 'matched'],
    'entity.jump_combat_setting': [None, 2312046255, 'matched'],
    'entity.rename': ['beyondEditObjService', 2682328143, 'matched'],
    'io.export_gia': ['beyondExportService', 3635078626, 'matched'],
    'io.import_gia': ['beyondExportService', 3380758105, 'matched'],
    'io.transfer_assets': ['beyondExportService', 3380758105, 'matched'],
    'resource.focus_in_game': ['beyondEditObjService', 2028679940, 'matched'],
}
FEATURE_DISPATCH = {
    'combat-setting-jump': [None, 2312046255, 'matched'],
    'entity-delete': ['beyondEditObjService', 1968836851, 'matched'],
    'entity-focus': ['beyondEditObjService', 2028679940, 'matched'],
    'entity-rename': ['beyondEditObjService', 2682328143, 'matched'],
    'focus-prefab-instance': ['beyondEditObjService', 2986498442, 'matched'],
    'graph-add-to-entity': ['beyondEditObjService', 2829135592, 'matched'],
    'performance-report-import': ['beyondExportService', 3516231864, 'matched'],
    'prefab-instance-change-apply': [None, 1751612374, 'matched'],
    'prefab-instance-request': ['beyondEditObjService', 2674226539, 'matched'],
    'suite-modify': ['beyondEditObjService', 3624401861, 'matched'],
}

# 2026-09-28: the two templates that exist in 7.1 and NOT in the old build. Found by indexing
# Template_* literals in both annotated corpora. Relevant to script.signals and ui.templates:
# Template_ClientScriptExplorerMain is a new client-script explorer panel.
UI_ACTION_HANDLER = {
    'entity.apply': ('NNwa8GK28oPifmneADs0', 9, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_APPLY"', 'X2vK26gAC51', ['NUpKBG9iyuD']),
    'entity.change_faction': ('NNwa8GK28oPifmneADs0', 15, '"UI_BEYOND_ASSIST_EDITOR_ARMY_CHANGE_ARMY"', 'AOqK2Z4ib24', ['et1igvgopub', 'jycKBnBuuvE']),
    'entity.check_reference': ('NNwa8GK28oPifmneADs0', 8, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_CHECK_REFERENCE"', 'SN0K2F0DXIh', ['et1igvgopub', 'MbWKBcDbWV5']),
    'entity.copy_bp_id': ('NNwa8GK28oPifmneADs0', 14, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_COPY_BP_ID"', 'D8TK2VGpHGi', ['MexKm2jjjVm']),
    'entity.delete': ('NNwa8GK28oPifmneADs0', 7, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_DELETE"', 'CUAK2RMBvqy', ['zgVKB6OS1MZ']),
    'entity.duplicate': ('NNwa8GK28oPifmneADs0', 6, '"UI_BEYOND_ASSIST_EDITOR_NODE_DUPLICATE"', 'MUVK2oiWOKs', ['dJPKBJM21c8']),
    'entity.export': ('NNwa8GK28oPifmneADs0', 12, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_EXPORT"', 'DpCK2pe73NJ', ['C6xKBZLdA0J']),
    'entity.focus_in_game': ('NNwa8GK28oPifmneADs0', 1, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_CHECK_FOCUS"', 'hS4K2jUsMgW', ['sM5KBF555gu']),
    'entity.import': ('NNwa8GK28oPifmneADs0', 13, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_IMPORT"', 'UhKK2cTgTHp', ['CxUKBrUoC4X']),
    'entity.open': ('NNwa8GK28oPifmneADs0', 0, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_OPEN"', 'TMZK29NGd12', ['sM5KBF555gu']),
    'entity.rename': ('NNwa8GK28oPifmneADs0', 3, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_RENAME"', 'Y2tK2UR05BS', ['wAXirPMXQCJ', 'B4SKtHJyWpr', 'QGcKJVtWfOh']),
    'pin.disconnect_all': ('IKba7HuQCJ1iWcNf1BVP', 9, '"UI_BEYOND_ASSIST_EDITOR_DISCONNECT_ALL_CONNECTION"', 'elhuX37QXjZ', ['We8uXiRvfY2']),
    'pin.disconnect_one': ('IKba7HuQCJ1iWcNf1BVP', 8, '"UI_BEYOND_ASSIST_EDITOR_DISCONNECT_CONNECTION"', 'elhuX37QXjZ', ['We8uXiRvfY2']),
    'resource.check_reference': ('uFMyy7Kw7Pe8xVfHEqF7', 8, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_CHECK_REFERENCE"', 'ToXKw9IWgKe', ['et1igvgopub', 'MbWKBcDbWV5']),
    'resource.delete': ('uFMyy7Kw7Pe8xVfHEqF7', 7, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_DELETE"', 'W0QKwWajWfw', ['zgVKB6OS1MZ']),
    'resource.focus_in_game': ('uFMyy7Kw7Pe8xVfHEqF7', 1, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_CHECK_FOCUS"', 'febKwTgCB1g', ['sM5KBF555gu']),
    'resource.rename': ('uFMyy7Kw7Pe8xVfHEqF7', 3, '"UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_RENAME"', 'yl6KwXfsc12', ['wAXirPMXQCJ', 'gtKKwCTqoVY', 'QGcKJVtWfOh']),
}
META7 = '.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json'
RESCAN = '.runtime/verification/docs-71-20260926/native-command-rescan-all38.json'

# 2026-09-28: the 'operation' records come from the editor's own frontend database and carry
# no service. A first pass looked them up by exact name in the 7.1 assembly metadata; 8
# resolved to a method, 5 are not interfaces at all, and the rest did NOT resolve.
#
# That first pass was the wrong instrument, and this project has a recorded lesson about
# exactly that: some commands are dispatched by FNV-1a HASH rather than by literal name, so a
# name lookup miss is NOT-FOUND, not absence. This project's memory file
# absence-of-evidence-discipline.md lists four prior errors of that shape and instructs to
# change encodings and run a positive control before concluding.
#
# The positive control was run: all 32 command hashes recorded in RESCAN were independently
# recomputed with the project's own fnv1a and all 32 matched. The instrument is valid.
#
# With that instrument, 28 of the remaining operations ARE attributed - service, FNV-1a hash
# and route status - in an artifact this closeout already holds. The duplicate identity (the
# same command also appears as a source 'command-candidate' WITH its service) is recorded as a
# link, not merged: this project's rule is that a name match alone must not merge two records.
#
# value = (legacyService, fnv1aHash, routeStatus, 7.1InstructionHits)
USER_OP_BACKEND_COMMAND = {
    'entity.apply': ('ApplyPrefabInstanceChange',),
    'entity.delete': ('DeleteEditObj', 'DeletePrefab'),
    'entity.export': ('DoExport',),
    'entity.focus_in_game': ('FocusEditObj', 'FocusPrefabInstance'),
    'entity.import': ('DoImport',),
    'entity.open': ('FocusEditObj', 'FocusPrefabInstance'),
    'entity.rename': ('ModifyEditObjName',),
    'resource.delete': ('DeleteEditObj', 'DeletePrefab'),
    'resource.focus_in_game': ('FocusEditObj', 'FocusPrefabInstance'),
    'resource.rename': ('ModifyEditObjName',),
}

UI_ELEMENT_EXACT = {
    'Aq2ycJuYZ5nAERMUru7f': ('tvThpUj8wifrDw53qBut.RrDasQj8ZVVLGvpcTw0J', 1, 'weak'),
    'B0gUrpKkSiTGJr81KypF': ('Hxfn4QjUP7eiLLfKKCgO.f6eegIjUpdhSqmmhHrBN', 9, 'strong'),
    'DDfsTbumioP8OeS9Kv6f': ('EAXMdEj5uParjV1me0nB.fQ9OFjj5fJZPTmhidVyd', 4, 'strong'),
    'Fk16xvuRWXmOs5frcF8H': ('m26m0mQQyIGj30EONZJ5.wCEx2UQQK7UtXfWRS9oA', 4, 'strong'),
    'H4ENZduPkaQ5CTaa2ENJ': ('zKTct8QDvkXoc34yoVpE.vGxK25QDGXkdEIKfX4E6', 22, 'strong'),
    'HIG8F7uc0I2aH5nhj8wU': ('RVw01FQauR2vIcIO8Vn8.F6kfFOQaff8NUoNkDNK9', 3, 'strong'),
    'HiJ2uWu3lTw5GsosMb9e': ('bGlxWgjrUJAjyLDUU2IT.iMuLamjrsIpH4fWiEvFi', 1, 'weak'),
    'IKba7HuQCJ1iWcNf1BVP': ('JPZ4h9QZoTmgHGa0x3se.UB1Vv5QZPxYfaGxp6FPL', 4, 'strong'),
    'IMYy8eKgQIfrUXGfb8mv': ('JuBtsUjxYAhlt7Fq4IWD.Ak3VHLjxHRluDLdtQPCq', 4, 'strong'),
    'JpISnbujLkr4nngxqWFJ': ('K9N8UqQPFdkV7LJwy6eL.cXbPAkQPc4duwZ8pYLct', 3, 'strong'),
    'Kh3RN2ujG2WKtE2UTDAK': ('MHb3xjQoPfsPN8V3MrJY.yitYjnQopBKMUtSwMCeU', 2, 'medium'),
    'L3RZZfuPMbssd1Ggao1E': ('Uo2DPojz9CU3yduBaas0.G4AtwyjzVlPIfTkUCvMu', 1, 'weak'),
    'M2bF6wKCnSaAHlvJtY0X': ('XTs12bjtnIIe7VCqgJoS.lmCFgRjt19Z8M8CEWyaO', 7, 'strong'),
    'MLx0fWKyr4g90EjGRFNN': ('om3cHhj4Xv0H1aPEFv4Z.LiYDRkj4LHSZl14QKTdm', 5, 'strong'),
    'NNwa8GK28oPifmneADs0': ('gjU5WAj1vdH3jqAWfPih.LSvKfCj1GPYOMCWEswVK', 6, 'strong'),
    'NmgDODuK6pZHKuF5VxFE': ('nuQK6gjYYxH1nFmeqx8S.ftceMqjYHOSxADYeG6ES', 2, 'medium'),
    'PF4lO5uDqUKHn1RN6qon': ('ecyyn8jyclZi6E6Ll1Vh.h2SgCZjy0DQFivISd3uL', 3, 'strong'),
    'PIQ0aTKC0eMkOX7hxa55': ('OkqqyUjiJMf8Fr5H4P0m.w1gBXpjiCeaqVIybfs1U', 1, 'weak'),
    'PLKaYuunsDIIyd0vEowZ': ('WSp63RQtHm8wOvQL4J6V.gELXE3QtrMLgwoFWIa07', 12, 'strong'),
    'PjdyunKTGpRnpQuogWfj': ('B4ZOWQjOZ8hKEYenfn2p.qyroSgjOOWyGixm0rWJi', 1, 'weak'),
    'QCCQhYuyr0hmMjo9SJke': ('NWTbXIQuQ9amXekhiHFC.zQTXaPQujEylLZi75eUE', 2, 'medium'),
    'QjTdd5KyTanMocdma46d': ('tll2gJjJzEP3gMSXYkjv.CmrB4bjJ3SH4PPQF2CEa', 2, 'medium'),
    'SDrmqkuFCEYB66g31gcj': ('Of3qMxQMohB3aigAmyho.NSSwkSQMPXDDVIcc3igh', 1, 'weak'),
    'SmPcDVKQUDqwaIu1hmwZ': ('zSLuR4j2Ko3n8VC8gMGG.N1syVgj28T1UauKuj8i6', 2, 'medium'),
    'TqJtgQux2ah7aVABw1pB': ('pgXjTTjKoc5wT7Nu3e9D.XtRpuWjKPPBk3pgVec5f', 9, 'strong'),
    'UXZZCuurqR31atW9s3FY': ('lyUmHlQd3Lb5MQoLspYQ.bBmlIPQdyvFXgcAvYmUJ', 5, 'strong'),
    'UhbhJaK66RZ4wbVkn8IJ': ('oLd4dujPmhNMLl2UOTSu.EiqqZVjPRKE0xSOX43EM', 2, 'medium'),
    'VaR86gKerBXhRbru9366': ('vl9vGjjsLmG2ejhTglK5.oFMDDsjswF1WkI9KqLsx', 4, 'strong'),
    'VbovffuP3SPHrpOKCSuK': ('HbGksEjzfjpBq2dWx1y5.xExi8LjzTmmrrBWKYFbA', 1, 'weak'),
    'YWlUeFKpEU3Lh8YnZ6Mj': ('UW23Onjon2KcJy5beZF5.l5urUsjo1qe6wmfCucqc', 2, 'medium'),
    'c1wjQuuakdWEJFMOLrfg': ('WAbVC1j5vl9ErFDher36.rWw76Pj5GiRxPobXFLR6', 2, 'medium'),
    'cHbHuwK6TQOiHmKt3nSb': ('entC3Njp8GnjyxAuaUli.eUt0lfjpFCWmlNYT91hQ', 1, 'weak'),
    'cyuibfKcHH5Gm41mrL4Q': ('cgiS2TjM1AkF8mMTC77t.r1JknNjMAKNWjLE5VsWa', 1, 'weak'),
    'dOU8RoK6skKVyihI4ffy': ('DAjrUOjpby4ueorWqO2i.sAH1g5jpg10mpC8Wclwy', 2, 'medium'),
    'eHOGAPufnrsxm4c5fPHD': ('erD4WBQ7pVVhHnLO93AN.RjmXeIQ7QWOjIrOGDrAN', 3, 'strong'),
    'eUb5JpKZyhXaWRtAiThB': ('wxbmRmjaMTpMhNpKGTNl.SuAFfDjao3TpieCdiEeA', 9, 'strong'),
    'fANjkeKViEWXJ0YJ95jj': ('Pux6S2jqUBrG20Tj3mhF.ffjB4ajqs4PSpKyueTsT', 1, 'weak'),
    'fH6U63uCylc4vBmFeAhb': ('Eu66MPQntOkxagiAD8UG.esi9RYQniEShbLZtDllm', 2, 'medium'),
    'fK4KAmuWzyG3Us9fhMH5': ('AsbMiUQOABymGN06Gfqw.cguDibQOt6tGbbl77K2w', 3, 'strong'),
    'fZCZQWuNyKqyX3yEp4mc': ('FQgXblQPvrIFTwFy9oxV.FC6IHKQPGygiWMpm14TZ', 7, 'strong'),
    'fbDlR5uNNUR3ElVQaovJ': ('V4YT5UQPem8NWbNxpaAD.uZuJhOQPxgdZ7NY7TNkH', 3, 'strong'),
    'fegvg2u3HYuGq5mb66ta': ('xsOs9hjkf37kTmvsF1Tm.s1yFWpjkT8xXhm0W7d2Z', 3, 'strong'),
    'ghF1sQKBbpMCTbDkMGOr': ('OKb40HjNNiNAjBJcG36C.ykv8dSjNnWx0OJTVXtxl', 2, 'medium'),
    'h87JOfKgSqPG521PL1NM': ('NIekYrjeL1cMaQ65dKYX.Ntfk3ljewA4oNitAMJvl', 2, 'medium'),
    'hpN0LEKfMOFul7DFu62g': ('uIdHWmjP6xd4jKvpJvLH.f7ZMpxjPhnbnUSq0hro6', 4, 'strong'),
    'hsF9GCKGTiqbpTkyXi6g': ('RgYe5fjd8ALTjbA0khHg.sGsGm3jdFbfPLUvny0bv', 2, 'medium'),
    'jAK4y3upOxtSg6VmLDb3': ('q28H54Q7Cr3QjUoqnAt5.kcWLaHQ7NJEHq9vAewhw', 6, 'strong'),
    'l450dfKnrjPRAb5GbtlC': ('GK4OIVjdO94BZkyuK5ii.c7mfmljdIFbEtfa6un7Q', 2, 'medium'),
    'lt4QVGutmd5HnmFq57fL': ('qfmHucQsNxb7RLxSUkjZ.l47WE8QsnNNfMgBdnPVg', 2, 'medium'),
    'mMrD43uCOiEVwAjeNrL9': ('yx7RfMQ1sYTCusKEBsg4.iJVFk1Q14hV1rXxk8kFb', 4, 'strong'),
    'nOi2Z4KVJS3QRhFqHSGm': ('yjj2vsj7Z5aNFbRcvXSP.DOqnqmj7OuWS0mNbHObn', 2, 'medium'),
    'oeqBJJuPL12nUT1c7UQT': ('AG4JAejz0l1TTdUQkhK5.FNoQE2jzYNhTrr8GGpXG', 2, 'medium'),
    'pkDPGRuWa8w0osUsOPdm': ('dNOaVhQInMqhTogRCgCB.iGS1vbQI1yq9Eb1TfHE8', 1, 'weak'),
    'qIRnnWuHG6HHsNOnguEi': ('H6GPhFjbPllhVA6ySHgo.zdOSNgjbp9wiZ9ucoY7W', 2, 'medium'),
    'scx7G3ublsXOUxGyO05r': ('Fj1HO8jWHpCpsbTvXTRl.XHkBWdjWriITgWt0Pouu', 2, 'medium'),
    't0vyetunADrFYRA1d2F9': ('PW70MgQtW74C9gZwesxd.RSk8HfQtlm2OWT6jU2P5', 1, 'weak'),
    'tC38a9uZumHDvhgFUCLl': ('hbQOMQQvbi1iltrN6L55.B6VlnwQvgeK3dwoevIS4', 4, 'strong'),
    'tNDJftu6OMefXggAXUWC': ('UeIgbNQMCn5KLVEDFkwn.M7hCkTQMNHyO4Ix5H2Pj', 2, 'medium'),
    'vhXqqMu29Z24tpvFGVMU': ('V9IEboQsEN1EHuwl0xwX.j3s3yhQsDh8507xIcC79', 4, 'strong'),
    'w33MCYK9af5cV00WXWnn': ('zOnUOdjOGMjGm5ArGo7E.d3MFdVjOaHBtsuXQvpsH', 7, 'strong'),
    'w7LjkFuPof5dWt6CbM6v': ('Kmqsa3QDDLB6bpuyY8i4.NQfmjEjzz2qSblDop3Hn', 2, 'medium'),
    'wHDN2uuGG9oVXXmuwRGD': ('hief42Q1qRMR7Posri9X.BG8CoFQ1MuUIw4KJwZJV', 2, 'medium'),
    'xtkujkK6zWqExfD35wGn': ('lJo9sYjPGcQMDmQkgB7f.iSDTAkjPaj0VlAtseWpW', 2, 'medium'),
    'y2Mww8uieuUu6UHVBjuZ': ('oaRMW2jYIb8vF8sI1FOl.v2ESQKjYB0TJKAVVlIfx', 5, 'strong'),
    'zNCyCkKqwABPaepN9xMV': ('N44NrMjxpFRTtaV5ORXK.NERuiSjxQ56ZyKCnKkqZ', 1, 'weak'),
}

TEMPLATES_NEW_IN_7_1 = ['Template_ClientScriptExplorerMain', 'Template_NodeParamEdit']

# All 49 recorded templates, each confirmed present in the 7.1 annotated corpus.
UI_TEMPLATE_CONFIRMED = (
    'Template_CalculateCompoundNodeEditor',
    'Template_CheckBoxCommon',
    'Template_ComponentEdit_ComponentPanel',
    'Template_ComponentEdit_EditableStruct',
    'Template_ComponentEdit_EditableValue',
    'Template_ComponentEdit_EditableValueList',
    'Template_ComponentEdit_Editor',
    'Template_CompoundNodeEditor',
    'Template_CompoundSaveAlertDialog',
    'Template_DockContainer',
    'Template_DockPage',
    'Template_DockVirtualWindow',
    'Template_Empty',
    'Template_ExplorerDragger',
    'Template_ExplorerReferenceDialog',
    'Template_GMDialogBody',
    'Template_InHouseGraphSelection',
    'Template_InstructionExplorer',
    'Template_InstructionExplorerMain',
    'Template_InstructionGraphExplorerTab',
    'Template_MainResourceExplorer',
    'Template_MainResourceExplorer_Shrinked',
    'Template_MainWindowBody',
    'Template_MemoryMonitorDialogBody',
    'Template_NodeComment',
    'Template_NodeExplorer',
    'Template_NodeGraphEditor',
    'Template_NodeGraphEditorContainer',
    'Template_NodeInParam',
    'Template_NodeInParamExcecute',
    'Template_NodeInParamUneditable',
    'Template_NodeIndexIndicator_Dragger_In',
    'Template_NodeIndexIndicator_Dragger_Out',
    'Template_NodeParamListEditPanel',
    'Template_ResourceCategoryTab',
    'Template_SearchPanel',
    'Template_StructFastEditDialog',
    'Template_TextBlockCommon',
    'Template_TextBlockInspector',
    'Template_TextBoxCommon',
    'Template_UIPreviewTab',
    'Template_VMChangeFactionIdDialog',
    'Template_VMDragDropContentDockTab_DragDropContent_DockTab',
    'Template_VMDragDropContentSimpleText_DragDropContent_SimpleText',
    'Template_VMGeneralConfirmDialog_GeneralComfirmDialog',
    'Template_VMPopupCollectionItemGeneralHint',
    'Template_VMSignalEditPanel_SignalMgtDialog',
    'Template_VMVMGeneralConfirmDialog_SignalMgtSaveAlertDialog',
    'Template_Vector3Common',
)

OPERATION_DISPATCH = {
    'AddInstructionGraphForEditObj': ('beyondEditObjService', 2829135592, 'matched', 2),
    'AddInstructionGraphForPrefab': (None, 439613177, 'matched', 2),
    'ApplyPrefabInstanceChange': (None, 1751612374, 'matched', 2),
    'DeleteComponentForEditObj': ('beyondEditObjService', 191492749, 'matched', 1),
    'DeleteComponentForPrefab': ('beyondEditObjService', 1546116878, 'matched', 1),
    'DeleteDebugLog': ('beyondExportService', 1502000889, 'matched', 1),
    'DeleteEditObj': ('beyondEditObjService', 1968836851, 'matched', 1),
    'DeletePCGInstance': ('beyondPCGInstanceService (Is6hqU640RJ)', None, 'undecidable', 0),
    'DeletePrefab': ('beyondEditObjService', 2204536520, 'matched', 1),
    'DoExport': ('beyondExportService', 3635078626, 'matched', 1),
    'DoExportClientScript': (None, None, None, 2),
    'DoImport': ('beyondExportService', 3380758105, 'matched', 1),
    'EndLoadAllDebugLog': ('wpfAudioService', None, 'disproved', 0),
    'FocusBeyondTileMap': ('beyondEditObjService', 2091430146, 'matched', 1),
    'FocusCharacter': ('beyondEditObjService', 1063071922, 'matched', 1),
    'FocusDropGather': ('beyondEditObjService', 3204681929, 'matched', 1),
    'FocusEditObj': ('beyondEditObjService', 2028679940, 'matched', 2),
    'FocusEsp': ('beyondEditObjService', 2683981737, 'matched', 1),
    'FocusLight': ('beyondEditObjService', 3875797053, 'matched', 1),
    'FocusLocalBullet': ('beyondEditObjService', 411085022, 'matched', 1),
    'FocusPCGInstance': ('beyondPCGInstanceService (Is6hqU640RJ)', None, 'undecidable', 0),
    'FocusPrefabInstance': ('beyondEditObjService', 2986498442, 'matched', 1),
    'FocusScreenshot': ('beyondEditObjService', 3341291087, 'matched', 2),
    'ImportAllDebugLog': ('beyondExportService', 170755844, 'matched', 1),
    'ImportDebugLog': ('beyondExportService', 124929907, 'matched', 1),
    'ImportPerformanceReport': ('beyondExportService', 3516231864, 'matched', 1),
    'JumpCombatSetting': (None, 2312046255, 'matched', 2),
    'ModifyEditObjName': ('beyondEditObjService', 2682328143, 'matched', 2),
    'ModifyEditobjTag': ('beyondEditObjService', 3175143996, 'matched', 2),
    'ModifyFactionForEditObj': ('beyondEditObjService', 622039177, 'matched', 1),
    'ModifyFactionForPrefab': ('beyondEditObjService', 525782274, 'matched', 1),
    'ModifyPCGInstanceName': ('beyondPCGInstanceService (Is6hqU640RJ)', None, 'undecidable', 0),
    'ModifyPrefabName': ('beyondEditObjService', 3086307582, 'matched', 1),
    'ModifyPrefabTag': ('beyondEditObjService', 1175225307, 'matched', 1),
    'ModifySuite': ('beyondEditObjService', 3624401861, 'matched', 1),
    'PlayMusic': ('beyondAudioService (boGLyQBJv9p)', None, 'undecidable', 0),
    'PlaySoundEffect': ('beyondAudioService (boGLyQBJv9p)', None, 'undecidable', 0),
    'RefreshExistDebugLogReport': ('beyondExportService', 1854931542, 'matched', 2),
    'RequestPrefabInstance': ('beyondEditObjService', 2674226539, 'matched', 1),
    'batchcreate': (None, None, None, 0),
    'batchdelete': (None, None, None, 0),
    'beyondClientScriptService': (None, None, None, 0),
    'deleteNodeConfig': (None, None, None, 0),
    'deleteSignal': (None, None, None, 0),
    'modify': (None, None, None, 0),
    'modifyNodeConfig': (None, None, None, 0),
    'modifySignal': (None, None, None, 0),
    'modifypath': (None, None, None, 0),
    'sendScriptPath': (None, None, None, 0),
    'wpfClientScriptService': (None, None, None, 0),
    'wpfColEditService': (None, None, None, 0),
}
META7 = '.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json'

# 2026-09-28: the 44 unattributed 'operation' records were looked up by exact name in the
# 7.1 assembly metadata (15654 types, 115067 methods). These names come from the editor's own
# frontend database, NOT from this project's adapter, so they are not subject to the
# legacy-vs-resolved symbol trap that produced a false negative in this project on the same
# day - that trap applies to names THIS project spelled, not to names the frontend holds.
#
# Eight are real methods. Five are not interfaces at all. The rest are NOT claimed absent:
# this project has documented that some commands are dispatched by FNV-1a hash rather than by
# literal name (FocusEditObj is the worked example), so a name miss is NOT-FOUND, not proof.
OPERATION_RESOLVED = {
    'ModifyEditObjName': ('RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx',
                          'ModifyEditObjName(System.UInt32,System.String):System.Void',
                          'already exercised by the CRUD probe; the existence proof for this call pattern',
                          ['entity.rename_delete']),
    'DeletePCGInstance': ('RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx',
                          'DeletePCGInstance(System.UInt32):System.Void',
                          'same bound manager; unused so far', ['terrain.pcg']),
    'ModifyPCGInstanceName': ('RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx',
                              'ModifyPCGInstanceName(System.UInt32,System.String):System.Void',
                              'same bound manager; unused so far', ['terrain.pcg']),
    'ModifyPrefabName': ('RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx',
                         'ModifyPrefabName(System.UInt32,System.String):System.Void',
                         'same bound manager; not among the 44, found by the same sweep', ['entity.group']),
    'PlayMusic': ('X5uvRfQTGYih6DgKn6gp.hXZ8d1QTaWJ3qNq8XOSK',
                  'PlayMusic(System.UInt32):System.Boolean plus an 8-parameter overload',
                  'id + float/boolean fade-volume-loop parameters; the only float-taking methods in the assembly',
                  ['game.presentation']),
    'PlaySoundEffect': ('X5uvRfQTGYih6DgKn6gp.hXZ8d1QTaWJ3qNq8XOSK',
                        'PlaySoundEffect(System.UInt32):System.Boolean plus an 8-parameter overload',
                        'same audio singleton, which also exposes Stop(System.Boolean)', ['game.presentation']),
    'EndLoadAllDebugLog': ('CEcKXnXKqAjqVtqjfcZJ.TFWklfXKM7D1bS3eT4qL',
                           'EndLoadAllDebugLog():System.Void',
                           'the completion half of the debug-log load the project already requests',
                           ['debug.events', 'editor.utilities']),
    'RefreshExistDebugLogReport': ('TRoi1ujS2p4haJpOxsdr.ikpAEujSeL6wx9AZQoxk',
                                   'RefreshExistDebugLogReport(zkyp5kLHpC5XO6iOBEWt.eGxFVaLHQMt4t2piKEQn):System.Void',
                                   'a report refresh the project has never used',
                                   ['debug.events', 'editor.utilities']),
}
# Not Miliastra interfaces. Recorded with the reason so the denominator stops counting them,
# rather than silently dropping them.
OPERATION_NOT_AN_INTERFACE = {
    'GetCursorPos': 'user32 P/Invoke declaration; absent from the assembly as a method',
    'GetForegroundWindow': 'user32 P/Invoke declaration; absent from the assembly as a method',
    'GetKeyboardLayout': 'user32 P/Invoke declaration; absent from the assembly as a method',
    'GetWindowThreadProcessId': 'user32 P/Invoke declaration; absent from the assembly as a method',
    'ShowToolTipWhenTrimmed': 'WPF attached-property getter/setter pair; a display helper, not a business action',
}


def read(path):
    return (ROOT / path).read_text(encoding='utf-8-sig')


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_lines(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def link(path, label='证据'):
    # closeout is four directories below the repository root.
    return f'[{label}](../../../../{path.replace(chr(92), "/")})'


def main():
    facts = json.loads((OUT / 'facts.json').read_text(encoding='utf-8'))
    plan = json.loads(read(PLAN))['items']
    sources = [json.loads(s) for s in read(SOURCE).splitlines() if s.strip()]
    assert len(sources) == 1726 and len({r['sourceKey'] for r in sources}) == len(sources)
    original_source_count = len(sources)
    official_path = 'docs/offline-research/capability-catalog.json'
    delta_path = '.runtime/verification/docs-71-20260926/install-delta.json'
    chapters = json.loads(read(official_path))['entries']
    prefabs = [x for x in json.loads(read(delta_path))['added'] if '/OfficialPrefab/' in x['path']]
    assert len(chapters) == 207 and len(prefabs) == 245
    # 2026-09-28: a SECOND, NEWER official source was found already on disk and had never
    # been ingested. The cached index above is a 2026-09-15 snapshot of 207 chapters; this
    # live tree holds 218 documents, including 11 chapters absent from the cache. Ingesting
    # both, with distinct sourceKey prefixes, makes the U01 refresh traceable instead of a
    # research note. Neither tree can be re-fetched from here (no verified network).
    live_official_path = '.runtime/verification/interface-experiments-20260928/client-script-runtime/official-catalog.json'
    live_docs = []
    def _walk_official(nodes, depth=0):
        for node in nodes:
            live_docs.append(dict(node, depth=depth))
            _walk_official(node.get('children') or [], depth + 1)
    _walk_official(json.loads(read(live_official_path)))
    assert len(live_docs) == 218
    for doc in live_docs:
        identity = str(doc.get('path_id') or doc.get('real_id'))
        sources.append(dict(sourceKey='official-doc-live:' + identity, kind='official-doc-live',
                            source=live_official_path, sourceIdentity=identity,
                            title=doc.get('title'), data=doc))
    for entry in chapters:
        key = 'official-chapter:' + str(entry['ordinal'])
        sources.append(dict(sourceKey=key, kind='official-chapter', source=official_path,
                            sourceIdentity=entry['ordinal'], title=entry['title'], data=entry))
    for entry in prefabs:
        key = 'added-prefab:' + entry['path']
        sources.append(dict(sourceKey=key, kind='added-prefab', source=delta_path,
                            sourceIdentity=entry['path'], title=entry['path'], data=entry))
    assert len({r['sourceKey'] for r in sources}) == len(sources)
    assert len(plan) == 56 and len(facts['groups']) == 56
    groups = {g['id']: g for g in facts['groups']}
    assert set(groups) == {g['id'] for g in plan}
    hashes = {p: digest(p) for p in [SOURCE, PLAN, BRIDGE, CALL, SCENE, AUTHOR, META7, RESCAN, VM_INDEX, UI_MATCH, TPL_INDEX, TEXTMAP, '.runtime/verification/interface-experiments-20260928/interface-discovery/menu-handlers.json', official_path, live_official_path, delta_path,
                                    'GOAL.md', 'docs/UPDATE-REPAIR-20260924.md',
                                    'tools/authoring/build_closeout_inventory.py',
                                    'docs/research/7.1-experiment-plan/closeout/facts.json']}
    evidence = facts['evidence']
    for key, e in evidence.items():
        assert (ROOT / e['path']).is_file(), (key, e['path'])
        e['sha256'] = digest(e['path'])
        if e['path'].endswith('.json'):
            json.loads(read(e['path']))
    # Recheck material contradictory outcomes from the actual stored evidence.
    reopen = json.loads(read(evidence['reopen']['path']))
    assert reopen['reopenRoundtripVerified'] is False
    assert set(reopen['failures']) == {'IPC_ENDPOINT_CHANGED', 'ACCOUNT_MTIME_CHANGED'}
    assert json.loads(read(evidence['scripts']['path']))['liveCrudPassed'] is True
    assert json.loads(read(evidence['files']['path']))['liveFileAssociationAndPathChangePassed'] is True
    assert json.loads(read(evidence['scriptBatch']['path']))['liveBatchCreateDeletePassed'] is True
    assert json.loads(read(evidence['graph']['path']))['persistenceVerified'] is True
    resource = json.loads(read(evidence['resources']['path']))
    assert resource['completeResources'] == 2722 and resource['geometryVerified'] is False
    for p in plan:
        g = groups[p['id']]
        assert g['remaining'] and all(g['remaining'])
        assert all(k in evidence for k in g['evidenceIds'])
        g.update(title=p['title'], phase=p['phase'], fullyClosed=False,
                 previousCampaignStatus=p['executionStatus'])
        # Manual gameplay evidence never counts as automatic-control progress.
        if g['id'] == 'playtest.control':
            g['state'] = 'manual-evidence-only'
        elif g['id'] == 'verify.reopen':
            g['state'] = 'partial-with-failure'
        elif g['evidenceIds'] or p['executionStatus'] == 'partial':
            g['state'] = 'partial'
        else:
            g['state'] = 'no-group-acceptance'
        # Stable group IDs are the counting unit, not these editorial bullet points.
        g['acceptance'] = ('按原计划完成该组适用的合同、独立读回、持久/行为、参数失败与清理验收；'
                           '下列剩余项不因固定样例通过而删除。')

    registry = {}
    mappings = []

    def add(rid, kind, title, **extra):
        if rid not in registry:
            registry[rid] = dict(id=rid, kind=kind, title=title, sourceKeys=[],
                                 sourceSites=[], status='not-individually-accepted', **extra)
        return registry[rid]

    command_ids = defaultdict(list)
    # First index the candidate identities without declaring their contract proven.
    for s in sources:
        if s['kind'] != 'command-candidate':
            continue
        name = s['data']['command']
        old = s['data'].get('old') or {}
        service = old.get('service')
        if name.endswith('Service'):
            rid = 'service-name:' + name
            kind = 'service-name'
        elif service:
            rid = 'native-candidate:' + service + ':' + name
            kind = 'native-command-candidate'
        elif name == 'DoExportClientScript':
            # Exact producer call in the current source, not inferred from its name.
            src = 'tools/editor-bridge/Adapter/ClientScriptExportProbe.cs'
            assert '"beyondExportService", "DoExportClientScript"' in read(src)
            hashes[src] = digest(src)
            rid = 'native-candidate:beyondExportService:DoExportClientScript'
            kind = 'native-command-candidate'
        else:
            rid = 'unscoped-command-candidate:' + name
            kind = 'unscoped-command-candidate'
        rec = add(rid, kind, name, contractConfirmed=False)
        rec['legacyServiceHint'] = service
        rec['versionEvidence'] = '7.1 rescan candidate; legacy service/parameters are not current proof'
        if name == 'EndLoadAllDebugLog':
            rec['caution'] = '旧服务归属不作调用合同；先确定接收/完成方向'
        # 2026-09-28: an unscoped candidate is one with no service. That is not the same as
        # unattributed. If the FNV-1a dispatch rescan holds a HASH and a route status for it,
        # the record has a 7.1 comparison point and can leave the pending pile. Candidates
        # with neither hash nor status stay unscoped and say so - the client-script family is
        # in that group and is genuinely unresolved here.
        dispatch = OPERATION_DISPATCH.get(name)
        if dispatch and dispatch[1] is not None:
            rec['dispatchHashFn1a'] = dispatch[1]
            rec['routeStatus7_1'] = dispatch[2]
            rec['instructionHits7_1'] = dispatch[3]
            rec['dispatchEvidence'] = RESCAN
            rec['dispatchMechanism'] = 'FNV-1a hash; the command is not looked up by literal name'
            rec['attributionNote'] = ('service is still not established, but the command HAS a '
                                      '7.1 comparison point via the dispatch rescan')
            unresolved = False
        elif dispatch:
            rec['dispatchEvidence'] = RESCAN
            rec['attributionNote'] = ('present in the 51-command rescan but with NO hash and NO '
                                      'route status; still unscoped')
        command_ids[name].append(rid)

    for s in sources:
        k, d, sk = s['kind'], s['data'], s['sourceKey']
        relation, unresolved = 'identity-indexed', False
        if k == 'capability':
            rid = 'group:' + str(s['sourceIdentity'])
            r = add(rid, 'capability-group', s['title'])
        elif k == 'node-file':
            nid = d.get('node_id')
            assert nid is not None
            rid = 'node:7.1:' + str(nid)
            r = add(rid, 'node-definition', s['title'], nodeId=str(nid),
                    definitionChange=d.get('status'), editingAccepted=False,
                    behaviorAccepted=False, schemaEvidenceId='nodes',
                    groupIds=['graph.schema', 'graph.nodes'])
            r['status'] = 'schema-read-only'
            r['sourceSites'].append(d['path'])
        elif k == 'official-chapter':
            rid = 'official-chapter:cached:' + str(d.get('real_id') or d.get('path_id') or s['sourceIdentity'])
            r = add(rid, 'official-chapter', s['title'], freshness='2026-09-15 cached index; not refreshed now',
                    hierarchy=d.get('hierarchy'), groupIds=['discovery.registry'])
            unresolved = True
        elif k == 'added-prefab':
            rid = 'resource-file:7.1:' + d['path']
            r = add(rid, 'resource-file', d['path'], size=d['size'], runtimeResourceId=None,
                    parameterMappingPending=True, groupIds=['resource.coverage'])
        elif k == 'command-candidate':
            rid = command_ids[d['command']][0]
            r = registry[rid]
            # Unscoped means "no service". It does NOT mean unattributed: if the FNV-1a
            # dispatch rescan holds a hash and a route status, this record has a 7.1
            # comparison point and leaves the pending pile. Without a hash it stays pending.
            unresolved = r['kind'] == 'unscoped-command-candidate' and r.get('dispatchHashFn1a') is None
        elif k == 'service_route':
            rid = 'service-route:' + d['side'] + ':' + d['service']
            r = add(rid, 'service-route', d['service'], side=d['side'])
        elif k == 'message_route':
            rid = f"message:legacy-backend:{d['direction']}:{d['msg_id']}"
            r = add(rid, 'message-route', str(d['msg_id']), direction=d['direction'],
                    perspective='legacy backend (not inferred editor direction)',
                    purpose=d.get('purpose'))
        elif k == 'channel':
            rid = f"channel:{d['direction']}:{d['msg_id']}:{d['channel']}"
            r = add(rid, 'channel', d['channel'], direction=d['direction'])
        elif k == 'ui_template':
            rid = 'ui-template:legacy:' + d['template']
            r = add(rid, 'ui-template', d['template'],
                    presentIn7_1=True, resolutionEvidence=[TPL_INDEX, '.runtime/verification/docs-71-20260926/annotated-71'])
            r['resolutionNote'] = ('the Template_* literal is present in the 7.1 annotated corpus; '
                                   'the panel exists. What it renders is not established here.')
            relation = 'template-present-in-7.1'
            unresolved = False
        elif k == 'ui_element':
            # Owner is essential: vmText in different classes is not one control.
            identity = [d.get('owner_class'), d.get('element'), d.get('kind')]
            rid = 'ui-control:legacy:' + ':'.join(str(x) for x in identity)
            if not all(identity):
                rid += ':' + str(s['sourceIdentity'])
            r = add(rid, 'ui-control', f"{d.get('owner_class')}.{d.get('element')}")
            resolved = UI_ELEMENT_EXACT.get(d.get('owner_class'))
            if resolved:
                owner_7_1, element_count, tier = resolved
                r['resolvedOwner7_1'] = owner_7_1
                r['resolutionMethod'] = ('vm* control names survive the 7.1 rebuild unmangled; the 7.1 '
                                         'type that declares EVERY element of this old class, and the only one '
                                         'that does, is the match. Set containment, not a similarity score.')
                r['resolutionEvidence'] = [VM_INDEX, UI_MATCH]
                r['recordedElementCount'] = element_count
                r['evidenceTier'] = tier
                r['resolutionLimit'] = ('identity only: which 7.1 control this is. backend_command is still '
                                        'NULL for every ui_element record, so which BUSINESS ACTION the control '
                                        'triggers remains open - this closes the class half of U06, not the '
                                        'action half.')
                relation = 'owner-identified-in-7.1'
                unresolved = False
            else:
                r['resolutionStatus'] = ('no exact 7.1 owner by element containment; either ambiguous '
                                         '(more than one candidate, or partial coverage) or no candidate')
                unresolved = True
        elif k == 'user_operation':
            op_id = str(d.get('op_id') or s['sourceIdentity'])
            rid = 'user-operation:legacy:' + op_id
            r = add(rid, 'user-operation', d.get('name_zh') or s['title'],
                    presentIn7_1=op_id in USER_OP_DISPATCH,
                    possibleAliasIds=command_ids.get(d.get('backend_command'), []))
            handler = UI_ACTION_HANDLER.get(op_id)
            if handler:
                owner_cls, grp, lbl, hname, tgts = handler
                r.update(menuOwnerClass=owner_cls, menuGroup=grp, menuLabel=lbl,
                         frontendHandler=hname, dispatchTargets=tgts,
                         actionEvidence=['.runtime/editor-catalog/resolved/'],
                         actionNote=('the menu item, its handler and the dispatch method it calls are identified '
                                     'from the resolved corpus, where the decompiler writes each obfuscated '
                                     'call target as a comment. The BACKEND command is not identified here - the '
                                     'dispatch class is control-flow flattened and was not traced.'))
                relation = 'frontend-action-identified'
            resolved_cmds = USER_OP_BACKEND_COMMAND.get(op_id)
            if resolved_cmds:
                r['backendCommands'] = list(resolved_cmds)
                r['backendCommandEvidence'] = ['.runtime/editor-catalog/resolved/',
                    '.runtime/verification/interface-experiments-20260928/interface-discovery/U06-BACKEND-COMMANDS.json']
                r['backendCommandNote'] = ('the command name is an ARGUMENT to the producer send, reached by '
                    'menu item -> handler -> dispatch method -> send. Some are literals and some are '
                    'XOR-folded string ids. A resolved name is an IDENTITY, not proof the command works.')
                relation = 'backend-command-resolved'
                unresolved = False
            if op_id in USER_OP_DISPATCH:
                svc, h, status = USER_OP_DISPATCH[op_id]
                r.update(legacyServiceHint=svc, dispatchHashFn1a=h, routeStatus7_1=status,
                         backendCommandHint=d.get('backend_command'),
                         dispatchEvidence=RESCAN,
                         resolutionNote='the operation already recorded a backend command; it now has a 7.1 comparison point')
                relation = 'backend-command-has-7.1-comparison'
                unresolved = False
            elif not handler:
                r['resolutionNote'] = ('no recorded backend command and no menu group extracted. '
                                       'reach=' + str(d.get('reach')))
                unresolved = True
        elif k == 'feature':
            slug = d.get('slug') or str(s['sourceIdentity'])
            rid = 'feature:legacy:' + slug
            r = add(rid, 'feature', d.get('name_zh') or s['title'],
                    presentIn7_1=slug in FEATURE_DISPATCH)
            if slug in FEATURE_DISPATCH:
                svc, h, status = FEATURE_DISPATCH[slug]
                r.update(legacyServiceHint=svc, dispatchHashFn1a=h, routeStatus7_1=status,
                         backendCommandHint=d.get('name_en'), dispatchEvidence=RESCAN)
                relation = 'backend-command-has-7.1-comparison'
                unresolved = False
            else:
                unresolved = True
        elif k == 'shortcut':
            key = d.get('action_key') or s['sourceIdentity']
            rid = 'shortcut:legacy:' + str(key)
            label = SHORTCUT_LABEL_7_1.get(key)
            r = add(rid, 'shortcut', label or d.get('action_zh') or d.get('action_key') or s['title'],
                    presentIn7_1=label is not None,
                    label7_1=label,
                    resolutionEvidence=TEXTMAP if label else None)
            if label:
                r['resolutionNote'] = 'the shortcut key carries a real 7.1 label; the key binding itself is not decoded here'
                relation = 'label-present-in-7.1'
                unresolved = False
            else:
                r['resolutionNote'] = ('no 7.1 label. Fifteen of these keys begin with "!" - a marker '
                                       'convention, not a missing key; not attributed either way.')
                unresolved = True
        elif k == 'operation':
            name = d['op_name']
            if name in OPERATION_RESOLVED:
                owner, signature, note, group_ids = OPERATION_RESOLVED[name]
                rid = 'operation:legacy:' + name
                r = add(rid, 'operation-name', name, resolvedTo=owner, resolvedSignature=signature,
                        resolutionEvidence=META7, resolutionNote=note, groupIds=group_ids,
                        possibleAliasIds=command_ids.get(name, []))
                relation = 'resolved-to-7.1-method'
                unresolved = False
            elif name in OPERATION_NOT_AN_INTERFACE:
                rid = 'operation:legacy:' + name
                r = add(rid, 'operation-name', name, notAnInterface=True,
                        notAnInterfaceReason=OPERATION_NOT_AN_INTERFACE[name],
                        resolutionEvidence=META7)
                relation = 'not-a-business-interface'
                unresolved = False
            elif name in OPERATION_DISPATCH:
                legacy_service, dispatch_hash, route_status, instruction_hits = OPERATION_DISPATCH[name]
                rid = 'operation:legacy:' + name
                r = add(rid, 'operation-name', name,
                        legacyServiceHint=legacy_service, dispatchHashFn1a=dispatch_hash,
                        routeStatus7_1=route_status, instructionHits7_1=instruction_hits,
                        dispatchEvidence=RESCAN,
                        dispatchMechanism='FNV-1a hash; the command is not looked up by literal name',
                        possibleAliasIds=command_ids.get(name, []),
                        attributionNote='service, hash and route status come from the FNV-1a rescan; '
                                        'the same command also appears as a source command-candidate, '
                                        'linked via possibleAliasIds and deliberately NOT merged')
                relation = 'attributed-via-fnv1a-dispatch-rescan'
                unresolved = False
            else:
                # No literal 7.1 method AND no entry in the dispatch rescan. Still NOT absence.
                rid = 'operation:legacy:' + name
                r = add(rid, 'operation-name', name,
                        possibleAliasIds=command_ids.get(name, []),
                        nameLookup='no-literal-7.1-method; not in the 51-command dispatch rescan')
                unresolved = True
        elif k == 'official-doc-live':
            rid = 'official-doc:live:' + str(d.get('path_id') or d.get('real_id') or s['sourceIdentity'])
            r = add(rid, 'official-document', s['title'],
                    officialUpdatedAt=d.get('updated_at'), docType=d.get('doc_type'),
                    treeDepth=d.get('depth'), groupIds=['discovery.registry'])
            unresolved = True
        elif k == 'live-node-category':
            rid = 'node-category:' + str(s['sourceIdentity'])
            r = add(rid, 'node-category', str(s['sourceIdentity']), count=d.get('count'))
            relation = 'aggregate-not-additional-nodes'
        else:
            raise ValueError(k)
        r['sourceKeys'].append(sk)
        r['sourceSites'].append(s['source'])
        mappings.append(dict(sourceKey=sk, sourceKind=k, source=s['source'], title=r['title'],
                             sourceIdentity=s['sourceIdentity'], registryId=rid,
                             relation=relation, businessMappingPending=unresolved,
                             reason=('仅来源身份或候选名；缺当前业务归属/动作合同，不自动与同名项合并'
                                     if unresolved else '身份已归档；接口合同与实测状态另算')))

    # Existing project routes: source-level enumeration, never a live invocation.
    bridge = read(BRIDGE)
    assert len(re.findall(r'switch\s*\(op\)', bridge)) == 1
    bridge_cases = re.findall(r'case "([^"]+)":', bridge)
    assert len(bridge_cases) == len(set(bridge_cases))
    call_ops = re.findall(r"'([^']+)'", re.search(r'\[ValidateSet\((.*?)\)\]', read(CALL), re.S).group(1))
    assert set(call_ops) == set(bridge_cases) - {'author-graph'}
    for op in bridge_cases:
        r = add('project:bridge:' + op, 'project-route', op, surface='bridge',
                containerOnly=op == 'author-graph', aliases=[], evidenceIds=[])
        r['sourceSites'] = [BRIDGE + ':' + str(bridge[:bridge.index('case "' + op + '":')].count('\n') + 1)]
        if op in call_ops:
            r['aliases'].append('call-bridge.ps1 -Operation ' + op)
        r['status'] = 'source-route-only'
    tree = ast.parse(read(AUTHOR))
    actions = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'GRAPH_ACTIONS' for t in n.targets))
    for alias, action in actions.items():
        r = add('project:author-graph:' + action, 'project-route', action, surface='author-graph',
                containerOnly=False, aliases=['author.py graph ' + alias], evidenceIds=[])
        r['sourceSites'] = [AUTHOR + ':32', BRIDGE]
        r['status'] = 'source-route-only'
    registry['project:bridge:catalog']['aliases'].append('author.py graph catalog')
    scene_tree = ast.parse(read(SCENE))
    parser_fn = next(n for n in scene_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_parser')
    scene_ops = next(ast.literal_eval(n.iter) for n in ast.walk(parser_fn)
                     if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'name')
    for op in scene_ops:
        r = add('project:scene:' + op, 'project-route', op, surface='scene',
                containerOnly=False, aliases=['scene_cli.py ' + op], evidenceIds=[])
        r['sourceSites'] = [SCENE]
        r['status'] = 'source-route-only'
    for op, alias in [('inspect', 'entity-inspect'), ('create', 'entity-create'), ('save', 'save')]:
        registry['project:scene:' + op]['aliases'].append('author.py ' + alias)
    for op in ('status', 'capabilities'):
        assert repr(op) in read(AUTHOR)
        r = add('project:author-local:' + op, 'project-route', op, surface='author-local',
                containerOnly=False, aliases=['author.py ' + op], evidenceIds=[])
        r['sourceSites'] = [AUTHOR]
        r['status'] = 'source-route-only'

    # Only attach existing bounded evidence to explicit operations; do not propagate
    # success to every route in a group, or across similar native command names.
    route_evidence = {
        'scene:inspect': ['observations'], 'scene:create': ['crud'],
        'scene:create-batch': ['batch'], 'scene:save': ['crud', 'graph'],
        'scene:reopen-current': ['reopen'],
        'bridge:catalog': ['observations'], 'bridge:node-definitions': ['nodes'],
        'bridge:node-definition-variants': ['nodes'], 'bridge:prefab-fields-page': ['resources'],
        'bridge:client-script-root': ['root'], 'bridge:create-client-script-probe': ['scripts'],
        'bridge:rename-client-script-probe': ['scripts'], 'bridge:delete-client-script-probe': ['scripts'],
        'bridge:create-client-script-file-probe': ['files'],
        'bridge:set-client-script-file-probe-path': ['files'],
        'bridge:create-client-script-batch-probe': ['scriptBatch'],
        'bridge:delete-client-script-batch-probe': ['scriptBatch'],
        'bridge:export-client-script-probe': ['scriptExport'],
        'bridge:add-client-script-variable-probe': ['variables'],
        'bridge:delete-client-script-variable-probe': ['variables'],
        'bridge:add-client-script-int-variable-probe': ['reset'],
        'bridge:reset-client-script-variable-type-probe': ['reset'],
    }
    for action in actions.values():
        route_evidence['author-graph:' + action] = ['graph']
    for tail, eids in route_evidence.items():
        r = registry['project:' + tail]
        r['evidenceIds'] = eids
        r['status'] = 'related-bounded-evidence'
        r['routeInvocationIndependentlyProven'] = False
    registry['project:scene:reopen-current']['status'] = 'latest-acceptance-failed'
    for r in registry.values():
        r['sourceSites'] = sorted(set(r['sourceSites']))
        r['sourceKeys'] = sorted(set(r['sourceKeys']))
        r['fullyAccepted'] = False
    assert len({r['nodeId'] for r in registry.values() if r['kind'] == 'node-definition'}) == 810
    assert all(m['registryId'] in registry for m in mappings)
    assert sum(len(r['sourceKeys']) for r in registry.values()) == len(sources)
    source_registry_ids = {m['registryId'] for m in mappings}
    explicit_routes = [r for r in registry.values() if r['kind'] == 'project-route']
    summary = dict(
        schemaVersion=1, asOf=facts['asOf'], generatedUtc=datetime.now(timezone.utc).isoformat(),
        mode='existing-evidence-only; no live calls', gameVersionEvidence='7.1',
        phases=15, capabilityGroups=56, fullyClosedGroups=0,
        groupStates=dict(Counter(g['state'] for g in groups.values())),
        originalSourceRecords=original_source_count, supplementalSourceRecords=len(sources)-original_source_count,
        totalSourceRecords=len(sources), sourceRecordsAccountedFor=len(mappings),
        operationsResolvedToMethod=len(OPERATION_RESOLVED),
        operationsAttributedViaDispatchRescan=len(OPERATION_DISPATCH),
        uiElementsOwnerIdentifiedIn7_1=sum(
            1 for s in sources if s['kind'] == 'ui_element'
            and (s['data'].get('owner_class') in UI_ELEMENT_EXACT)),
        templatesConfirmedPresentIn7_1=len(UI_TEMPLATE_CONFIRMED),
        templatesNewIn7_1NotInOldBuild=len(TEMPLATES_NEW_IN_7_1),
        shortcutsWithLabelIn7_1=len(SHORTCUT_LABEL_7_1),
        userOperationsWithDispatchComparison=len(USER_OP_DISPATCH),
        userOperationsWithFrontendActionIdentified=len(UI_ACTION_HANDLER),
        userOperationsWithBackendCommandResolved=len(USER_OP_BACKEND_COMMAND),
        featuresWithDispatchComparison=len(FEATURE_DISPATCH),
        uiElementsStillPending=sum(
            1 for s in sources if s['kind'] == 'ui_element'
            and (s['data'].get('owner_class') not in UI_ELEMENT_EXACT)),
        commandCandidatesWithDispatchComparison=sum(
            1 for v in OPERATION_DISPATCH.values() if v[1] is not None),
        operationsReclassifiedNotAnInterface=len(OPERATION_NOT_AN_INTERFACE),
        officialChapterOccurrences=len(chapters), officialDocumentsLive=len(live_docs),
        addedPrefabFiles=len(prefabs),
        resourceFilesPendingRuntimeIdMapping=len(prefabs),
        sourceIdentityRecords=len(source_registry_ids),
        exactIdentityDuplicatesMerged=len(sources)-len(source_registry_ids),
        sourceRecordsPendingBusinessMapping=sum(m['businessMappingPending'] for m in mappings),
        nodeDefinitions=810, perNodeEditingFullyAccepted=0, perNodeBehaviorFullyAccepted=0,
        nodeAcceptanceCountingNote='零表示本清单没有逐定义独立完整验收；固定MVP组合证据保留在组内，不推定节点从未执行',
        projectRoutes=len(explicit_routes),
        projectLeafRoutes=sum(not r['containerOnly'] for r in explicit_routes),
        projectRouteContainers=sum(r['containerOnly'] for r in explicit_routes),
        projectRoutesBySurface=dict(Counter(r['surface'] for r in explicit_routes)),
        projectRouteEvidenceStates=dict(Counter(r['status'] for r in explicit_routes)),
        registryKinds=dict(Counter(r['kind'] for r in registry.values())),
        scopeGaps=len(facts['scopeGaps']), evidenceFiles=len(evidence),
        canonicalBusinessApiTotal=None, canonicalContractsComplete=False,
        denominatorSealed=False, totalCompletionPercent=None,
        checks=dict(sourceKeysUnique=True, sourceCoverageComplete=True, groupIdsMatchPlan=True,
                    nodeIdsUnique=True, allEvidencePathsExist=True, jsonEvidenceParsed=True,
                    bridgeCliMatchesDispatch=True, aliasesNotDoubleCounted=True,
                    noInheritedFullAcceptance=True, goalSha256=digest('GOAL.md')),
        inputHashes=hashes,
    )
    facts['groups'] = [groups[p['id']] for p in plan]
    # Preserve hand-edited facts input; the enriched file is generated.
    write_json(OUT / 'closure.json', facts)
    write_json(OUT / 'summary.json', summary)
    write_lines(OUT / 'registry.jsonl', sorted(registry.values(), key=lambda r: r['id']))
    write_lines(OUT / 'source-map.jsonl', mappings)
    write_lines(OUT / 'pending-mapping.jsonl', [m for m in mappings if m['businessMappingPending']])
    entry_lines = ['# 已枚举工程操作', '',
                   '源码范围：BridgeServer主分发、author图动作、scene_cli子命令、author本地命令。',
                   '139个路由记录含1个分发容器；138个叶子操作不是138个已验收官方接口。包装别名不重复计数。',
                   '相关证据不等于该包装入口独立实测；固定探针不能直接作为通用工具调用。', '',
                   '| 稳定ID | 操作/别名 | 证据状态 | 范围及来源 |', '| --- | --- | --- | --- |']
    labels = {'source-route-only': '仅源码入口', 'related-bounded-evidence': '相关受限证据',
              'latest-acceptance-failed': '当前验收失败'}
    for r in sorted(explicit_routes, key=lambda x: x['id']):
        proof = '；'.join(link(evidence[e]['path'], evidence[e]['scope']) for e in r['evidenceIds'])
        site = '；'.join(link(x.split(':')[0], x) for x in r['sourceSites'])
        title = '；'.join(r['aliases']) or r['title']
        entry_lines.append(f"| `{r['id']}` | {title} | {labels[r['status']]}{'（容器）' if r['containerOnly'] else ''} | {proof or site} |")
    (OUT / 'ENTRIES.md').write_text('\n'.join(entry_lines)+'\n', encoding='utf-8')

    state_zh = {'partial': '部分实证', 'partial-with-failure': '部分实证/当前失败',
                'manual-evidence-only': '仅人工触发证据', 'no-group-acceptance': '未形成组级验收'}
    lines = ['# 全项目收口清单', '',
             '更新时间：2026-09-28。只整理已存在的7.1及历史证据，没有新增实机实验。', '',
             '**这份清单固定已知范围、证据和剩余工作；官方全部接口的总量尚未封口。**', '',
             '## 计数口径', '',
             '| 对象 | 准确数量 | 当前含义 |', '| --- | ---: | --- |',
             '| 阶段 / 能力组 | 15 / 56 | 整组全范围验收完成0；固定样例不清空通用剩余项 |',
             f"| 来源记录 | {len(sources)} | 原1726＋官方章节{len(chapters)}＋官方文档现读{len(live_docs)}＋新增预制文件{len(prefabs)}；不是API数 |",
             f"| 全部来源身份去重后 | {len(source_registry_ids)} | 只合并同类型、同命名空间、同身份；共移除{summary['exactIdentityDuplicatesMerged']}条重复身份 |",
             f"| 仍待业务归属的来源记录 | {summary['sourceRecordsPendingBusinessMapping']} | 已编号，但名称/控件/快捷键不能直接当业务接口 |",
             f"| 当前显式工程路由 | {len(explicit_routes)} | {summary['projectLeafRoutes']}个叶子路由＋1个author-graph分发容器；包装别名不再加一次 |",
             '| 节点定义 | 810 | 定义读取已覆盖；逐节点编辑/运行完整验收未建立，固定MVP证据单列 |',
             '| 资源目录字段 | 2722 | 两快照合并、旧字段未重验；不是2722种资产行为已验 |',
             f"| 已挂接证据文件 | {len(evidence)} | 文件数不是完成接口数 |",
             '| 官方业务接口总数 / 总完成率 | 未知 | 禁止将不同层级相加或把未知项删出分母 |', '',
             '### 能力组状态', '']
    for state, count in summary['groupStates'].items():
        lines.append(f'- {state_zh[state]}：{count}组。')
    lines += ['', '早期固定MVP、基本节点图和批量创建已补回，因此这里与旧coverage.json的15部分/41待验不相同。'
              '“未形成组级验收”不表示没有源码或研究。“逐节点完整验收0”不表示旧游戏没有运行任何节点。', '',
              '## 56组逐项收口', '',
              '每行稳定ID是能力组。剩余检查项是工作说明，不作为新增API数量。每组均须满足原计划适用的独立读回、持久/行为、参数失败和清理要求。', '',
              '| ID / 阶段 | 能力 | 状态与已验证范围 | 剩余收口项 | 证据 |',
              '| --- | --- | --- | --- | --- |']
    for g in facts['groups']:
        refs = '、'.join(link(evidence[e]['path'], e) for e in g['evidenceIds']) or '仅来源/待验'
        lines.append(f"| `{g['id']}` / {g['phase']} | {g['title']} | {state_zh[g['state']]}；{g['verifiedScope']} | {'；'.join(g['remaining'])} | {refs} |")
    lines += ['', '## 不能隐藏的总量缺口', '', '| ID | 缺口 | 处置 |', '| --- | --- | --- |']
    for gap in facts['scopeGaps']:
        count = f"（计划引用{gap['knownReferenceCount']} {gap['unit']}）" if 'knownReferenceCount' in gap else ''
        lines.append(f"| {gap['id']} | {gap['title']}{count} | {gap['reason']} |")
    lines += ['', '### 操作名归属（2026-09-28 离线核对，未调用任何接口）', '',
              f'44条 operation 记录按**精确名**在7.1程序集元数据中查证：**{len(OPERATION_RESOLVED)}条是真实方法**'
              f'（含完整签名与所属类型），**{len(OPERATION_NOT_AN_INTERFACE)}条不是业务接口**'
              '（4条为 Win32 P/Invoke 声明，1条为 WPF 附加属性显示辅助），其余为**未命中而非不存在** —— '
              '本工程已记录部分命令按 FNV-1a 哈希派发（FocusEditObj 为已验证样例），精确名查不到不能推出不存在。', '',
              '音频为一整个类型 `X5uvRfQTGYih6DgKn6gp.hXZ8d1QTaWJ3qNq8XOSK`：PlayMusic / PlaySoundEffect 各两个重载及 '
              'Stop，是**全程序集中唯一带多个 float 参数的方法**；该类型尚未纳入绑定配置。对象管理器 '
              '`RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx` **已绑定**，其上另有 DeletePCGInstance / '
              'ModifyPCGInstanceName / ModifyPrefabName 三个未使用方法，可沿用 CRUD 探针已验证的同一调用方式。', '',
              '另以**签名**（≥3个float且≥1个整数）对全部115067个方法做了一次不依赖命名的检索，只命中上述三个音频方法：'
              '**编辑器程序集中不存在任何变换 setter**，该否定不依赖任何命名。', '',
              f'**按哈希而非按名字查证（本条是本工程「搜不到不能推出不存在」教训的直接应用）**：'
              f'operation 记录来自前端库，本身不带服务。上一轮按**精确名**查程序集元数据：8条命中方法、5条非接口，'
              f'其余未命中。**但工具用错了** —— 本工程已记录部分命令按 **FNV-1a 哈希**派发，名字查不到只是未命中。',
              '',
              '先做**正向对照**：用本工程自己的 fnv1a 独立重算 rescan 里记录的全部 32 个命令哈希，**32/32 全部吻合**，'
              '确认工具有效。再用该工件复查：**其余 operation 中有 28 条本就有归属**（服务、FNV-1a 哈希、7.1 路由状态），'
              f'证据一直躺在 `{RESCAN}` 里，只是本清单从未对它按 operation 取用。',
              '',
              f'这 28 条按「服务＋哈希＋路由状态」记为已归属，**未做合并**：同一条命令在 source 里另有带服务的 '
              '`command-candidate` 记录，二者通过 possibleAliasIds 关联而不并成一条 —— 本工程规则是**仅凭名字相同不得合并**。'
              f'结果：待归属 operation 由 44 → 3（所余 3 条：RequestTypeUrl / SerializeObject / SetFocus，'
              '既无字面方法也不在派发表中，仍为**未命中而非不存在**）。', '',
              '### ui_element 归属：换一个字段就解开了（2026-09-28 离线核对，未调用任何接口）', '',
              '这 395 条钉在**旧构建的混淆类名**上，而该名字在 7.1 里按命名空间、完整名、前缀三种口径**都不存在** —— '
              '一度据此认为它们没有 7.1 对应物。**但这个结论只对 class 字段成立。**', '',
              '**`vm*` 控件名从未被混淆。** `vmText`、`vmFilter`、`vmBtnClearLog` 等 238 个名字在 7.1 重建时**保留了原名**，'
              '所以应该用 **element 字段**去定位，而**根本不必去解那个类名映射问题**。', '',
              '方法用**集合包含**而非相似度：只有当某个 7.1 类型声明了旧类**全部**已记录元素、**且仅它一个**满足时，'
              '才算精确命中。并列或部分覆盖的一律留待归属。每条命中带证据档位：'
              f'**strong**（旧类有≥3个元素）{len([1 for v in UI_ELEMENT_EXACT.values() if v[2]=='strong'])}个类、'
              f'**medium**（2个）{len([1 for v in UI_ELEMENT_EXACT.values() if v[2]=='medium'])}个类、'
              f'**weak**（1个）{len([1 for v in UI_ELEMENT_EXACT.values() if v[2]=='weak'])}个类 —— '
              'weak 档**单列**，不并入 strong。', '',
              f'结果：**395 → 已归属 {sum(1 for s in sources if s["kind"]=="ui_element" and s["data"].get("owner_class") in UI_ELEMENT_EXACT)} 条**'
              f'（其余 {sum(1 for s in sources if s["kind"]=="ui_element" and s["data"].get("owner_class") not in UI_ELEMENT_EXACT)} 条中，'
              '97 条为并列或部分覆盖，38 条无任何候选）。已抽查三个命中的 7.1 类型并读回其声明，确为真实成员。', '',
              '**边界必须写明**：这一步解的是**身份**——这条记录对应 7.1 的哪个控件。'
              '`backend_command` 对全部 395 条**仍为 NULL**，即**控件触发哪个业务动作仍未解**。'
              '**这关闭的是 U06 的类这一半，不是动作那一半。**', '',
              '### 其余四堆（2026-09-28 离线核对，未调用任何接口）', '',
              '| 堆 | 记录 | 已归属 | 依据 | 仍待归属 |',
              '| --- | ---: | ---: | --- | ---: |',
              f'| ui_template | 49 | 49 | 全部 49 个 `Template_*` 字面量在 7.1 annotated 语料中确认存在 | 0 |',
              f'| shortcut | 62 | {len(SHORTCUT_LABEL_7_1)} | 快捷键键在 7.1 TextMap 中有真实中文标签 | {62-len(SHORTCUT_LABEL_7_1)} |',
              f'| user_operation | 92 | {len(USER_OP_DISPATCH)} | 记录本身已带 backend_command，且该命令在 FNV 派发表中有 7.1 比较点 | {92-len(USER_OP_DISPATCH)} |',
              f'| feature | 80 | {len(FEATURE_DISPATCH)} | 同上，命令名在派发表中有比较点 | {80-len(FEATURE_DISPATCH)} |', '',
              f'**7.1 新增模板 2 个**（旧构建没有）：`{TEMPLATES_NEW_IN_7_1[0]}` 与 `{TEMPLATES_NEW_IN_7_1[1]}`。'
              '前者是**客户端脚本浏览器面板**，与 script.signals / ui.templates 直接相关。', '',
              '**一次失败的正向对照也要记**：ui_template 的第一次核查用了 `.runtime/editor-catalog/decomp`（只有 BeyondEditor 子树，14930 文件），'
              '得到 **0/49**，差一点写成"模板在 7.1 里不存在"。正确语料是 `.runtime/editor-catalog/annotated`（12375）与 '
              '`.runtime/verification/docs-71-20260926/annotated-71`（12955）—— 两个数字正好等于 `type-ranking.json` 里的 '
              '`oldTypes`/`newTypes`。**换对语料后 49/49 全部命中。**', '']
    lines += ['', '## 去重与验收规则', '',
              '- 节点按7.1定义ID去重；类别计数不是新增节点。控件必须带所属类；服务、消息、命令分开。',
              '- 工程入口按显式分发层＋动作编号；author的包装命令挂到实际入口。固定探针和通用命令不会仅凭功能相似就合并。',
              '- operation只有名字、没有服务时保留待归属；possibleAlias仅供调查，不能据此合并。旧库的class_candidate_commands不作为控件绑定证据。',
              '- 当前工程路由只证明源码中有明确入口；related-bounded-evidence表示相关功能有证据，不保证每个包装入口均独立调用。测试断言、47项检查、版本号和重复请求不计作接口。',
              '- 导出文件通过与保存重开、自动试玩、Lua执行分别记；旧人工重开通过与新自动重开失败同时保留。',
              '- 每次新发现必须追加来源及映射；只有待归属记录、合同缺口及外部来源缺口全部有依据处置，才可封口业务API分母。', '',
              '### U06 动作半边：菜单项 → 后端命令名（2026-09-29 离线核对，未调用任何接口）', '',
              '先前的判断是「派发类控制流平坦化，从派发方法到后端命令名是真正的逆向工作」。**那个判断错了。**', '',
              '**派发类不决定命令，它只是被交了一个命令。** 每个派发方法最后都调用同一个生产者发送 `Ikci0qkvMZX`，',
              '而**命令名就是那个调用的参数**。平坦化让代码难读，但它没有藏住决定 —— 因为没有决定可藏。', '',
              '| 菜单项 | 派发方法 | **后端命令** |', '| --- | --- | --- |',
              '| 打开 / 在局内查看（聚焦） | sM5KBF555gu | FocusEditObj、FocusPrefabInstance |',
              '| 删除 | zgVKB6OS1MZ | DeleteEditObj、DeletePrefab |',
              '| 应用 | NUpKBG9iyuD | ApplyPrefabInstanceChange |',
              '| 导出 | C6xKBZLdA0J | DoExport |', '',
              '服务通道由本工程自己的 `COMMAND-CHANNEL.md` 独立记录为 `YSDhqo1YVyx` = `beyondEditObjService`，',
              '其记载内容正是 DeleteEditObj / DeletePrefab / ModifyEditObjName / Focus* —— 与这里读出的一组完全吻合。', '',
              '**XOR 折叠常量已解开**：`--1347725427 ^ 0x50557993` = **119264**、`--506316066 ^ 0x1E2C1734` = **119318**，',
              '这两个是 string 表 ID，分别解析为 `ApplyPrefabInstanceChange` 与 `AddInstructionGraphForPrefab`。',
              '本工程自己的 `INTERFACE-INVENTORY.md:156` 已独立记录这三个 ID，**两处吻合**。这正是本工程记忆文件',
              '第 2 条错误的机制：`ApplyPrefabInstanceChange` 曾因名字被 XOR 折叠而被误判不存在。', '',
              '**删除项三重印证**：菜单处理器、派发方法的发送实参、以及本项目自己的有界删除（调用同一个 `zgVKB6OS1MZ`）。', '',
              '**仍未解**：改名 / 复制 / 查看引用 / 导入 四项的发送点本轮未解码，**记为未命中而非不存在**；',
              '更改阵营发送的是 UI 标签键而非命令名，**单列不强行解释**。', '',
              '## 接下来按清单推进', '',
              '1. 先处理U01—U07和pending-mapping中的记录，确认服务、方向、动作、别名和参数分支，封口业务接口总数。',
              '2. 实机任务恢复后解决自动重开与实际恢复，随后推进范围/尺寸、已有实体变换和通用图编辑。',
              '3. 脚本优先挂载运行与保存重开；试玩控制和当前run日志优先打通。其它系统按P06—P13依赖展开。',
              '4. dsh从已经验收的工具开始做需求到修正闭环；固定MVP和组合回归不替代逐项覆盖。', '',
              '## 机器清单', '',
              '- [ENTRIES.md](ENTRIES.md)：139个工程路由的逐项操作、包装别名、相关证据和限制。',
              '- [closure.json](closure.json)：56组当前范围、证据、剩余项及7项总量缺口。',
              '- [registry.jsonl](registry.jsonl)：稳定身份目录；每行带类型、来源、状态，不能把总行数当API数。',
              f'- [source-map.jsonl](source-map.jsonl)：原1726及补入{len(sources) - original_source_count}条来源的逐条去向。',
              '- [pending-mapping.jsonl](pending-mapping.jsonl)：尚待业务归属的来源键（含旧官方章节），可直接安排调查。',
              '- [summary.json](summary.json)：自动计数、输入哈希及完整性核对。',
              '- [facts.json](facts.json)：人工维护的范围及证据输入；不改旧原始验收。',
              '- 重新生成：`python tools/authoring/build_closeout_inventory.py`；仅本地读写清单，不连接游戏。', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ['inputHashes', 'checks', 'registryKinds']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
