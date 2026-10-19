"""Read-only ECO footprint audit:179 pads of34 new and40 replaced parts."""
import hashlib
import json
import math
import runpy
import zipfile
from collections import Counter,defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'output/candidates/adc-dc-buffer'
SOURCE=ROOT/'output/validation/native-adc10-pcb-eco_applied-20261017.epru'
BEFORE=ROOT/'output/validation/native-adc10-pcb-before-20261017.epru'
SCH=ROOT/'output/validation/native-adc10-sch-reopened-20261017.epru'
CP=ROOT/'output/checkpoints/STM32H747_adc10_schematic_20261017.epro2'
M=runpy.run_path(str(HERE/'independent-adc10-candidate-graph-audit.py'))


def read_libs():
    with zipfile.ZipFile(CP) as z:
        raw=z.read(next(n for n in z.namelist() if n.endswith('.epru'))).decode('utf-8-sig')
    docs,cur={},None
    for line in raw.splitlines():
        if not line.strip():continue
        h,b=line.split('||',1)
        h,b=json.loads(h),b.rstrip('|')
        b=json.loads(b) if b else None
        if h['type']=='DOCHEAD':cur=b['docType'],b['uuid'];docs.setdefault(cur,{})
        k=h['type'],h.get('id');p=docs[cur].get(k)
        if p is None or h.get('ticket',0)>=p[0].get('ticket',0):docs[cur][k]=(h,b)
    return {key:{k:b for k,(h,b) in rows.items() if isinstance(b,dict)} for key,rows in docs.items()}


