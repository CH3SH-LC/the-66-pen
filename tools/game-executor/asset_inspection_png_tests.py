"""Adam7 structure, malformed stream and decode-budget regressions; stdlib only."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_inspection_icons as icons
import asset_inspection_templates as templates
import asset_inspection_common as c

def chunk(kind,value):return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)

def png(payload,width=8,height=8,depth=8,color=6,interlace=1,compressed=None):
    header=struct.pack('>IIBBBBB',width,height,depth,color,0,0,interlace)
    palette=chunk(b'PLTE',b'\0\0\0\xff\xff\xff') if color==3 else b''
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+palette+chunk(b'IDAT',zlib.compress(payload) if compressed is None else compressed)+chunk(b'IEND',b'')

def rgba8():
    # Independent expected reduced sizes for an 8x8 image, PNG's 8x8 pass map.
    return b''.join((bytes([i%5])+bytes([20+i])*(w*4))*h for i,(w,h) in enumerate(((1,1),(1,1),(2,1),(2,2),(4,2),(4,4),(8,4))))

class Adam7Tests(unittest.TestCase):
    def test_all_seven_rgba_passes(self):
        out=icons.png_info(png(rgba8()));self.assertEqual(out['decodedScanlineBytes'],271);self.assertEqual(len(out['passes']),7)
    def test_filter_byte_in_every_pass_is_checked(self):
        for offset in (0,5,10,19,37,71,139):
            with self.subTest(offset=offset):
                payload=bytearray(rgba8());payload[offset]=5
                with self.assertRaisesRegex(ValueError,'FILTER_TYPE'):icons.png_info(png(payload))
    def test_one_pixel_skips_empty_passes(self):
        out=icons.png_info(png(b'\0\1\2\3\4',1,1));self.assertEqual([x['passNumber'] for x in out['passes']],[1])
    def test_one_column_skips_zero_width_passes(self):
        out=icons.png_info(png(b'\0\1\2\3\4'*8,1,8));self.assertEqual([x['passNumber'] for x in out['passes']],[1,3,5,7])
    def test_one_row_skips_zero_height_passes(self):
        payload=b'\0'+bytes(4)+b'\0'+bytes(4)+b'\0'+bytes(8)+b'\0'+bytes(16)
        out=icons.png_info(png(payload,8,1));self.assertEqual([x['passNumber'] for x in out['passes']],[1,2,4,6])
    def test_odd_dimensions(self):
        # 3x5 RGBA: reduced sizes 1x1, 1x1, 1x2, 2x1, 1x3, 3x2.
        sizes=((1,1),(1,1),(1,2),(2,1),(1,3),(3,2))
        payload=b''.join((b'\0'+bytes(w*4))*h for w,h in sizes)
        out=icons.png_info(png(payload,3,5));self.assertEqual(sum(x['width']*x['height'] for x in out['passes']),15)
    def test_packed_one_bit_rows_round_up_per_pass(self):
        out=icons.png_info(png(b'\0\x80'*15,depth=1,color=0));self.assertEqual(out['decodedScanlineBytes'],30)
    def test_indexed_adam7_supported(self):self.assertEqual(icons.png_info(png(b'\0\0'*15,depth=1,color=3))['colorType'],3)
    def test_rgba_sixteen_bit(self):
        sizes=((1,1),(1,1),(2,1),(2,2),(4,2),(4,4),(8,4))
        payload=b''.join((b'\0'+bytes(w*8))*h for w,h in sizes)
        self.assertEqual(icons.png_info(png(payload,depth=16))['decodedScanlineBytes'],527)
    def test_noninterlaced_preserved(self):self.assertEqual(icons.png_info(png((b'\0'+bytes(32))*8,interlace=0))['decodedScanlineBytes'],264)
    def test_pass_truncation_rejected(self):
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(png(rgba8()[:-1]))
    def test_extra_pass_bytes_rejected(self):
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(png(rgba8()+b'\0'))
    def test_filter_for_empty_pass_is_not_allowed(self):
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(png(b'\0\0\0\0\0\0',1,1))
    def test_incomplete_zlib_trailer_rejected(self):
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(png(b'',compressed=zlib.compress(rgba8())[:-2]))
    def test_invalid_deflate_rejected(self):
        with self.assertRaisesRegex(ValueError,'DEFLATE_INVALID'):icons.png_info(png(b'',compressed=b'bad zlib'))
    def test_concatenated_zlib_stream_refused(self):
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(png(b'',compressed=zlib.compress(rgba8())+zlib.compress(b'other')))
    def test_bad_crc_rejected(self):
        raw=bytearray(png(rgba8()));raw[-1]^=1
        with self.assertRaisesRegex(ValueError,'CRC'):icons.png_info(raw)
    def test_truncated_chunk_rejected(self):
        with self.assertRaisesRegex(ValueError,'CHUNK_TRUNCATED'):icons.png_info(png(rgba8())[:-1])
    def test_unknown_interlace_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_FORMAT'):icons.png_info(png(b'',interlace=2))
    def test_disallowed_depth_color_pairs(self):
        for color,depth in ((2,4),(4,1),(6,2),(3,16),(5,8)):
            with self.subTest(color=color,depth=depth),self.assertRaisesRegex(ValueError,'UNSUPPORTED_FORMAT'):icons.png_info(png(b'',color=color,depth=depth))
    def test_budget_refused_before_inflate(self):
        with patch.object(icons.zlib,'decompressobj') as inflate,self.assertRaisesRegex(ValueError,'DECODE_LIMIT'):
            icons.png_info(png(b'',8192,8192,depth=16))
        inflate.assert_not_called()
    def test_overexpansion_is_bounded_to_expected_plus_one(self):
        raw=png(bytes(10000),1,1)
        with self.assertRaisesRegex(ValueError,'DECODE_SIZE'):icons.png_info(raw)
    def test_adjacent_idat_fragments_supported(self):
        compressed=zlib.compress(rgba8());raw=png(b'');start=raw[:33]
        raw=start+chunk(b'IDAT',compressed[:3])+chunk(b'IDAT',b'')+chunk(b'IDAT',compressed[3:])+chunk(b'IEND',b'')
        self.assertTrue(icons.png_info(raw)['decodedScanlinesVerified'])
    def test_nonadjacent_idat_refused(self):
        compressed=zlib.compress(rgba8());raw=png(b'')[:33]+chunk(b'IDAT',compressed[:3])+chunk(b'tEXt',b'x\0y')+chunk(b'IDAT',compressed[3:])+chunk(b'IEND',b'')
        with self.assertRaisesRegex(ValueError,'IDAT_NOT_CONTIGUOUS'):icons.png_info(raw)

class TemplateConsumerTests(unittest.TestCase):
    def test_template_plan_uses_same_adam7_validator(self):
        c.OUTPUT.mkdir(parents=True,exist_ok=True);folder=Path(tempfile.mkdtemp(prefix='adam7-consumer-',dir=c.OUTPUT)).resolve()
        try:
            picture=folder/'native.png';picture.write_bytes(png(rgba8()));manifest=folder/'manifest.json'
            c.write(manifest,dict(ok=True,kind='asset-inspection-icons-v1',sourceBundleSha256=icons.INSTALLED_SHA,capturedBundleSha256=icons.INNER_SHA,
                rows=[dict(templateId=99,ok=True,thumbnailPixelsVerified=True,catalog=dict(sourceSha256=c.CATALOG_SHA),exactZipMember='exact.png',
                    assetBundleSha256=icons.INNER_SHA,imagePath=str(picture),imageSha256=c.sha(picture))]))
            result,_=templates.icon_evidence(manifest,[99],{'99':dict(iconPath='exact.png')})
            self.assertTrue(result['99']['thumbnailPixelsVerified']);self.assertFalse(result['99']['runtimeModelAppearanceVerified'])
        finally:
            if not folder.is_relative_to(c.OUTPUT.resolve()):raise RuntimeError('Unsafe test cleanup')
            shutil.rmtree(folder)

if __name__=='__main__':unittest.main()
