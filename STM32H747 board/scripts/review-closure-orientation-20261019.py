"""Read-only pin-labelled geometry fit to supplier library footprints."""
from pathlib import Path
import json,math,collections,csv
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019';O=OUT/'orientation'
tasks=json.loads((O/'footprint-tasks.json').read_text(encoding='utf8'))
placement={x['ref']:x for x in json.loads((ROOT/'output/jlcpcb-20261019-review/PLACEMENT_AUDIT.json').read_text(encoding='utf8'))}
def records(p):
 r=[]
 for l in p.read_text(encoding='utf8').splitlines():
  if '||' not in l:continue
  h,b=l.split('||',1);h=json.loads(h);raw=b.removesuffix('|')
  if raw:r.append((h,json.loads(raw)))
 return r
def key(s):return str(int(s)) if str(s).isdigit() else s
rows=[]
for index,t in enumerate(tasks):
 p=O/f'canonical-{index}.epru'
 if not p.exists():continue
 pads=[{'pin':key(b['num']),'x':b['centerX']*.0254,'y':b['centerY']*.0254} for h,b in records(p) if h['type']=='PAD' and b.get('num')]
 for ref in t['refs']:
  actual=placement[ref];pairs=[]
  if t['mpn']=='SMA-KWE901':
   # Manufacturer library: centre 5, shields 1..4. Existing circuit: centre 1,
   # all four shields 2. Shell has rotational symmetry; use model/body direction.
   src=next(p for p in pads if p['pin']=='5');dst=next(p for p in actual['pads'] if p['pin']=='1');angle=float(actual['modelTransform'].split(',')[3]);pairs=[(src,dst)]
   candidates=[angle];basis='Supplier centre 5 -> board signal 1; four shell pins -> board 2. Port direction follows preserved mechanical model.'
  else:
   ca=collections.defaultdict(list);aa=collections.defaultdict(list)
   for p1 in pads:ca[p1['pin']].append(p1)
   for p1 in actual['pads']:
    if p1['pin']:aa[key(p1['pin'])].append(p1)
   pairs=[(ca[k][0],aa[k][0]) for k in sorted(set(ca)&set(aa)) if len(ca[k])==len(aa[k])==1]
   candidates=[0,90,180,270];basis='Least-squares 90-degree rotation using unique pad numbers; original lands retained.'
  fits=[]
  for angle in candidates:
   c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle));q=[(a['x']*c-a['y']*s,a['x']*s+a['y']*c,b['x'],b['y']) for a,b in pairs]
   if not q:continue
   tx=sum(z[2]-z[0] for z in q)/len(q);ty=sum(z[3]-z[1] for z in q)/len(q);errs=[math.hypot(z[0]+tx-z[2],z[1]+ty-z[3]) for z in q]
   fits.append({'angle':angle,'originXmm':tx,'originYmm':ty,'maxErrorMm':max(errs),'rmsErrorMm':math.sqrt(sum(e*e for e in errs)/len(errs))})
  fits.sort(key=lambda x:x['rmsErrorMm']);best=fits[0] if fits else None
  p1=next((p for p in actual['pads'] if key(p['pin']) in ['1','A1','01']),None)
  rows.append({'ref':ref,'mpn':t['mpn'],'supplierId':t['supplierId'],'canonicalFootprint':t['footprintUuid'],'canonicalFile':p.name,'namedPinsCompared':len(pairs),'boardPads':len(actual['pads']),'canonicalPads':len(pads),'side':actual['physicalSide'],'bestFit':best,'alternatives':fits[1:],'pin1':p1,'basis':basis,'review':'FIT' if best and best['maxErrorMm']<.31 and (len(pairs)>=2 or t['mpn']=='SMA-KWE901') else 'REVIEW'})
(O/'pin-fit-review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'capturedMasters':sum((O/f'canonical-{i}.epru').exists() for i in range(len(tasks))),'parts':len(rows),'fits':sum(r['review']=='FIT' for r in rows),'review':[(r['ref'],r['namedPinsCompared'],r['bestFit']) for r in rows if r['review']!='FIT']},ensure_ascii=False))