def main():
    sha,parse,attrs_for=M['sha'],M['parse'],M['attrs_for']
    rows,before,sch=parse(SOURCE),parse(BEFORE),parse(SCH)
    a,refs=attrs_for(rows);olda,oldrefs=attrs_for(before);sa,srefs=attrs_for(sch)
    lib=read_libs()
    mapping_path=OLD/'adc-dc-runtime-library-map.json'
    manifest_path=OLD/'adc-dc-library-manifest.json'
    mapping=json.loads(mapping_path.read_text());manifest=json.loads(manifest_path.read_text())
    contract_path=HERE/'independent-adc10-expected-full-pin-contract-20261017.json'
    expected={(p['ref'],p['number']):p['net'] for p in json.loads(contract_path.read_text())['expectedPins']}
    errors,tests=[],[]
    def check(ok,name,detail=None):
        t={'test':name,'passed':bool(ok)}
        if detail is not None:t['detail']=detail
        tests.append(t)
        if not ok:errors.append(t)
    added=set(refs)-set(oldrefs)
    newrefs={f'U{i}' for i in range(9,20)}|{f'C{i}' for i in range(97,120)}
    rrefs={f'R{i}' for i in range(137,146)}|{f'R{i}' for i in range(149,158)}|{f'R{i}' for i in range(161,173)}
    crefs={f'C{i}' for i in range(80,83)}|{f'C{i}' for i in range(86,89)}|{f'C{i}' for i in range(93,97)}
    replaced=rrefs|crefs
    actualreplaced={ref for ref in refs.keys()&oldrefs.keys() if a[refs[ref]].get('Footprint')!=olda[oldrefs[ref]].get('Footprint')}
    check(added==newrefs and len(added)==34,'exact34 new footprint instances',sorted(added))
    check(actualreplaced==replaced and len(replaced)==40,'exact40 replaced footprint masters',sorted(actualreplaced))
    targets=newrefs|replaced
    padnets=defaultdict(list)
    for (kind,rid),b in rows.items():
        if kind!='PAD_NET':continue
        decoded=json.loads(rid)
        check(len(decoded)==4 and decoded[0]=='PAD_NET','native PAD_NET composite key valid '+rid)
        _,cid,num,pid=decoded
        padnets[cid].append((str(num),pid,b))
    foot_summary={}
    for name,spec in mapping['footprints'].items():
        uid=spec['uuid']
        f=lib['FOOTPRINT',uid]
        pads={b['num']:(pid,b) for (kind,pid),b in f.items() if kind=='PAD'}
        check(len(pads)==len(spec['pads']),'unique expected numbered pads '+name)
        check(set(pads)=={p['number'] for p in spec['pads']},'footprint pad numbering '+name)
        positions=[]
        for standard in spec['pads']:
            num=standard['number'];pid,p=pads[num];shape=p['defaultPad']
            if 'centerMm' in standard:
                expected_geo=standard['centerMm']+standard['copperSizeMm']+[standard['cornerRadiusMm'],standard['solderMaskExpansionMm'],standard['pasteExpansionMm']]
                actual_geo=[p['centerX']*.0254,p['centerY']*.0254,shape['width']*.0254,shape['height']*.0254,shape['radius']*.0254,p['topSolderExpansion']*.0254,p['topPasteExpansion']*.0254]
                check(max(abs(x-y) for x,y in zip(actual_geo,expected_geo))<1e-6,'TI verified land geometry '+name+'.'+num,{'expectedMm':expected_geo,'actualMm':actual_geo})
            else:
                check(p['centerX']==standard['xMil'] and p['centerY']==standard['yMil'] and shape==standard['defaultPad'],'trusted passive land geometry '+name+'.'+num)
            check(shape['padType']=='RECT' and shape['width']>0 and shape['height']>0 and 0<=shape.get('radius',0)<=min(shape['width'],shape['height'])/2,'valid positive roundrect pad '+name+'.'+num)
            check(p['layerId']==1 and p['hole'] is None and p['padAngle']==0 and not p['specialPad'] and p['padOffsetX']==p['padOffsetY']==p['relativeAngle']==0,'SMD top-layer holeless pad without hidden shape override '+name+'.'+num)
            positions.append({'number':num,'primitiveId':pid,'centerMm':[p['centerX']*.0254,p['centerY']*.0254],'copperSizeMm':[shape['width']*.0254,shape['height']*.0254],'cornerRadiusMm':shape.get('radius',0)*.0254,'solderMaskExpansionMm':None if p.get('topSolderExpansion') is None else p['topSolderExpansion']*.0254,'pasteExpansionMm':None if p.get('topPasteExpansion') is None else p['topPasteExpansion']*.0254})
        separations=[]
        for i,p in enumerate(positions):
            for q in positions[:i]:
                dx=max(0,abs(p['centerMm'][0]-q['centerMm'][0])-(p['copperSizeMm'][0]+q['copperSizeMm'][0])/2)
                dy=max(0,abs(p['centerMm'][1]-q['centerMm'][1])-(p['copperSizeMm'][1]+q['copperSizeMm'][1])/2)
                lower=math.hypot(dx,dy)
                check(lower>.1524,'intrinsic master bounding-rectangle pad clearance >0.1524mm '+name+p['number']+'/'+q['number'],lower)
                separations.append(lower)
        foot_summary[name]={'runtimeUuid':uid,'padCount':len(pads),'pads':positions,'minimumConservativeIntrinsicCopperClearanceMm':min(separations),'basis':spec['geometryOrigin'],'manufacturerDrawing':spec.get('drawing'),'manufacturingApproved':False}
    namebyuuid={v['uuid']:k for k,v in mapping['footprints'].items()}
    part_reports=[]
    target_pad_count=0
    for ref in sorted(targets):
        cid=refs[ref];schid=srefs[ref]
        fp,dev=a[cid]['Footprint'],a[cid]['Device']
        check(fp==sa[schid]['Footprint'] and dev==sa[schid]['Device'],'PCB exact schematic runtime binding '+ref)
        check(fp in namebyuuid,'expected reviewed footprint master '+ref)
        f=lib['FOOTPRINT',fp]
        pads={str(b['num']):(pid,b) for (kind,pid),b in f.items() if kind=='PAD'}
        actual=padnets[cid]
        check(len(actual)==len(pads),'pad count no missing or duplicate PAD_NET '+ref,{'master':len(pads),'instance':len(actual)})
        check({(n,pid) for n,pid,b in actual}=={(n,pid) for n,(pid,p) in pads.items()},'exact numbered pad-to-primitive identity '+ref)
        cc=rows['COMPONENT',cid]
        check(cc['layerId']==1,'PCB top-layer instance, no bottom numbering reflection '+ref)
        check(not [rid for (kind,rid),b in rows.items() if kind=='PAD' and cid in rid],'no PCB-level footprint pad geometry override '+ref)
        dmeta=[b for (kind,pid),b in lib['DEVICE',dev].items() if kind=='META']
        check(len(dmeta)==1 and dmeta[0]['attributes']['Footprint']==fp and dmeta[0]['attributes']['Symbol']==sa[schid]['Symbol'],'DEVICE maps exact symbol/footprint '+ref)
        records=[]
        for num,pid,b in actual:
            check(b['padNet']==expected[ref,num],'target pad net '+ref+'.'+num,{'actual':b['padNet'],'expected':expected[ref,num]})
            check(not b.get('attrsMap'),'no target pad-level property override '+ref+'.'+num,b.get('attrsMap'))
            local=pads[num][1]
            t=math.radians(cc['angle'])
            global_mm=[(cc['x']+local['centerX']*math.cos(t)-local['centerY']*math.sin(t))*.0254,(cc['y']+local['centerX']*math.sin(t)+local['centerY']*math.cos(t))*.0254]
            records.append({'number':num,'primitiveId':pid,'net':b['padNet'],'globalCenterMmYUp':global_mm})
        target_pad_count+=len(actual)
        part_reports.append({'ref':ref,'change':'new' if ref in newrefs else 'replaced','componentId':cid,'deviceUuid':dev,'footprintUuid':fp,'footprintName':namebyuuid[fp],'instanceAngleDeg':cc['angle'],'padCount':len(actual),'pads':records})
    check(target_pad_count==179,'all179 pads across74 target parts independently checked')
    pinouts={
      'OPA320AIDBVR':{'1':'OUT','2':'V- / GND','3':'IN+','4':'IN-','5':'V+'},
      'REF3325AIDBZR':{'1':'IN','2':'OUT','3':'GND'}}
    for ref in sorted({f'U{i}' for i in range(10,20)}):
        cid=refs[ref];nets={n:b['padNet'] for n,pid,b in padnets[cid]}
        check(nets['1']==nets['4'] and nets['2']=='GND' and nets['5']=='+3V3' and '_PRE' in nets['3'],'OPA320 DBV5 pin contract '+ref,nets)
    cid=refs['U9'];unets={n:b['padNet'] for n,pid,b in padnets[cid]}
    check(unets=={'1':'+3V3','2':'ADC_BIAS_2V5','3':'GND'},'REF3325 DBZ3 pin contract',unets)
    report={'schema':'adc10-independent-pcb-footprint179-pad-audit-20261017-v1','passed':not errors,
      'sourcePath':str(SOURCE),'sourceSha256':sha(SOURCE),'beforePath':str(BEFORE),'beforeSha256':sha(BEFORE),
      'libraryCheckpointPath':str(CP),'libraryCheckpointSha256':sha(CP),'trustedRuntimeLibraryMapPath':str(mapping_path),'trustedRuntimeLibraryMapSha256':sha(mapping_path),
      'trustedGeometryManifestPath':str(manifest_path),'trustedGeometryManifestSha256':sha(manifest_path),
      'scope':{'newParts':34,'replacedParts':40,'totalParts':74,'pads':target_pad_count,'uniqueFootprintMasters':6},
      'pinoutBasis':'Previously reviewed local TI datasheets, TI land-pattern captures and library manifest; identity pin-number mapping is crosschecked against actual PAD_NET primitive IDs and latest schematic. No new internet research needed.',
      'officialSources':manifest['officialSources'],'manufacturerPinouts':pinouts,'footprintMasters':foot_summary,'parts':part_reports,
      'hazardsFound':errors,'liveApiCalls':0,'nativeFilesWritten':0,'pcbMutatedByAudit':False,
      'limitations':['Pad geometry and pin mapping only, not placement/routing or fabrication approval. New parts remain parked outside board until root placement work.','Passive0402/0603/0805 lands are preserved project-local clones, not manufacturer-specific passive land approval.','Intrinsic master-pad clearance bounds do not assess clearances to neighboring board copper or rule-inherited solder/paste masks.','Full1136-pin PCB/SCH contract, preserved project/library scope and placement are separately audited by parent/root.'],
      'checks':tests,'errors':errors}
    out=HERE/'independent-adc10-pcb-footprint179-pad-audit-20261017.json'
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'sourceSha256':sha(SOURCE),'scope':report['scope'],'errors':errors},indent=2))
    if errors:raise ValueError('PCB footprint-pad audit failed')


if __name__=='__main__':main()
