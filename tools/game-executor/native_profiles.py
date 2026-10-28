"""Pinned disk profile and query-only Windows session identity for readonly bootstrap.

No memory read, hook, game call, process launch or elevation happens on import.
"""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = Path(__file__).with_name('profiles') / 'genshin-cn-7.1.0-readonly.json'
TARGET_IMAGE = Path(os.environ.get("MILIASTRA_GAME_DIR", r"C:\Games\Genshin Impact Game")) / "YuanShen.exe"
PROFILE_SHA256 = '63eb1c66ff63d637f8a0a61d06b8ec6f2407c63236238674472347154b23878a'
ANCHOR_NAMES = ('CONTEXT', 'LEVEL', 'PLACE', 'SAVE')
LAYOUT_NAMES = frozenset(('GS_GLOBAL_SLOT_RVA', 'GS_CONTEXT_MANAGER_OFFSET', 'GS_SAVE_MANAGER_OFFSET',
 'GS_MANAGER_KEY_OFFSET', 'GS_MANAGER_DICTIONARY_OFFSET', 'GS_CONTEXT_BUCKETS_OFFSET',
 'GS_CONTEXT_ENTRIES_OFFSET', 'GS_CONTEXT_VERSION_OFFSET', 'GS_CONTEXT_ORIGIN_OFFSET',
 'GS_ENTITY_DICTIONARY_OFFSET', 'GS_ENTITY_BUCKETS_OFFSET', 'GS_ENTITY_ENTRIES_OFFSET',
 'GS_ENTITY_VERSION_OFFSET', 'GS_OWNER_ID_OFFSET', 'GS_OWNER_CONTEXT_OFFSET',
 'GS_OWNER_CONFIG_OFFSET', 'GS_CONFIG_ID_OFFSET'))

class ProfileError(ValueError):
    pass

def require(value, reason):
    if not value:
        raise ProfileError(reason)

def sha256(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def powershell_host() -> dict:
    """Use the explicitly selected host; never change policy or try another host."""
    import subprocess
    raw = os.environ.get('MILIASTRA_POWERSHELL_HOST')
    require(isinstance(raw, str) and bool(raw), 'NATIVE_POWERSHELL_HOST_REQUIRED')
    host = Path(raw)
    require(host.is_absolute() and host.name.lower() in ('pwsh.exe', 'powershell.exe') and host.is_file(),
            'NATIVE_POWERSHELL_HOST_INVALID')
    host = host.resolve()
    environment = os.environ.copy()
    environment['PSModulePath'] = str(host.parent / 'Modules')
    command = "@{version=$PSVersionTable.PSVersion.ToString();edition=$PSVersionTable.PSEdition;policy=(Get-ExecutionPolicy).ToString()} | ConvertTo-Json -Compress"
    result = subprocess.run([str(host), '-NoProfile', '-NonInteractive', '-Command', command],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            env=environment, timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == 0, 'NATIVE_POWERSHELL_HOST_QUERY_FAILED')
    try:
        observed = json.loads(result.stdout.lstrip('\ufeff'))
    except (ValueError, TypeError):
        raise ProfileError('NATIVE_POWERSHELL_HOST_QUERY_INVALID')
    require(isinstance(observed, dict) and isinstance(observed.get('version'), str),
            'NATIVE_POWERSHELL_HOST_QUERY_INVALID')
    require(observed.get('policy') in ('RemoteSigned', 'Unrestricted'),
            'NATIVE_POWERSHELL_HOST_POLICY_REFUSED:' + str(observed.get('policy')))
    return dict(observed, path=str(host), sha256=sha256(host), policyOverride=False, fallbackAttempted=False)

def load_profile(path: Path = DEFAULT_PROFILE) -> dict:
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == PROFILE_SHA256, 'PROFILE_SOURCE_HASH_MISMATCH')
    p = json.loads(data.decode('utf-8-sig'))
    require(p.get('schemaVersion') == 1 and p.get('allowWrites') is False, 'READONLY_PROFILE_REQUIRED')
    require(set(p['anchors']) == set(ANCHOR_NAMES), 'PROFILE_ANCHOR_SET')
    require(set(p['layout']) == LAYOUT_NAMES, 'PROFILE_LAYOUT_SET')
    for name in ANCHOR_NAMES:
        row = p['anchors'][name]
        require(len(bytes.fromhex(row['bytes'])) == 32, 'PROFILE_ANCHOR_LENGTH')
        require(0 < int(row['rva'], 16) < p['image']['sizeOfImage'] - 32, 'PROFILE_ANCHOR_RANGE')
    for value in p['layout'].values():
        require(type(value) is str and 0 < int(value, 16) < p['image']['sizeOfImage'], 'PROFILE_LAYOUT_RANGE')
    require(len(p['callbackStackRvas']) == 2 and len(p['defaultHotfixByteRvas']) == 4, 'PROFILE_GUARD_SET')
    return p

