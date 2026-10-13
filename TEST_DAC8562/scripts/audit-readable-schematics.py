"""Reject topology or part-identity changes before native source import."""
import importlib.util
import itertools
import json
from collections import defaultdict
from pathlib import Path

s=importlib.util.spec_from_file_location('draw',Path(__file__).with_name('redraw-readable-schematics.py'))
d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
m,io=d.m,d.io

def on(p,a,b):
    return min(a[0],b[0])-1e-5<=p[0]<=max(a[0],b[0])+1e-5 and min(a[1],b[1])-1e-5<=p[1]<=max(a[1],b[1])+1e-5 and abs((p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0]))<1e-4

def graph(doc):
    aa=io.attrs(doc);segments=[];names=defaultdict(set)
    for (t,i),(_,p) in doc['records'].items():
        if t=='LINE' and p.get('lineGroup') and ('WIRE',p['lineGroup']) in doc['records']:
            w=p['lineGroup'];segments.append((w,(p['startX'],p['startY']),(p['endX'],p['endY'])))
            if aa.get(w,{}).get('NET'):names[w].add(aa[w]['NET'])
    roots={w:w for w,a,b in segments}
    def root(x):
        while roots[x]!=x:roots[x]=roots[roots[x]];x=roots[x]
        return x
    for (w,a,b),(v,c,e) in itertools.combinations(segments,2):
        if w!=v and any(on(p,a,b) and on(p,c,e) for p in [a,b,c,e]):roots[root(v)]=root(w)
    pins=[]
    for (t,i),(_,p) in doc['records'].items():
        pr=aa.get(i,{})
        if t!='COMPONENT' or not pr.get('Symbol'):continue
        for num,pt in m.pins(p,pr).items():
            hits={w for w,a,b in segments if on(pt,a,b)}
            label=pr.get('Global Net Name')
            if pr['Symbol'] in ('ba868eccc9511b9e','a81d11d7d2be7e62'):label=pr.get('Name')
            if label:
                for w in hits:names[w].add(label)
            if pr.get('Designator'):pins.append((pr['Designator']+'.'+num,hits))
    nets=defaultdict(set)
    for w,ns in names.items():nets[root(w)].update(ns)
    result={}
    for pin,hits in pins:result[pin]=sorted(set(result.get(pin,[]))|set().union(*(nets[root(w)] for w in hits)))
    return result,[sorted(ns) for ns in nets.values() if len(ns)>1]

if __name__=='__main__':
    reports=[];allpins={}
    for pg,filename in zip(m.BEFORE['pages'],['DAC8562.readable-source.txt','DAC_MCU.readable-source.txt']):
        before=next(iter(io.documents(pg['source']).values()))
        after=next(iter(io.documents((m.OUT/filename).read_text(encoding='utf8')).values()))
        old,new=m.components(before),m.components(after)
        expected_parts=d.Page(pg).comp
        identity=[]
        for ref,c in old.items():
            nc=new.get(ref)
            expected=expected_parts[ref]
            if not nc or nc['id']!=c['id'] or nc['props']!=expected['props'] or any(expected['item'].get(k)!=nc['item'].get(k) for k in ['partId','uniqueId']):identity.append(ref)
        pn,shorts=graph(after);allpins.update(pn)
        fail=[{'pin':pin,'expected':d.netpins.get(pin),'actual':nets} for pin,nets in pn.items() if nets!=([d.netpins[pin]] if pin in d.netpins else [])]
        reports.append({'file':filename,'identityFailures':identity,'shorts':shorts,'pinFailures':fail,'connectedPins':sum(bool(n) for n in pn.values())})
    report={'pages':reports,'approvedElectricalChanges':{'R117.2':'formerly $2N56 -> MCU_SENSE_B (PCB was already correct)'},'approvedPartChanges':{'Q3':'AO3400A -> onsemi 2N7002LT1G C16338; 1=G 2=S 3=D; actual supplier SOT-23 footprint'},'pinNets':allpins,'passed':all(not r['identityFailures'] and not r['shorts'] and not r['pinFailures'] for r in reports)}
    (m.OUT/'source-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'pages':reports},indent=2))
    raise SystemExit(0 if report['passed'] else 1)
