"""Observed pixel descriptions for the current life product; no silent substitutions.

Generate evidence and review inputs only after the original pixels in the supplied
catalog have been viewed. Descriptions below were reviewed from original-review-02.
They do not claim official TextMap labels or native player UI acceptance.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
from catalog import ROOT,sha
from cli import new_output,write,relative

# Every choice is bound to the exact RGBA image that was actually viewed.
OBSERVED={
90001:('198a3658d338a09c272fb37eaf9101bd30769538f3380214035312f9ac219283','红色苹果，有短果柄和高光'),
90009:('9ad0b125a23f4b430c3d24bf791726c8c9af7bde2b399f3c83a995431ed66ac4','用细绳捆扎的一束金黄色麦穗'),
90027:('d9728fc65af3c60107c9b187d3ee830dc0d4b83d0e2d491084e63eb348391bf4','保留灰色鱼皮的橙红鱼肉切块；不是整条活鱼'),
90031:('1fb8fc69a208fd250e279dd925523a091eac90e3ac26b3d26e3432a864b6ffc4','纸上放着一堆带壳褐色坚果及一粒剖开白仁'),
90036:('4e5a0c0e58719397bb3f6ec5ed2b24e523dc0c80f736d6f324d2e6f8883a02ad','几块褐色尖棱状铁矿原石'),
90037:('ed311599e3258af43e2a0bdf57fd1f125e1575279b968efc6836f659e76063be','灰白金属色的碎矿石块；不是铸成的铁锭'),
90052:('b4ce3ebd878ab1514248d1efbe3f5e69195c100f82c0f9fc41287b08da2ded44','用细绳捆扎的牛皮纸方形包裹；不能看见内装物'),
100005:('aae76342d02f8632ee709deedcce76f6c1f16b7d3b08da1b50f45b41db2674c1','圆形金色硬币，正面为五角星；不是摩拉纹样'),
92002:('027f87aef53bd31a8dcda5b9064dfb6ef7201da0fb705563fbc449a3c24ddf2e','盘中浇橙色汁、带方块配料的炸整鱼；不是蒙德烤鱼外观'),
}
SPECS=[
('item.crop','新鲜作物',90009,'representative','当前道具泛指作物；麦穗可代表谷物，但不是所有作物，且鱼饵配方需产品明确使用谷物原料。'),
('item.seed','田园种子',90052,'representative','仅可表达种子包装；原图不含可见种子，不可称原作种子专用图。'),
('item.apple','苹果',90001,'exact','原图为苹果，原生 iconId 和资源名及像素均已核实。'),
('item.dish','蒙德烤鱼',92002,'mismatch','原图为浇汁炸鱼。要保持蒙德烤鱼语义就不能把它标为精确复刻；产品若选用必须明确承认代表性图标。'),
('item.ore','铁矿石',90036,'exact','原图为铁矿原石，原生资源 UI_ItemIcon_101001。'),
('item.ingot','铁锭',None,'unavailable','类别9所有已提取原料、物件和料理图中没有可确认的铁锭；90037是白色矿石，不能冒充。25个武器ID有同名像素版本，亦不是铁锭。'),
('item.fish','花鳉',90027,'mismatch','类别9表中没有 UI_ItemIcon_131000；90027是鱼肉切块，不能把活花鳉的图标宣称一致。产品可在捕获后明确加工成鱼肉，或保留代表性差异。'),
('currency.mora','田园币',100005,'representative','适合自定义金币；图案是五角星而非原作摩拉纹样。'),
('shop.template','测试交易配置',None,'not-applicable','交易模板不是 item/currency 图标属性对象，不应进入 v2 定义属性列表。'),
]

def generate(catalog,out):
    path=Path(catalog).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('PROJECT_CATALOG_REQUIRED')
    raw=path.read_bytes();catalog=json.loads(raw);index={r['iconId']:r for r in catalog['rows']}
    if catalog['kind']!='template-icon-original-catalog':raise ValueError('CATALOG_KIND')
    observations=[]
    for icon,(digest,description) in OBSERVED.items():
        row=index[icon]
        if not row['originalPixelsResolved'] or row['rgbaSha256']!=digest:raise ValueError('REVIEWED_ORIGINAL_PIXEL_CHANGED_'+str(icon))
        observations.append(dict(iconId=icon,observedSubject=description,rgbaSha256=digest,preview=row['preview'],resourcePath=row['resourcePath'],pngSha256=row['pngSha256']))
    choices=[];exact=[];proposed=[]
    for role,name,icon,status,reason in SPECS:
        row=dict(role=role,name=name,candidateIconId=icon,status=status,reason=reason,playerPixelsVerified=False)
        if icon:
            row.update(next(v for v in observations if v['iconId']==icon))
            review=dict(role=role,name=name,iconId=icon,rgbaSha256=row['rgbaSha256'],observedSubject=row['observedSubject'],match='exact' if status=='exact' else 'representative')
            if status=='exact':exact.append(review)
            else:review['semanticDecision']=''
            proposed.append(review)
        choices.append(row)
    out=new_output(out)
    data=dict(kind='template-icon-life-selection',catalog=relative(path),catalogSha256=sha(raw),choices=choices,
              observations=observations,exactRoleCount=len(exact),allProductSemanticsExact=False,
              requiresProductOwnerDecisions=True,nativeDispatched=False,playerPixelsVerified=False,
              absentSpecificAssets=['UI_ItemIcon_131000'],absenceScope='complete decoded native category9 table; not all installed textures')
    write(out/'selection.json',data)
    write(out/'exact-review.json',dict(catalogSha256=sha(raw),rows=exact))
    write(out/'proposed-review-requires-decisions.json',dict(catalogSha256=sha(raw),rows=proposed))
    lines=['# 当前生活系统图标核实','',f'原图目录：`{relative(path)}`。全部143个原生普通物品/货币条目已获取纹理候选，118个条目在当前已完成索引中只有同一像素；25个武器条目有多个不同像素版本，未自动选定。','',
           '|角色|实际名称|原生 iconId|核实结果|','|---|---|---:|---|']
    for row in choices:lines.append('|'+row['role']+'|'+row['name']+'|'+str(row['candidateIconId'] or '无')+'|'+row['status']+'：'+row['reason']+'|')
    lines+=['','`exact-review.json` 只含苹果、铁矿两项。其余有候选的角色写在 `proposed-review-requires-decisions.json`，representative 的 `semanticDecision` 故意为空，产品负责人必须作真实决定后才可绑定；工具不会自动改名或掩盖差异。铁锭没有已核实的相符候选，不能以白色矿石或武器图充数。','',
            '钓鱼当前消耗 item.crop，图标候选 90009 为麦穗；这不是独立鱼饵图。若产品另建鱼饵定义，需要另外明确配方与名称。商店模板不参与图标属性。图册中的“原图已提取”与玩家实际背包/商店显示分别验收。']
    (out/'selection.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return dict(selection=relative(out/'selection.json'),exact=len(exact),roles=len(choices),requiresProductOwnerDecisions=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    print(json.dumps(generate(a.catalog,a.out),ensure_ascii=False))
if __name__=='__main__':main()
