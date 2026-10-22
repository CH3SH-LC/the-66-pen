"""Strict formal-level identity and separately protected upgrade backups."""
from pathlib import Path
import re
from contract import require,sha

def level_number(value):
    return bool(re.fullmatch(r'[1-9][0-9]*',value)) and int(value)<=0xffffffff

def classify(recovery):
    targets=[item for item in recovery if item.get('target') is True]
    require(len(targets)==1,'EXACTLY_ONE_TARGET_RECOVERY_REQUIRED')
    target=Path(targets[0]['source']).resolve()
    root=target.parent.parent
    require(root.name=='Beyond_Local_Save_Level' and level_number(target.stem) and
            target.parent.name==target.stem and target.suffix=='.gil','FORMAL_TARGET_RECOVERY_REQUIRED')
    formal={};auxiliary=[];seen=set()
    for item in recovery:
        source=Path(item['source']).resolve()
        require(source not in seen and source.parent.parent==root and source.suffix=='.gil' and
                level_number(source.stem) and type(item.get('target')) is bool,'SAVE_RECOVERY_SOURCE_SET')
        seen.add(source)
        if source.parent.name==source.stem:
            kind='formal-level'
            require(source.stem not in formal,'DUPLICATE_FORMAL_LEVEL_RECOVERY')
            formal[source.stem]=item
        elif source.parent.name=='UpgradeBackup' and item['target'] is False:
            kind='auxiliary-upgrade-backup';auxiliary.append(item)
        else:
            raise ValueError('UNCLASSIFIED_RECOVERY_SOURCE:'+str(source))
        require(item.get('sourceKind',kind)==kind,'RECOVERY_SOURCE_KIND_MISMATCH')
    return formal,auxiliary

def auxiliary_unchanged(prepared,items):
    result=[]
    for item in items:
        source=Path(item['source']).resolve();backup=Path(item['backup']).resolve()
        expected=Path(prepared['run']).resolve()/'recovery'/('UpgradeBackup-'+source.name)
        require(backup==expected,'AUXILIARY_RECOVERY_PATH_MISMATCH')
        for file in (source,backup):
            for part in (file,*file.parents):
                require(part.exists() and not part.is_symlink() and
                        not (getattr(part.stat(),'st_file_attributes',0)&0x400),'AUXILIARY_REPARSE_OR_MISSING')
        require(sha(backup)==item['sha256'],'AUXILIARY_RECOVERY_CHANGED')
        current=sha(source)
        require(current==item['sha256'],'AUXILIARY_SOURCE_CHANGED')
        result.append(dict(source=str(source),backup=str(backup),sha256=current,
            scope='current-source-compared-with-pre-transform-backup',
            afterSaveSnapshotAvailable=False,unchangedAtVerification=True))
    return result
