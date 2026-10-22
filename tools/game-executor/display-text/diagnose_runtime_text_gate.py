"""Prepare one-shot text diagnostics using fixed native read queries.

No account/scene setters, export, save, or gate writes are linked. The two native
queries read property 10074 and permission 4; the profile display field at +128
must not be labelled creator rank. Preparation does not execute the candidate.
"""
from pathlib import Path
import sys,json,shutil
HERE=Path(__file__).resolve().parent;EX=HERE.parent;ROOT=EX.parents[1]
sys.path.insert(0,str(EX))
import build_readonly_profile as ro
import native_profiles as p

def replace(s,a,b):
 p.require(s.count(a)==1,'SOURCE_PATTERN_CHANGED:'+a[:60]);return s.replace(a,b,1)

def main():
 profile=p.load_profile();p.verify_disk(profile)
 stage=ro.output_directory(ROOT/'.runtime/display-text/rank-source')
 for name in ro.SOURCES:(stage/name).write_bytes((ro.NATIVE/name).read_bytes())
 anchors={}
 with p.TARGET_IMAGE.open('rb') as f:
  pe=p.inspect_pe(f.read(8192))
  for rva,size in [(0x9f73bb0,0xd3),(0x9573820,0xff),(0x132011e0,0x174),(0x96b36b0,0x10b)]:
   off=p.rva_offset(pe['sections'],rva,size,p.TARGET_IMAGE.stat().st_size)
   f.seek(off);anchors[rva]=f.read(size)
 checks='\n'.join('  const unsigned char a'+str(rva)+'[]={'+','.join(hex(x) for x in code)+'};\n  if(std::memcmp(reinterpret_cast<void*>(base+'+hex(rva)+'),a'+str(rva)+',sizeof(a'+str(rva)+'))!=0){out->status=2;return;}' for rva,code in anchors.items())
 header='''#pragma once
#include "game_context_snapshot.h"
struct CreatorRankSnapshot { unsigned status,rank,rankAfter,hotfix,gateAvailable,gateSuppress; char gateClasses[4][48]; unsigned queryAvailable,permissionAllowed,requiredValue; double propertyValue,propertyRepeat; };
void CaptureCreatorRank(const GameContextSnapshot*,CreatorRankSnapshot*) noexcept;
'''
 (stage/'creator_rank.h').write_text(header,encoding='utf8')
 capture=r'''
#include "creator_rank.h"
static void ReadDiagnosticClassName(std::uint64_t object,char* output) noexcept {
 const unsigned offsets[]={0x8,0x10,0x18,0x20,0x28};
 for(const auto off:offsets){
  __try {
   if(object<0x10000)continue;
   const auto klass=*reinterpret_cast<std::uint64_t*>(object);
   const auto ptr=*reinterpret_cast<std::uint64_t*>(klass+off);
   if(ptr<0x10000)continue;
   char text[48]{};unsigned n=0;
   for(;n<47;++n){const auto c=*reinterpret_cast<const char*>(ptr+n);if(c==0)break;if(c<'A'||c>'Z'){n=0;break;}text[n]=c;}
   if(n==11){std::memcpy(output,text,48);return;}
  }__except(EXCEPTION_EXECUTE_HANDLER){}
 }
}
void CaptureCreatorRank(const GameContextSnapshot* context,CreatorRankSnapshot* out) noexcept {
 *out={};out->status=1;
 if(!context || context->status!=GS_OK || context->reserved!=1073741842 || !(context->flags&GS_LEVEL_OBSERVED))return;
 __try {
  const auto base=context->moduleBase;
@CHECKS@
  out->hotfix=*reinterpret_cast<unsigned char*>(base+0x56f862b) | *reinterpret_cast<unsigned char*>(base+0x56f8629);
  const unsigned guards[]={0x57356fb,0x572b841,0x57756c2,0x57756c1,0x577ae96};
  for(const auto rva:guards)out->hotfix|=*reinterpret_cast<unsigned char*>(base+rva);
  if(out->hotfix){out->status=3;return;}
  const auto g=*reinterpret_cast<std::uint64_t*>(base+0x5783de8);
  if(g!=context->global){out->status=4;return;}
  const auto mod=*reinterpret_cast<std::uint64_t*>(g+0xa440);
  if(mod<0x10000){out->status=5;return;}
  const auto data=*reinterpret_cast<std::uint64_t*>(mod+0x118);
  if(data<0x10000){out->status=6;return;}
  out->rank=*reinterpret_cast<volatile unsigned*>(data+0x128);
  out->rankAfter=*reinterpret_cast<volatile unsigned*>(data+0x128);
  if(out->rank!=out->rankAfter || out->rank>100 || mod!=*reinterpret_cast<std::uint64_t*>(g+0xa440) || data!=*reinterpret_cast<std::uint64_t*>(mod+0x118)){out->status=7;return;}
  const auto community=*reinterpret_cast<std::uint64_t*>(g+0xa400);
  if(community<0x10000){out->status=9;return;}
  using PropertyQuery=double(__fastcall*)(std::uint64_t,unsigned);
  using PermissionQuery=bool(__fastcall*)(std::uint64_t,unsigned);
  out->propertyValue=reinterpret_cast<PropertyQuery>(base+0x9573820)(data,10074);
  out->permissionAllowed=reinterpret_cast<PermissionQuery>(base+0x132011e0)(community,4)?1U:0U;
  out->requiredValue=*reinterpret_cast<volatile unsigned*>(base+0x578c108);
  out->propertyRepeat=reinterpret_cast<PropertyQuery>(base+0x9573820)(data,10074);
  if(out->propertyValue!=out->propertyRepeat || out->propertyValue<0 || out->propertyValue>100 || out->requiredValue>100){out->status=10;return;}
  out->queryAvailable=1;
  out->status=0;
  const auto gateModule=*reinterpret_cast<std::uint64_t*>(g+0xa150);
  if(gateModule<0x10000)return;
  ReadDiagnosticClassName(gateModule,out->gateClasses[0]);
  const auto gateContext=*reinterpret_cast<std::uint64_t*>(gateModule+0x68);
  if(gateContext<0x10000)return;
  ReadDiagnosticClassName(gateContext,out->gateClasses[1]);
  const auto gateLevel=*reinterpret_cast<std::uint64_t*>(gateContext+0x20);
  if(gateLevel<0x10000)return;
  ReadDiagnosticClassName(gateLevel,out->gateClasses[2]);
  const auto gateData=*reinterpret_cast<std::uint64_t*>(gateLevel+0x20);
  if(gateData<0x10000)return;
  ReadDiagnosticClassName(gateData,out->gateClasses[3]);
  out->gateSuppress=*reinterpret_cast<volatile unsigned char*>(gateData+0xe4);
  out->gateAvailable=1;
 } __except(EXCEPTION_EXECUTE_HANDLER){if(out->status!=0)out->status=8;}
}
'''.replace('@CHECKS@',checks)
 with (stage/'game_context_snapshot.cpp').open('a',encoding='utf8') as f:f.write(capture)
 path=stage/'hook_receipt_protocol.h';s=path.read_text();s=replace(s,'struct Receipt {','#include "creator_rank.h"\nstruct Receipt {');s=replace(s,'    GameContextSnapshot context;','    GameContextSnapshot context;\n    CreatorRankSnapshot creatorRank;');s=replace(s,'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = 19; // isolated rank diagnostic\n/* constexpr DWORD unusedVersion = HR_READ_REOPEN_GUARDS');s=replace(s,'HR_ACTION ? 3 : 2;','HR_ACTION ? 3 : 2; */');path.write_text(s,encoding='utf8')
 path=stage/'hook_receipt.cpp';s=path.read_text();s=replace(s,'                    CaptureGameContextSnapshot(&receipt->context);','                    CaptureGameContextSnapshot(&receipt->context);\n                    CaptureCreatorRank(&receipt->context,&receipt->creatorRank);');path.write_text(s,encoding='utf8')
 path=stage/'hook_receipt_probe.cpp';s=path.read_text();s=replace(s,'bool reportedOk = receipt->context.status == GS_OK;','bool reportedOk = receipt->context.status == GS_OK && receipt->creatorRank.status==0;');s=replace(s,'                std::printf("}\\n");',r'''                std::printf(",\"profileDisplayField\":{\"status\":%u,\"value\":%u,\"repeat\":%u,\"hotfix\":%u},\"textGate\":{\"available\":%u,\"suppressesText\":%u,\"classes\":[\"%s\",\"%s\",\"%s\",\"%s\"]},\"permissionQuery\":{\"available\":%u,\"permissionId\":4,\"propertyId\":10074,\"propertyValue\":%.17g,\"propertyRepeat\":%.17g,\"requiredValue\":%u,\"allowed\":%u},\"nativeReadQueriesCalled\":true,\"nativeSettersCalled\":false}",receipt->creatorRank.status,receipt->creatorRank.rank,receipt->creatorRank.rankAfter,receipt->creatorRank.hotfix,receipt->creatorRank.gateAvailable,receipt->creatorRank.gateSuppress,receipt->creatorRank.gateClasses[0],receipt->creatorRank.gateClasses[1],receipt->creatorRank.gateClasses[2],receipt->creatorRank.gateClasses[3],receipt->creatorRank.queryAvailable,receipt->creatorRank.propertyValue,receipt->creatorRank.propertyRepeat,receipt->creatorRank.requiredValue,receipt->creatorRank.permissionAllowed);
                std::printf("\n");''');path.write_text(s,encoding='utf8')
 ro.NATIVE=stage;ro.SOURCES=ro.SOURCES+('creator_rank.h',)
 result=ro.prepare(ROOT/'.runtime/scratch/native-tabs-20261014/session-1323.json',output_root=ROOT/'.runtime/display-text/rank-readonly',ttl_seconds=300)
 (ROOT/'.runtime/display-text/latest-rank-readonly.json').write_text(json.dumps(result,indent=2),encoding='utf8')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