def require_action(profile: dict, action: str) -> None:
    require(action == 'inspect' and profile.get('allowWrites') is False, 'NATIVE_WRITES_NOT_VALIDATED')

def inspect_pe(data) -> dict:
    require(len(data) >= 64 and data[:2] == b'MZ', 'INVALID_DOS_HEADER')
    pe = struct.unpack_from('<I', data, 60)[0]
    require(64 <= pe <= len(data) - 264 and data[pe:pe+4] == b'PE\0\0', 'INVALID_PE_HEADER')
    n = struct.unpack_from('<H', data, pe+6)[0]
    size = struct.unpack_from('<H', data, pe+20)[0]
    opt = pe+24
    require(1 <= n <= 96 and size >= 112 and opt+size+n*40 <= len(data), 'INVALID_PE_SECTIONS')
    sections = [struct.unpack_from('<IIII', data, opt+size+i*40+8) for i in range(n)]
    return {'machine': struct.unpack_from('<H', data, pe+4)[0],
            'timestamp': struct.unpack_from('<I', data, pe+8)[0],
            'optionalMagic': struct.unpack_from('<H', data, opt)[0],
            'sizeOfImage': struct.unpack_from('<I', data, opt+56)[0], 'sections': sections}

def rva_offset(sections, rva: int, length: int, file_size: int) -> int:
    matches = [raw+rva-va for _, va, size, raw in sections
               if va <= rva and rva+length <= va+size and raw+rva-va+length <= file_size]
    require(len(matches) == 1, 'UNMAPPED_OR_AMBIGUOUS_RVA')
    return matches[0]

def verify_disk(profile: dict, image: Path = TARGET_IMAGE) -> dict:
    expected = profile['image']
    with image.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        require(len(data) == expected['fileBytes'], 'GAME_FILE_SIZE_MISMATCH')
        observed = inspect_pe(data)
        for name in ('machine', 'timestamp', 'optionalMagic', 'sizeOfImage'):
            require(observed[name] == expected[name], 'GAME_PE_MISMATCH:'+name)
        digest = hashlib.sha256(data).hexdigest()
        require(digest == expected['sha256'], 'GAME_SOURCE_HASH_MISMATCH')
        for name in ANCHOR_NAMES:
            row = profile['anchors'][name]
            b = bytes.fromhex(row['bytes']); pos = rva_offset(observed['sections'], int(row['rva'],16), len(b), len(data))
            require(data[pos:pos+len(b)] == b, 'GAME_ANCHOR_MISMATCH:'+name)
    return {'profileId': profile['profileId'], 'sha256': digest,
            'timestamp': observed['timestamp'], 'sizeOfImage': observed['sizeOfImage'],
            'anchorNames': list(ANCHOR_NAMES), 'allowWrites': False}

def windows_api():
    require(os.name == 'nt', 'WINDOWS_X64_REQUIRED')
    k = C.WinDLL('kernel32', use_last_error=True); u = C.WinDLL('user32', use_last_error=True)
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.OpenThread.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenThread.restype=W.HANDLE
    k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle.restype=W.BOOL
    k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)];k.QueryFullProcessImageNameW.restype=W.BOOL
    k.GetProcessTimes.argtypes=[W.HANDLE,*([C.POINTER(W.FILETIME)]*4)];k.GetProcessTimes.restype=W.BOOL
    k.GetThreadTimes.argtypes=[W.HANDLE,*([C.POINTER(W.FILETIME)]*4)];k.GetThreadTimes.restype=W.BOOL
    k.GetProcessIdOfThread.argtypes=[W.HANDLE];k.GetProcessIdOfThread.restype=W.DWORD
    k.IsWow64Process.argtypes=[W.HANDLE,C.POINTER(W.BOOL)];k.IsWow64Process.restype=W.BOOL
    k.GetTickCount64.restype=C.c_ulonglong
    u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)];u.GetWindowThreadProcessId.restype=W.DWORD
    u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int];u.GetClassNameW.restype=C.c_int
    u.IsWindow.argtypes=[W.HWND];u.IsWindow.restype=W.BOOL
    u.RegisterWindowMessageW.argtypes=[W.LPCWSTR];u.RegisterWindowMessageW.restype=W.UINT
    return k,u

