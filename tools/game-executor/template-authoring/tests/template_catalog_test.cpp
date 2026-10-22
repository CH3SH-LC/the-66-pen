#include "../template_catalog.h"
#include <cstdio>
#include <stdexcept>
using namespace ge::templates;
namespace {int checks=0;void check(bool ok) {if(!ok)throw std::runtime_error("catalog delta");++checks;}}
int main() {
    try {
        TemplateIdentity old[]={{1119879169,12,0x11000,0x21000},{1136656385,17,0x12000,0x22000}};
        TemplateIdentity rows[]={old[1],{1115684865,11,0x13000,0x23000},old[0]};
        TemplateCatalogView before{old,2,0x10000,1073741842,true};
        TemplateCatalogView after{rows,3,0x10000,1073741842,true};
        auto verify=[&] {return VerifySingleMainTemplateCreated(before,after,11,0x23000,0x13000);};
        check(verify().code==CatalogCode::verified && verify().added.id==1115684865);
        // Reordering is valid, replacement of an old identity is not.
        rows[2].resource=0x14000;check(verify().code==CatalogCode::prior_resource_changed);rows[2]=old[0];
        rows[2].klass=0x24000;check(verify().code==CatalogCode::prior_resource_changed);rows[2]=old[0];
        rows[2].subtype=13;check(verify().code==CatalogCode::prior_resource_changed);rows[2]=old[0];
        after.complete=false;check(verify().code==CatalogCode::incomplete);after.complete=true;
        before.complete=false;check(verify().code==CatalogCode::incomplete);before.complete=true;
        after.manager=0x18000;check(verify().code==CatalogCode::context_changed);after.manager=before.manager;
        ++after.level_id;check(verify().code==CatalogCode::context_changed);after.level_id=before.level_id;
        after.count=2;check(verify().code==CatalogCode::count_mismatch);after.count=3;
        rows[1].id=old[0].id;check(verify().code==CatalogCode::invalid_catalog);rows[1].id=1115684865;
        rows[1].resource=old[0].resource;check(verify().code==CatalogCode::invalid_catalog);rows[1].resource=0x13000;
        rows[1].resource=0x14000;check(verify().code==CatalogCode::added_resource_mismatch);rows[1].resource=0x13000;
        rows[1].klass=0x24000;check(verify().code==CatalogCode::added_resource_mismatch);rows[1].klass=0x23000;
        rows[1].id=1107296257;check(verify().code==CatalogCode::added_resource_mismatch);
        rows[1].subtype=9;check(VerifySingleMainTemplateCreated(before,after,9,0x23000).code==CatalogCode::verified);
        rows[1].id=1098907649;rows[1].subtype=6;
        check(VerifySingleMainTemplateCreated(before,after,6,0x23000).code==CatalogCode::invalid_request);
        rows[1].id=1107296257;rows[1].subtype=9;
        rows[1].id|=0x80000000U;
        check(VerifySingleMainTemplateCreated(before,after,9,0x23000).code==CatalogCode::added_resource_mismatch);
        check(VerifySingleMainTemplateCreated(before,after,10,0x23000).code==CatalogCode::invalid_request);
        check(VerifySingleMainTemplateCreated(before,after,9,0x23001).code==CatalogCode::invalid_request);
        TemplateCatalogView empty{nullptr,0,0x10000,1073741842,true};
        TemplateIdentity one{1107296257,9,0x13000,0x23000};
        TemplateCatalogView oneview{&one,1,0x10000,1073741842,true};
        check(VerifySingleMainTemplateCreated(empty,oneview,9,0x23000).code==CatalogCode::verified);
        oneview.rows=nullptr;check(VerifySingleMainTemplateCreated(empty,oneview,9,0x23000).code==CatalogCode::invalid_catalog);
        std::printf("template catalog: %d checks passed; synthetic observations only\n",checks);
        return 0;
    } catch(const std::exception& e) {std::fprintf(stderr,"%s\n",e.what());return 1;}
}
