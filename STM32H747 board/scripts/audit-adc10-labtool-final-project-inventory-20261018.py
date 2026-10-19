"""Read-only final 437/1342/704/863 saved-project binding and drill audit.

This is not a copper-connectivity/DRC substitute. Run only after the independent
native copper-union readback and saved-checkpoint durability audits pass.
"""
import argparse,copy,hashlib,json,math,re,runpy
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'output/candidates/adc10-labtool-20261018';VAL=ROOT/'output/validation';MM=.0254
BASE=VAL/'native-adc10-pcb-labtool_107_placed_v6_saved-20261018.epru'
BASESHA='a5d126649aa3e03dd0b74baa5e412d03c2a6ae93466b0fc4e04010f37232e9f9'
ROUTES=HERE/'routing/frozen-combined-routing-v5.json';ROUTESHA='d7fd2b7683da5e25e8591c88bba0a7711ecb700681f30cf4b8938f88380d6c07'
ECO=ROOT/'output/checkpoints/STM32H747_labtool_pcb_eco_wip_20261018.epro2'
NET=VAL/'native-adc10-labtool_schematic-Protel2-20261018.net'
H=runpy.run_path(str(ROOT/'output/candidates/adc-inline-wiring/audit-inline-final-project.py'));U=H['UTIL'];M=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def scoped(p,suffix):
    p=(ROOT/p).resolve();assert p.is_relative_to((ROOT/'output').resolve()) and p.suffix==suffix;return p
