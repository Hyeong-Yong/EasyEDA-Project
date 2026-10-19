"""Separate V4: terminate C103 power bridge on the actual VIA centre, not its search preference."""
import json,hashlib,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018/routing'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
old=H/'frozen-combined-routing-v3.json';assert sha(old)=='7242a437de06cddc8efa24723a6b062964dcae935130a0ec5710775932ff3abf';r=json.loads(old.read_text());v=next(p for p in r['newViaCreates'] if p['key']=='C103_POWER_VIN_V6');assert v['xyMm']==[25.4,72.9];changed=[]
for p in r['newLineCreates']:
    if p['key']=='LABTOOL_C103-REFERENCE-FINAL-V6D_0004':before=copy.deepcopy(p);assert p['startXYmm']==[25.6,72.9];p['startXYmm']=v['xyMm'];changed.append({'before':before,'after':copy.deepcopy(p)})
    elif p['key']=='C103_POWER_BOTTOM_001':before=copy.deepcopy(p);assert p['endXYmm']==[25.6,72.9];p['endXYmm']=v['xyMm'];changed.append({'before':before,'after':copy.deepcopy(p)})
assert len(changed)==2
r['schema']='adc10-labtool-frozen-combined-routing-v4';r['status']='CANDIDATE_REQUIRES_FRESH_COPPER_SCREEN';r['frozenModules']=[{'path':str(old),'sha256':sha(old)}];r['changesFromV3']={'onlyTwoTraceEndpointEdits':changed,'all62ViasExact':True,'allOther524LinesExact':True,'physicalPlacementChanged':False,'allHighZFilterAndLowZRefJogsExact':True,'reason':'VIA search selected25.4,72.9, not the preferred25.6,72.9. V3 was literally connected by annular overlap; V4 connects the two trace centrelines to the actual VIA centre.'};r['replacementForUnroutedV7PowerEdge']='C103 local U9 VIN connection: TOP1mm -> powerVIA21.4,72.775 -> BOTTOM4.00195mm -> actual powerVIA25.4,72.9 -> TOP1.30162mm -> U9.2. Dedicated C103 GND VIA21.5,71.225 via .9mmTOPstub.'
for k in ['exactLiteralCopperConflicts','newDrillClearanceConflicts','viaInPadConflicts','unroutedConnections','physicalNetGraphsExcludingGroundAnd3V3']:r.pop(k,None)
target=H/'combined-routing-v4-candidate.json';target.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'candidate':str(target),'sha256':sha(target)}))
