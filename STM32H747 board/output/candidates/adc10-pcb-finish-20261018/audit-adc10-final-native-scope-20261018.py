"""Final actual PCB electrical, original-drill/rule/mechanical/checkpoint scope proof."""
import argparse,hashlib,json,math,runpy
from collections import Counter,defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
E=runpy.run_path(str(ROOT/'output/candidates/adc10-dc-buffer-20261017/independent-adc10-pcb-electrical-audit-20261017.py'))
SNAP=runpy.run_path(str(ROOT/'output/candidates/adc-inline-wiring/audit-inline-final-project.py'))['read_snapshot']
BASE=ROOT/'output/validation/native-adc10-pcb-baseline-20261018.epru'
BASE_SHA='5a1fe43c0ce8e36ee89bcac512321e55610b83c3e890b429373878efb6825b9b'
BASE_CP=ROOT/'output/checkpoints/STM32H747_before_pcb_route_20261018.epro2'
CONTRACT=ROOT/'output/candidates/adc10-dc-buffer-20261017/independent-adc10-expected-full-pin-contract-20261017.json'
MIN_DRILL_MM=11.811*MM
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def attrs(rows):
    aa=defaultdict(dict)
    for(k,i),b in rows.items():
        if k=='ATTR':aa[b['parentId']][b['key']]=b['value']
    return aa,{a['Designator']:cid for cid,a in aa.items()if'Designator'in a}
