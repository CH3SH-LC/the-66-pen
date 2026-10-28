"""Prepare one immutable transfer card for existing static model accessories."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import struct
import sys
from collections import Counter
import json
from contract import read, write, sha, require, identifier, POSE_KEYS
import build as b
import assembly_build as ab

KIND = "entity-accessory-reparent-prepared-v1"
BUILD_KIND = "entity-accessory-reparent-build-v1"
SCOPE = "FIXED_EXISTING_ACCESSORY_REPARENT"
HERE = Path(__file__).resolve().parent
FILES = ("reparent_build.py", "reparent_receipt.py", "native_reparent.h",
         "native_reparent.cpp", "reparent-profile.json", "ownership_contract.py", "saved_assembly.py")


def validate_pairs(pairs):
    require(isinstance(pairs, list) and 1 <= len(pairs) <= 512, "REPARENT_BATCH_1_TO_512")
    result = []
    for item in pairs:
        require(isinstance(item, dict) and set(item) == {"accessoryId", "oldHostId", "hostId"},
                "REPARENT_PAIR_FIELDS")
        q = {k: identifier(v) for k, v in item.items()}
        require(len(set(q.values())) == 3, "REPARENT_SELF_PARENT")
        result.append(q)
    require(len({q["accessoryId"] for q in result}) == len(result), "REPARENT_DUPLICATE_CHILD")
    hosts = {q[k] for q in result for k in ("oldHostId", "hostId")}
    require(len(hosts) <= 128 and not hosts & {q["accessoryId"] for q in result},
            "REPARENT_ENTITY_PREFLIGHT_LIMIT")
    return result


def check_saved(path, pairs, templates, ownership=None, level=None):
    from saved_assembly import records, nested_records, component_ids, saved_world, accessories, static_flag
    raw, entities = records(Path(path))
    children = {i: r for i, (_, r) in nested_records(raw, set(accessories(raw))).items()}
    if ownership:
        from ownership_contract import check
        check(ownership, level, path, templates, [q["accessoryId"] for q in pairs],
              pairs, "reparent")
    else:
        raise ValueError("EXPLICIT_OWNERSHIP_REQUIRED_IN_PUBLIC_RELEASE")
    for eid, tag in templates.items():
        r = entities[eid]
        require(r.tag == tag and static_flag(r) == 1 and
                r.component(6, 3).payload.data == b"", "REPARENT_STATIC_NO_LOGIC")
    counts = Counter({eid: len(component_ids(entities[eid].component(5, 40), 501))
                      for eid in templates})
    expected = {}
    for q in pairs:
        r = children[q["accessoryId"]]
        old, new = entities[q["oldHostId"]], entities[q["hostId"]]
        require(component_ids(r.component(5, 40), 502) == [q["oldHostId"]] and
                not component_ids(r.component(5, 40), 501), "REPARENT_CHILD_RELATION")
        require(q["accessoryId"] in component_ids(old.component(5, 40), 501) and
                q["accessoryId"] not in component_ids(new.component(5, 40), 501),
                "REPARENT_HOST_RELATION")
        scale = new.transform.scale.triple()
        require(min(scale) > 0 and max(scale)-min(scale) <= .0001, "REPARENT_UNIFORM_HOST")
        require(20001000 <= r.tag < 20010000, "REPARENT_BUILTIN_MODEL")
        require(r.component(6,22).payload.data == new.component(6,22).payload.data,
                "REPARENT_MATERIAL_INHERITANCE")
        counts[q["oldHostId"]] -= 1
        counts[q["hostId"]] += 1
        require(0 <= counts[q["oldHostId"]] <= 999 and counts[q["hostId"]] <= 999,
                "REPARENT_CAPACITY")
        expected[str(q["accessoryId"])] = dict(modelId=r.tag,
            world=saved_world(old, r), recordSha256=__import__("hashlib").sha256(r.raw_bytes).hexdigest())
    require(Path(path).read_bytes() == raw, "REPARENT_SAVE_CHANGED")
    return sha(path), expected


def sources(run):
    hashes = ab.sources(run)
    dest = run / "candidate-source/entity-transform"
    original = (dest / "native_assembly.cpp").read_text(encoding="utf-8")
    (dest / "native_assembly_legacy.cpp").write_text(original, encoding="utf-8")
    for name in FILES:
        path = HERE / name
        hashes[str(path)] = sha(path)
        (dest / name).write_bytes(path.read_bytes())
    text = (dest / "native_reparent.cpp").read_text(encoding="utf-8")
    (dest / "native_assembly.cpp").write_text(
        text.replace('#include "native_assembly.cpp"', '#include "native_assembly_legacy.cpp"'),
        encoding="utf-8")
    for name in ("hook_receipt_protocol.h", "hook_receipt.cpp", "hook_receipt_probe.cpp"):
        path = run / "candidate-source/native" / name
        text = path.read_text(encoding="utf-8")
        text = text.replace("native_assembly.h", "native_reparent.h")
        text = text.replace("AssemblyReceipt assembly;", "ReparentReceipt assembly;")
        text = text.replace("ExecuteAssembly(", "ExecuteReparent(")
        if name == "hook_receipt_probe.cpp":
            # The 512-item transfer can outlive the legacy 60-second mutation
            # wait. Keep its mapping until this bounded 240-second wait ends;
            # retain the original unhook, drain, expiry, and no-replay guards.
            old = "(HR_ACTION ? 60000 : 10000)"
            require(text.count(old) == 1, "REPARENT_WAIT_SOURCE_DRIFT")
            text = text.replace(old, "(HR_ACTION ? 240000 : 10000)")
        # Outer transport checks read the status in the embedded common header.
        for key in ("status", "seh", "completed", "count", "sceneUnchanged"):
            text = text.replace("receipt->assembly." + key, "receipt->assembly.common." + key)
        if name == "hook_receipt_probe.cpp":
            old = "receipt->assembly.common.completed == receipt->assembly.common.count"
            require(text.count(old) == 1, "REPARENT_PREFIX_PROBE_SOURCE_DRIFT")
            text = text.replace(old,
                "(receipt->assembly.common.completed == receipt->assembly.common.count || "
                "(receipt->assembly.common.version == 3 && receipt->assembly.budgetExceeded == 1 && "
                "receipt->assembly.batchClosed == 1 && receipt->assembly.common.failedValue == 309 && "
                "receipt->assembly.common.stage == 5 && receipt->assembly.common.mode == 1 && "
                "receipt->assembly.common.completed > 0 && "
                "receipt->assembly.common.completed < receipt->assembly.common.count && "
                "receipt->assembly.common.completed == receipt->assembly.common.mutationCalls))")
        path.write_text(text.replace(ab.SCOPE, SCOPE), encoding="utf-8")
    return hashes


def prepare(args, compile_only=False):
    profile = b.p.load_profile()
    b.p.verify_disk(profile)
    runtime, route = read(b.HERE/"runtime-profile.json"), read(HERE/"reparent-profile.json")
    metadata = b.p.TARGET_IMAGE.parent/"YuanShen_Data/Managed/Metadata/global-metadata.dat"
    require(route["imageSha256"] == runtime["imageSha256"] == profile["image"]["sha256"] and
            sha(metadata) == route["metadataSha256"], "REPARENT_BUILD_DRIFT")
    mode = int(args.mode == "set")
    if compile_only:
        raw = bytearray(262584 if args.large_scene else 33208)
        struct.pack_into("<II", raw, 0, len(raw), 2 if args.large_scene else 1)
        raw = bytes(raw)
        session = dict(pid=1, tid=1, processCreation=1, threadCreation=1,
                       image=str(b.OUTPUT/"compile-only.invalid"))
        level, origin = 1073741846, [0., 0., 0.]
        if getattr(args, "compile_level", None) is not None:
            level = identifier(args.compile_level)
        pairs = [dict(accessoryId=1000+i, oldHostId=1, hostId=2) for i in range(64)]
        templates = {1:20001340, 2:20001340}
        expected = {str(q["accessoryId"]):dict(modelId=20001340,
            world=dict(position=[0.,0.,0.],scale=[1.,1.,1.],rotationQuaternion=[0.,0.,0.,1.]))
            for q in pairs}
    else:
        session, snapshot, raw = b.baseline(args.baseline)
        session = b.p.validate_session(session)
        level, origin = snapshot["levelObservation"]["levelId"], snapshot["origin"]
        request = read(args.request)
        require(set(request) == {"schemaVersion", "levelId", "pairs"} and
                request["schemaVersion"] == 1 and request["levelId"] == level and
                (level == 1073741846 or getattr(args, "ownership", None) is not None),
                "REPARENT_TARGET_LEVEL")
        pairs = validate_pairs(request["pairs"])
        require(len(pairs) <= 64, "REPARENT_TIMED_BATCH_MAX_64")
        entities = {r["id"]:r for r in snapshot["entities"]}
        ids = {q[k] for q in pairs for k in ("oldHostId", "hostId")}
        require(ids <= entities.keys(), "REPARENT_HOST_NOT_IN_SCENE")
        templates = {eid:entities[eid]["configId"] for eid in sorted(ids)}
        require(args.save is not None, "REPARENT_SAVE_REQUIRED")
        reviewed_sha, expected = check_saved(args.save, pairs, templates,
                                             getattr(args, "ownership", None), level)
    empty = {k:[0.,0.,0.] for k in POSE_KEYS}
    empty["scale"] = [1.,1.,1.]
    requests = [dict(entityId=eid, mask=0, requireRoot=0, expectedFrame=0,
                    expectedParent=0, expected=empty, desired=empty) for eid in sorted(templates)]
    run = b.ro.output_directory(b.OUTPUT)
    (run/"baseline-snapshot.bin").write_bytes(raw)
    hashes = sources(run)
    if not compile_only and getattr(args, "ownership", None):
        hashes[str(Path(args.ownership).resolve())] = sha(args.ownership)
    hashes[str(metadata)] = route["metadataSha256"]
    backups = b.backups(run, args.save, level) if mode and not compile_only else []
    if compile_only:
        harness = HERE/"reparent_callback_startup.cpp"
        hashes[str(harness)] = sha(harness)
        (run/"candidate-source/entity-transform/callback_startup.cpp").write_bytes(harness.read_bytes())
    else:
        require(sha(args.save) == reviewed_sha, "REPARENT_SAVE_REVIEW_CHANGED")
        hashes[str(Path(args.save).resolve())] = reviewed_sha
    deadline, nonce = b.emit_header(run, profile, runtime, session, raw, level, requests, 0, not compile_only)
    header = run/"target_config.h"
    text = b.replace(header.read_text(encoding="utf-8"), "#define HR_ACTION 13ULL", "#define HR_ACTION 17ULL")
    text += f"\n#define ASSEMBLY_REVIEWED 1\n#define ASSEMBLY_WRITE {mode}\n"
    text += f"#define REPARENT_AUTHORIZED_LEVEL {level}U\n"
    text += "#define ASSEMBLY_COUNT 1U\n#define ASSEMBLY_PAIRS {1U,2U}\n"
    text += f"#define REPARENT_REVIEWED 1\n#define REPARENT_COUNT {len(pairs)}U\n"
    def literal(q):
        item = expected[str(q["accessoryId"])]
        w = item["world"]
        def vector(values, suffix):
            return "{"+",".join(format(float(v), ".17g")+
                (".0" if "." not in format(float(v), ".17g") and
                 "e" not in format(float(v), ".17g") else "")+suffix for v in values)+"}"
        return ("{"+",".join(str(q[k])+"U" for k in ("accessoryId", "oldHostId", "hostId"))+
            ","+str(item["modelId"])+"U,"+
            vector([x+y for x,y in zip(w["position"],origin)],"f")+","+
            vector(w["scale"],"f")+","+vector(w["rotationQuaternion"],"")+"}")
    text += "#define REPARENT_REQUESTS " + ",".join(literal(q) for q in pairs) + "\n"
    text += "#define ASSEMBLY_CODE_RVAS " + ",".join(x["rva"] for x in route["functions"])+"\n"
    text += "#define ASSEMBLY_CODE_BYTES " + ",".join(
        "{"+",".join(hex(v) for v in bytes.fromhex(x["head32"]))+"}" for x in route["functions"])+"\n"
    text += "#define ASSEMBLY_HOTFIX_RVAS " + ",".join(route["hotfixZeroRvas"])+"\n"
    text += "#define ASSEMBLY_USAGE_GROUPS " + ",".join(route["usageGroups"])+"\n"
    header.write_text(text, encoding="utf-8")
    b.compile_card(run, assembly=True, startup_fixture=compile_only)
    for path,digest in hashes.items():
        require(sha(path) == digest, "REPARENT_SOURCE_CHANGED")
    prepared = dict(schemaVersion=1, kind=KIND, run=str(run), action=17, receiptVersion=21,
        mode="reparent-set" if mode else "reparent-inspect", launchable=not compile_only,
        reparentAbi=3, transactionScope="whole-batch", callbackBudgetMillis=2000,
        allowBudgetPrefix=True,
        compileOnly=compile_only, session=session, levelId=level, origin=origin,
        ownershipManifest=str(Path(args.ownership).resolve()) if getattr(args, "ownership", None) else None,
        requests=requests, pairs=pairs, templateIds=templates, expectedAccessories=expected,
        sourceHashes=hashes, recovery=backups, deadlineTick=deadline, nonce=str(nonce),
        createdUtc=datetime.now(timezone.utc).isoformat(),
        expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        nativeSnapshotVersion=struct.unpack_from("<I",raw,4)[0],
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,
        imagePath=str(b.p.TARGET_IMAGE), imageSha256=profile["image"]["sha256"])
    prepared["artifacts"] = {x.relative_to(run).as_posix():sha(x) for x in run.rglob("*") if x.is_file()}
    write(run/"prepared.json", prepared)
    if not compile_only:
        pins = dict(hashes)
        pins.update({str(run/name):digest for name,digest in prepared["artifacts"].items()})
        pins[str(run/"prepared.json")] = sha(run/"prepared.json")
        pins[str(b.p.TARGET_IMAGE)] = profile["image"]["sha256"]
        pins.update({x["source"]:x["sha256"] for x in backups})
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        wrapper = (b.HERE/"invoke.template.ps1").read_text(encoding="utf-8")
        wrapper = wrapper.replace("FIXED_ENTITY_TRANSFORM_ACTION", SCOPE)
        wrapper = wrapper.replace("entity-transform-build-v1", BUILD_KIND)
        wrapper = wrapper.replace("@@EXPIRES@@", quote(prepared["expiresUtc"]))
        wrapper = wrapper.replace("@@PINS@@", ",\n".join(
            "    @("+quote(path)+","+quote(digest)+")" for path,digest in sorted(pins.items())))
        require("@@" not in wrapper, "REPARENT_WRAPPER_PLACEHOLDER")
        (run/"invoke-transform.ps1").write_text(wrapper, encoding="utf-8-sig")
    result = dict(ok=True, kind=BUILD_KIND, run=str(run), compiled=True,
        launchable=not compile_only, mode=prepared["mode"], actionCode=17, receiptVersion=21,
        called=False, nativeStarted=False, outcomeUncertain=False, cleanupVerified=True,
        safeToRelease=True, replayForbidden=False, preparedSha256=sha(run/"prepared.json"),
        wrapperSha256=sha(run/"invoke-transform.ps1") if not compile_only else None)
    write(run/"build-result.json", result)
    return result