def attrs(rows):
    out=defaultdict(dict)
    for (k,r),b in rows.items():
        if k=='ATTR':out[b['parentId']][b['key']]=b.get('value')
    return out
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--checkpoint',type=Path,required=True);ap.add_argument('--stage',required=True);args=ap.parse_args()
    assert re.fullmatch('[a-z0-9_]{3,60}',args.stage);src=scoped(args.source,'.epru');cp=scoped(args.checkpoint,'.epro2');assert sha(BASE)==BASESHA and sha(ROUTES)==ROUTESHA
    old=M['parse'](BASE);actual=M['parse'](src);aa=attrs(actual);oa=attrs(old);raw,_=H['read_snapshot'](cp);docs={k:U['bodies'](v) for k,v in raw.items()};eco,_=H['read_snapshot'](ECO);edocs={k:U['bodies'](v) for k,v in eco.items()};errors=[]
    def need(ok,code,**detail):
        if not ok:errors.append({'code':code,**detail})
    heads=[b for (k,r),b in actual.items() if k=='DOCHEAD'];need(len(heads)==1 and heads[0].get('uuid')=='0ac2a19168000d8e' and heads[0].get('docType')=='PCB','WRONG_NATIVE_PCB_IDENTITY')
    protected={}
    for typ in ['COMPONENT','ATTR','PAD_NET','RULE','RULE_TEMPLATE','LAYER','LAYER_PHYS','PAD','ARC','POLY','STRING']:
        a={k:v for k,v in old.items() if k[0]==typ};b={k:v for k,v in actual.items() if k[0]==typ};protected[typ]={'baselineCount':len(a),'finalCount':len(b),'allBodiesExact':a==b};need(a==b,'PROTECTED_RECORD_CHANGED',type=typ)
    outline_a={k:v for k,v in old.items() if k[0]=='LINE' and v.get('layerId')==11};outline_b={k:v for k,v in actual.items() if k[0]=='LINE' and v.get('layerId')==11};need(outline_a==outline_b,'MECHANICAL_OUTLINE_CHANGED')
    comp={cid:b for (k,cid),b in actual.items() if k=='COMPONENT'};refs={aa[cid].get('Designator'):cid for cid in comp};need(len(comp)==len(refs)==437 and None not in refs,'COMPONENT_MEMBERSHIP_COUNT')
    footprint_changes=[str(k) for k in docs.keys()|edocs.keys() if k[0]=='FOOTPRINT' and docs.get(k)!=edocs.get(k)];need(not footprint_changes,'SAVED_FOOTPRINT_DOCUMENT_CHANGED',documents=footprint_changes)
    stored=docs.get(('PCB','0ac2a19168000d8e'),{});stored_pn={k:v for k,v in stored.items() if k[0]=='PAD_NET'};source_pn={k:v for k,v in actual.items() if k[0]=='PAD_NET'};need(stored_pn==source_pn and len(source_pn)==1523,'SAVED_PCB_PAD_NET_MISMATCH')
    sch={}
    for (kind,uuid),rows in docs.items():
        if kind!='SCH_PAGE':continue
        a=attrs(rows)
        for cid,v in a.items():
            if v.get('Convert to PCB')!='yes' or not v.get('Designator'):continue
            ref=v['Designator'];info={k:v.get(k) for k in ('Unique ID','Footprint','Device')}
            need(ref not in sch or sch[ref]==info,'MULTIUNIT_SCHEMATIC_BINDING_CONFLICT',ref=ref);sch[ref]=info
    need(set(sch)==set(refs) and len(sch)==437,'SCHEMATIC_PCB_437_COMPONENT_SET_MISMATCH')
    uid=[]
    for ref,cid in refs.items():
        if ref not in sch:continue
        for field in ('Device','Footprint'):need(aa[cid].get(field)==sch[ref][field],'SCHEMATIC_PCB_BINDING',ref=ref,field=field)
        u=comp[cid].get('attrs',{}).get('Unique ID');uid.append(u);need(u==sch[ref]['Unique ID'],'SCHEMATIC_PCB_UID',ref=ref)
    need(None not in uid and len(set(uid))==437,'DUPLICATE_OR_MISSING_UID')
    padnet={};seen=set();physical_pad_errors=[]
    for (kind,rid),b in actual.items():
        if kind!='PAD_NET':continue
        _,cid,pn,pid=json.loads(rid);ref=aa[cid]['Designator'];key=ref,str(pn);fp=docs.get(('FOOTPRINT',aa[cid]['Footprint']),{});pad=fp.get(('PAD',pid));seen.add((cid,pid))
        if pad is None or str(pad.get('num'))!=str(pn):physical_pad_errors.append({'ref':ref,'number':pn,'padId':pid})
        need(key not in padnet or padnet[key]==b.get('padNet'),'DUPLICATE_NUMBER_CONFLICTING_NET',pin=key);padnet[key]=b.get('padNet')
    missing_owned=[]
    for cid,b in comp.items():
        for (kind,pid),p in docs.get(('FOOTPRINT',aa[cid]['Footprint']),{}).items():
            if kind=='PAD' and (cid,pid) not in seen:missing_owned.append([aa[cid]['Designator'],pid])
    need(not physical_pad_errors and not missing_owned,'PHYSICAL_PAD_NET_BINDING_ERROR',badBindings=physical_pad_errors,missingOwned=missing_owned)
    expected_netsha=json.loads((HERE/'independent-schematic-audit.json').read_text())['finalNativeSchematic']['netlistSha256'];need(sha(NET)==expected_netsha,'FROZEN_VERIFIED_SCHEMATIC_NETLIST_CHANGED')
    nodes=runpy.run_path(str(ROOT/'scripts/verify-native-netlist.py'))['parse_protel2'](NET.read_text(encoding='utf-8-sig'));expected={(p['ref'],str(p['number'])):p['net'] for p in nodes};connected={k:v for k,v in padnet.items() if v};diff=[{'pin':k,'schematic':expected.get(k),'pcb':connected.get(k)} for k in expected.keys()|connected.keys() if expected.get(k)!=connected.get(k)];need(len(nodes)==len(expected)==len(connected)==1342 and not diff,'ALL1342_SCHEMATIC_PCB_PINS',differences=diff)
    for n in ('1','3','7','8'):need(not padnet.get(('U9',n)),'REF5025_UNUSED_PIN_CONNECTED',pin=n)
    def drills(rows,a):
        out={}
        for (kind,rid),b in rows.items():
            if kind=='VIA':out['VIA',rid]={'kind':'via_round','centerMm':[b['centerX']*MM,b['centerY']*MM],'widthMm':b['holeDiameter']*MM,'heightMm':b['holeDiameter']*MM,'net':b['netName']}
            elif kind=='PAD' and max((b.get('hole') or {}).get('width',0),(b.get('hole') or {}).get('height',0))>0:out['BOARD_NPTH',rid]={'kind':'board_npth','body':b}
            elif kind=='COMPONENT':
                for (pk,pid),p in docs['FOOTPRINT',a[rid]['Footprint']].items():
                    h=p.get('hole') or {}
                    if pk!='PAD' or max(h.get('width',0),h.get('height',0))<=0:continue
                    point=Point(p['centerX']*MM,p['centerY']*MM)
                    if b['layerId']==2:point=Point(point.x,-point.y)
                    point=M['world'](point,(b['x']*MM,b['y']*MM),b['angle']);category='component_npth' if p.get('plated') is False else 'component_slot' if h.get('holeType')=='SLOT' else 'component_round'
                    out['COMPONENT_PAD',rid,pid]={'kind':category,'ref':a[rid]['Designator'],'number':str(p['num']),'centerMm':[point.x,point.y],'widthMm':h.get('width',0)*MM,'heightMm':h.get('height',0)*MM,'holeRelativeAngleDeg':p.get('relativeAngle',0),'componentAngleDeg':b['angle'],'componentLayer':b['layerId'],'plated':p.get('plated')}
        return out
    from shapely.geometry import Point
    old_drills=drills(old,oa);final_drills=drills(actual,aa);need(len(old_drills)==799 and len(final_drills)==863,'PHYSICAL_DRILL_COUNT',before=len(old_drills),after=len(final_drills));old_drill_diffs=[str(k) for k,v in old_drills.items() if final_drills.get(k)!=v];need(not old_drill_diffs,'ORIGINAL799_PHYSICAL_DRILL_CHANGED',drills=old_drill_diffs)
    old_v={k:v for k,v in old.items() if k[0]=='VIA'};new_v={k:v for k,v in actual.items() if k[0]=='VIA' and k not in old_v};need(len(old_v)==640 and len(new_v)==64 and all(actual.get(k)==v for k,v in old_v.items()),'ORIGINAL640_VIA_BODIES_OR_NEW64_COUNT')
    plan=json.loads(ROUTES.read_text());unmatched=dict(new_v);via_matches=[]
    def serialized(actual,expected):return actual==expected or actual==float(f'{expected:.4f}')
    for v in plan['newViaCreates']:
        matches=[k for k,b in unmatched.items() if b.get('netName')==v['net'] and b.get('centerX')==round(v['xyMm'][0]/MM,4) and b.get('centerY')==round(v['xyMm'][1]/MM,4) and serialized(b.get('viaDiameter'),v['viaDiameterMm']/MM) and serialized(b.get('holeDiameter'),v['holeDiameterMm']/MM)]
        need(len(matches)==1,'NEW_VIA_PLAN_MATCH',key=v['key'],matches=[str(k) for k in matches]);via_matches.append({'key':v['key'],'nativeId':matches[0][1] if len(matches)==1 else None})
        if len(matches)==1:unmatched.pop(matches[0])
    need(not unmatched,'UNEXPECTED_NEW_VIA',records=[str(k) for k in unmatched]);watched={n.casefold() for c in json.loads((HERE/'schematic-plan.json').read_text())['allPinContracts'].values() for n in c.values() if n and n.casefold() not in ('gnd','+3v3')};need(len(watched)==74,'TARGET74_NET_SET_COUNT')
    report={'schema':'labtool-final-native-saved-project-inventory-v1','passed':not errors,'source':{'path':str(src),'sha256':sha(src)},'checkpoint':{'path':str(cp),'sha256':sha(cp)},'baseline':{'path':str(BASE),'sha256':sha(BASE)},'frozenRouting':{'path':str(ROUTES),'sha256':sha(ROUTES)},'schematicNetlist':{'path':str(NET),'sha256':sha(NET)},'components':len(comp),'schematicPhysicalRefs':len(sch),'uniqueIds':len(set(uid)),'connectedLogicalPins':len(connected),'physicalPadNetRecords':len(source_pn),'targetPhysicalGraphNetSetCount':len(watched),'drillCounts':dict(Counter(v['kind'] for v in final_drills.values())),'physicalDrills':len(final_drills),'original799DrillsUnchanged':not old_drill_diffs,'original640ViaBodiesExact':all(actual.get(k)==v for k,v in old_v.items()),'newViaMatches':via_matches,'protected':protected,'outlineLayer11Exact':outline_a==outline_b,'allFootprintDocumentsExactVsEco':not footprint_changes,'errors':errors,'nativeCalls':0,'manufacturingReady':False,'limitations':['This proves metadata, physical drill identity and component/pin binding only; 74-net physical connectivity requires the independent actual/native-union topology proof.','Full native-copper receipt-chain/union and durable whole-project audits must pass separately.','Actual strict unchanged18-rule DRC, preserving all6 FILL/GND/+3V3 anchors and Gerber CAM verification remain separate gates.']}
    out=HERE/'audits'/f'final-project-inventory-{args.stage}.json';assert not out.exists(),'Append a new stage instead of overwriting evidence';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':not errors,'report':str(out),'sha256':sha(out),'parts':len(comp),'pins':len(connected),'physicalDrills':len(final_drills),'errors':errors[:4]}))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
