"""Offline cross-level ownership contract regression; does not prepare or dispatch a native card."""
import json
from ownership_contract import validate_selection


def main():
    checks = []
    def check(label, doc, level, digest="a"*64, hosts=(1,2), children=(3,), pairs=None, error=None):
        pair = {"accessoryId":3,"oldHostId":1,"hostId":2}
        try:
            validate_selection(doc, level, digest, hosts, children, pairs or [pair], "reparent")
            checks.append({"name":label,"ok":error is None})
        except Exception as exc:
            checks.append({"name":label,"ok":bool(error and error in str(exc)),"error":str(exc)})
    for level in (1073741901,1073741902):
        document = {"schemaVersion":1,"kind":"miliastra-ownership-v1","levelId":level,"saveSha256":"a"*64,
                    "entityIds":[1,2],"accessoryIds":[3],"operations":{
                        "reparent":[{"accessoryId":3,"oldHostId":1,"hostId":2}]}}
        check("explicit_level_"+str(level),document,level)
        check("wrong_level_"+str(level),document,level+1,error="OWNERSHIP_SAVE_OR_LEVEL_DRIFT")
        check("wrong_save_"+str(level),document,level,digest="b"*64,error="OWNERSHIP_SAVE_OR_LEVEL_DRIFT")
        check("foreign_host_"+str(level),document,level,hosts=(1,4),error="OWNERSHIP_SELECTION")
        check("foreign_child_"+str(level),document,level,children=(4,),error="OWNERSHIP_SELECTION")
        check("unselected_pair_"+str(level),document,level,
              pairs=[{"accessoryId":3,"oldHostId":2,"hostId":1}],error="OWNERSHIP_PAIR_NOT_SELECTED")
        check("protected_level_"+str(level),dict(document,levelId=1073741842),1073741842,
              error="OWNERSHIP_PROTECTED")
    from saved_assembly import saved_world
    from types import SimpleNamespace
    def vector(values):
        return SimpleNamespace(triple=lambda:tuple(values))
    host=SimpleNamespace(transform=SimpleNamespace(position=vector([10,20,30]),
        rotation=vector([0,90,0]),scale=vector([2,2,2])))
    child=SimpleNamespace(transform=SimpleNamespace(position=vector([1,0,0]),
        rotation=vector([0,0,0]),scale=vector([1,1,1])))
    world=saved_world(host,child)
    checks.append({"name":"world_pose_keeps_rotation_scale_translation",
                   "ok":all(abs(a-b)<1e-10 for a,b in zip(world["position"],[10,20,28]))
                   and world["scale"]==(2,2,2)})
    # Regression against actual saved records, with no current-state/installer dependency.
    from pathlib import Path
    import tempfile
    import dataclasses
    import hashlib
    from saved_assembly import ROOT, records, accessories, nested_records, static_flag, component_ids
    from gil_container import parse_fields, encode_fields, decode_container, encode_container, LEVEL_FIELD_ID
    from reparent_build import check_saved
    original=ROOT/"data/codex-main-street/knights-rebuild/upper-stair-wall-repair/backups/1073741846.gil"
    if original.exists():
        raw,rows=records(original)
        children=nested_records(raw,set(accessories(raw)))
        selected=None
        for child_id,(_,child) in children.items():
            parents=component_ids(child.component(5,40),502)
            if len(parents)!=1 or parents[0] not in rows:
                continue
            old=rows[parents[0]]
            if static_flag(old)!=1 or old.component(6,3).payload.data:
                continue
            for new_id,new in rows.items():
                scale=new.transform.scale.triple() if new.transform else ()
                if new_id==parents[0] or not scale or static_flag(new)!=1 or new.component(6,3).payload.data:
                    continue
                if min(scale)<=0 or max(scale)-min(scale)>.0001 or new.component(6,22).payload.data!=child.component(6,22).payload.data:
                    continue
                if len(component_ids(new.component(5,40),501))>=999:
                    continue
                selected=({"accessoryId":child_id,"oldHostId":parents[0],"hostId":new_id},
                          {parents[0]:old.tag,new_id:new.tag})
                break
            if selected:
                break
        if selected:
            base=ROOT/".runtime/ai-workbench-validation"
            base.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="ownership-",dir=base) as temporary:
                folder=Path(temporary)
                assert folder.resolve().is_relative_to(base.resolve())
                container=decode_container(raw)
                payload=encode_fields([f for f in parse_fields(container.payload) if f.number!=LEVEL_FIELD_ID])
                for level in (1073741901,1073741902):
                    save=folder/f"save{level}.gil"
                    save.write_bytes(encode_container(dataclasses.replace(container,payload=payload)))
                    pair,templates=selected
                    document={"schemaVersion":1,"kind":"miliastra-ownership-v1","levelId":level,
                        "saveSha256":hashlib.sha256(save.read_bytes()).hexdigest(),"entityIds":list(templates),
                        "accessoryIds":[pair["accessoryId"]],"operations":{"reparent":[pair]}}
                    ownership=folder/"ownership.json"
                    ownership.write_text(json.dumps(document),encoding="utf-8")
                    digest,poses=check_saved(save,[pair],templates,ownership,level)
                    checks.append({"name":"real_saved_geometry_on_foreign_level_"+str(level),
                                   "ok":digest==document["saveSha256"] and str(pair["accessoryId"]) in poses})
        else:
            checks.append({"name":"actual_saved_accessory_fixture_available","ok":False})
    report={"ok":all(c["ok"] for c in checks),"checks":checks,"nativeCalled":False}
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
