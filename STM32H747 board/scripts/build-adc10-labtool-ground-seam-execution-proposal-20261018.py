"""Offline compiler for exactly four frozen LINE-only GND corrections."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018'
PLAN=H/'routing/frozen-legacy-ground-four-line-corrective-addendum-v1.json';OUT=H/'pcb-ground-seam-four-line-execution-proposal-v1.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert not OUT.exists()
    assert sha(PLAN)=='801e10de9ece1ae57c80c13e289277377e80d4576874acaa3d80ddb56a1c6da9'
    p=json.loads(PLAN.read_text());assert p['newLineCount']==4 and p['coplanarForeignScreenAllPassed'] and p['allDrillScreensPassed']
    assert p['sourceSha256']=='74d29fb7f5d3579cbf12ef085f26059cad63b86aff5a3dcf8dff8a0cfaf92bfb' and sha(Path(p['sourcePath']))==p['sourceSha256']
    ops=[{'action':'line','type':'LINE',**{k:v[k] for k in('key','net','layerId','startXYMil','endXYMil','widthMil')}} for v in p['newLineCreates']]
    assert len(ops)==4 and all(o['net']=='GND' and o['widthMil']==8 and o['layerId'] in(1,17) for o in ops)
    result={'schema':'stm32h747-labtool-exact-four-ground-seam-line-execution-offline-proposal-v1','status':'OFFLINE_PROPOSAL_REQUIRES_ROOT_EXACT_HASH_AUTHORIZATION','PCBRequired':'0ac2a19168000d8e','sourcePath':p['sourcePath'],'sourceSha256':p['sourceSha256'],'rootReviewAuthorized':False,'routesPath':str(PLAN),'routesSha256':sha(PLAN),'batches':[{'stage':'ground_seam0','operations':ops}],'newLineCount':4,'newViaCount':0,'existingCopperChanges':0,'fillChanges':0,'holeChanges':0,'ruleChanges':0,'nativeCalls':0,'nativeDesignModified':False,'manufacturingReady':False,'requireBeforeGuards':p['existingBeforeGuards'],'allowedLayer17Exception':'Only exact operations 2 and 3 from this frozen manifest after root authorization; no broader inner-layer authorization.'}
    OUT.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'proposal':str(OUT),'sha256':sha(OUT),'sourceSha256':p['sourceSha256'],'operationCount':len(ops),'layerIds':[o['layerId'] for o in ops]}))
if __name__=='__main__':main()
