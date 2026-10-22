"""Read-only, stable formal-save recovery copies made before a terrain write."""
from __future__ import annotations
from pathlib import Path
import time
from terrain_model import ROOT, artifact_path, digest, require

MAX_GIL_BYTES=32*1024*1024

def plain_path(value):
    lexical=Path(value).absolute()
    for part in (lexical,*lexical.parents):
        if part.exists() or part.is_symlink():
            require(not part.is_symlink() and not (getattr(part.lstat(),'st_file_attributes',0)&0x400),'REPARSE_SAVE_PATH')
    return lexical.resolve()

def formal_source(value,level):
    source=plain_path(value)
    official=(Path.home()/'AppData/LocalLow/miHoYo/原神/BeyondLocal').resolve()
    require(source.is_relative_to(official),'FORMAL_LEVEL_SAVE_REQUIRED')
    parts=source.relative_to(official).parts
    require(len(parts)==4 and parts[0].isdigit() and parts[1]=='Beyond_Local_Save_Level' and
            parts[2]==str(level) and parts[3]==f'{level}.gil','FORMAL_LEVEL_SAVE_REQUIRED')
    return source

def sibling_files(source):
    parent=source.parent.parent
    files=[]
    for path in sorted(parent.glob('*/*.gil')):
        # UpgradeBackup/<id>.gil and differently named extra files are not
        # formal levels. Classify the lexical path before resolving it; a
        # matching formal path must still pass the reparse/source checks.
        identifier=path.parent.name
        if not identifier.isascii() or not identifier.isdecimal() or str(int(identifier))!=identifier or path.name!=identifier+'.gil':
            continue
        path=plain_path(path)
        require(path.parent.parent==parent and path.stem.isdigit() and path.parent.name==path.stem,
                'UNCLASSIFIED_SIBLING_GIL_PATH')
        files.append(path)
    require(source in files and len({p.stem for p in files})==len(files),'TARGET_OR_SIBLING_SAVE_SET_INVALID')
    return files

def stable_bytes(path):
    previous=None;until=time.monotonic()+3
    while True:
        first=path.stat();require(first.st_size<=MAX_GIL_BYTES,'GIL_RECOVERY_SIZE_LIMIT')
        data=path.read_bytes();last=path.stat();stamp=(last.st_size,last.st_mtime_ns)
        if (first.st_size,first.st_mtime_ns)==stamp and len(data)==last.st_size:
            if previous==(stamp,data):return data
            previous=(stamp,data)
        else:previous=None
        require(time.monotonic()<until,'GIL_CHANGED_DURING_RECOVERY')
        time.sleep(.05)

def capture(run,source,level,expected_target_sha):
    run=artifact_path(run);source=formal_source(source,level)
    files=sibling_files(source);folder=run/'recovery';folder.mkdir(exist_ok=False)
    rows=[]
    for item in files:
        data=stable_bytes(item);sha=digest(data)
        if item==source:require(sha==expected_target_sha,'PLAN_SOURCE_CHANGED_DURING_RECOVERY')
        backup=folder/item.name
        with backup.open('xb') as f:f.write(data)
        require(digest(backup.read_bytes())==sha,'RECOVERY_COPY_CHANGED')
        rows.append({'levelId':int(item.stem),'source':str(item),'backup':str(backup),
                     'sha256':sha,'bytes':len(data),'target':item==source})
    require(files==sibling_files(source),'SIBLING_SET_CHANGED_DURING_RECOVERY')
    # A source read near the start cannot silently become stale while the other
    # sibling copies are made. These same formal hashes are also pinned at execute.
    for row in rows:
        require(digest(stable_bytes(Path(row['source'])))==row['sha256'],'SIBLING_CHANGED_DURING_RECOVERY')
    return {'schema':'terrain-save-recovery-v1','levelId':level,'source':str(source),
            'levelDirectory':str(source.parent.parent),'entries':rows}

def validate(run,recovery,level,source):
    run=artifact_path(run);source=formal_source(source,level)
    require(recovery.get('schema')=='terrain-save-recovery-v1' and recovery.get('levelId')==level and
            recovery.get('source')==str(source) and recovery.get('levelDirectory')==str(source.parent.parent),
            'RECOVERY_MANIFEST_REQUIRED')
    entries=recovery.get('entries');require(type(entries) is list and entries,'RECOVERY_ENTRIES_REQUIRED')
    result={}
    for item in entries:
        identifier=item['levelId'];require(type(identifier) is int and identifier>0 and str(identifier) not in result,'RECOVERY_DUPLICATE_LEVEL')
        original=formal_source(item['source'],identifier)
        require(original.parent.parent==source.parent.parent,'RECOVERY_SOURCE_DIRECTORY_CHANGED')
        expected=run/'recovery'/f'{identifier}.gil';backup=artifact_path(item['backup'])
        require(backup==expected,'RECOVERY_COPY_OUTSIDE_CARD')
        blob=backup.read_bytes()
        require(len(blob)==item['bytes'] and digest(blob)==item['sha256'],'RECOVERY_BACKUP_CHANGED')
        require(type(item.get('target')) is bool and item['target']==(original==source),'RECOVERY_TARGET_FLAG_INVALID')
        result[str(identifier)]=dict(item,blob=blob)
    require(str(level) in result and sum(item['target'] for item in result.values())==1,'RECOVERY_TARGET_MISSING')
    return result
