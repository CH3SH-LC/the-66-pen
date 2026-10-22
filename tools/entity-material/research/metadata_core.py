"""Read-only current-build PE/metadata arithmetic, no import-time IO or output.
Transcribed from the preserved task-k readers. Construction reads two disk files;
it never opens a process, executes game code, or creates output directories.
"""
import bisect, hashlib, pathlib, struct
u32 = lambda x: x & 0xffffffff
u64 = lambda x: x & 0xffffffffffffffff
i32 = lambda x: x if x < 0x80000000 else x-0x100000000

class Image:
    def __init__(self, image_path=None):
        import sys
        sys.dont_write_bytecode = True
        try:
            import capstone
        except ImportError:
            deps = pathlib.Path(__file__).resolve().parents[3] / ".runtime/native-analysis/deps"
            sys.path.insert(0, str(deps))
            import capstone
        self.data = pathlib.Path(image_path or 'D:/games/Genshin Impact Game/YuanShen.exe').read_bytes()
        self.sha = hashlib.sha256(self.data).hexdigest()
        assert self.sha == '7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e'
        p = struct.unpack_from('<I', self.data, 60)[0]
        n = struct.unpack_from('<H', self.data, p+6)[0]
        z = struct.unpack_from('<H', self.data, p+20)[0]
        o = p+24
        self.base = struct.unpack_from('<Q', self.data, o+24)[0]
        self.sections = []
        for i in range(n):
            s = o+z+i*40
            vs, va, rs, ro = struct.unpack_from('<IIII', self.data, s+8)
            flags = struct.unpack_from('<I', self.data, s+36)[0]
            self.sections.append((vs, va, rs, ro, flags))
        r, size = struct.unpack_from('<II', self.data, o+112+3*8)
        pd = self.get(r, size)
        self.funcs = [row[:2] for row in struct.iter_unpack('<III', pd)]
        self.starts = [a for a,b in self.funcs]
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    def get(self, r, size):
        for vs, va, rs, ro, flags in self.sections:
            if va <= r and r+size <= va+rs:
                return self.data[ro+r-va:ro+r-va+size]
        raise ValueError(f'non-file-backed RVA {r:x}, size {size}')
    def d(self,r): return struct.unpack('<I',self.get(r,4))[0]
    def q(self,r): return struct.unpack('<Q',self.get(r,8))[0]
    def containing(self, r):
        i = bisect.bisect_right(self.starts,r)-1
        if i >= 0 and self.funcs[i][0] <= r < self.funcs[i][1]: return self.funcs[i]
        return None

