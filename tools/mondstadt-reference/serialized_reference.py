"""Bounded Unity 17 metadata and object-name reader, no game code execution.

Format basis is pinned AnimeStudio SerializedFile.cs and the class source files.
This reader deliberately rejects unknown versions instead of guessing layouts.
"""
from __future__ import annotations
import struct


class Reader:
    def __init__(self, data, endian='<'):
        self.data=data;self.p=0;self.endian=endian
    def take(self,n):
        if n<0 or self.p+n>len(self.data):raise ValueError('Serialized read outside available bytes')
        b=self.data[self.p:self.p+n];self.p+=n;return b
    def read(self,fmt):
        return struct.unpack(self.endian+fmt,self.take(struct.calcsize(fmt)))[0]
    def align(self):self.p=(self.p+3)&~3
    def cstring(self,limit=4096):
        end=self.data.find(b'\0',self.p,min(len(self.data),self.p+limit))
        if end<0:raise ValueError('Missing bounded string terminator')
        b=self.take(end-self.p+1);return b[:-1].decode('utf8')
    def string(self,limit=4096):
        n=self.read('i')
        if not 0<=n<=limit:raise ValueError('String outside length bounds')
        s=self.take(n).decode('utf8');self.align();return s
    def count(self,limit=1000000):
        n=self.read('i')
        if not 0<=n<=limit:raise ValueError('Count outside bounds')
        return n
    def ptr(self):return {'fileId':self.read('i'),'pathId':self.read('q')}


def metadata(data,total_size=None):
    if len(data)<20:raise ValueError('Short serialized header')
    ms,fs,version,start=struct.unpack_from('>IIII',data)
    if version!=17:raise ValueError('Unsupported Unity serialization version '+str(version))
    if total_size is None:total_size=len(data)
    if fs!=total_size or not 20<=start<=fs or ms>start:raise ValueError('Invalid serialized header sizes')
    endian='<' if data[16]==0 else '>';encoded=bool(data[17]);r=Reader(data,endian);r.p=20
    unity=r.cstring();platform=r.read('i');tree=bool(r.read('B'));types=[]
    for _ in range(r.count(100000)):
        cid=r.read('i')
        if encoded:cid=(int.from_bytes(struct.pack('<i',cid),'big')^0x23746FBE)-3
        stripped=bool(r.read('B'));script=r.read('h')
        scriptid=r.take(16).hex() if cid==114 else None
        oldhash=r.take(16).hex();nodes=[];strings=''
        if tree:
            count=r.count();size=r.count(16*1024**2)
            raw=r.take(count*24);strings=r.take(size).hex()
            for j in range(count):
                v,l,f,t,n,b,i,m=struct.unpack_from(endian+'HBBIIiii',raw,j*24)
                nodes.append({'version':v,'level':l,'flags':f,'typeOffset':t,'nameOffset':n,'byteSize':b,'index':i,'metaFlags':m})
        types.append({'classId':cid,'stripped':stripped,'scriptTypeIndex':script,'scriptId':scriptid,'typeHash':oldhash,'nodes':nodes,'stringsHex':strings})
    objects=[]
    for _ in range(r.count()):
        r.align();pid=r.read('q');offset=r.read('I')+start;size=r.read('I');tid=r.read('i')
        if not 0<=tid<len(types) or offset<start or offset+size>fs:raise ValueError('Object outside serialized file')
        objects.append({'pathId':pid,'offset':offset,'size':size,'typeId':tid,'classId':types[tid]['classId']})
    scripts=[]
    for _ in range(r.count()):
        fileid=r.read('i');r.align();scripts.append({'fileId':fileid,'pathId':r.read('q')})
    externals=[]
    for _ in range(r.count(100000)):
        empty=r.cstring();guid=r.take(16).hex();kind=r.read('i');name=r.cstring()
        externals.append({'guid':guid,'type':kind,'path':name})
    user=r.cstring()
    if r.p>start:raise ValueError('Metadata overlaps object section')
    return {'unityVersion':unity,'serializationVersion':version,'fileSize':fs,'dataOffset':start,'metadataSize':ms,'metadataEnd':r.p,'endian':endian,'encodedClassIds':encoded,'platform':platform,'typeTreeEnabled':tree,'types':types,'objects':objects,'externals':externals,'scripts':scripts,'userInformation':user}


NAMED={21,28,43,48,49,74,83,89,90,91,93,95,115,128,142,152,156,184,213,221,687078895}
def object_identity(obj,data,endian='<'):
    r=Reader(data,endian);cid=obj['classId'];result={}
    if cid==1:
        result['components']=[r.ptr() for _ in range(r.count(1024))]
        result['layer']=r.read('i');result['name']=r.string()
    elif cid in NAMED:result['name']=r.string()
    elif cid==4:
        result['gameObject']=r.ptr();result['localRotation']=[r.read('f') for _ in range(4)]
        result['localPosition']=[r.read('f') for _ in range(3)];result['localScale']=[r.read('f') for _ in range(3)]
        result['children']=[r.ptr() for _ in range(r.count(100000))];result['father']=r.ptr()
    elif cid==33:result={'gameObject':r.ptr(),'mesh':r.ptr()}
    result['parsedBytes']=r.p
    return result
