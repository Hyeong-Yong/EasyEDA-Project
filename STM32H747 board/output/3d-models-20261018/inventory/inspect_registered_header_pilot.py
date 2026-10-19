"""Read-only spatial/differential proof for explicitly transformed headers."""
from collections import Counter
import json
from pathlib import Path
import sys
from inspect_header_defaults import parse,signature,inspect

HERE=Path(__file__).resolve().parent
OUT=HERE.parent
ref=sys.argv[1]
filename=sys.argv[2]
previous=sys.argv[3]
stage=sys.argv[4]
parts={p['ref']:p for p in json.loads((HERE/'components-437.json').read_text(encoding='utf-8'))}
old,oldmeta=parse(OUT/previous)
counts=Counter(signature(f) for f in old)
del old
new,newmeta=parse(OUT/filename)
added=[]
for f in new:
    s=signature(f)
    if counts[s]:
        counts[s]-=1
    else:
        added.append(f)
p=parts[ref]
x,y=p['x_mm'],p['y_mm']
if ref=='J16':
    window=[x-3.6,y-3.6,x+3.6,y+11.7]
elif ref=='J12':
    window=[x-3.6,y-3.6,x+11.7,y+3.6]
else:
    raise ValueError(ref)
selected=[f for f in added if all(window[0]<=pt[0]<=window[2] and window[1]<=pt[1]<=window[3] for pt in f[1])]
data=inspect(selected,[x,y])
report={'schema':'stm32-registered-header-pilot-v1','ref':ref,'before':oldmeta,'after':newmeta,
        'unchanged_faces_missing':sum(counts.values()),'new_faces':len(added),'window_xy_mm':window,
        'selected_new_faces':len(selected),'geometry':data,
        'limitations':['Native OBJ has no component labels; complete model attribution follows changed-face subtraction and isolated region.','Full mount/pin proof uses per-face horizontal sections, not whole material block bounds.']}
target=OUT/'audits'/f'header-registered-{stage}.json'
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'report':str(target),'ref':ref,'new_faces':len(added),'missing_faces':sum(counts.values()),
                  'selected_new_faces':len(selected),'bbox_local_mm':data['bbox_local_mm'],
                  'sections_at_z_minus_half_mm':data['horizontal_sections_mm'].get('-0.5')}))
