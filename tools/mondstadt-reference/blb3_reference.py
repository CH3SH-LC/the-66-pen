"""Pure-Python bounded read-only Blb3 metadata decoder for reference acquisition.

Format basis: pinned AnimeStudio BlbFile.cs/BlbUtils.cs. No game library, process,
network service, or downloaded executable is loaded. Public constant tables are
parsed as byte literals, never executed. Decoded payload extraction is separate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from reference_cli import digest, project_path, write_json
from regional_registration import SOURCE, relative

WORK=SOURCE/'source-chain-v5'
KEYFILE=WORK/'AnimeStudio_Crypto_CryptoHelper.cs'
INSTALL=Path('D:/games/Genshin Impact Game').resolve()


def tables():
    lock=json.loads((WORK/'anime-parser-source-lock.json').read_text(encoding='utf-8'))
    expected=next(r['sha256'] for r in lock['files'] if r['upstreamPath']=='AnimeStudio/Crypto/CryptoHelper.cs')
    if digest(KEYFILE)!=expected:raise ValueError('Pinned constant source SHA changed')
    text=KEYFILE.read_text(encoding='utf-8')
    sizes={'Blb3RC4Key':256,'Blb3SBox':1024,'Blb3ShiftRow':48,'Blb3Key':8,'Blb3Mul':8,
           'Blb3AESSBox':256,'Blb3AESShift':16,'GF256Exp':256,'GF256Log':256}
    result={}
    for name,size in sizes.items():
        m=re.search(r'\b'+name+r'\s*=\s*new byte\[\d*\]\s*\{([^}]+)\}',text)
        if not m:raise ValueError('Missing constant array '+name)
        parts=m.group(1).split(',');values=[int(s.strip(),0) for s in parts if s.strip()]
        if len(values)!=size or any(not 0<=v<=255 for v in values):raise ValueError('Invalid byte table '+name)
        result[name]=values
    return result


def aes_expand(key,t):
    box,shift=t['Blb3AESSBox'],t['Blb3AESShift'];keys=[0]*176
    keys[:16]=[key[s] for s in shift];offset=31
    for power in [1,2,4,8,16,32,64,128,27,54]:
        a=box[keys[offset-20]];b=box[keys[offset-16]]
        c=box[keys[offset-24]]^keys[offset-24]^power^keys[offset-31];d=box[keys[offset-28]]
        keys[offset-15]=c
        temp=a^keys[offset-20]^keys[offset-27];keys[offset-11]=temp
        a=b^keys[offset-16]^keys[offset-23];keys[offset-7]=a
        b=d^keys[offset-28]^keys[offset-19];keys[offset-3]=b
        c^=keys[offset-30];keys[offset-14]=c
        temp^=keys[offset-26];keys[offset-10]=temp
        a^=keys[offset-22];keys[offset-6]=a
        b^=keys[offset-18];keys[offset-2]=b
        c^=keys[offset-29];keys[offset-13]=c
        temp^=keys[offset-25];keys[offset-9]=temp
        a^=keys[offset-21];keys[offset-5]=a
        b^=keys[offset-17];keys[offset-1]=b
        keys[offset-12]=c^keys[offset-28]
        keys[offset-8]=temp^keys[offset-24]
        keys[offset-4]=a^keys[offset-20]
        keys[offset]=b^keys[offset-16]
        offset+=16
    return keys


def aes_transform(block,key,t):
    keys=aes_expand(key,t);state=list(block)
    def round_key(r):
        for i in range(4):
            for j in range(4):state[i*4+j]^=keys[i+j*4+r*16]
    def sub_shift():
        a=[v^t['Blb3AESSBox'][v] for v in state]
        state[:]=[a[i] for i in [0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]]
    def g2(x):return ((x<<1)^ (0x11b if x&128 else 0))&255
    round_key(0)
    for r in range(1,11):
        sub_shift()
        if r<10:
            for p in range(0,16,4):
                a=state[p:p+4]
                state[p:p+4]=[g2(a[i])^(g2(a[(i+1)%4])^a[(i+1)%4])^a[(i+2)%4]^a[(i+3)%4] for i in range(4)]
        round_key(r)
    return state


def decrypt_prefix(header,data,t):
    if len(header)!=16:raise ValueError('Blb3 nonce must be16 bytes')
    buf=bytearray(data);limit=min(128,len(buf))
    for i in range(min(16,limit)):buf[i]^=header[i]
    if limit<16:return bytes(buf)
    buf[:16]=bytes(aes_transform(buf[:16],header,t))
    if limit>16:
        s=t['Blb3RC4Key'].copy();key=[]
        for i in range(0,256,2):key.extend([buf[i&6],buf[(i+1)&7]])
        j=0
        for i in range(256):
            j=(j+s[i]+key[i])%256;s[i],s[j]=s[j],s[i]
        i=j=0
        for off in range(16,limit):
            i=(i+1)%256;j=(j+s[i])%256;s[i],s[j]=s[j],s[i]
            k=s[(s[j]+s[i])%256];mode=buf[i%8+8]%3
            buf[off]=(buf[off]^k) if mode==0 else ((buf[off]-k if mode==1 else buf[off]+k)&255)
    def mul(a,b):return 0 if not a or not b else t['GF256Exp'][(t['GF256Log'][a]+t['GF256Log'][b])%255]
    for iteration in range(3):
        vector=[t['Blb3Key'][j%8]^t['Blb3SBox'][(j%4*256)|mul(t['Blb3Mul'][j%8],buf[t['Blb3ShiftRow'][(2-iteration)*16+j]%16])] for j in range(16)]
        buf[:16]=bytes(vector)
    return bytes(buf)


def parse_metadata(data,container_size,header_size):
    if len(data)<56:raise ValueError('Decoded metadata too short')
    size,last,_,blob_offset,blob_size=struct.unpack_from('<IIIiI',data)
    comp,power=struct.unpack_from('<BB',data,20);block_count,node_count=struct.unpack_from('<ii',data,24)
    if not (28+header_size<=size<=container_size):raise ValueError(f'Decoded bundle size {size} inconsistent with container {container_size}')
    if not(0<block_count<=100000 and 0<=node_count<=100000 and 0<=power<=30 and comp<=9):raise ValueError('Decoded count/codec/power invalid')
    offsets=[p+struct.unpack_from('<q',data,p)[0] for p in (32,40,48)]
    bo,no,fo=offsets
    if not(0<=bo<=len(data)-block_count*4 and 0<=no<=len(data)-node_count*16 and 0<=fo<=len(data)-((node_count+31)//32)*4):raise ValueError('Metadata pointer out of bounds')
    cumulative=struct.unpack_from('<'+'I'*block_count,data,bo);blocks=[];old=0;expanded=0
    for i,end in enumerate(cumulative):
        u=last if i==block_count-1 else 1<<power;c=end-old
        if c<=0 or u<=0 or end>size:raise ValueError('Invalid compressed block range')
        blocks.append({'compressedOffset':28+header_size+old,'compressedSize':c,'uncompressedSize':u,
            'compressionType':0 if i>0 and c==u else comp,'uncompressedOffset':expanded})
        old=end;expanded+=u
    if 28+header_size+old>size:raise ValueError('Compressed payload exceeds bundle')
    nodes=[]
    for i in range(node_count):
        p=no+i*16;o,n=struct.unpack_from('<ii',data,p);ptr=p+8+struct.unpack_from('<q',data,p+8)[0]
        if not(0<=o<=expanded and 0<=n<=expanded-o and 0<=ptr<len(data)):raise ValueError('Node range out of bounds')
        end=data.find(b'\0',ptr,min(ptr+4096,len(data)))
        if end<0:raise ValueError('Node path lacks bounded terminator')
        path=data[ptr:end].decode('utf-8',errors='strict')
        flags=(struct.unpack_from('<I',data,fo+i//32*4)[0]>>(i%32))&1
        nodes.append({'offset':o,'size':n,'path':path,'serializedAsset':bool(flags)})
    return {'bundleSize':size,'uncompressedSize':expanded,'compressionType':comp,'blocks':blocks,'nodes':nodes,
            'metadataPointerBoundsValid':True,'blobOffset':blob_offset,'blobSize':blob_size}


def read_header(path,offset=0,t=None):
    if t is None:t=tables()
    with Path(path).open('rb') as stream:
        stream.seek(offset);prefix=stream.read(28)
        if len(prefix)!=28 or prefix[:4]!=b'Blb\x03':raise ValueError('Not Blb3 at requested offset')
        header_size,version=struct.unpack_from('<II',prefix,4)
        if header_size>4*1024**2 or header_size<56:raise ValueError('Metadata size outside bounded reader')
        encoded=stream.read(header_size)
    if len(encoded)!=header_size:raise ValueError('Short encoded metadata')
    decoded=decrypt_prefix(prefix[12:28],encoded,t)
    metadata=parse_metadata(decoded,Path(path).stat().st_size-offset,header_size)
    metadata.update(offset=offset,headerSize=header_size,formatVersionField=version,
        headerReadBytes=28+header_size,encodedHeaderSha256=hashlib.sha256(prefix+encoded).hexdigest(),
        decodedHeaderSha256=hashlib.sha256(decoded).hexdigest())
    return metadata,prefix[12:28],decoded


def lz4_block(data,expected):
    """Bounded raw LZ4 block decoder, including overlapping backreferences."""
    out=bytearray();p=0
    def length(n):
        nonlocal p
        if n==15:
            while True:
                if p>=len(data):raise ValueError('Truncated LZ4 length')
                b=data[p];p+=1;n+=b
                if b!=255:break
        return n
    while p<len(data):
        token=data[p];p+=1;n=length(token>>4)
        if p+n>len(data) or len(out)+n>expected:raise ValueError('LZ4 literal outside bounded output')
        out.extend(data[p:p+n]);p+=n
        if p==len(data):break
        if p+2>len(data):raise ValueError('Truncated LZ4 offset')
        offset=data[p]|data[p+1]<<8;p+=2
        if offset==0 or offset>len(out):raise ValueError('Invalid LZ4 backreference')
        n=length(token&15)+4
        if len(out)+n>expected:raise ValueError('LZ4 match exceeds expected output')
        for _ in range(n):out.append(out[-offset])
    if len(out)!=expected:raise ValueError('LZ4 output size mismatch')
    return bytes(out)


_CODEC=None
_CODEC_PROCESS=None
_CODEC_PIPE=None
def _oodle_native(data,expected):
    import ctypes
    global _CODEC
    if _CODEC is None:
        directory=WORK/'ooz-build-v2';receipt=json.loads((directory/'build-receipt.json').read_text(encoding='utf-8'))
        path=directory/'reference_codec.dll'
        if receipt['exitCode'] or digest(path)!=receipt['files']['reference_codec.dll']:raise ValueError('Built decoder integrity failed')
        _CODEC=ctypes.CDLL(str(path))
        _CODEC.reference_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
        _CODEC.reference_decompress.restype=ctypes.c_int
    if not 0<expected<=64*1024**2 or len(data)>64*1024**2:raise ValueError('Oodle bounds')
    src=ctypes.create_string_buffer(data,len(data)+64);dst=ctypes.create_string_buffer(expected+64)
    result=_CODEC.reference_decompress(src,len(data),dst,expected)
    if result!=expected:raise ValueError(f'Oodle decoded {result}, expected {expected}')
    return dst.raw[:expected]


def _codec_worker(pipe):
    """Pure codec child receives only byte buffers, never installation handles."""
    while True:
        try:data,expected=pipe.recv()
        except EOFError:return
        try:pipe.send((True,_oodle_native(data,expected)))
        except Exception as e:pipe.send((False,str(e)))


def oodle_block(data,expected):
    import os,multiprocessing
    global _CODEC_PROCESS,_CODEC_PIPE
    if os.environ.get('MONDSTADT_CODEC_ISOLATE')!='1':return _oodle_native(data,expected)
    if _CODEC_PROCESS is None or not _CODEC_PROCESS.is_alive():
        if _CODEC_PROCESS is not None:_CODEC_PROCESS.join(timeout=0)
        parent,child=multiprocessing.get_context('spawn').Pipe()
        _CODEC_PROCESS=multiprocessing.get_context('spawn').Process(target=_codec_worker,args=(child,),daemon=True)
        _CODEC_PROCESS.start();child.close();_CODEC_PIPE=parent
    try:
        _CODEC_PIPE.send((data,expected))
        if not _CODEC_PIPE.poll(30):raise ValueError('Isolated codec timed out')
        success,result=_CODEC_PIPE.recv()
        if not success:raise ValueError(result)
        return result
    except (EOFError,BrokenPipeError,ValueError) as e:
        if _CODEC_PROCESS.is_alive():_CODEC_PROCESS.terminate()
        _CODEC_PROCESS.join(timeout=2);code=_CODEC_PROCESS.exitcode
        _CODEC_PROCESS=None;_CODEC_PIPE=None
        raise ValueError(f'Isolated codec failed ({code}): {e}') from e


def read_nodes(path,offset=0,node_ids=None,t=None):
    if t is None:t=tables()
    meta,nonce,_=read_header(path,offset,t)
    if node_ids is None:node_ids=[i for i,n in enumerate(meta['nodes']) if n['serializedAsset']]
    if any(i<0 or i>=len(meta['nodes']) for i in node_ids):raise ValueError('Unknown node index')
    selected=[meta['nodes'][i] for i in node_ids]
    if sum(n['size'] for n in selected)>64*1024**2:raise ValueError('Requested nodes exceed64MiB')
    decoded={};readbytes=meta['headerReadBytes'];block_proofs=[]
    with Path(path).open('rb') as stream:
        for i,b in enumerate(meta['blocks']):
            begin=b['uncompressedOffset'];end=begin+b['uncompressedSize']
            if not any(n['offset']<end and n['offset']+n['size']>begin for n in selected):continue
            if b['compressedSize']>64*1024**2:raise ValueError('Compressed block exceeds64MiB')
            stream.seek(offset+b['compressedOffset']);raw=stream.read(b['compressedSize']);readbytes+=len(raw)
            if len(raw)!=b['compressedSize']:raise ValueError('Truncated block')
            body=decrypt_prefix(nonce,raw,t) if len(raw)>6 or b['compressionType']!=9 else raw
            comp=b['compressionType']
            if comp==0:
                if len(body)!=b['uncompressedSize']:raise ValueError('Raw size mismatch')
            elif comp in (2,3):body=lz4_block(body,b['uncompressedSize'])
            elif comp==9:body=oodle_block(body,b['uncompressedSize'])
            else:raise ValueError('Unsupported compression type '+str(comp))
            decoded[i]=body;block_proofs.append({'blockIndex':i,'encodedSha256':hashlib.sha256(raw).hexdigest(),'decodedSha256':hashlib.sha256(body).hexdigest()})
    result=[]
    for node_id,n in zip(node_ids,selected):
        parts=[]
        for i,b in enumerate(meta['blocks']):
            if i not in decoded:continue
            begin=b['uncompressedOffset'];lo=max(begin,n['offset']);hi=min(begin+b['uncompressedSize'],n['offset']+n['size'])
            if hi>lo:parts.append(decoded[i][lo-begin:hi-begin])
        data=b''.join(parts)
        if len(data)!=n['size']:raise ValueError('Incomplete node data')
        result.append((node_id,n,data))
    return meta,result,{'readBytes':readbytes,'decodedBlockProofs':block_proofs}


class BundleReader:
    """Lazy bounded ranges, cached per bundle; resS is never read implicitly."""
    def __init__(self,path,offset=0,t=None):
        self.path=Path(path);self.offset=offset;self.tables=t or tables()
        self.meta,self.nonce,_=read_header(path,offset,self.tables)
        self.cache={};self.read_bytes=self.meta['headerReadBytes']
    def read(self,node_id,relative_offset,size):
        node=self.meta['nodes'][node_id]
        if relative_offset<0 or size<0 or size>64*1024**2 or relative_offset+size>node['size']:raise ValueError('Node range outside bounds')
        lo=node['offset']+relative_offset;hi=lo+size;parts=[]
        with self.path.open('rb') as stream:
            for i,b in enumerate(self.meta['blocks']):
                begin=b['uncompressedOffset'];end=begin+b['uncompressedSize']
                if begin>=hi or end<=lo:continue
                if i not in self.cache:
                    if max(b['compressedSize'],b['uncompressedSize'])>64*1024**2:raise ValueError('Compressed block bounds')
                    stream.seek(self.offset+b['compressedOffset']);raw=stream.read(b['compressedSize']);self.read_bytes+=len(raw)
                    if len(raw)!=b['compressedSize']:raise ValueError('Short block')
                    body=decrypt_prefix(self.nonce,raw,self.tables) if len(raw)>6 or b['compressionType']!=9 else raw
                    c=b['compressionType']
                    if c in (2,3):body=lz4_block(body,b['uncompressedSize'])
                    elif c==9:body=oodle_block(body,b['uncompressedSize'])
                    elif c!=0:raise ValueError('Unsupported compression '+str(c))
                    if len(body)!=b['uncompressedSize']:raise ValueError('Wrong expanded size')
                    self.cache[i]=body
                parts.append(self.cache[i][max(lo,begin)-begin:min(hi,end)-begin])
        result=b''.join(parts)
        if len(result)!=size:raise ValueError('Incomplete range')
        return result


def inspect(args):
    path=Path(args.path).resolve();out=project_path(args.out)
    if not path.is_relative_to(INSTALL):raise ValueError('This acquisition entry accepts only the explicit installation')
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned source output only')
    out.mkdir(parents=True);metadata,nonce,decoded=read_header(path,args.offset)
    (out/'decoded-metadata.bin').write_bytes(decoded)
    node_rows=[];proof={}
    if args.payload:
        _,nodes,proof=read_nodes(path,args.offset)
        for i,n,data in nodes:
            target=out/f'node-{i:04d}.bin';target.write_bytes(data)
            strings=re.findall(rb'[A-Za-z0-9_./\\ -]{6,}',data)
            node_rows.append(dict(n,nodeIndex=i,pathOnDisk=relative(target),sha256=digest(target),
                boundedAsciiStrings=[v.decode('ascii') for v in strings if len(v)<300][:500]))
    write_json(out/'metadata.json',{'schema':1,'sourcePath':str(path),'sourceFileSize':path.stat().st_size,
        'sourceReadMode':'rb','sourceWrites':False,'sourceNonceHex':nonce.hex(),**metadata,
        'payloadDecoded':args.payload,'nativeTerrainIdentified':False,'decodedNodes':node_rows,'readProof':proof})
    print(json.dumps({'metadata':metadata,'decodedNodes':node_rows}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('path');p.add_argument('--out',required=True);p.add_argument('--offset',type=int,default=0);p.add_argument('--payload',action='store_true')
    inspect(p.parse_args())
