"""Compile frozen, independently reviewed plans into bounded public-API batches.

Offline only: writes a manifest, never an EasyEDA source or native project.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'output/candidates/adc10-labtool-20261018'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    out={}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '||' not in line:
            continue
        h,b=line.split('||',1)
        h=json.loads(h)
        key=h['type'],h.get('id')
        assert key not in out,key
        out[key]=json.loads(b.removesuffix('|'))
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--placement-sha',required=True)
    ap.add_argument('--isolation-sha',required=True)
    ap.add_argument('--placement-file',default='independent-pcb-placement-rebased-eco-proposal.json')
    ap.add_argument('--output-name',default='pcb-isolation-placement-execution-v1.json')
    args=ap.parse_args()
    source=ROOT/'output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru'
    assert Path(args.placement_file).name==args.placement_file and args.placement_file.endswith('.json')
    assert Path(args.output_name).name==args.output_name and args.output_name.endswith('.json')
    pp=HERE/args.placement_file
    ip=HERE/'routing/exact-old-copper-isolation-post-eco-manifest.json'
    assert sha(pp)==args.placement_sha,'Placement changed since review'
    assert sha(ip)==args.isolation_sha,'Isolation changed since review'
    placement=json.loads(pp.read_text())
    isolation=json.loads(ip.read_text())
    rows=parse(source)
    assert placement['sourceSha256']==sha(source)
    assert len(placement['edits'])==107
    assert sum(e['newPart'] for e in placement['edits'])==83
    assert not placement['unplacedNewRefs'] and not placement['failedSearches']
    assert len(isolation['operations'])==179
    assert sum(o['action']=='delete' for o in isolation['operations'])==138
    assert sum(o['action']=='rename_net' for o in isolation['operations'])==41
    assert isolation['sourceSha256']==sha(source) and not isolation['rebaseMismatches']
    assert sum(k[0]=='COMPONENT' for k in rows)==437
    operations=[]
    for op in isolation['operations']:
        assert op['type']=='LINE'
        assert rows['LINE',op['id']]==op['beforeBody'],op['id']
        if op['action']=='rename_net':
            expect=copy.deepcopy(op['beforeBody'])
            expect['netName']=op['afterBody']['netName']
            assert expect==op['afterBody']
        normalized=copy.deepcopy(op)
        if normalized['action']=='rename_net':
            normalized['action']='rename'
        operations.append(normalized)
    moves=[]
    for p in placement['edits']:
        assert p['actualPadNetContractVerified']
        assert rows['COMPONENT',p['componentId']]==p['sourceBodyBefore'],p['ref']
        assert p['uniqueId']==p['sourceBodyBefore']['attrs']['Unique ID']
        b=copy.deepcopy(p['sourceBodyBefore'])
        b.update(x=p['set']['x'],y=p['set']['y'],angle=p['set']['rotation'],layerId=1)
        moves.append({'type':'COMPONENT','id':p['componentId'],'action':'place',
                      'ref':p['ref'],'uniqueId':p['uniqueId'],
                      'beforeBody':p['sourceBodyBefore'],'afterBody':b,
                      'expectedWorldPads':p['pads']})
    batches=[]
    for name,ops,n in [('isolate',[o for o in operations if o['action']=='delete'],60),
                       ('rename',[o for o in operations if o['action']=='rename'],20),
                       ('place',moves,20)]:
        for start in range(0,len(ops),n):
            batches.append({'stage':f'{name}_{start//n}','operations':ops[start:start+n]})
    report={'schema':'stm32h747-labtool-pcb-bounded-execution-20261018-v1',
            'PCBRequired':'0ac2a19168000d8e','sourcePath':str(source),'sourceSha256':sha(source),
            'reviewedPlacementPath':str(pp),'reviewedPlacementSha256':sha(pp),
            'reviewedIsolationPath':str(ip),'reviewedIsolationSha256':sha(ip),
            'batches':batches,'nativeApiCalls':0,'nativeDesignModified':False,
            'groundVoidsAndNewRoutingIncluded':False,'manufacturingReady':False}
    path=HERE/args.output_name
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'manifest':str(path),'sha256':sha(path),
                      'stages':[b['stage'] for b in batches],
                      'operations':len(operations)+len(moves),'manufacturingReady':False}))


if __name__=='__main__':
    main()
