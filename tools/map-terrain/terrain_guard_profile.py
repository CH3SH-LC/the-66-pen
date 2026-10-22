"""Classify the pinned build's byte guards by both native branch bodies.

This is a disk-disassembly reader, not a process reader. A conditional jump alone
does not identify a hotfix flag: metadata initialization also uses JE and JNE.
Unknown branch shapes fail closed instead of being added to either runtime list.
"""
import re


def instructions(text):
    result=[]
    for line in text.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'([0-9a-f]+): (.+)',line)
        if not match:raise ValueError('GUARD_DISASSEMBLY_LINE:'+line)
        result.append((int(match[1],16),match[2].strip()))
    if any(a[0]>=b[0] for a,b in zip(result,result[1:])):
        raise ValueError('GUARD_INSTRUCTION_ORDER')
    return result


def rip_byte(rows,index,operation,value):
    match=re.fullmatch(operation+r' byte ptr \[rip ([+-]) 0x([0-9a-f]+)\], '+str(value),rows[index][1])
    if not match or index+1==len(rows):return None
    return rows[index+1][0]+int(match[2],16)*(1 if match[1]=='+' else -1)


def classify_function(text):
    rows=instructions(text);lookup={address:i for i,(address,_) in enumerate(rows)};result=[]
    for index,(address,_) in enumerate(rows[:-1]):
        flag=rip_byte(rows,index,'cmp',0)
        if flag is None:continue
        branch=index+1
        # These operations preserve EFLAGS. Do not cross CALL, TEST, CMP or an
        # arithmetic instruction in search of a conveniently matching branch.
        while branch<len(rows) and rows[branch][1].split(' ')[0] in ('mov','lea','movss','movsd','movaps'):
            branch+=1
        match=re.fullmatch(r'(je|jne) 0x([0-9a-f]+)',rows[branch][1]) if branch<len(rows) else None
        if not match or int(match[2],16) not in lookup:
            raise ValueError('UNCLASSIFIED_BYTE_GUARD:'+hex(address))
        taken=lookup[int(match[2],16)];fall=branch+1
        zero,nonzero=(taken,fall) if match[1]=='je' else (fall,taken)
        evidence={'flagRva':hex(flag),'compareRva':hex(address),'branchRva':hex(rows[branch][0]),
                  'zeroRva':hex(rows[zero][0]),'nonzeroRva':hex(rows[nonzero][0]),
                  'condition':[f'{a:x}: {s}' for a,s in rows[index:branch+1]]}
        # A zero byte calls the metadata-usage initializer and writes 1 back to
        # exactly the compared byte. Both initial and repeated checks qualify.
        z=rows[zero:zero+4]
        if len(z)>=3 and re.fullmatch(r'mov ecx, 0x[0-9a-f]+',z[0][1]) and z[1][1]=='call 0x524250' and rip_byte(rows,zero+2,'mov',1)==flag:
            evidence.update(kind='metadata-initialized',usage=int(z[0][1].split('0x')[1],16),
                            proof=[f'{a:x}: {s}' for a,s in z[:3]])
        else:
            # A nonzero hotfix byte loads a method from global->0x256d0 and a
            # method slot, then checks that method pointer. Some functions load
            # global between CMP and JNE; that case must not be silently missed.
            n=rows[nonzero:nonzero+5];start=0
            local_global=bool(n and re.fullmatch(r'mov (rax|rcx), qword ptr \[rip [+-] 0x[0-9a-f]+\]',n[0][1]))
            if local_global:start=1
            elif len(n)>1 and n[0][1]=='mov rdx, rcx' and n[1][1]=='mov rax, qword ptr [rax + 0x256d0]':start=1
            walk=re.fullmatch(r'mov (rax|rcx), qword ptr \[\1 \+ 0x256d0\]',n[start][1]) if len(n)>start else None
            slot=re.fullmatch(r'mov (rax|rcx|rdx), qword ptr \[(rax|rcx) \+ (0x[0-9a-f]+)\]',n[start+1][1]) if len(n)>start+1 else None
            loaded_before=any(re.fullmatch(r'mov '+(walk[1] if walk else 'INVALID')+r', qword ptr \[rip [+-] 0x[0-9a-f]+\]',s) for _,s in rows[index+1:branch])
            # Some terrain render builders load global once, retain it across
            # null checks in other registers, then dispatch through that same
            # register. Require the nearest preceding definition to be the
            # exact RIP load; never cross a call, unconditional jump or write.
            if walk and not loaded_before:
                register=walk[1]
                for _,previous in reversed(rows[max(0,index-32):index]):
                    if previous.startswith(('call ','jmp ')):break
                    parts=previous.split(' ',1)
                    destination=parts[1].split(',')[0] if len(parts)==2 else ''
                    if destination in (register,'eax' if register=='rax' else 'ecx') and parts[0] not in ('cmp','test','push'):
                        loaded_before=bool(re.fullmatch(r'mov '+register+r', qword ptr \[rip [+-] 0x[0-9a-f]+\]',previous))
                        break
            if not (walk and slot and slot[2]==walk[1] and (local_global or loaded_before) and
                    len(n)>start+2 and n[start+2][1]=='test '+slot[1]+', '+slot[1]):
                raise ValueError('UNCLASSIFIED_BYTE_GUARD:'+hex(address))
            evidence.update(kind='hotfix-dispatch',dispatchSlot=slot[3],
                            proof=[f'{a:x}: {s}' for a,s in n[:start+3]])
        result.append(evidence)
    return result


def classify_profile(functions):
    """Functions are {rva, assembly}; return complete lists and per-use evidence."""
    uses=[]
    for function in functions:
        uses.extend(dict(row,functionRva=function['rva']) for row in classify_function(function['assembly']))
    hotfix={row['flagRva'] for row in uses if row['kind']=='hotfix-dispatch'}
    initialized={row['flagRva'] for row in uses if row['kind']=='metadata-initialized'}
    if hotfix&initialized:raise ValueError('CONFLICTING_BYTE_GUARD_CLASSIFICATION')
    key=lambda value:int(value,16)
    return {'classifier':'branch-body-v1','hotfixZeroRvas':sorted(hotfix,key=key),
            'initializationBooleanRvas':sorted(initialized,key=key),'uses':uses}