class Metadata(Image):
    def __init__(self, image_path=None, metadata_path=None):
        super().__init__(image_path)
        raw = pathlib.Path(metadata_path or 'D:/games/Genshin Impact Game/YuanShen_Data/Managed/Metadata/global-metadata.dat').read_bytes()
        self.metadata_sha = hashlib.sha256(raw).hexdigest()
        assert self.metadata_sha == '469eccd43aa48fe7a2df4e1caf66fa1268a17f5a4a03fa209e1427e467cb0161'
        # 2f3730 static initializer and 536179 metadata loader.
        self.header = 0x27d5cb0
        self.registration = 0x2871c08
        self.types_registration = 0x2871b68
        self.body = raw[0x210:]
    def bd(self, a):
        assert 0 <= a <= len(self.body)-4, a
        return struct.unpack_from('<I', self.body, a)[0]
    def bq(self, a):
        assert 0 <= a <= len(self.body)-8, a
        return struct.unpack_from('<Q', self.body, a)[0]
    def type(self, source):
        r = self.q(self.types_registration+0x50)-self.base+source*16
        record = self.get(r,16)
        return {'index':source,'rva':hex(r),'hex':record.hex(),'kind':record[10],
                'definitionIndex':struct.unpack_from('<I',record)[0] if record[10] in (17,18) else None}
    def usage(self, index):
        # Exact arithmetic at 524250, including 32/64-bit wrap widths.
        bounds = i32(self.d(self.header+0x19c)) ^ 0x159fbc84
        pairs = i32(self.d(self.header+0x14c)) ^ 0x2f249c2f
        def bound(i):
            mix = u64(u64((u64(i*0x6536)^0x138d67f3)*0x44b1aad4)+0x1f9ea55ad057d0)>>21
            return u32(u32(mix)*0xd0dc29d5+(self.bd(bounds+4*i)^0x15a6f604)+0xe6495e3d)
        a,b = bound(index),bound(index+1)
        assert a <= b <= a+2048, (a,b)
        fields = {0:0x38,1:0x50,2:None,3:8,4:0x58,5:0x28,6:8,7:0x18}
        rows = []
        for j in range(a,b):
            key = u32((u32(u64(j*0x3c5f6dc3f5d0)>>20)^0x615eb706)+0x63d46a21)
            encoded = self.bd(pairs+8*j+4)^key^0x5cd30101
            kind,source = encoded>>29,encoded&0x1fffffff
            destination = key^u32(self.bd(pairs+8*j)+0x8ab89515)
            actual = destination&0xffffff if kind in (0,7) else destination
            field = fields[kind]
            slot = self.q(self.registration+field)-self.base+actual*8 if field is not None else None
            row = {'pair':j,'kind':kind,'source':source,'destination':destination,'slot':hex(slot) if slot else None}
            if kind == 1: row['type'] = self.type(source)
            if kind == 5: row['literal'] = self.literal(source)
            rows.append(row)
        return {'usage':hex(index),'range':[a,b],'entries':rows}
    def literal(self,index):
        # Offset arithmetic from 524547; byte cipher from 526bd0.
        offsets = i32(u32(self.d(self.header+0x88)+0xf3c0b2fe))
        data = i32(self.d(self.header+0x13c))^0x28b1d785
        def offset(i):
            value = u64(u64(u64(i*0x9825)^0x250621a3)*0x76c8023d)>>12
            value = u64(value*0x5e626528)>>15
            value = u32(value+0x3483f478)^0xa0d4507f
            return i32(u32(value+self.bd(offsets+i*4)+0x81555d04))
        a,b = offset(index),offset(index+1)
        assert 0 <= b-a <= 8192, (index,a,b)
        key = u64(index*0x34044c3b94b40c)^0x2c165a1e0d09c29e
        key = u64(key*0x4d613e5575a12594)^0x1b34fa773fee107e
        key = u64(key*0x29140a6156b9041e)
        decoded = b''.join(struct.pack('<Q',self.bq(data+a+k*8)^u64(key+k*0x70ba8080760ac800)) for k in range((b-a+7)//8))[:b-a]
        return {'index':index,'bodyOffset':data+a,'length':b-a,'utf8':decoded.decode('utf-8'),'hex':decoded.hex()}
    def identifier(self,packed):
        # Class resolver 19f64153 -> 510060, cipher at 510ec6.
        if packed == 0xffffffff: return None
        data = i32(u32(self.d(self.header+0x150)+0xc8542dd2))
        offset,length = packed&0xffffff,packed>>24
        key = u64(offset*0xb33e40427d5668c0+0x6d8c4aab00fe8e27)^0x30ee5b43130fe0cd
        decoded = b''.join(struct.pack('<Q',self.bq(data+offset+k*8)^u64(key+k*0x889eeea326afb36)) for k in range((length+7)//8))[:length]
        return {'packed':hex(packed),'bodyOffset':data+offset,'name':decoded.decode('utf-8'),'hex':decoded.hex()}
    def definition_name(self,index):
        # Current class kind 0x12 -> 50e7ca -> 51db00 -> 19f63c4d.
        definitions = i32(self.d(self.header+0xdc))^0x5278ca3b
        at = definitions+index*70
        return {'index':index,'recordBodyOffset':at,'recordHex':self.body[at:at+70].hex(),
                'identifier':self.identifier(u32(self.bd(at+0x14)+0xe811f779))}
    def factory_controls(self,rows):
        by_slot = {row['slot']:row for row in rows}
        wanted = [('Currency','ClientBeyondCurrencyConfigTemplateEditData',0x57e8730,0x5a294b8),
                  ('Shop','ClientBeyondShopConfigTemplateEditData',0x57cb518,0x5a29ad0),
                  ('StuffBag','ClientBeyondStuffBagConfigTemplateEditData',0x57e8ae0,0x5a29b30)]
        result = []
        for label,name,slot,literal_slot in wanted:
            typed,literal = by_slot[hex(slot)],by_slot[hex(literal_slot)]
            assert literal['kind'] == 5 and literal['literal']['utf8'] == name
            assert typed['kind'] == 1 and typed['type']['kind'] == 18
            result.append({'label':label,'semanticName':name,'typeSlot':hex(slot),
                           'literalSlot':hex(literal_slot),'source':typed['source'],
                           'type':typed['type'],
                           'definition':self.definition_name(typed['type']['definitionIndex']),
                           'literal':literal['literal']})
        return result
    def definition_aliases(self,index):
        # Type-cache allocation count at 5361be, current registration fields.
        count = self.d(self.types_registration+0x30)^0x28a0fa2d
        assert count == 683568
        start = self.q(self.types_registration+0x50)-self.base
        raw = self.get(start,count*16)
        needle,pos,result = struct.pack('<I',index),0,[]
        while True:
            pos = raw.find(needle,pos)
            if pos < 0: break
            if pos%16 == 0 and raw[pos+10] in (17,18): result.append(self.type(pos//16))
            pos += 1
        return result
    def definition_usage_refs(self,index):
        aliases = self.definition_aliases(index)
        sources = {row['index'] for row in aliases}
        # All-usage preinitializer 5281de uses this byte count /4 -1.
        size = u32(self.d(self.header+0x1a0)+0x80130d0f)
        assert size == 1246924
        count = size//4-1
        bounds_at = i32(self.d(self.header+0x19c))^0x159fbc84
        pairs_at = i32(self.d(self.header+0x14c))^0x2f249c2f
        bounds = []
        for i in range(count+1):
            mix = u64(u64((u64(i*0x6536)^0x138d67f3)*0x44b1aad4)+0x1f9ea55ad057d0)>>21
            bounds.append(u32(u32(mix)*0xd0dc29d5+(self.bd(bounds_at+4*i)^0x15a6f604)+0xe6495e3d))
        assert bounds[0] == 0 and bounds[-1] == 788057
        assert all(a <= b for a,b in zip(bounds,bounds[1:]))
        result = []
        for j in range(bounds[-1]):
            key = u32((u32(u64(j*0x3c5f6dc3f5d0)>>20)^0x615eb706)+0x63d46a21)
            encoded = self.bd(pairs_at+j*8+4)^key^0x5cd30101
            kind,source = encoded>>29,encoded&0x1fffffff
            if kind not in (1,7) or source not in sources: continue
            destination = key^u32(self.bd(pairs_at+j*8)+0x8ab89515)
            usage = bisect.bisect_right(bounds,j)-1
            actual = destination if kind == 1 else destination&0xffffff
            field = 0x50 if kind == 1 else 0x18
            result.append({'pair':j,'usage':usage,'usageHex':hex(usage),'kind':kind,'source':source,
                           'slot':hex(self.q(self.registration+field)-self.base+actual*8)})
        return {'definitionIndex':index,'usageCount':count,'boundsBytes':size,
                'pairCount':bounds[-1],'pairsBytes':bounds[-1]*8,'aliases':aliases,'refs':result}
    def method_owner(self,index):
        # 51e11e current method owner decoder; 5156e1 default pointer table.
        methods = i32(self.d(self.header+0x1e0))^0x2ee480fb
        at = methods+index*26
        mix = u32(index*0x4e94)^0x62d8b7b8
        mix = u32(mix*0x7572748a+0x1f4d9eea)^0x6e8931d6
        owner = u32((self.bd(at+0xe)^0x394729c)+u32(mix*0xc6fc9c8b))
        pointers = self.q(0x22df450+0x28)-self.base
        return {'methodIndex':index,'functionRva':hex(self.q(pointers+index*8)-self.base),
                'recordBodyOffset':at,'recordHex':self.body[at:at+26].hex(),
                'owner':self.definition_name(owner)}

