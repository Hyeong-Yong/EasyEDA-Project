"""Read-only candidate probes for preserving the original layer17 GND neck."""
import json
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
T=runpy.run_path(str(HERE/'plan-tap-vias.py'));M=T['M']
M['Board'].__init__.__globals__['SOURCE']=M['ROOT']/'output/validation/native-adc10-pcb-direct4_copper-20261018.epru'
b=M['Board']();six=T['AllLayers'](b)
base=json.loads((HERE.parent/'strip/c95-layer18/branch-alternatives-layer18-ADC3_INP7.json').read_text())
base=next(r for r in base if r['xyMm']==[52.84,78.2])
result=[]
for xy in [[52.84,78.0],[52.8,78.04],[52.84,77.96],[52.84,77.84],[52.84,77.72],[55.36,78.44]]:
    points=base['innerBranchRoute']['pointsMm']+[xy]
    copper=M['capsule'](points,.06);bb=M['paths_bbox'](copper);hits=[]
    for o in six.obs:
        if 18 not in o['layers'] or o['net']=='ADC3_INP7' or o['kind']=='FILL' and o['net'] in T['POWER_FILL_EXCEPTION']:continue
        if M['overlap'](bb,o['bbox'],M['CLR']+.0005) and M['inter'](copper,M['offset'](o['paths'],M['CLR']+.0005)):hits.append(o['id'])
    result.append({'xyMm':xy,'allSixLayerViaClear':six.viable(xy,'ADC3_INP7'),'layer18ExtendedBranchClear':not hits,'layer18Hits':hits})
print(json.dumps(result,indent=2))
