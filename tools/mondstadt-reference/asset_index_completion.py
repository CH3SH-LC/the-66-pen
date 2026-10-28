"""Summarize completed static name indexes and exact unresolved ranges.

Reads existing receipts/gzip metadata/SQLite only, never reopens installed game
files. Existing scanner errors stay errors. Nonserialized nodes were not indexed.
"""
from __future__ import annotations
import argparse
import collections
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from reference_cli import digest, project_path, write_json, PROJECT


def rel(p):
    return p.resolve().relative_to(PROJECT).as_posix()


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def summarize(index, db, out):
    allowed = PROJECT/'.runtime/mondstadt/rework-20261017/reference3d'
    if not out.is_relative_to(allowed) or out.exists():
        raise ValueError('New owned report directory required')
    inventory = read(index/'source-inventory.json')
    summaries = []
    pending = []
    errors = []
    snapshot = []
    for source in inventory['files']:
        key = hashlib.sha256(source['path'].encode()).hexdigest()[:20]
        path = index/(key+'.summary.json')
        if not path.exists():
            pending.append(source)
            continue
        summary = read(path)
        if summary['sourcePath'] != source['path']:
            raise ValueError('Index key does not correspond to inventory source path')
        summaries.append(summary)
        snapshot.append({'key': key, 'sourcePath': summary['sourcePath'],
                         'summarySha256': digest(path), 'completeBundleTraversal': summary['complete'],
                         'lastBundleEnd': summary['lastBundleEnd'], 'sourceBytes': summary['size'],
                         'nodes': summary['nodes'], 'objects': summary['objects'],
                         'errorCount': len(summary['errors'])})
        # Only files with errors need their gzip metadata read a second time.
        nodes = {}
        if summary['errors']:
            wanted = {(e.get('bundleOffset'), e.get('nodeIndex')) for e in summary['errors']}
            with gzip.open(index/(key+'.jsonl.gz'), 'rt', encoding='utf8') as stream:
                for line in stream:
                    row = json.loads(line)
                    k = (row['bundleOffset'], row['nodeIndex'])
                    if k in wanted:
                        row.pop('objects', None)
                        nodes[k] = row
        for err in summary['errors']:
            row = {'sourcePath': summary['sourcePath'], 'sourceBytes': summary['size'],
                   'summary': rel(path), 'summarySha256': digest(path), **err}
            if err.get('stage') == 'serialized':
                node = nodes.get((err['bundleOffset'], err['nodeIndex']))
                row['affectedNodeMetadata'] = node
                row['scope'] = 'one serialized node could not be decoded/indexed; not proof the resource is absent'
                if node:
                    row['containingBundleByteRangeHalfOpen'] = [node['bundleOffset'], node['bundleOffset']+node['bundleSize']]
                    row['decodedNodeByteRangeHalfOpen'] = [0, node['nodeSize']]
                    row['compressedSourceBytePrecision'] = 'containing bundle only; individual compressed block mapping not retained'
            elif err.get('stage') == 'header':
                row['untraversedSourceByteRangeHalfOpen'] = [err['bundleOffset'], summary['size']]
                row['scope'] = 'header failure prevented subsequent bundle traversal in this file'
            else:
                row['scope'] = 'source stability or unknown stage; retain original error'
            errors.append(row)
    c = sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True)
    catalog_files = dict(c.execute('SELECT key,sha FROM files'))
    missing_catalog = [x['key'] for x in snapshot if x['key'] not in catalog_files]
    mismatched = [x['key'] for x in snapshot if x['key'] in catalog_files and catalog_files[x['key']] != x['summarySha256']]
    counts = {name: c.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('files', 'nodes', 'objects')}
    node_errors = c.execute("SELECT count(*) FROM nodes WHERE json LIKE '%\"error\":%'").fetchone()[0]
    # Null names include unnamed classes; restrict to the actual named-class parser.
    from serialized_reference import NAMED
    named = sorted(set(NAMED)|{1})
    placeholders = ','.join('?' for _ in named)
    name_errors = []
    for cls, count in c.execute('SELECT classid,count(*) FROM objects WHERE name IS NULL AND classid IN ('+placeholders+') AND json LIKE ? GROUP BY classid', (*named, '%"nameError":%')):
        name_errors.append({'classId': cls, 'objectsWithNameError': count})
    c.close()
    out.mkdir(parents=True)
    write_json(out/'files.json', {'files': snapshot, 'pendingInventoryFiles': pending})
    write_json(out/'errors.json', {'errors': errors})
    scan_receipt = index/'scan-receipt.json'
    result = {'schema': 1, 'createdUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'completed-with-explicit-parse-gaps' if not pending and not missing_catalog and not mismatched else 'incomplete',
        'indexDirectory': rel(index), 'catalog': rel(db),
        'inventorySha256': digest(index/'source-inventory.json'),
        'scanReceipt': rel(scan_receipt) if scan_receipt.exists() else None,
        'scanReceiptSha256': digest(scan_receipt) if scan_receipt.exists() else None,
        'inventoryFiles': len(inventory['files']), 'completedSummaryFiles': len(snapshot),
        'pendingFiles': len(pending), 'allBundleTraversalComplete': all(s['complete'] for s in summaries),
        'sourceFilesWithErrors': sum(bool(s['errors']) for s in summaries), 'parseErrors': len(errors),
        'errorsByStage': dict(collections.Counter(e['stage'] for e in errors)),
        'bundles': sum(s['bundles'] for s in summaries), 'indexedSuccessfulNodes': sum(s['nodes'] for s in summaries),
        'objects': sum(s['objects'] for s in summaries),
        'scannerAccumulatedPayloadBytesRead': sum(s['readBytes'] for s in summaries),
        'catalogCounts': counts, 'catalogNodeErrorRows': node_errors,
        'catalogNamedObjectErrorsByClass': name_errors,
        'catalogMissingFileKeys': missing_catalog, 'catalogReceiptMismatchKeys': mismatched,
        'files': 'files.json', 'errors': 'errors.json',
        'scope': 'streaming serialized-asset metadata and bounded named-object prefixes, including null names/errors',
        'notIndexed': ['nonserialized nodes (including raw hex-named bin resources)',
            'resources outside the source inventory', 'failed serialized nodes or failed name prefixes'],
        'readApi': {'module': 'tools/mondstadt-reference/blb3_reference.py',
            'header': 'read_header(path,bundleOffset) returns all node descriptors, including nonserialized nodes',
            'boundedRead': 'BundleReader(path,bundleOffset).read(nodeIndex,relativeOffset,size)',
            'sqlite': 'open URI with mode=ro; objects join nodes on objects.node=nodes.id'},
        'scannerResumedByRoot': 'original local_asset_reference.py with same output directory and 2 workers; existing summary markers reused',
        'priorStopCause': 'not conclusively established from this agent; unknown exec session is not a process termination cause',
        'currentReportReopenedInstalledFiles': False, 'installationWrites': False,
        'gameProcessAccess': False, 'desktopAccess': False}
    write_json(out/'completion.json', result)
    write_json(out/'PACKAGE.json', {'files': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size}
                                               for p in sorted(out.iterdir()) if p.is_file()},
                                  'tool': rel(Path(__file__)), 'toolSha256': digest(Path(__file__))})
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index', required=True); p.add_argument('--db', required=True); p.add_argument('--out', required=True)
    a = p.parse_args()
    print(json.dumps(summarize(project_path(a.index), project_path(a.db), project_path(a.out))))
