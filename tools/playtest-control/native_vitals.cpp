// Read-only runtime properties. No graph calls, damage calls, inventory writes,
// managed decode failure reporting, property initializers, or virtual calls.
#include "native_vitals.h"
#include "native_control.cpp"
#if VITALS_OPERATION != 13 || CONTROL_OPERATION != 3
#error "Dedicated bound read-only vitals card required"
#endif
namespace {
bool vitalsCode(U b,VitalsReceipt* o){
    static constexpr unsigned rvas[]={VITALS_CODE_RVAS};static constexpr unsigned char expected[][32]={VITALS_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->control.observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={VITALS_HOTFIX_RVAS};for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->control.observation.failedRva=r;return false;}}return true;
}
bool derives(U klass,U base){
    if(!klass||!base)return false;if(klass==base)return true;
    unsigned char depth=0,total=0;if(!read(base+0xc5,depth)||!depth||depth>64||!read(klass+0xc5,total)||total<depth||total>64)return false;
    const U hierarchy=ptr(klass+0x40);return hierarchy&&ptr(hierarchy+8ULL*(depth-1))==base;
}
// 9391b70's successful branch. Copy the already-existing 12x256 substitution
// rows; refuse malformed bounds/checksum. Never call its failure reporter.
unsigned decodeHp(const unsigned char* raw,const unsigned char* table,float& value){
    bool zero=true;for(unsigned i=0;i<16;++i)zero=zero&&raw[i]==0;if(zero){value=0;return 0;}
    std::uint32_t seed=0;for(unsigned i=0;i<4;++i)seed|=static_cast<std::uint32_t>(table[(8+i)*256+raw[i]])<<(8*i);
    const auto signedSeed=static_cast<std::int32_t>(seed);const int remainder=signedSeed%12;
    std::uint32_t values[3]{};for(unsigned group=0;group<3;++group)for(unsigned i=0;i<4;++i){
        const int index=(remainder+static_cast<int>(i)+static_cast<int>(group*4))%12;
        const unsigned word=index>=4?1U:0U,shift=(static_cast<unsigned>(index)*8U+32U)&63U;
        U encoded=0;std::memcpy(&encoded,raw+word*8,8);const unsigned byte=static_cast<unsigned>((encoded>>shift)&255U);
        values[group]|=static_cast<std::uint32_t>(table[(8+i)*256+byte])<<(8*i);
    }
    const std::uint32_t bits=seed^values[1];if((values[0]^bits)!=values[2])return 3;
    float decoded=0;std::memcpy(&decoded,&bits,4);if(!std::isfinite(decoded)||decoded<0)return 4;value=decoded;return 0;
}
bool tableSample(U global,U expected,unsigned char* output,U& table){
    table=ptr(global+0x36520);if(!table||(expected&&table!=expected))return false;
    const U bounds=ptr(table+0x10);U capacity=0;
    // Current IL2CPP bounds: 8-byte length, 4-byte lower bound, 4-byte padding.
    std::int32_t lower0=1,lower1=1;U rowLength=0,columnLength=0;
    if(!bounds||!read(bounds,rowLength)||!read(bounds+8,lower0)||!read(bounds+16,columnLength)||!read(bounds+24,lower1)||lower0||lower1||rowLength<12||rowLength>64||columnLength!=256||!read(table+0x18,capacity)||capacity!=rowLength*columnLength)return false;
    return memory(table+0x20,output,kVitalsTable);
}
bool vitalsContext(U global,VitalsReceipt* o,VitalsContext& c,bool first){
    const U manager=ptr(global+0x9d50),dictionary=ptr(manager+0x1e8),entries=ptr(dictionary+0x28);U comparer=1,capacity=0;
    if(!manager||!dictionary||!read(dictionary+0x30,comparer)||comparer||!read(dictionary+0x38,c.count)||c.count>65536||!read(dictionary+0x3c,c.version)||!read(manager+0x250,c.avatarId))return false;
    if(c.count&&(!entries||!read(entries+0x18,capacity)||capacity<c.count||capacity>65536))return false;
    c.capacity=static_cast<unsigned>(capacity);
    if(first){o->dictionary=dictionary;o->entries=entries;return true;}
    return o->dictionary==dictionary&&o->entries==entries;
}
void vitalRow(U b,U entity,unsigned id,unsigned index,bool local,const unsigned char* table,bool tableOk,VitalsRow& row){
    row.entity=entity;row.id=id;row.entryIndex=index;row.localAvatar=local?1U:0U;row.status=row.hpStatus=row.lifeStatus=1;row.klass=ptr(entity);
    if(!derives(row.klass,ptr(b+0x57dbd80)))return;
    unsigned observed=0;unsigned char alive=255,loaded=255,ready=255,cleared=255;U eventDispatcher=0;
    if(!read(entity+0x3a8,observed)||observed!=id||!read(entity+0x4dc,row.configId)||!read(entity+0x458,row.entityType)||!read(entity+0x49b,alive)||alive>1||!read(entity+0x42f,loaded)||loaded>1||!read(entity+0x482,ready)||ready>1||!read(entity+0x491,cleared)||cleared>1||!read(entity+0x1a0,eventDispatcher))return;
    const unsigned recycled=eventDispatcher==0?1U:0U;
    row.alive=alive;row.flags=loaded|(ready<<1)|(cleared<<2)|(recycled<<3);row.status=0;
    // The raw native isAlive flag is retained even for loading/recycled rows.
    // A lifecycle interpretation requires a fully loaded, ready, uncleared row.
    if(loaded&&ready&&!cleared&&!recycled)row.lifeStatus=0;
    const U manager=ptr(entity+0x2d0),array=ptr(manager+0x68);U length=0;
    if(!array||!read(array+0x18,length)||length<=13||length>4096)return;
    row.component=ptr(array+0x20+13*8);const U componentClass=ptr(row.component);
    if(!derives(componentClass,ptr(b+0x57d4e40))||ptr(row.component+0x28)!=entity)return;
    row.properties=ptr(row.component+0x138);if(!derives(ptr(row.properties),ptr(b+0x583b038)))return;
    if(!memory(row.properties+0x5e0,row.currentEncoded,16)||!memory(row.properties+0x570,row.maxEncoded,16)){row.hpStatus=2;return;}
    if(!tableOk){row.hpStatus=5;return;}
    const unsigned cur=decodeHp(row.currentEncoded,table,row.currentHp),max=decodeHp(row.maxEncoded,table,row.maxHp);
    row.hpStatus=cur?cur:max; // zero is valid only after positive property ownership.
}
bool enumerateVitals(U b,VitalsReceipt* o){
    const auto& s=o->control.observation.after;o->avatar=s.avatar;o->count=1;o->pageEnd=VITALS_PAGE_START;
    vitalRow(b,s.avatar,s.avatarId,0xffffffffU,true,o->tableBefore,o->tableStatus==0,o->first[0]);
    for(unsigned i=VITALS_PAGE_START;i<o->before.count&&o->count<kVitalsRows;++i){
        if(GetTickCount64()>=HR_DEADLINE)return false;
        const U at=o->entries+0x20+24ULL*i;std::int32_t hash=0;unsigned id=0;
        if(!read(at,hash))return false;o->pageEnd=i+1;if(hash<0)continue;
        const U entity=ptr(at+16);if(!entity||!read(at+8,id)||!id)return false;
        if(entity==s.avatar){if(id!=s.avatarId)return false;continue;}
        for(unsigned j=0;j<o->count;++j)if(o->first[j].id==id)return false;
        vitalRow(b,entity,id,i,false,o->tableBefore,o->tableStatus==0,o->first[o->count++]);
    }
    return true;
}
void vitals(VitalsReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!vitalsCode(b,o))return;
    ExecuteControl(&o->control);const auto& control=o->control;
    if(control.status||!control.stateStable||!control.observation.stable||!control.after.trialReady||control.after.exitReady||!bound(control.after)||control.observation.after.avatarStatus!=2)return;
    if(!vitalsContext(control.after.global,o,o->before,true)||VITALS_PAGE_START>o->before.count)return;o->stage=2;
    o->tableStatus=tableSample(control.after.global,0,o->tableBefore,o->table)?0U:1U;
    if(!enumerateVitals(b,o))return;
    U secondTable=0;const bool secondTableOk=tableSample(control.after.global,o->table,o->tableAfter,secondTable);
    if(o->tableStatus==0&&(!secondTableOk||std::memcmp(o->tableBefore,o->tableAfter,kVitalsTable)))o->tableStatus=2;
    for(unsigned i=0;i<o->count;++i){const auto& row=o->first[i];
        if(!row.localAvatar){const U at=o->entries+0x20+24ULL*row.entryIndex;std::int32_t hash=-1;unsigned id=0;if(!read(at,hash)||hash<0||!read(at+8,id)||id!=row.id||ptr(at+16)!=row.entity)return;}
        vitalRow(b,row.entity,row.id,row.entryIndex,row.localAvatar!=0,o->tableAfter,o->tableStatus==0,o->second[i]);
    }
    o->dictionaryStable=vitalsContext(control.after.global,o,o->after,false)&&std::memcmp(&o->before,&o->after,sizeof(VitalsContext))==0?1U:0U;
    o->samplesStable=std::memcmp(o->first,o->second,sizeof(VitalsRow)*o->count)==0?1U:0U;
    // Read trial identity and local avatar again after all runtime reads.
    PlaySample last{};const unsigned readable=sample(b,last,&o->control.observation);
    if(readable!=o->control.observation.readableAfter||!stable(o->control.observation.after,last))return;
    TrialState finish{};state(b,last,finish,&o->control);if(std::memcmp(&control.after,&finish,sizeof(finish))||!bound(finish))return;
    o->stage=3;o->status=o->dictionaryStable&&o->samplesStable?0U:2U;
}
}
void ExecuteVitals(VitalsReceipt* o) noexcept {
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=4;o->status=1;o->stage=1;o->operation=VITALS_OPERATION;o->resourcesReleased=1;o->pageStart=VITALS_PAGE_START;o->pageEnd=VITALS_PAGE_START;o->tableStatus=1;
    auto& c=o->control;c.bytes=sizeof(c);c.version=2;c.status=1;c.stage=1;c.operation=3;c.resourcesReleased=1;c.observation.bytes=sizeof(PlayReceipt);c.observation.version=1;c.observation.status=1;c.observation.targetLevel=PLAY_TARGET_LEVEL;c.observation.before.positionStatus=c.observation.after.positionStatus=1;
    __try{vitals(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
