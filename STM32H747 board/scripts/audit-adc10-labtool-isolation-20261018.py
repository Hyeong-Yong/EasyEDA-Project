"""Read-only exact copper isolation and automatic empty-net cleanup audit."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'output/candidates/adc10-labtool-20261018'
EMPTY_NET=dict(netType=None,specialColor=None,retLine=True,differentialName=None,isPositiveNet=False,equalLengthGroupName=None)
EMPTY_SELECTOR=dict(ruleOrder=4,ruleKeyValue={},copperValue={},innerPlaneValue={})
VIEW={'DOCHEAD','CANVAS','ACTIVE_LAYER','ELE_PLACEHOLDER'}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    out={}
    for line in p.read_text(encoding='utf-8-sig').splitlines():
        if '||' not in line:continue
        h,b=line.split('||',1);h=json.loads(h)
        k=h['type'],h.get('id')
        assert k not in out,k
        out[k]=json.loads(b.removesuffix('|'))
    return out


def exact_line_union(rows):
    groups={}
    for (typ,rid),b in rows.items():
        if typ!='LINE':continue
        coords=[int(round(b[f]*10000)) for f in ('startX','startY','endX','endY')]
        x,y,z,w=coords;dx,dy=z-x,w-y
        if not dx and not dy:
            direction=(0,0);offset=(x,y);lo=hi=0
        else:
            g=math.gcd(abs(dx),abs(dy));dx//=g;dy//=g
            if dx<0 or dx==0 and dy<0:dx,dy=-dx,-dy
            direction=(dx,dy);offset=dx*y-dy*x
            lo,hi=sorted((dx*x+dy*y,dx*z+dy*w))
        metadata={k:v for k,v in b.items() if k not in ('startX','startY','endX','endY')}
        key=(json.dumps(metadata,sort_keys=True,separators=(',',':')),direction,offset)
        groups.setdefault(key,[]).append((lo,hi))
    out={}
    for k,intervals in groups.items():
        merged=[]
        for lo,hi in sorted(intervals):
            if merged and lo<=merged[-1][1]:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
            else:merged.append((lo,hi))
        out[k]=merged
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True)
    ap.add_argument('--manifest',default='pcb-isolation-placement-execution-v1.json')
    a=ap.parse_args();assert Path(a.manifest).name==a.manifest
    mp=HERE/a.manifest
    plan=json.loads(mp.read_text());base=Path(plan['sourcePath'])
    assert sha(base)==plan['sourceSha256']
    before=read(base);expected=before.copy();selected=set();ops=[]
    for batch in plan['batches']:
        assert batch['stage'].startswith(('isolate_','rename_'))
        for op in batch['operations']:
            k=op['type'],op['id'];assert before[k]==op['beforeBody']
            assert op['action'] in ('delete','rename')
            selected.add(op['beforeBody']['netName'].upper())
            if op['action']=='delete':del expected[k]
            else:expected[k]=op['afterBody']
            ops.append(op)
        if batch['stage']==a.stage:break
    else:raise ValueError('Unknown isolation stage')
    actualpath=ROOT/f'output/validation/native-adc10-pcb-labtool_{a.stage}-20261018.epru'
    after=read(actualpath)
    # Native deletion also joins collinear remnants across removed tee nodes.
    # Compare exact integer-grid centerline unions INCLUDING width/layer/net and
    # every non-coordinate LINE field; this permits identity consolidation only.
    line_union_equal=exact_line_union(expected)==exact_line_union(after)
    selected_line_ids={k for k,b in expected.items() if k[0]=='LINE' and b.get('netName','').upper() in selected}
    used={str(b.get(f)).upper() for (t,k),b in after.items() if t not in ('NET','RULE_SELECTOR') and isinstance(b,dict) for f in ('netName','padNet') if b.get(f)}
    cleanup=[];issues=[]
    for k,b in expected.items():
        t,rid=k
        if t in VIEW or after.get(k)==b:continue
        if t=='LINE' and k in selected_line_ids and line_union_equal:continue
        n=None
        if k not in after and t in ('NET','RULE_SELECTOR'):
            h=json.loads(rid)
            if t=='NET' and h[0]=='NET':n=h[1]
            elif t=='RULE_SELECTOR' and h[0]=='RULE_SELECTOR' and h[1][0]=='NET':n=h[1][1]
            if n and n.upper() in selected and n.upper() not in used and b==(EMPTY_NET if t=='NET' else EMPTY_SELECTOR):
                cleanup.append({'type':t,'id':rid,'net':n,'reason':'native removed unused default-only declaration, not a design rule'});continue
        issues.append({'key':k,'issue':'unexpected-body-change-or-deletion'})
    for k in after:
        if k[0]=='LINE' and k not in expected and after[k].get('netName','').upper() in selected and line_union_equal:continue
        if k[0] not in VIEW and k not in expected:issues.append({'key':k,'issue':'unexpected-record'})
    if not line_union_equal:issues.append({'issue':'exact-per-net-width-layer-line-union-differs'})
    counts=Counter(t for t,k in after)
    assert counts['VIA']==640 and counts['COMPONENT']==437 and counts['RULE']==18
    protected=['VIA','PAD','FILL','ARC','POLY','STRING','RULE','LAYER','LAYER_PHYS','COMPONENT','PAD_NET']
    for typ in protected:
        assert {k:b for k,b in before.items() if k[0]==typ}=={k:b for k,b in after.items() if k[0]==typ},typ
    report={'stage':a.stage,'passed':not issues,'source':str(actualpath),'sourceSha256':sha(actualpath),
            'manifestSha256':sha(mp),'completedOperationCount':len(ops),
            'removedLineCount':sum(o['action']=='delete' for o in ops),'renamedLineCount':sum(o['action']=='rename' for o in ops),
            'automaticUnusedDefaultNetCleanup':cleanup,'issues':issues,
            'exactIntegerGridLineUnionWithMetadataPreserved':line_union_equal,
            'protectedPrimitiveTypesBodyExact':protected,'oldVias640Preserved':True,
            'rules18Preserved':True,'physicalParts437Preserved':True,'nativeApiCalls':0,'manufacturingReady':False}
    out=HERE/f'independent-isolation-{a.stage}-audit.json'
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not issues,'sourceSha256':sha(actualpath),'report':str(out),
                      'removedLines':report['removedLineCount'],'renamedLines':report['renamedLineCount'],
                      'unusedDefaultNetRecordsRemoved':len(cleanup),'issues':issues[:5]}))
    if issues:raise ValueError('Isolation containment failed')


if __name__=='__main__':main()
