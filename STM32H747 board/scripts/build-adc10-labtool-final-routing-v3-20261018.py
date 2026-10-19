"""Immutable V2 -> separate V3 candidate; actual C103 V6 source is required."""
import json,copy,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/candidates/adc10-labtool-20261018';H=BASE/'routing'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf8'))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args();src=args.source.resolve();assert src.exists()
    old=H/'frozen-combined-routing-v2.json';v=load(old);names=['query-c103-reference-final-v6d-layer1.json','query-c103-reference-final-v6d-layer2.json','independent-eight-positive-ground-stitches-v3.json'];v['newLineCreates']=[p for p in v['newLineCreates'] if p['sourceModule']!='query-reference-power-final-v1-layer1.json' and p['key']!='LABTOOL_LOCAL_0432'];v['newViaCreates']=[p for p in v['newViaCreates'] if p['key']!='REFERENCE_POWER_RAIL_PORT']
    for n in names:
        m=load(H/n)
        for p in m['newLineCreates']:
            p=copy.deepcopy(p);p['sourceModule']=n
            if n==names[1]:p['key']='C103_POWER_BOTTOM_001'
            v['newLineCreates'].append(p)
    for n in ['six-layer-via-port-candidates-reference-two-ground-v6.json','six-layer-via-port-candidates-reference-c103-shortbridge-v6b.json','six-layer-via-port-candidates-reference-c103-shortbridge-v6.json','six-layer-via-port-candidates-reference-c103-rightpower-v6d.json']:
        v['newViaCreates'].extend(copy.deepcopy(load(H/n)['viasProposed']))
    v['newViaCreates'].extend(copy.deepcopy(load(H/names[2])['newViaCreates']))
    assert len(v['newLineCreates'])==526 and len(v['newViaCreates'])==62
    assert len({p['key'] for p in v['newLineCreates']+v['newViaCreates']})==588
    placement=BASE/'independent-pcb-placement-v6-c103-local-bypass-proposal.json'
    deps=[old,placement]+[H/n for n in names]+[H/n for n in ['six-layer-via-port-candidates-reference-two-ground-v6.json','six-layer-via-port-candidates-reference-c103-shortbridge-v6b.json','six-layer-via-port-candidates-reference-c103-shortbridge-v6.json','six-layer-via-port-candidates-reference-c103-rightpower-v6d.json']]
    v.update({'schema':'adc10-labtool-frozen-combined-routing-v3','sourcePath':str(src),'sourceSha256':sha(src),'placementPath':str(placement),'placementSha256':sha(placement),'frozenModules':[{'path':str(p),'sha256':sha(p)} for p in deps],'nativeCalls':0,'status':'CANDIDATE_REQUIRES_INDEPENDENT_ALL6_SCREEN_AND_GROUND_MASK','changesFromV2':{'C103Pose':[22.4,72.0,180],'removedLineKeys':['LABTOOL_REFERENCE-POWER-FINAL-V1_0001','LABTOOL_REFERENCE-POWER-FINAL-V1_0002','LABTOOL_LOCAL_0432'],'removedViaKey':'REFERENCE_POWER_RAIL_PORT','newGroundReturns':11,'newLocalPowerBridgeVias':2,'highImpedanceFilterGeometryExact':True,'oldCopperViaDrillChanges':0},'replacementForUnroutedV7PowerEdge':'C103 now has local U9 VIN connection: TOP1mm -> powerVIA21.4,72.775 -> BOTTOM4.20186mm -> powerVIA25.6,72.9 -> TOP1.307mm -> U9.2. Dedicated C103 GND VIA21.5,71.225 via .9mmTOPstub.','strictSpacingQualification':{'selectedNativeStrictCopperGapMm':.1524,'offlineRequiredMm':.1535,'oldNativeRulesChanged':False},'requires':['Authoritative preserving-split six-layer local FILL masks and every physical GND/+3V3 anchor audit.','Strict unchanged-rule native DRC and complete437parts1342pins comparison.']})
    for key in ['physicalNetGraphsExcludingGroundAnd3V3','unroutedConnections','exactLiteralCopperConflicts','newDrillClearanceConflicts','viaInPadConflicts']:v.pop(key,None)
    target=H/'combined-routing-v3-candidate.json';target.write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({'target':str(target),'sha256':sha(target),'lines':len(v['newLineCreates']),'vias':len(v['newViaCreates'])}))
if __name__=='__main__':main()
