"""Independent decoding for existing accessory transfers; never writes a save."""
import math
import struct
from contract import read, sha, require, decode_extension
from assembly_receipt import quaternion, same_world
from reparent_build import KIND, BUILD_KIND, SCOPE, validate_pairs


def manifest(run):
    from receipt import guarded_run
    run = guarded_run(run)
    p,built = read(run/"prepared.json"),read(run/"build-result.json")
    require(p.get("kind") == KIND and p.get("action") == 17 and p.get("receiptVersion") == 21
            and p.get("run") == str(run) and
            (p["levelId"] == 1073741846 or
             (p.get("ownershipManifest") in p.get("sourceHashes", {}) and
              type(p["levelId"]) is int and 0 < p["levelId"] <= 0xffffffff and
              p["levelId"] not in range(1073741835,1073741845))), "REPARENT_CONTRACT")
    validate_pairs(p["pairs"])
    require(built.get("kind") == BUILD_KIND and
            built.get("preparedSha256") == sha(run/"prepared.json"), "REPARENT_PREPARED_BINDING")
    for name,digest in p["artifacts"].items():
        path = run/name
        require(path.resolve().is_relative_to(run) and sha(path) == digest,
                "REPARENT_ARTIFACT_CHANGED:"+name)
    if p["launchable"]:
        require(sha(run/"invoke-transform.ps1") == built["wrapperSha256"], "REPARENT_WRAPPER_CHANGED")
    return run,p,built


def extension(raw, size):
    pose_size = 48+128*280+size
    row_start = 48+pose_size+size+128*152+88
    names = ("size", "version", "status", "stage", "seh", "count", "completed",
             "sceneUnchanged", "mode", "mutationCalls", "failedRva", "failedValue")
    out = dict(zip(names,struct.unpack_from("<12I",raw)))
    require(out["size"] == len(raw) and out["version"] in (2,3) and
            0 <= out["count"] <= 512 and out["mode"] in (0,1), "REPARENT_RECEIPT_ABI")
    rows_end = row_start+512*216
    require(len(raw) == rows_end+(72 if out["version"] == 3 else 0), "REPARENT_RECEIPT_SIZE")
    if out["version"] == 3:
        names = ("startedTick","preflightDoneTick","mutationDoneTick","finishedTick","batchTransaction",
                 "budgetMillis","budgetExceeded","batchOpened","batchClosed","pendingPeak","reserved",
                 "baseDepth","batchDepth")
        out["batch"] = dict(zip(names,struct.unpack_from("<5Q6I2i",raw,rows_end)))
    block = raw[48:48+pose_size]
    if block == bytes(pose_size):
        out["beforePose"] = dict(status=1,seh=0,mode=0,rows=[])
        before = bytes(size)
    else:
        out["beforePose"],before = decode_extension(block,size)
    after = raw[48+pose_size:48+pose_size+size]
    unused = 48+pose_size+size
    require(raw[unused:unused+128*152] == bytes(128*152), "REPARENT_LEGACY_ROWS_USED")
    names = ("manager","record","klass","target","before","function0","function1","function2",
             "count","base","depth","flags","dirty","reserved")
    out["undoDiagnostic"] = dict(zip(names,struct.unpack_from("<8Q6I",raw,unused+128*152)))
    rows = []
    names = ("accessoryId","oldHostId","hostId","modelId","status","called",
             "oldBefore","oldAfter","newBefore","newAfter","parentBefore","parentAfter",
             "accessory","oldHost","host","childComponent","oldComponent","component",
             "transform","transaction")
    for i in range(out["count"]):
        at = row_start+i*216
        row = dict(zip(names,struct.unpack_from("<12I8Q",raw,at)))
        for offset,label in ((112,"before"),(148,"after")):
            v = struct.unpack_from("<9f",raw,at+offset)
            row[label] = dict(position=v[:3],rotation=v[3:6],scale=v[6:])
        row.update(zip(("pendingBefore","pendingAfter","depthBefore","depthAfter","opened","closed"),
                       struct.unpack_from("<2I2i2I",raw,at+184)))
        row.update(zip(("oldComponentId","componentId"),
                       struct.unpack_from("<2I",raw,at+208)))
        rows.append(row)
    require(raw[row_start+len(rows)*216:rows_end] == bytes((512-len(rows))*216), "REPARENT_UNUSED_ROWS")
    out["rows"] = rows
    return out,before,after


