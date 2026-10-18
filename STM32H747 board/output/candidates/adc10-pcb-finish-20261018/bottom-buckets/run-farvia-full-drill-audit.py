import hashlib
import json
import runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'plan-bottom-buckets.py'))
M['Board'].__init__.__globals__['SOURCE']=M['ROOT']/'output/validation/native-adc10-pcb-remaining6_move-20261018.epru'
b=M['Board']()
d=json.loads((HERE/'remaining6-native-operations-c95-farvia-20261018.json').read_text())
proposals=[{'ref':p['ref'],'xyMm':[x*M['MM'] for x in p['xyMil']],'holeMm':p['holeDiameterMil']*M['MM']} for p in d['viaCreates']]
a=runpy.run_path(str(HERE/'audit-full-original-drills.py'))['audit'](M,b,proposals)
target=HERE/'c95-farvia-all793-physical-hole-audit-20261018.json';target.write_text(json.dumps(a,indent=2)+'\n',encoding='utf8')
print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'originalHoles':a['originalPhysicalDrillCount'],'counts':a['originalDrillKindCounts'],'allPassed':a['allNewVsOriginalHoleEdgesPassed'],'newHoles':a['newVsOriginalDrillAudits']}))