def bodydocs(d):return{k:b for k,(h,b)in d.items()if k[0]!='DOCHEAD'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--manifest-sha',required=True)
    ap.add_argument('--pcb-netlist',required=True);ap.add_argument('--sch-netlist',default=str(E['SCH_NET']));ap.add_argument('--drc',required=True);ap.add_argument('--erc',required=True)
    ap.add_argument('--chain-report',required=True);ap.add_argument('--ground-report',required=True);ap.add_argument('--checkpoint');ap.add_argument('--tag',default='final')
    args=ap.parse_args();source=Path(args.source).resolve();mp=Path(args.manifest).resolve()
    assert sha(BASE)==BASE_SHA and sha(mp)==args.manifest_sha
    plan=json.loads(mp.read_text());before,_=M['M']['parse'](BASE);rows,_=M['M']['parse'](source);ss=sha(source)
    aa,refs=attrs(rows);ba,brefs=attrs(before);libs=M['BM']['LM']['read_libs']();checks=[];errors=[]
    def check(ok,test,detail=None):
        r={'test':test,'passed':bool(ok)}
        if detail is not None:r['detail']=detail
        checks.append(r)
        if not ok:errors.append(r)
    contract={(r['ref'],str(r['number'])):r['net']for r in json.loads(CONTRACT.read_text())['expectedPins']}
    _,pins,conflicts=E['pad_assignments'](rows,refs)
    check(pins==contract and not conflicts and len(pins)==1136 and len(refs)==354,'Actual full354parts1136pin contract exact',{'parts':len(refs),'pins':len(pins),'conflicts':conflicts})
    check(refs==brefs,'All354original instance IDs/reference identities unchanged')
    check({k:b for k,b in before.items()if k[0]=='PAD_NET'}=={k:b for k,b in rows.items()if k[0]=='PAD_NET'},'Every original physical PAD_NET body exact, including MCU ports')
    check(all(rows['COMPONENT',cid]['attrs']==before['COMPONENT',cid]['attrs']and aa[cid]['Footprint']==ba[cid]['Footprint']and aa[cid]['Device']==ba[cid]['Device']for cid in refs.values()),'All component values/UIDs/device/footprint bindings unchanged')
    check(rows['COMPONENT',refs['U1']]==before['COMPONENT',brefs['U1']],'MCU U1 full component body unchanged')
    original_vias={k:b for k,b in before.items()if k[0]=='VIA'};final_vias={k:b for k,b in rows.items()if k[0]=='VIA'}
    newkeys=final_vias.keys()-original_vias.keys()
    check(len(original_vias)==634 and len(final_vias)==640 and len(newkeys)==6 and all(rows.get(k)==b for k,b in original_vias.items()),'All634originalVIA full bodies exact plus exactly6new')
    def via_spec(b):return(b['netName'],b['centerX'],b['centerY'],b['holeDiameter'],b['viaDiameter'])
    expected_vias=Counter((o['net'],round(o['xyMil'][0],4),round(o['xyMil'][1],4),round(o['holeDiameterMil'],4),round(o['diameterMil'],4))for o in plan['viaCreates'])
    check(Counter(via_spec(rows[k])for k in newkeys)==expected_vias,'All6newVIA net/XY/drill/pad dimensions exactly approved4decimal-mil specs')
    check(all(rows[k]['viaType']=='NORMAL'and not rows[k].get('unusedInnerLayers')and rows[k].get('locked')is False for k in newkeys),'All6newVIAs plated through/normal, no inner-layer suppressions')
    for kinds,title in [({'RULE','RULE_TEMPLATE'},'All18selected strict RULEdefinitions/template exact'),({'LAYER','LAYER_PHYS'},'All6Cu stack/layer definitions exact'),
                        ({'POLY'},'All500original POLYs including8outline/CN1cutout exact'),({'PAD'},'All4mountingNPTH PAD full bodies exact'),({'STRING'},'All21J18Bottomsilk STRING bodies exact')]:
        check({k:b for k,b in before.items()if k[0]in kinds}=={k:b for k,b in rows.items()if k[0]in kinds},title)
    check(sum(k[0]=='RULE'for k in rows)==18 and sum(k[0]=='PAD'for k in rows)==4 and sum(k[0]=='STRING'for k in rows)==21,'Rule/mechanical/J18 exact record counts')
    drilled=[];categories=Counter();owner_diffs=[]
    for ref,cid in brefs.items():
        for(pk,pid),p in libs['FOOTPRINT',ba[cid]['Footprint']].items():
            if pk!='PAD':continue
            hole=p.get('hole')or{};w,h=hole.get('width',0),hole.get('height',0)
            if max(w,h)<=0:continue
            oldc=before['COMPONENT',cid];newc=rows['COMPONENT',cid]
            if oldc!=newc:owner_diffs.append(ref)
            angle=math.radians(oldc['angle']);x=p['centerX'];y=p['centerY']
            if oldc['layerId']==2:y=-y
            center=((oldc['x']+x*math.cos(angle)-y*math.sin(angle))*MM,(oldc['y']+x*math.sin(angle)+y*math.cos(angle))*MM)
            cat='componentNPTH'if p.get('plated')is False else('componentSlot'if hole.get('holeType')=='SLOT'else'componentRound')
            categories[cat]+=1;drilled.append({'id':ref+':'+pid,'kind':cat,'centerXYmm':center,'conservativeRadiusMm':max(w,h)*MM/2})
    check(not owner_diffs,'Every155original component-owned drill owner full component body unchanged',owner_diffs)
    check(categories==Counter({'componentRound':133,'componentSlot':13,'componentNPTH':9}),'Original155component-owned drill inventory exact',dict(categories))
    for(k,i),b in before.items():
        if k=='VIA':drilled.append({'id':'VIA:'+i,'kind':'originalVIA','centerXYmm':[b['centerX']*MM,b['centerY']*MM],'conservativeRadiusMm':b['holeDiameter']*MM/2})
        elif k=='PAD':
            h=b['hole'];drilled.append({'id':'PAD:'+i,'kind':'boardNPTH','centerXYmm':[b['centerX']*MM,b['centerY']*MM],'conservativeRadiusMm':max(h['width'],h['height'])*MM/2})
    check(len(drilled)==793,'All793original physical drills retained:634VIAs+155component-owned+4mounting')
    newdrills=[{'id':k[1],'centerXYmm':[rows[k]['centerX']*MM,rows[k]['centerY']*MM],'radiusMm':rows[k]['holeDiameter']*MM/2}for k in sorted(newkeys)]
    edges=[]
    for a in newdrills:
        nearest=min((math.dist(a['centerXYmm'],b['centerXYmm'])-a['radiusMm']-b['conservativeRadiusMm'],b['id'])for b in drilled)
        edges.append({'newVIAId':a['id'],'nearestOriginalDrillId':nearest[1],'gapMm':nearest[0]})
        check(nearest[0]>=MIN_DRILL_MM,'NewVIA drill clears ALL793original drills by exact selected11.811mil '+a['id'],edges[-1])
    newpairs=[]
    for i,a in enumerate(newdrills):
        for b in newdrills[i+1:]:
            gap=math.dist(a['centerXYmm'],b['centerXYmm'])-a['radiusMm']-b['radiusMm'];newpairs.append({'a':a['id'],'b':b['id'],'gapMm':gap})
            check(gap>=MIN_DRILL_MM,'New-to-new drill edge gap exact selected11.811mil '+a['id']+':'+b['id'],gap)
    pcbnet=Path(args.pcb_netlist).resolve();schnet=Path(args.sch_netlist).resolve();pp,pr=E['protel'](pcbnet);sp,sr=E['protel'](schnet)
    check(pp==sp==contract and pr==sr==set(refs),'Actual PCB Protel/SCHsaved export/source independent full pin contract all match')
    drcp,ercp=Path(args.drc).resolve(),Path(args.erc).resolve();drc=json.loads(drcp.read_text());erc=json.loads(ercp.read_text())
    check(drc.get('passed')is True and drc.get('violations')==0 and not drc.get('details'),'Actual supplied strict native DRC passed with0violations',drc)
    check(erc.get('passed')is True,'Actual supplied native schematic ERC passed')
    linked=[]
    for label,value in [('signalChains',args.chain_report),('all44Grounds',args.ground_report)]:
        p=Path(value).resolve();r=json.loads(p.read_text());check(r.get('passed')is True and r.get('sourceSha256')==ss,'Final actual-source matching independent '+label+' report')
        if label=='all44Grounds':check(r.get('mode')=='ACTUAL_NATIVE_FINAL_COPPER','Ground graph is actual native, not prospective')
        linked.append({'type':label,'path':str(p),'sha256':sha(p)})
    scope=None
    if args.checkpoint:
        cp=Path(args.checkpoint).resolve();b,bt=SNAP(BASE_CP);a,at=SNAP(cp)
        check(b.keys()==a.keys(),'Full checkpoint document set unchanged')
        changed=[k for k in b.keys()&a.keys()if bodydocs(b[k])!=bodydocs(a[k])]
        check(changed==[('PCB','0ac2a19168000d8e')],'Exactly PCB document changed; all3923non-PCBdocuments exact',changed)
        pcb=a['PCB','0ac2a19168000d8e'];check(bodydocs(pcb)=={k:v for k,v in rows.items()if k[0]!='DOCHEAD'},'Final checkpoint PCB body exactly matches actual reopened native source')
        scope={'path':str(cp),'sha256':sha(cp),'beforePath':str(BASE_CP),'beforeSha256':sha(BASE_CP),'documents':len(a),'changedDocuments':changed,
               'otherDocumentCountExact':len(a)-len(changed),'beforeEffectiveTombstones':bt['effectiveLatestTombstones'],'finalEffectiveTombstones':at['effectiveLatestTombstones']}
    check(sha(source)==ss and sha(mp)==args.manifest_sha,'Actual source and frozen manifest unchanged during final audit')
    out=HERE/f'adc10-{args.tag}-native-scope-electrical-drill-independent-audit-20261018.json'
    report={'schema':'stm32h747-adc10-final-native-scope-electrical-drill-independent-20261018-v1','passed':not errors,
        'sourcePath':str(source),'sourceSha256':ss,'originalBaselinePath':str(BASE),'originalBaselineSha256':BASE_SHA,
        'manifestPath':str(mp),'manifestSha256':args.manifest_sha,'parts':len(refs),'connectedPins':len(pins),
        'originalVIAcount':len(original_vias),'newVIAcount':len(newkeys),'originalPhysicalDrillCount':len(drilled),'finalPhysicalDrillCount':len(drilled)+len(newdrills),
        'originalComponentDrillCategories':dict(categories),'newDrillToOriginalEdgeChecks':edges,'newToNewDrillEdgeChecks':newpairs,
        'exactSelectedDrillEdgeMinimumMm':MIN_DRILL_MM,'linkedActualGeometryReports':linked,'checkpointScope':scope,
        'pcbNetlist':{'path':str(pcbnet),'sha256':sha(pcbnet)},'schematicNetlist':{'path':str(schnet),'sha256':sha(schnet)},'DRC':{'path':str(drcp),'sha256':sha(drcp)},'ERC':{'path':str(ercp),'sha256':sha(ercp)},
        'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['No fabrication approval: open-input RAW ADC0 detector and high-bandwidth redesign are outside frozen architecture; existing CAM caveat remains.',
            'Slots/component NPTH are conservatively enclosed by max-axis circles for new-hole spacing; every original owner/component and library binding must remain unchanged.',
            'All18RULEdefinitions/template/stack exact; prior native normalizations of empty old-net metadata/selectors are separately qualified in copper-cut phase reports.',
            'Strict DRC/independent geometry apply only to the explicit actual source/export/checkpoint files.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