def _filetime(t):
    return (t.dwHighDateTime<<32)|t.dwLowDateTime

def query_identity(pid: int, tid: int, hwnd: int, image: Path = TARGET_IMAGE) -> dict:
    require(all(type(v) is int and v>0 for v in (pid,tid,hwnd)), 'INVALID_SESSION_IDENTITY')
    k,u=windows_api();proc=k.OpenProcess(0x1000,False,pid)
    if not proc:raise C.WinError(C.get_last_error())
    try:
        path=C.create_unicode_buffer(32768);length=W.DWORD(len(path));times=[W.FILETIME() for _ in range(4)];wow=W.BOOL(True)
        if not k.QueryFullProcessImageNameW(proc,0,path,C.byref(length)) or not k.GetProcessTimes(proc,*(C.byref(t) for t in times)) or not k.IsWow64Process(proc,C.byref(wow)):
            raise C.WinError(C.get_last_error())
        require(Path(path.value).resolve().as_posix().casefold()==image.resolve().as_posix().casefold(), 'TARGET_IMAGE_MISMATCH')
        require(not wow.value,'TARGET_NOT_X64')
        creation=_filetime(times[0])
    finally:k.CloseHandle(proc)
    thread=k.OpenThread(0x0800,False,tid)
    if not thread:raise C.WinError(C.get_last_error())
    try:
        times=[W.FILETIME() for _ in range(4)]
        require(k.GetProcessIdOfThread(thread)==pid,'THREAD_OWNER_MISMATCH')
        if not k.GetThreadTimes(thread,*(C.byref(t) for t in times)):raise C.WinError(C.get_last_error())
        thread_creation=_filetime(times[0])
    finally:k.CloseHandle(thread)
    owner=W.DWORD();actual_tid=u.GetWindowThreadProcessId(hwnd,C.byref(owner));name=C.create_unicode_buffer(256)
    u.GetClassNameW(hwnd,name,len(name))
    require(u.IsWindow(hwnd) and owner.value==pid and actual_tid==tid and name.value=='UnityWndClass','TARGET_WINDOW_MISMATCH')
    return {'schemaVersion':1,'pid':pid,'tid':tid,'window':hwnd,'windowClass':name.value,
            'processCreation':creation,'threadCreation':thread_creation,'image':str(image.resolve()),
            'source':'query-only-window-process-thread-identity','callbackObserved':False}

def discover_session(image: Path = TARGET_IMAGE) -> dict:
    _,u=windows_api();found={};errors=[]
    callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback_type
    def visitor(hwnd,_):
        name=C.create_unicode_buffer(256);u.GetClassNameW(hwnd,name,len(name))
        if name.value!='UnityWndClass':return True
        owner=W.DWORD();tid=u.GetWindowThreadProcessId(hwnd,C.byref(owner))
        try:
            value=query_identity(owner.value,tid,int(hwnd),image);found[(value['pid'],value['tid'])]=value
        except (OSError,ProfileError) as exc:errors.append(str(exc))
        return True
    u.EnumWindows.argtypes=[callback_type,W.LPARAM];u.EnumWindows.restype=W.BOOL
    if not u.EnumWindows(visitor,0):raise C.WinError(C.get_last_error())
    require(len(found)==1, 'EXACTLY_ONE_GAME_WINDOW_THREAD_REQUIRED:'+str(len(found))+';'+(';'.join(errors)[:250]))
    return next(iter(found.values()))

def validate_session(session: dict, image: Path = TARGET_IMAGE) -> dict:
    observed=query_identity(session['pid'],session['tid'],session['window'],image)
    for name in ('schemaVersion','pid','tid','window','windowClass','processCreation','threadCreation','image'):
        require(session.get(name)==observed[name], 'SESSION_CHANGED:'+name)
    return observed

