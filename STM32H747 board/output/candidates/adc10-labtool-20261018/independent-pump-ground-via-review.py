"""Optional3localpumpreturnvias; read-only proposal, all6Cu/799+45drills.
Doesnotassertexistinggroundislandsarefloating untilseparateplannergraph.
"""
import ast,json,hashlib,runpy
from pathlib import Path
from shapely.geometry import Point,LineString
HERE=Path(__file__).resolve().parent;RT=HERE/'routing'
helper=HERE/'independent-raw5-bilayer-routing.py'
tree=ast.parse(helper.read_text(encoding='utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
stop=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='region' for t in n.targets))
fn.body=fn.body[:stop]+[ast.Return(value=ast.Call(func=ast.Name(id='locals',ctx=ast.Load()),args=[],keywords=[]))]
tree.body=[n for n in tree.body if not isinstance(n,ast.If)]
env={'__file__':str(helper),'__name__':'pump_ground_model'}
exec(compile(ast.fix_missing_locations(tree),str(helper),'exec'),env)
env['PORT']=RT/'six-layer-via-port-candidates-commonpower-v4.json'
m=env['main']();copper=m['copper'];drills=m['drills'];allpads=m['allpads'];fills=m['fills'];ports=m['ports'];h=m['h']
rawpath=RT/'independent-raw5-bilayer-route-v2-shortvia.json';raw=json.loads(rawpath.read_text(encoding='utf8'))
for q in raw['newLineCreates']:
    copper.append({'key':q['key'],'net':'+5v','layers':(q['layerId'],),'shape':LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=32)})
for v in raw['newViaCreates']:
    copper.append({'key':v['key'],'net':'+5v','layers':(1,2,15,16,17,18),'shape':Point(v['xyMm']).buffer(.225,resolution=32)})
allnew=ports+raw['newViaCreates'];candidates=[('PUMP_CHIP_GND','U30','4',(32.4,29.5)),('PUMP_INPUT_CAP_GND','C150','2',(27.7,28.0)),('PUMP_OUTPUT_CAP_GND','C152','2',(31.0,35.4))]
plan=json.loads(env['PLACE'].read_text(encoding='utf8'));pp={p['ref']:p for p in plan['edits']}
newvias=[];lines=[];fails=[]
for key,ref,pin,xy in candidates:
    p=Point(xy);cu=p.buffer(.225,resolution=64);hole=p.buffer(.1,resolution=64)
    bad=[{'key':o['key'],'net':o['net'],'distanceMm':cu.distance(o['shape'])} for o in copper if o['net']!='gnd' and cu.distance(o['shape'])<.17]
    vip=[{'key':k,'distanceMm':cu.distance(s)} for k,s in allpads if cu.distance(s)<.06]
    oldgap=min(hole.distance(d) for k,d in drills)
    newgap=min(hole.distance(Point(v['xyMm']).buffer(.1,resolution=64)) for v in allnew)
    pad=next(q for q in pp[ref]['pads'] if q['number']==pin);assert pad['net']=='GND'
    stub=LineString([pad['centerMm'],xy]).buffer(.15,resolution=32)
    stubbad=[{'key':o['key'],'net':o['net'],'distanceMm':stub.distance(o['shape'])} for o in copper if 1 in o['layers'] and o['net']!='gnd' and stub.distance(o['shape'])<.17]
    ok=not bad and not vip and not stubbad and oldgap>=.301 and newgap>=.301 and all(hole.distance(Point(v['xyMm']).buffer(.1,resolution=64))>=.301 for v in newvias)
    cuts=[{'id':f['id'],'layerId':f['layerId'],'net':f['net'],'originalPolygonValid':f['valid']} for f in fills if f['net'].casefold()!='gnd' and cu.buffer(.17).intersects(f['shape'].envelope) and (not f['valid'] or cu.buffer(.17).intersects(f['shape']))]
    if not ok:fails.append({'key':key,'otherCu':bad,'viaInPad':vip,'stubConflicts':stubbad,'oldDrillGap':oldgap,'new45DrillGap':newgap});continue
    newvias.append({'key':key,'net':'GND','xyMm':list(xy),'viaDiameterMm':.45,'holeDiameterMm':.20,'allLayers':[1,2,15,16,17,18],'minimumOriginal799DrillEdgeGapMm':oldgap,'minimumReserved45DrillEdgeGapMm':newgap,'requiresLocalFillAntipads':cuts,'placementQualification':'OutsideSMAcourts, notvia-in-pad(.06mmminimum); mayoverlapconservativeSOT23/capcourtyardbutnotcomponentbodyorPAD. Rootreviewrequired.'})
    lines.append({'key':key+'_STUB','net':'GND','layerId':1,'widthMm':.3,'startXYmm':pad['centerMm'],'endXYmm':list(xy),'role':f'LocalHFpumpgroundreturn {ref}:{pin}','lengthMm':LineString([pad['centerMm'],xy]).length})
out={'schema':'independent-optional-pump-three-local-ground-via-review','status':'PASS_PROSPECTIVE_ROOT_REVIEW_REQUIRED' if not fails and len(newvias)==3 else 'FAIL','nativeCalls':0,'sourceActualPlacedV4Sha256':h['sha'](env['SOURCE']),'fixedPlacementSha256':h['sha'](env['PLACE']),'fixedRow332Sha256':h['sha'](env['ROW']),'fixedCommon34Sha256':h['sha'](env['PWR']),'reserved43PortSha256':h['sha'](env['PORT']),'raw5V2Sha256':h['sha'](rawpath),'newViaCreates':newvias,'newLineCreates':lines,'fails':fails,'old640Vias799DrillsUntouched':True,'purpose':'BoundpumpHFreturnstoGNDplanesbesideICandinput/outputcapacitors, ratherthanlongindirectTOPgroundpath; separateGNDplannerwillprove128targetanchors. Notanoise/stabilitymeasurement.','remaining':['Parentapprovalbeforeanynativecreation','All6localFILLantipads(layer16+3V3)andnewlobeanchorgraph','MutualCuwithfinalsharedplus/minus/offsetroutes','NativeDRC/sourceaudit'],'manufacturingApproved':False}
p=RT/'independent-optional-pump-three-ground-vias-v1.json';p.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print(json.dumps({'path':str(p),'sha256':h['sha'](p),'status':out['status'],'vias':newvias,'stubs':lines,'fails':fails}))
