"""Append only two independently approved Ground-plane stitches to frozen V4."""
import json,hashlib,argparse,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018/routing'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--ground-module',type=Path,required=True);ap.add_argument('--ground-sha256',required=True);args=ap.parse_args();gp=args.ground_module.resolve();assert sha(gp)==args.ground_sha256
old=H/'frozen-combined-routing-v4.json';assert sha(old)=='c255e19d838132efe682fb9c024dd53e017a4fd0119a17732983efafc1f34048';r=json.loads(old.read_text());g=json.loads(gp.read_text());extra=g['newViaCreates'];assert len(extra)==2 and not g.get('newLineCreates',[])
for v in extra:assert v['net']=='GND' and v['viaDiameterMm']==.45 and v['holeDiameterMm']==.20 and set(v['allLayers'])=={1,2,15,16,17,18}
r['newViaCreates'].extend(copy.deepcopy(extra));assert len(r['newViaCreates'])==64 and len({tuple(v['xyMm']) for v in r['newViaCreates']})==64
r['schema']='adc10-labtool-frozen-combined-routing-v5';r['status']='CANDIDATE_REQUIRES_FRESH_ALL6_SCREEN_AND_GROUND_MASK';r['frozenModules']=[{'path':str(old),'sha256':sha(old)},{'path':str(gp),'sha256':sha(gp)}];r['changesFromV4']={'all526LinesExact':True,'allExisting62ViasExact':True,'addedOnlyGroundPlaneStitches':[{'key':v['key'],'xyMm':v['xyMm']} for v in extra],'noNewLines':True,'physicalPlacementChanged':False,'sourceChanged':False,'rootApprovalRequiredForListedSites':True};r['explicitPlaneOnlyGroundViaKeys']=['BOTTOM70_GND_LOBE_STITCH']+[v['key'] for v in extra]
for k in ['exactLiteralCopperConflicts','newDrillClearanceConflicts','viaInPadConflicts','unroutedConnections','physicalNetGraphsExcludingGroundAnd3V3']:r.pop(k,None)
target=H/'combined-routing-v5-candidate.json';target.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'candidate':str(target),'sha256':sha(target),'lines':len(r['newLineCreates']),'vias':len(r['newViaCreates']),'planeOnlyGroundViaKeys':r['explicitPlaneOnlyGroundViaKeys']}))
