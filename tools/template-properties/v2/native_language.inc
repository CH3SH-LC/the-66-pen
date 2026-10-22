// Targeted language records. No full-scene export/refresh and no gate writes.
bool languageText(U p,LanguageText& t){return text(p,t.value,t.length);}
bool sameText(const LanguageText& a,const LanguageText& b){return a.length==b.length&&!std::memcmp(a.value,b.value,256);}
bool stringHash(U p,U& h){int n=0;if(!p){h=hash(&n,sizeof(n),h);return true;}if(!read(p+0x10,n)||n<0||n>32768)return false;h=hash(&n,sizeof(n),h);unsigned char buf[256]{};for(unsigned done=0;done<static_cast<unsigned>(n)*2;){const unsigned part=static_cast<unsigned>(n)*2-done<256?static_cast<unsigned>(n)*2-done:256;if(!memory(p+0x14+done,buf,part))return false;h=hash(buf,part,h);done+=part;}int after=0;return read(p+0x10,after)&&after==n;}
bool listInfo(U list,U& array,unsigned& count,unsigned& version,unsigned max){U cap=0;array=ptr(list+0x10);return list&&array&&read(list+0x18,count)&&count<=max&&read(list+0x1c,version)&&read(array+0x18,cap)&&cap>=count&&cap<=8192;}
bool integerListHash(U list,U& h){U a=0;unsigned n=0,v=0,again=0;if(!listInfo(list,a,n,v,64))return false;h=hash(&n,sizeof(n),h);unsigned x[64]{};if(n&&!memory(a+0x20,x,n*4))return false;h=hash(x,n*4,h);return read(list+0x1c,again)&&v==again;}
bool entryHash(U entry,unsigned primary,bool mask,U& h){
 unsigned index=0;unsigned char blocked=255;const U source=ptr(entry+0x20);if(!source||!read(entry+0x30,index)||!read(entry+0x34,blocked)||blocked>1)return false;
 h=hash(&entry,8,h);if(!stringHash(source,h)||!integerListHash(ptr(entry+0x28),h))return false;h=hash(&index,4,h);h=hash(&blocked,1,h);
 U a=0;unsigned n=0,v=0,again=0;const U list=ptr(entry+0x18);if(!listInfo(list,a,n,v,64))return false;
 unsigned seen[64]{},kept=0;for(unsigned i=0;i<n;++i){const U row=ptr(a+0x20+i*8);unsigned lang=0;if(!row||!read(row+0x20,lang)||lang>64)return false;for(unsigned j=0;j<i;++j)if(seen[j]==lang)return false;seen[i]=lang;
  if(mask&&lang==primary)continue;++kept;h=hash(&row,8,h);h=hash(&lang,4,h);if(!stringHash(ptr(row+0x18),h))return false;
 }h=hash(&kept,4,h);return read(list+0x1c,again)&&again==v;
}
bool languageContext(const GameContextSnapshot& s,LanguageReceipt& l){
 const U resourceManager=ptr(s.global+0xee80),method=ptr(s.moduleBase+0x5903e10);if(!resourceManager||!method)return false;
 const U main=reinterpret_cast<U>(native<void*(*)(void*,unsigned,void*)>(s.moduleBase,0x142a0540)(reinterpret_cast<void*>(resourceManager),1,reinterpret_cast<void*>(method)));
 const U prop=property(s.moduleBase,main,66),registry=ptr(prop+0x38),list=ptr(registry+0x18);
 if(!prop||ptr(prop)!=ptr(s.moduleBase+0x57e1fc0)||ptr(prop+0x20)!=main||!registry||!list||(l.property&&l.property!=prop)||(l.registry&&l.registry!=registry)||(l.list&&l.list!=list))return false;
 l.property=prop;l.registry=registry;l.list=list;return read(registry+0x28,l.primaryLanguage)&&l.primaryLanguage==2;
}
bool permissions(const GameContextSnapshot& s,LanguageReceipt& l){
 const U community=ptr(s.global+0xa400),policy=ptr(s.global+0x31100),allowed=ptr(policy+0x18),method=ptr(s.moduleBase+0x594bd78);
 if(!community||!policy||!ptr(policy+0x10)||!allowed||!method)return false;
 l.permissionAllowed=native<bool(*)(void*,unsigned)>(s.moduleBase,0x132011e0)(reinterpret_cast<void*>(community),4)?1U:0U;
 l.categoryAllowed=native<bool(*)(void*,unsigned,void*)>(s.moduleBase,0x166df280)(reinterpret_cast<void*>(allowed),16,reinterpret_cast<void*>(method))?1U:0U;
 return true;
}
bool languageCapture(const GameContextSnapshot& s,PropertyReceipt& o,bool after){
 auto& l=o.language;if(!languageContext(s,l))return false;U a=0;unsigned count=0,v=0,again=0;
 if(!listInfo(l.list,a,count,v,4096))return false;if(after){l.afterCount=count;if(count!=l.beforeCount+l.created)return false;}else l.beforeCount=count;
 U full=1469598103934665603ULL,guardHash=full;const unsigned oldCount=after?l.beforeCount:count;
 if(!integerListHash(ptr(l.registry+0x20),full))return false;guardHash=full;full=hash(&count,4,full);guardHash=hash(&oldCount,4,guardHash);
 for(unsigned j=0;j<o.count;++j){auto& row=l.rows[j];if(after){row.afterIndex=0xffffffffU;row.afterEntry=0;row.after={};row.afterFound=0;}else{row.beforeIndex=0xffffffffU;row.beforeEntry=0;row.before={};row.beforeFound=0;}}
 for(unsigned i=0;i<count;++i){const U e=ptr(a+0x20+i*8);if(!e||ptr(e)!=ptr(s.moduleBase+0x57e86e0))return false;bool target=false;
  int len=-1;const U source=ptr(e+0x20);if(!source||!read(source+0x10,len)||len<0||len>32768)return false;
  for(unsigned j=0;j<o.count;++j){auto& row=l.rows[j];if(static_cast<unsigned>(len)!=row.source.length)continue;LanguageText value{};if(!languageText(source,value))return false;if(!sameText(value,row.source))continue;
   target=true;auto& index=after?row.afterIndex:row.beforeIndex;if(index!=0xffffffffU)return false;index=i;unsigned char blocked=255;if(!read(e+0x34,blocked)||blocked>1)return false;
   U translated=0;const bool found=native<bool(*)(void*,unsigned,void**)>(s.moduleBase,0x11796380)(reinterpret_cast<void*>(e),l.primaryLanguage,reinterpret_cast<void**>(&translated));
   U translations=0;unsigned tn=0,tv=0;const U tl=ptr(e+0x18);if(!listInfo(tl,translations,tn,tv,64))return false;unsigned matched=0;U rawValue=0;for(unsigned k=0;k<tn;++k){const U tr=ptr(translations+0x20+k*8);unsigned lang=0;if(!tr||!read(tr+0x20,lang))return false;if(lang==l.primaryLanguage){++matched;rawValue=ptr(tr+0x18);}}if(matched>1||found!=(matched==1)||(found&&rawValue!=translated))return false;
   if(after){row.afterEntry=e;row.afterFound=found?1U:0U;row.blockedAfter=blocked;if(!languageText(translated,row.after))return false;}
   else{row.beforeEntry=e;row.beforeFound=found?1U:0U;row.blockedBefore=blocked;if(!languageText(translated,row.before))return false;}
  }
  if(!entryHash(e,l.primaryLanguage,false,full))return false;if(i<oldCount&&!entryHash(e,l.primaryLanguage,target,guardHash))return false;
  if(i>=oldCount&&!target)return false;
 }
 if(!read(l.list+0x1c,again)||v!=again)return false;
 if(after){l.afterHash=full;l.guardAfter=guardHash;}else{l.beforeHash=full;l.guardBefore=guardHash;}return true;
}
bool languageBefore(const GameContextSnapshot& s,PropertyReceipt& o,const PropertyRequest* requests){
 auto& l=o.language;l.status=1;for(unsigned i=0;i<o.count;++i){auto& row=l.rows[i];row.id=requests[i].id;row.source.length=requests[i].desired.nameLength;std::memcpy(row.source.value,requests[i].desired.name,256);if(!row.source.length)return false;for(unsigned j=0;j<i;++j)if(sameText(row.source,l.rows[j].source))return false;}
 if(!languageCapture(s,o,false)||!permissions(s,l))return false;l.stage=1;
 if constexpr(PROPERTIES_WRITE!=0){
  unsigned missing=0;for(unsigned i=0;i<o.count;++i)if(!l.rows[i].beforeEntry)++missing;if(l.beforeCount+missing>4096)return false;
  if(l.property!=LANGUAGE_EXPECTED_PROPERTY||l.registry!=LANGUAGE_EXPECTED_REGISTRY||l.list!=LANGUAGE_EXPECTED_LIST||l.beforeHash!=LANGUAGE_EXPECTED_HASH||!l.permissionAllowed||!l.categoryAllowed)return false;
  for(unsigned i=0;i<o.count;++i)if(l.rows[i].blockedBefore)return false;
 }return true;
}
bool languageFinish(const GameContextSnapshot& s,PropertyReceipt& o){
 auto& l=o.language;const U frozenHash=l.beforeHash;const unsigned frozenCount=l.beforeCount;
 if(!languageCapture(s,o,false)||l.beforeHash!=frozenHash||l.beforeCount!=frozenCount)return false;
 bool need=false;for(unsigned i=0;i<o.count;++i)if(!l.rows[i].beforeEntry||!l.rows[i].beforeFound||!sameText(l.rows[i].before,l.rows[i].source))need=true;
 if constexpr(PROPERTIES_WRITE!=0){if(need){
  Edit start{},now{};if(!edit(s.moduleBase,s.global,0,start)||start.count||start.depth!=start.base||!permissions(s,l)||!l.permissionAllowed||!l.categoryAllowed)return false;
  l.uncertain=1;l.openCalled=1;++o.nativeCalls;l.transaction=reinterpret_cast<U>(native<void*(*)(void*,bool,bool)>(s.moduleBase,0xe827750)(nullptr,false,false));bool good=false;
  do{if(!l.transaction||!edit(s.moduleBase,s.global,0,now)||now.count||now.depth!=start.depth+1)break;
   l.snapshotCalled=1;native<void(*)(void*,void*,bool)>(s.moduleBase,0x107abdf0)(reinterpret_cast<void*>(l.property),nullptr,false);
   if(!edit(s.moduleBase,s.global,l.property,now)||now.count!=1||now.depth!=start.depth+1||now.dirty)break;l.record=now.record;l.blob=now.blob;l.stage=2;
   bool all=true;for(unsigned i=0;i<o.count;++i){auto& row=l.rows[i];if(row.beforeEntry&&row.beforeFound&&sameText(row.before,row.source))continue;
    U entry=row.beforeEntry;char utf8[512]{};const int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,reinterpret_cast<const wchar_t*>(row.source.value),static_cast<int>(row.source.length),utf8,sizeof(utf8),nullptr,nullptr);
    const U str=n>0?reinterpret_cast<U>(native<void*(*)(const char*,int)>(s.moduleBase,0x526de0)(utf8,n)):0;if(!str){all=false;break;}
    if(!entry){
     // A real class44983 managed object, initialized by its constructor. Source
     // setter and category List<uint>.Add are the same native field/list paths
     // used by collection; no permissions or blocked flags are written.
     entry=reinterpret_cast<U>(native<void*(*)(void*)>(s.moduleBase,0x52aa00)(reinterpret_cast<void*>(ptr(s.moduleBase+0x57e86e0))));if(!entry){all=false;break;}
     native<void(*)(void*)>(s.moduleBase,0x11796a70)(reinterpret_cast<void*>(entry));
     native<void(*)(void*,unsigned,void*)>(s.moduleBase,0x11796300)(reinterpret_cast<void*>(entry),0x3b46cf2b,reinterpret_cast<void*>(str));
     const U categories=ptr(entry+0x28);if(!categories){all=false;break;}native<void(*)(void*,unsigned)>(s.moduleBase,0x18277b60)(reinterpret_cast<void*>(categories),16);
     const U add=ptr(s.moduleBase+0x58bee50);if(!add){all=false;break;}native<void(*)(void*,void*,void*)>(s.moduleBase,0x18baf8c0)(reinterpret_cast<void*>(l.list),reinterpret_cast<void*>(entry),reinterpret_cast<void*>(add));row.created=1;++l.created;
    }
    row.setterCalled=1;native<void(*)(void*,unsigned,void*)>(s.moduleBase,0x11796450)(reinterpret_cast<void*>(entry),l.primaryLanguage,reinterpret_cast<void*>(str));
   }if(!all)break;l.notifyCalled=1;native<void(*)(void*,void*)>(s.moduleBase,0x9c26c70)(reinterpret_cast<void*>(start.manager),reinterpret_cast<void*>(l.property));
   if(!edit(s.moduleBase,s.global,l.property,now)||now.record!=l.record||now.blob!=l.blob||now.dirty!=1)break;good=true;
  }while(false);
  if(l.transaction&&edit(s.moduleBase,s.global,l.property,now)&&now.depth==start.depth+1){l.closeCalled=1;native<void(*)(void*)>(s.moduleBase,0xc7bab90)(reinterpret_cast<void*>(l.transaction));if(edit(s.moduleBase,s.global,0,now)&&!now.count&&now.depth==start.depth)l.closed=1;}
  if(!good||!l.closed)return false;
 }}else{(void)need;}
 if(!languageCapture(s,o,true)||l.guardBefore!=l.guardAfter)return false;l.guardsUnchanged=1;
 for(unsigned i=0;i<o.count;++i){auto& row=l.rows[i];if constexpr(PROPERTIES_WRITE!=0){if(!row.afterEntry||!row.afterFound||row.blockedAfter||!sameText(row.source,row.after))return false;row.verified=1;}else{if(row.beforeEntry!=row.afterEntry||row.beforeFound!=row.afterFound||row.blockedBefore!=row.blockedAfter||!sameText(row.before,row.after))return false;}}
 l.stage=3;l.status=0;l.uncertain=0;return true;
}
