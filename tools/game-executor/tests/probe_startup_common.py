"""Read-only x64 PE unwind/stack inspection for private probe startup tests."""
from pathlib import Path
import struct


def inspect_pe(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('PE_SIGNATURE')
    machine, count = struct.unpack_from('<HH', data, pe + 4)
    optional_size = struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    if machine != 0x8664 or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('X64_PE_REQUIRED')
    sections = []
    for index in range(count):
        at = optional + optional_size + index * 40
        virtual_size, rva, raw_size, raw = struct.unpack_from('<4I', data, at + 8)
        sections.append((rva, max(virtual_size, raw_size), raw, raw_size))

    def offset(rva, size=1):
        for start, extent, raw, raw_size in sections:
            if start <= rva and rva + size <= start + extent and rva - start + size <= raw_size:
                return raw + rva - start
        raise ValueError('RVA_OUTSIDE_FILE:' + hex(rva))

    def unwind(rva, seen=()):
        if rva in seen or len(seen) >= 32:
            raise ValueError('UNWIND_CHAIN_CYCLE')
        at = offset(rva, 4)
        version, flags = data[at] & 7, data[at] >> 3
        if version != 1:
            raise ValueError('UNWIND_VERSION:' + str(version))
        code_count = data[at + 2]
        offset(rva, 4 + code_count * 2)
        index, allocation, pushes = 0, 0, 0
        while index < code_count:
            code = data[at + 4 + index * 2 + 1]
            op, info = code & 15, code >> 4
            used = 1
            if op == 0: pushes += 8
            elif op == 1:
                used = 2 if info == 0 else 3 if info == 1 else 0
                if not used or index + used > code_count: raise ValueError('UNWIND_ALLOC_LARGE')
                allocation += (struct.unpack_from('<H', data, at + 4 + (index + 1) * 2)[0] * 8
                               if info == 0 else struct.unpack_from('<I', data, at + 4 + (index + 1) * 2)[0])
            elif op == 2: allocation += info * 8 + 8
            elif op == 3: pass
            elif op in (4, 8): used = 2
            elif op in (5, 9): used = 3
            elif op == 10: pushes += 40 + info * 8
            else: raise ValueError('UNWIND_OPCODE:' + str(op))
            if index + used > code_count: raise ValueError('UNWIND_CODE_OVERRUN')
            index += used
        if flags & 4:
            chain_at = at + 4 + ((code_count + 1) & ~1) * 2
            parent = struct.unpack_from('<3I', data, chain_at)[2]
            parent_allocation, parent_pushes = unwind(parent, (*seen, rva))
            allocation += parent_allocation
            pushes += parent_pushes
        return allocation, pushes

    exception_rva, exception_size = struct.unpack_from('<II', data, optional + 112 + 3 * 8)
    functions = []
    if exception_size % 12:
        raise ValueError('EXCEPTION_DIRECTORY_SIZE')
    for delta in range(0, exception_size, 12):
        begin, end, info = struct.unpack_from('<3I', data, offset(exception_rva + delta, 12))
        allocation, pushes = unwind(info)
        functions.append(dict(beginRva=begin, endRva=end, unwindRva=info,
                              allocatedStackBytes=allocation, pushedStackBytes=pushes,
                              stackBytes=allocation + pushes))
    return dict(path=str(Path(path).resolve()), stackReserve=struct.unpack_from('<Q', data, optional + 72)[0],
                stackCommit=struct.unpack_from('<Q', data, optional + 80)[0],
                entryRva=struct.unpack_from('<I', data, optional + 16)[0],
                maxStackBytes=max((row['stackBytes'] for row in functions), default=0), functions=functions)
