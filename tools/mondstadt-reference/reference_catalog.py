"""Incremental query catalog of completed read-only bundle-index receipts."""
import argparse,gzip,json,sqlite3
from pathlib import Path
from reference_cli import project_path,digest
from regional_registration import SOURCE


def update(index,db):
    if not db.is_relative_to(SOURCE):raise ValueError('Owned catalog only')
    c=sqlite3.connect(db)
    c.executescript('CREATE TABLE IF NOT EXISTS files(key TEXT PRIMARY KEY,sha TEXT,path TEXT); CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY,source TEXT,offset INTEGER,node INTEGER,cab TEXT,json TEXT); CREATE INDEX IF NOT EXISTS cab_idx ON nodes(cab); CREATE TABLE IF NOT EXISTS objects(node INTEGER,pathid INTEGER,classid INTEGER,name TEXT,json TEXT); CREATE INDEX IF NOT EXISTS name_idx ON objects(name); CREATE INDEX IF NOT EXISTS class_idx ON objects(classid);')
    done=dict(c.execute('SELECT key,sha FROM files'));added=0
    for receipt in sorted(index.glob('*.summary.json')):
        key=receipt.name.split('.')[0]
        if key in done:
            if digest(receipt)!=done[key]:raise ValueError('Completed source index receipt mutated')
            continue
        try:info=json.loads(receipt.read_text(encoding='utf8'))
        except json.JSONDecodeError:continue
        with gzip.open(index/(key+'.jsonl.gz'),'rt',encoding='utf8') as stream:
            for line in stream:
                row=json.loads(line);objects=row.pop('objects',[])
                nodeid=c.execute('INSERT INTO nodes(source,offset,node,cab,json) VALUES(?,?,?,?,?)',(info['sourcePath'],row['bundleOffset'],row['nodeIndex'],row['nodePath'].lower(),json.dumps(row))).lastrowid
                c.executemany('INSERT INTO objects VALUES(?,?,?,?,?)',[(nodeid,o['pathId'],o['classId'],o.get('name'),json.dumps(o)) for o in objects])
        c.execute('INSERT INTO files VALUES(?,?,?)',(key,digest(receipt),info['sourcePath']));c.commit();added+=1
    result={'addedFiles':added,'files':c.execute('SELECT count(*) FROM files').fetchone()[0],'nodes':c.execute('SELECT count(*) FROM nodes').fetchone()[0],'objects':c.execute('SELECT count(*) FROM objects').fetchone()[0]};c.close();return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',required=True);p.add_argument('--db',required=True);a=p.parse_args();print(json.dumps(update(project_path(a.index),project_path(a.db))))
