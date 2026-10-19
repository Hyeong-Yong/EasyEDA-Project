"""Separate C103-only placement/guarded-native-operation proposal, no native calls."""
import json,copy,hashlib,runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/candidates/adc10-labtool-20261018';HERE=BASE/'routing';MM=.0254
M=runpy.run_path(str(BASE/'independent-pcb-placement-proposal.py'));SRC=ROOT/'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru';OLD=BASE/'independent-pcb-placement-short-negative-commonpower-v5b-ref-flipped-proposal.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def main():
    before=json.loads(OLD.read_text());after=copy.deepcopy(before);rows=M['parse'](SRC);attrs=M['attrs_of'](rows);docs,_=M['READ'](M['CHECK']);entry=next(p for p in after['edits'] if p['ref']=='C103');cid=entry['componentId'];body=rows['COMPONENT',cid];pp,court=M['footprint'](docs['FOOTPRINT',attrs[cid]['Footprint']]);xy=(22.4,72.0);angle=180;entry['xyMm']=list(xy);entry['angle']=angle;entry['set']={'x':xy[0]/MM,'y':xy[1]/MM,'rotation':angle,'layer':1};entry['sourceBodyBefore']=body;entry['role']='Local 1uF REF VIN bypass, rerouted near U9 VIN rather than remote channel rail';entry['pads']=[]
    for pn,(s,pb) in pp.items():
        s=M['world'](s,xy,angle);entry['pads'].append({'number':pn,'net':'+5V_AFE' if pn=='1' else 'GND','centerMm':[s.centroid.x,s.centroid.y],'boundsMm':list(s.bounds)})
    entry['conservativeCourtBoundsMm']=list(M['world'](court,xy,angle).bounds);entry['requiresOldAFEGeometryRework']=[]
    after.update({'schema':'adc10-labtool-placement-v6-c103-local-bypass','parentPlacementSha256':sha(OLD),'sourcePath':str(SRC),'sourceSha256':sha(SRC),'changedRefsOnly':['C103'],'nativeCalls':0,'nativeWriteApproved':False,'variantReason':'Resolve 151.8mm remote capacitor feed with a short directly routed U9 VIN bypass; GND stitch still requires verification.'})
    target=BASE/'independent-pcb-placement-v6-c103-local-bypass-proposal.json';target.write_text(json.dumps(after,indent=2)+'\n')
    expected=copy.deepcopy(body);expected.update({'x':xy[0]/MM,'y':xy[1]/MM,'angle':angle})
    op={'schema':'adc10-labtool-C103-only-placement-guarded-operations-v6','sourcePath':str(SRC),'sourceSha256':sha(SRC),'placementPath':str(target),'placementSha256':sha(target),'operations':[{'ref':'C103','componentId':cid,'uniqueId':entry['uniqueId'],'beforeBody':body,'beforeBodySha256':digest(body),'afterBody':expected,'allowedChangedFields':['x','y','angle'],'value':attrs[cid].get('Value'),'footprint':attrs[cid]['Footprint'],'expectedPads':entry['pads']}],'allOther106EntriesExact':all(p==q for p,q in zip(before['edits'],after['edits']) if p['ref']!='C103'),'nativeCalls':0,'originalDrillChanges':0,'viaChanges':0,'rootMustVerifySourceBeforeApplying':True}
    opt=HERE/'c103-only-placement-exact-operations-v6.json';opt.write_text(json.dumps(op,indent=2)+'\n')
    base=json.loads((HERE/'frozen-combined-routing-v2.json').read_text());base['newLineCreates']=[p for p in base['newLineCreates'] if p['sourceModule']!='query-reference-power-final-v1-layer1.json'];base['newViaCreates']=[p for p in base['newViaCreates'] if p['key']!='REFERENCE_POWER_RAIL_PORT'];base['newViaCreates'].extend(json.loads((HERE/'six-layer-via-port-candidates-reference-two-ground-v6.json').read_text())['viasProposed']);base['status']='INCOMPLETE_V6_EXPLORATION_NOT_FROZEN';bt=HERE/'v6-base-preserved-copper-with-two-ground-ports.json';bt.write_text(json.dumps(base,indent=2)+'\n')
    print(json.dumps({'placement':str(target),'placementSha256':sha(target),'operations':str(opt),'operationsSha256':sha(opt),'base':str(bt),'pads':entry['pads']}))
if __name__=='__main__':main()
