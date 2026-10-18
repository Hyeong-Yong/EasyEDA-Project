"""Exact native-grid prospective6VIA drill spacing against793original holes."""
import argparse,hashlib,json,math,runpy
from collections import Counter,defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254;MIN=11.811*MM
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
BASE=ROOT/'output/validation/native-adc10-pcb-baseline-20261018.epru'
BASE_SHA='5a1fe43c0ce8e36ee89bcac512321e55610b83c3e890b429373878efb6825b9b'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--manifest-sha',required=True);args=p.parse_args()
    mp=Path(args.manifest).resolve();assert sha(mp)==args.manifest_sha and sha(BASE)==BASE_SHA
    plan=json.loads(mp.read_text());rows,_=M['M']['parse'](BASE);libs=M['BM']['LM']['read_libs']();aa=defaultdict(dict)
    for(k,i),b in rows.items():
        if k=='ATTR':aa[b['parentId']][b['key']]=b['value']
    holes=[];categories=Counter()
    for(k,i),b in rows.items():
        if k=='VIA':holes.append({'id':i,'kind':'originalVIA','center':[b['centerX']*MM,b['centerY']*MM],'radius':b['holeDiameter']*MM/2});categories['originalVIA']+=1
        elif k=='PAD':
            h=b['hole'];holes.append({'id':i,'kind':'boardNPTH','center':[b['centerX']*MM,b['centerY']*MM],'radius':max(h['width'],h['height'])*MM/2});categories['boardNPTH']+=1
        elif k=='COMPONENT':
            for(pk,pid),pad in libs['FOOTPRINT',aa[i]['Footprint']].items():
                if pk!='PAD':continue
                h=pad.get('hole')or{};w,hh=h.get('width',0),h.get('height',0)
                if max(w,hh)<=0:continue
                t=math.radians(b['angle']);x,y=pad['centerX'],pad['centerY']
                if b['layerId']==2:y=-y
                cat='componentNPTH'if pad.get('plated')is False else('componentSlot'if h.get('holeType')=='SLOT'else'componentRound')
                holes.append({'id':aa[i]['Designator']+':'+pid,'kind':cat,'center':[(b['x']+x*math.cos(t)-y*math.sin(t))*MM,(b['y']+x*math.sin(t)+y*math.cos(t))*MM],'radius':max(w,hh)*MM/2});categories[cat]+=1
    assert len(holes)==793 and categories==Counter({'originalVIA':634,'boardNPTH':4,'componentRound':133,'componentSlot':13,'componentNPTH':9})
    new=[{'ref':o['ref'],'net':o['net'],'center':[round(v,4)*MM for v in o['xyMil']],'radius':round(o['holeDiameterMil'],4)*MM/2}for o in plan['viaCreates']]
    assert len(new)==6
    oldchecks=[];pairs=[]
    for a in new:
        gap,hid=min((math.dist(a['center'],b['center'])-a['radius']-b['radius'],b['id'])for b in holes)
        oldchecks.append({'newRef':a['ref'],'nearestOriginalDrill':hid,'edgeGapMm':gap,'passed':gap>=MIN})
    for i,a in enumerate(new):
        for b in new[i+1:]:
            gap=math.dist(a['center'],b['center'])-a['radius']-b['radius'];pairs.append({'a':a['ref'],'b':b['ref'],'edgeGapMm':gap,'passed':gap>=MIN})
    passed=all(c['passed']for c in oldchecks+pairs)and sha(mp)==args.manifest_sha
    out=HERE/'adc10-final60735-prospective-six-via-drill-independent-audit-20261018.json'
    report={'schema':'stm32h747-prospective-native-grid-six-via-drills-independent-20261018-v1','passed':passed,'mode':'PROSPECTIVE_NATIVE4DECIMALMIL_GRID',
        'manifestPath':str(mp),'manifestSha256':args.manifest_sha,'baselinePath':str(BASE),'baselineSha256':BASE_SHA,
        'originalDrillCount':len(holes),'originalDrillCategories':dict(categories),'newDrills':new,'exactSelectedMinimumMm':MIN,
        'newToOriginal':oldchecks,'newToNew':pairs,'minimumNewToOriginalMm':min(c['edgeGapMm']for c in oldchecks),'minimumNewToNewMm':min(c['edgeGapMm']for c in pairs),
        'liveAPICalls':0,'nativeFilesWritten':0,'limits':['Native4decimal-mil serialized centers/drill diameters, not ideal rounded-mm routing coordinates.',
            'All13component slots conservatively enclosed by max-axis circles; a PASS is conservative. Native rule-specific strict DRC remains required.',
            'Prospective proof only. All793original drill bodies/owners/library definitions must be separately preserved in final native/checkpoint. No fabrication approval.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':passed,'path':str(out),'sha256':sha(out),'minimumNewToOriginalMm':report['minimumNewToOriginalMm'],'minimumNewToNewMm':report['minimumNewToNewMm']},indent=2))
    if not passed:raise SystemExit(1)
if __name__=='__main__':main()