def validate_success(o,p):
    mode = int(p["mode"] == "reparent-set")
    prefix = (mode == 1 and o["version"] == 3 and p.get("allowBudgetPrefix") is True and
              0 < o["completed"] < o["count"])
    require(o["status"] == o["seh"] == 0 and o["stage"] == 5 and
            (o["completed"] == o["count"] or prefix) and o["count"] == len(p["pairs"]) and
            o["sceneUnchanged"] == 1 and o["mode"] == mode and
            o["mutationCalls"] == mode*o["completed"] and
            o["failedValue"] == (309 if prefix else 0), "REPARENT_INCOMPLETE")
    require(o["version"] == p.get("reparentAbi", 2), "REPARENT_ABI_CARD_BINDING")
    if o["version"] == 3:
        t = o["batch"]
        require(p["transactionScope"] == "whole-batch" and p["callbackBudgetMillis"] == t["budgetMillis"] == 2000
                and t["budgetExceeded"] == int(prefix) and t["reserved"] == 0 and
                0 < t["startedTick"] <= t["preflightDoneTick"] <= t["mutationDoneTick"] <= t["finishedTick"],
                "REPARENT_BATCH_TIMING")
        require(o["count"] <= 64 and t["batchOpened"] == t["batchClosed"] == mode
                and bool(t["batchTransaction"]) == bool(mode) and
                t["baseDepth"] == t["batchDepth"] >= 0 and 0 <= t["pendingPeak"] <= 4*o["count"]
                and all(r["transaction"] == (t["batchTransaction"] if mode and i<o["completed"] else 0)
                        and r["depthBefore"] == t["baseDepth"]
                        for i,r in enumerate(o["rows"])), "REPARENT_BATCH_TRANSACTION")
    pose = o["beforePose"]
    require(pose["status"] == pose["seh"] == pose["mode"] == 0 and pose["sceneUnchanged"] == 1 and
            pose["completed"] == pose["count"] == len(p["requests"]), "REPARENT_POSE_PREFLIGHT")
    poses = {r["entityId"]:r for r in pose["rows"]}
    u = o["undoDiagnostic"]
    require(u["reserved"] in (0,2) and (u["reserved"] != 2 or
            (mode and u["count"] == 1 and u["base"] == u["depth"] and not u["flags"])),
            "REPARENT_PREVIOUS_TRANSACTION_NOT_CLOSED")
    require(set(poses) == {r["entityId"] for r in p["requests"]}, "REPARENT_POSE_IDS")
    for i,(r,q) in enumerate(zip(o["rows"],p["pairs"])):
        row_mode = mode if i < o["completed"] else 0
        require(all(r[k] == q[k] for k in q), "REPARENT_PAIR_BINDING")
        require(r["oldHost"] == poses[r["oldHostId"]]["owner"] and
                r["host"] == poses[r["hostId"]]["owner"], "REPARENT_HOST_BINDING")
        require(all(r[k] for k in ("accessory","childComponent","oldComponent","component","transform")),
                "REPARENT_POINTER_MISSING")
        require(r["status"] == int(i >= o["completed"]) and r["pendingBefore"] == r["pendingAfter"] == 0 and
                r["depthBefore"] == r["depthAfter"] >= 0 and
                r["called"] == r["opened"] == r["closed"] == row_mode and
                bool(r["transaction"]) == bool(row_mode), "REPARENT_TRANSACTION_INCOMPLETE")
        require(r["oldComponentId"] > 0 and r["componentId"] > 0 and
                r["oldComponentId"] != r["componentId"] and
                r["parentBefore"] == r["oldComponentId"] and
                r["parentAfter"] == (r["componentId"] if row_mode else r["oldComponentId"]),
                "REPARENT_PARENT_WRONG")
        require(r["oldAfter"] == r["oldBefore"]-row_mode >= 0 and
                r["newAfter"] == r["newBefore"]+row_mode <= 999, "REPARENT_COUNT_DELTA")
        require(same_world(r["before"],r["after"]), "REPARENT_WORLD_CHANGED")
        expected = p["expectedAccessories"][str(r["accessoryId"])]
        require(r["modelId"] == expected["modelId"], "REPARENT_MODEL_REQUEST_BINDING")
        # Saved coordinates are relative to the scene context translation.
        w = expected["world"]
        position = [float(x)+float(y) for x,y in zip(w["position"],p["origin"])]
        require(all(abs(x-y) <= .004 for x,y in zip(position,r["before"]["position"])) and
                all(abs(x-y) <= .004 for x,y in zip(w["scale"],r["before"]["scale"])) and
                abs(sum(x*y for x,y in zip(w["rotationQuaternion"],quaternion(r["before"]["rotation"])))) >= .999999,
                "REPARENT_SAVE_WORLD_BINDING")


