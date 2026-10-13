"""Additional offline native feature checks against 2-layer/1oz rules."""
import importlib.util,json,math,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight';sys.path.insert(0,str(root/'.tools/pcb-python'))
s=importlib.util.spec_from_file_location('m',root/'scripts/readability-model.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
from shapely.geometry import Point,LineString
from shapely.strtree import STRtree
s=importlib.util.spec_from_file_location('audit',root/'scripts/audit-final-physical.py');a=importlib.util.module_from_spec(s)
sys.argv=[str(root/'scripts/audit-final-physical.py'),str(out),'pcb-restored-rule.json'];s.loader.exec_module(a)
tracks=[];vias=[];holes=[];widths=[]
for (t,i),(_,p) in a.doc['records'].items():
 if t=='LINE' and p.get('layerId') in (1,2) and p.get('netName'):
  widths.append(p['width']*.0254);tracks.append((p['netName'],LineString([(p['startX']*.0254,p['startY']*.0254),(p['endX']*.0254,p['endY']*.0254)]).buffer(p['width']*.0254/2)))
 if t=='VIA':vias.append((p['netName'],Point(p['centerX']*.0254,p['centerY']*.0254),p['holeDiameter']*.0254,p['viaDiameter']*.0254))
 if t=='PAD' and p.get('hole') and not p.get('plated'):holes.append(('NPTH',Point(p['centerX']*.0254,p['centerY']*.0254),p['hole']['width']*.0254))
tree=STRtree([g for n,g in tracks]);min_via_track=float('inf');via_close=[]
for net,point,drill,diam in vias:
 hole=point.buffer(drill/2)
 for j in tree.query(hole.buffer(.36)):
  n,g=tracks[int(j)]
  if n==net:continue
  dist=hole.distance(g);min_via_track=min(min_via_track,dist)
  if dist<.2-1e-4:via_close.append({'net':net,'otherNet':n,'gapMm':dist,'centerMm':list(point.coords)[0]})
min_via_via=min(a[1].distance(b[1])-(a[2]+b[2])/2 for i,a in enumerate(vias) for b in vias[i+1:])
silk=out/'gerber-dfm-processing.json'
result={'process':'2 layer / 1oz / green, offline not manufacturer approval','source':'https://jlcpcb.com/capabilities/pcb-',
 'minimumTrackWidthMm':min(widths),'publishedMinimumWidthMm':.1,
 'viaDrillRangeMm':[min(v[2] for v in vias),max(v[2] for v in vias)],'minimumViaAnnulusMm':min((v[3]-v[2])/2 for v in vias),
 'minimumViaHoleToDifferentNetTrackMm':min_via_track,'publishedMinimumViaHoleToTrackMm':.2,'viaHoleTrackExceptions':via_close,
 'minimumViaHoleToViaHoleMm':min_via_via,'publishedViaHoleToHoleMm':.2,
 'headerHoleNominalMm':1.100023,'headerPadDiameterMm':1.7,'headerAnnulusMm':(1.7-1.100023)/2,'headerTailDiagonalApproxMm':math.hypot(.79,.41),
 'mountingHoles':len(holes),'mountingHoleDiameterMm':3.2,
 'limitations':['Native DRC reports only the protected R102 netlist difference, not a fabrication release.','Soldermask-to-neighboring-track ownership and full paste stencil/assembly DFM not certified.','Native designator text 0.762mm is below the 1mm manufacturer recommendation; printing readability requires manufacturer review/assembly map.','SMA bodies protrude from board; mating cable clearance and assembled 3D enclosure fit not certified.']}
(out/'dfm-native-features.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
