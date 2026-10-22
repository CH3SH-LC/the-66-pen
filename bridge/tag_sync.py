"""Single synthetic Tag fixture for an explicitly opted-in fresh editor probe.

No socket, process launch, arbitrary message input, or game integration here.
"""
import hashlib
import os
from .ipc_frames import encode_frame

NAME = 'MW_SYNTHETIC_TAG_PROBE'


def _varint(value):
    result=bytearray()
    while value>127:
        result.append((value&127)|128);value>>=7
    result.append(value)
    return bytes(result)


def _nested(tag,data):
    return _varint(tag)+_varint(len(data))+data


def encode_tag(tag_id):
    if type(tag_id) is not int or not 1<=tag_id<=0xffffffff:
        raise ValueError('TAG_ID_UINT32_REQUIRED')
    # Key field1 omitted: this bounded Tag handler does not read it.
    key=b'\x10\x01\x18\x17\x20'+_varint(tag_id)
    data=b'\x08'+_varint(tag_id)+_nested(18,NAME.encode('utf8'))
    tag=_nested(10,data)
    record=_nested(10,key)+_nested(218,tag)  # N8 field27, wire2
    # field2 retains this same key; it is not a deletion list.
    group=_nested(10,key)+_nested(18,key)+_nested(26,record)
    payload=_nested(10,group)
    inner=encode_frame(1017,payload)
    wire=len(inner).to_bytes(4,'big')+inner
    return wire,{'source':'synthetic-project-tag','tagID':tag_id,'name':NAME,
                 'messageID':1017,'payloadBytes':len(payload),
                 'payloadSha256':hashlib.sha256(payload).hexdigest(),
                 'wireBytes':len(wire),'wireSha256':hashlib.sha256(wire).hexdigest(),
                 'modelReadbackVerified':False,'gameVerified':False}


def require_owned_editors(ok,rows,peer,exe):
    """Fresh pre-send observation; the accepted editor chain is the only exception."""
    if not ok:raise ValueError('PRE_SEND_PROCESS_OBSERVATION_UNKNOWN')
    owned=set(peer['editorChainPIDs'])
    seen=set()
    for row in rows:
        if row.simulated or (not row.name and not row.executable_path):
            raise ValueError('PRE_SEND_PROCESS_IDENTITY_UNKNOWN')
        name=(row.name or '').casefold()
        if name in {'yuanshen.exe','genshinimpact.exe'}:
            raise ValueError('PRE_SEND_GAME_PRESENT')
        exact=os.path.normcase(row.executable_path or '')==os.path.normcase(exe)
        if name=='beyondeditor.exe' or exact:
            if row.pid not in owned or not exact:
                raise ValueError('PRE_SEND_UNOWNED_EDITOR')
            seen.add(row.pid)
    if seen!=owned:raise ValueError('PRE_SEND_EDITOR_CHAIN_CHANGED')
