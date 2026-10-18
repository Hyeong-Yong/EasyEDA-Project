"""Rebase pending copper operations after root has applied six native moves."""
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'plan-bottom-buckets.py'))
CURRENT=M['ROOT']/'output/validation'/(sys.argv[2] if len(sys.argv)>2 else 'native-adc10-pcb-remaining6_move-20261018.epru')
EXPECTED=sys.argv[3] if len(sys.argv)>3 else 'af83b97cf7b775d834fc8339eb627beade225247ff077c2a234b3a50a4f808d4'
assert hashlib.sha256(CURRENT.read_bytes()).hexdigest()==EXPECTED
rows=M['OLD']['PARSE'](CURRENT)
target=HERE/(sys.argv[1] if len(sys.argv)>1 else 'remaining6-native-operations.json')
d=json.loads(target.read_text())
assert d['passedOfflineCompositeAudit']
oldmoves=d.get('componentMoves',[])
assert len(oldmoves)==6
for o in d['fillModifyOperations']:
    assert rows['FILL',o['primitiveId']]==o['beforeBody'],o['primitiveId']
verified=[]
for op in oldmoves:
    c=rows['COMPONENT',op['primitiveId']]
    assert c['layerId']==op['targetLayerId']
    assert math.dist([c['x'],c['y']],op['targetXYmil'])<.0002
    assert abs((c['angle']-op['nativeRotationDegrees']+180)%360-180)<.0001
    verified.append({**op,'beforeComponentBody':c,'alreadyAppliedAndNativeWorldPadsVerifiedByRoot':True,'performModify':False})
d['componentMoves']=[]
d['alreadyAppliedRemaining6ComponentMoves']=verified
d['geometryAnalysisSourcePath']=d['sourcePath'];d['geometryAnalysisSourceSha256']=d['sourceSha256']
d['sourcePath']=str(CURRENT);d['sourceSha256']=EXPECTED
d['allTwelveTargetFillBodiesExactAgainstCurrentAfterMoveSource']=True
d['nativeExecutionInstructions']=['All ten capacitor moves and final C95 rotation are already applied; do not repeat component moves.',f"Apply only these pending {len(d['fillModifyOperations'])} FILL modifications, {len(d['fillCreateOperations'])} retained GND lobe FILL create, six normal VIAs, and listed signal/GND LINEs.",'Every FILL source body is guarded exact against current source. Preconstruct every explicitly closed compound polygon before changing its existing FILL.','Perform full strict native DRC without disabling checks; audit and fix any reported imported per-instance silk overlap before final fabrication output.']
vias=d['viaCreates'];minhole=min((math.dist(a['xyMil'],b['xyMil'])-(a['holeDiameterMil']+b['holeDiameterMil'])/2)*M['MM'] for i,a in enumerate(vias) for b in vias[i+1:])
d['newVsNewPhysicalDrillEdgeGapAudit']={'minimumEdgeGapMm':minhole,'requiredMm':.2999994,'passed':minhole>=.2999994}
assert d['newVsNewPhysicalDrillEdgeGapAudit']['passed']
M['Board'].__init__.__globals__['SOURCE']=CURRENT
board=M['Board']()
audit=runpy.run_path(str(HERE/'audit-full-original-drills.py'))['audit']
proposals=[{'ref':p['ref'],'xyMm':[x*M['MM'] for x in p['xyMil']],'holeMm':p['holeDiameterMil']*M['MM']} for p in vias]
d['all793OriginalPhysicalHoleClearanceAudit']=audit(M,board,proposals)
assert d['all793OriginalPhysicalHoleClearanceAudit']['allNewVsOriginalHoleEdgesPassed']
rotation=HERE/'c95-rotation0-move-only-guard-20261018.json'
if rotation.exists():d['alreadyAppliedFinalC95RotationContract']={'path':str(rotation),'sha256':hashlib.sha256(rotation.read_bytes()).hexdigest(),'rotationDegrees':0,'nativeWorldPadVerificationRequired':True}
target.write_text(json.dumps(d,indent=2)+'\n',encoding='utf8')
print(json.dumps({'report':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'passed':d['passedOfflineCompositeAudit'],'sourceSha256':EXPECTED,'componentMovesPending':0,'viaCreates':len(vias),'lineCreates':len(d['lineCreates']),'fillModifies':len(d['fillModifyOperations']),'fillCreates':len(d['fillCreateOperations']),'minimumNewDrillEdgeGapMm':minhole}))
