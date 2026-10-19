"""One prospectiveGNDstitch preserves exact70.3mm²Bottomsplitlobe.
No nativecalls; all6nonFILL/799old+48planned drill/body/no-VIP screen.
"""
import ast,hashlib,json,math
from pathlib import Path
from shapely.geometry import Point,Polygon,LineString,box
from shapely.strtree import STRtree
HERE=Path(__file__).resolve().parent;RT=HERE/'routing'
helper=HERE/'independent-pump-ground-via-review.py'
tree=ast.parse(helper.read_text(encoding='utf8'))
stop=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='plan' for t in n.targets))
tree.body=tree.body[:stop]
ns={'__file__':str(helper),'__name__':'bottom_lobe_stitch_model'}
exec(compile(ast.fix_missing_locations(tree),str(helper),'exec'),ns)
copper=ns['copper'];drills=ns['drills'];allpads=ns['allpads'];fills=ns['fills'];allnew=ns['allnew'];h=ns['h']
groundpath=RT/'independent-optional-pump-three-ground-vias-v3.json'
assert h['sha'](groundpath)=='cd16b7dc9f49f1e32df989b67438b10f0132e1590496a685e28dc72354638264'
ground=json.loads(groundpath.read_text(encoding='utf8'))
for v in ground['newViaCreates']:
    copper.append({'key':v['key'],'net':'gnd','layers':(1,2,15,16,17,18),'shape':Point(v['xyMm']).buffer(.225,resolution=32)})
allnew+=ground['newViaCreates']
for q in ground['newLineCreates']:copper.append({'key':q['key'],'net':'gnd','layers':(1,),'shape':LineString([q['startXYmm'],q['endXYmm']]).buffer(.15,resolution=32)})
maskpath=HERE/'ground/local-static-fill-clearance-phase366-v4-commonv5-42ports-approved2notches.json'
mask=json.loads(maskpath.read_text(encoding='utf8'))
lobe=next(q for q in mask['fillCreateOperations'] if q['layerId']==2 and 70<q['areaMm2']<71)
rr=[h['G']['ring_path'](p) for p in lobe['afterPath']];poly=Polygon(rr[0],rr[1:]);assert poly.is_valid
plan=json.loads((HERE/'independent-pcb-placement-short-negative-commonpower-v4-proposal.json').read_text(encoding='utf8'))
courts=[(q['ref'],box(*q['conservativeCourtBoundsMm'])) for q in plan['edits']]
ct=STRtree([o['shape'] for o in copper]);pt=STRtree([s for k,s in allpads]);dt=STRtree([s for k,s in drills])
preferred=(33,82);xylist=[(round(29.0+.1*i,2),round(73.5+.1*j,2)) for i in range(90) for j in range(138)]
xylist.sort(key=lambda p:math.dist(p,preferred));chosen=None;rejected=0
for xy in xylist:
    p=Point(xy);s=p.buffer(.225,resolution=64);probe=s.buffer(.17,resolution=32);hole=p.buffer(.1,resolution=64)
    if not poly.contains(s.buffer(.02)) or any(s.intersects(c) for ref,c in courts):rejected+=1;continue
    if any(copper[int(i)]['net']!='gnd' and s.distance(copper[int(i)]['shape'])<.17 for i in ct.query(probe)):rejected+=1;continue
    if any(s.distance(allpads[int(i)][1])<.06 for i in pt.query(s.buffer(.06))):rejected+=1;continue
    if any(hole.distance(drills[int(i)][1])<.301 for i in dt.query(hole.buffer(.301))):rejected+=1;continue
    if any(hole.distance(Point(v['xyMm']).buffer(.1,resolution=64))<.301 for v in allnew):rejected+=1;continue
    chosen=xy;break
assert chosen,'Noqualifiedsitefound'
p=Point(chosen);s=p.buffer(.225,resolution=64);hole=p.buffer(.1,resolution=64)
cuts=[{'id':f['id'],'layerId':f['layerId'],'net':f['net'],'valid':f['valid']} for f in fills if f['net'].casefold()!='gnd' and s.buffer(.17).intersects(f['shape'].envelope) and (not f['valid'] or s.buffer(.17).intersects(f['shape']))]
anchors=[]
for f in fills:
    if f['layerId'] not in (15,17,18) or f['net'].casefold()!='gnd' or not f['valid'] or s.intersection(f['shape']).area<1e-8:continue
    vv=[o for o in copper if o['key'].startswith('VIA:') and o['net']=='gnd' and o['shape'].intersection(f['shape']).area>1e-8]
    if vv:
        v=min(vv,key=lambda q:s.distance(q['shape']))
        anchors.append({'layerId':f['layerId'],'fillId':f['id'],'candidateAnnulusContactAreaMm2':s.intersection(f['shape']).area,'oldGroundViaKey':v['key'],'oldViaCenterMm':[v['shape'].centroid.x,v['shape'].centroid.y],'qualification':'SamevalidsourceFILLpolygonpositiveareacontact; finalantipadandMCUVSSglobalgraphmustberechecked.'})
assert anchors,'NoinnerGNDsourceanchorfound'
out={'schema':'independent-prospective-one-bottom-lobe-stitch-20261018','status':'PASS_SCOPED_ROOT_REVIEW_REQUIRED_FINAL_SHARED_ROUTE_PENDING','nativeCalls':0,'sourceActualV4Sha256':h['sha'](ns['env']['SOURCE']),'placementV4Sha256':h['sha'](HERE/'independent-pcb-placement-short-negative-commonpower-v4-proposal.json'),'maskPlanSha256':h['sha'](maskpath),'groundPumpApproved3Sha256':h['sha'](groundpath),'lobeKey':lobe['key'],'lobeAreaMm2':poly.area,'lobeBoundsMm':list(poly.bounds),'newViaCreates':[{'key':'BOTTOM70_GND_STITCH_1','net':'GND','xyMm':list(chosen),'viaDiameterMm':.45,'holeDiameterMm':.20,'allLayers':[1,2,15,16,17,18],'minimumOriginal799DrillEdgeGapMm':min(hole.distance(d) for k,d in drills),'minimumReserved48DrillEdgeGapMm':min(hole.distance(Point(v['xyMm']).buffer(.1,resolution=64)) for v in allnew),'minimumAnyPadCuGapMm':min(s.distance(z) for k,z in allpads),'fullViaAnnulusInsidePreservedBottomLobe':poly.contains(s),'requiresLocalFillAntipads':cuts}],'newLineCreates':[],'innerLayerNominalAnchorEvidence':anchors,'candidateCountRejected':rejected,'existing640Vias799DrillsChanged':0,'bottomLobeDeletedCopperAreaMm2':0,'finalSharedRouteMutualCheckPending':True,'remaining':['Rootapproval/exactsitebeforecreation','Finalallnewshared+RAWroutes/moreVIAsmutualCu/drillcheck','Finalall6FILLantipadsandglobal345GNDpadMCUVSSgraph','NativeDRC/source/readback/reopen'],'manufacturingApproved':False}
op=RT/'independent-bottom70-ground-stitch-v1.json';op.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print(json.dumps({'path':str(op),'sha256':h['sha'](op),'site':chosen,'anchors':anchors,'via':out['newViaCreates'][0]}))