def decode(run):
    from receipt import same_scene
    from build import ro
    run,p,_ = manifest(run)
    require(p["launchable"] and not p["compileOnly"], "REPARENT_COMPILE_ONLY")
    end = read(run/"exit.json")
    require(end.get("scope") == SCOPE, "REPARENT_WRAPPER_SCOPE")
    base = dict(run=str(run),mode=p["mode"],levelId=p["levelId"],session=p["session"],
                replayForbidden=True,persistentSaveVerified=False,reopenVerified=False)
    if end.get("executed") is False:
        require(not (run/"attempt.used").exists(), "REPARENT_ATTEMPT_DESPITE_REFUSAL")
        return dict(base,ok=False,error=end.get("error"),called=False,nativeStarted=False,
                    outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(end.get("executed") is True, "REPARENT_EXECUTION_UNKNOWN")
    decoder = ro.load_decoder()
    record,_ = decoder.read_probe(run/"stdout.jsonl")
    require(record.get("scope") == SCOPE and record.get("selfTestOnly") is False and
            record.get("pid") == p["session"]["pid"] and record.get("tid") == p["session"]["tid"],
            "REPARENT_IDENTITY")
    require(record.get("assemblyNonce") == p["nonce"] and
            record.get("assemblyDeadline") == str(p["deadlineTick"]) and
            record.get("assemblyProtocol") == 21, "REPARENT_CARD_IDENTITY")
    raw = bytes.fromhex(record.get("assemblyHex",""))
    require(record.get("assemblyBytes") == len(raw), "REPARENT_BYTES")
    original = (run/"baseline-snapshot.bin").read_bytes()
    o,before,after = extension(raw,len(original))
    cleanup = (record.get("callbackCount") == 1 and record.get("activeCallbacks") == 0 and
        record.get("unhooked") is True and record.get("transportOk") is True and
        record.get("probeElevatedHigh") is True and o["seh"] == 0 and
        o["undoDiagnostic"]["reserved"] != 1 and
        all(not r["opened"] or (r["closed"] == 1 and r["pendingAfter"] == 0 and
            r["depthAfter"] == r["depthBefore"]) for r in o["rows"]))
    if o["version"] == 3:
        t = o["batch"]
        cleanup = cleanup and (not t["batchOpened"] or
            (t["batchClosed"] == 1 and t["batchDepth"] == t["baseDepth"]))
    result = dict(base,ok=False,called=o["mutationCalls"]>0,nativeStarted=True,
        outcomeUncertain=o["mutationCalls"]>0 or not cleanup,cleanupVerified=cleanup,
        safeToRelease=cleanup,nativeReceipt=o,rows=o["rows"],
        rawReceiptSha256=sha(run/"stdout.jsonl"),error="REPARENT_OPERATION_NOT_COMPLETE")
    if not(record.get("ok") is True and cleanup and end.get("exitCode") == 0 and not end.get("error")):
        return result
    validate_success(o,p)
    snap = lambda x:decoder.decode_snapshot(dict(snapshotHex=x.hex(),snapshotBytes=len(x)))
    baseline = snap(original)
    for current in (decoder.decode_snapshot(record),snap(before),snap(after)):
        same_scene(baseline,current)
    result.update(ok=True,error=None,outcomeUncertain=False,
                  worldTransformsPreserved=True,transferredAccessories=o["mutationCalls"],
                  independentEntitiesAdded=0,independentEntitiesRemoved=0,
                  requestedCount=o["count"], batchComplete=o["completed"]==o["count"],
                  stoppedForTimeBudget=o["completed"]<o["count"],
                  rows=o["rows"][:o["completed"]])
    if o["version"] == 3:
        t = o["batch"]
        result["timingMillis"] = dict(preflight=t["preflightDoneTick"]-t["startedTick"],
            mutation=t["mutationDoneTick"]-t["preflightDoneTick"],
            commitAndVerification=t["finishedTick"]-t["mutationDoneTick"],
            total=t["finishedTick"]-t["startedTick"])
        result["transactionScope"] = "whole-batch"
    return result
