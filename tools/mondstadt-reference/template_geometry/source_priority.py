"""Capture manifest and native conditional disk-source precedence, no runtime claim."""
import hashlib,json
from pathlib import Path
from sources import ROOT,OUTPUT,INSTALL,write_json

def capture():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    base=INSTALL/'YuanShen_Data';manifest=base/'Persistent/res_versions_persist';raw=manifest.read_bytes()
    inventory={x['remoteName']:x for x in [json.loads(line)for line in raw.splitlines()]};rows=[]
    data_manifest=base/'Persistent/data_versions_persist';data_raw=data_manifest.read_bytes()
    data_inventory={x['remoteName']:x for x in [json.loads(line)for line in data_raw.splitlines()]}
    sources={json.loads(p.read_text(encoding='utf8'))['sourcePath']for pattern in ['raw/*/source.json','raw-persistent-index/*/source.json']for p in OUTPUT.glob(pattern)}
    for text in sorted(sources):
        source=Path(text);parts=source.parts;start=parts.index('blocks');relative=Path(*parts[start:]).as_posix();entry=inventory.get(relative)
        manifest_kind='resource'
        if entry is None:entry=data_inventory.get(relative);manifest_kind='data'
        external=base/'Persistent/AssetBundles'/relative;streaming=base/'StreamingAssets/AssetBundles'/relative
        current=external if external.is_file()else streaming
        rows.append({'capturedPath':text,'manifestEntry':entry,'manifestKind':manifest_kind,'externalExists':external.is_file(),'streamingExists':streaming.is_file(),
            'diskPreferredPath':str(current),'capturedIsPreferred':source==current,'capturedBytes':source.stat().st_size,
            'manifestMatchesCapturedSize':entry is not None and source.stat().st_size==entry['fileSize'],
            'interpretation':'Historic base index retained separately'if source!=current else 'Preferred disk container exists'})
    result={'manifest':str(manifest),'manifestSha256':hashlib.sha256(raw).hexdigest(),'dataManifest':str(data_manifest),
        'dataManifestSha256':hashlib.sha256(data_raw).hexdigest(),'rows':rows,
        'nativeEvidence':[
            {'function':'0x7022350 CheckBlockExixt(languageCode,blockID,onlyStreaming,error)',
             'observations':['0x7022551..0x7022590 forms get_externalBundleDirectory path.',
                 '0x70225d1 skips external when onlyStreaming=true; otherwise 0x702264b checks external path attributes and 0x7022658 returns location0 if it exists.',
                 'Only after failure/skip,0x7022685 calls get_streamingBundleDirectory;0x70226cc IsFileExists and 0x70226f6 returns location1.',
                 'The earlier remote/download registry branch can return location2. No running loader state was inspected.']},
            {'function':'0x710ac70 GetBlockFile','observations':['Location0 selects get_externalBundleDirectory0x6de4300; location1 selects get_streamingBundleDirectory0x6de3ff0.']},
            {'function':'0x7015370 LoadResourceIndex(filename,onlyStreaming,append)','observations':['Explicit filename is supplied to AssetIndexDeserializer; append=false constructs fresh ResourceIndex, append=true reuses it. Native call site startup values are not asserted.']}],
        'indexPolicy':'Use manifest-validated Persistent index for offline current disk reference; retain Streaming index and compare every selected binding.',
        'runtimeIndexSelectionObserved':False,'forcedStreamingUnknown':True,
        'geometryConsequence':'All38 selected logical handle/bundle/offset bindings identical between both captured indexes. Selected geometry blocks have no competing Persistent copies.'}
    write_json(OUTPUT/'source-priority.json',result);print(json.dumps({'containers':len(rows),'nonPreferredCaptured':[x['capturedPath']for x in rows if not x['capturedIsPreferred']]}))

if __name__=='__main__':capture()
