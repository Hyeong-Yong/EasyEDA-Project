"""Thirdsiteskeep.17mmreservefromBottomPG12byC150nearbyvia."""
import hashlib,json
from pathlib import Path
from shapely.geometry import box,Point
HERE=Path(__file__).resolve().parent
code=(HERE/'independent-pump-ground-via-review-v2.py').read_text(encoding='utf8')
code=code.replace("(28.7,28.85)","(28.7,28.8)")
code=code.replace('independent-optional-pump-three-ground-vias-v2.json','independent-optional-pump-three-ground-vias-v3.json')
code=code.replace("via-review-v2'","via-review-v3'")
exec(compile(code,str(HERE/'independent-pump-ground-via-review-v2.py'),'exec'),globals())
p=HERE/'routing/independent-optional-pump-three-ground-vias-v3.json';report=json.loads(p.read_text(encoding='utf8'))
for v in report['newViaCreates']:
    ref={'PUMP_CHIP_GND':'U30','PUMP_INPUT_CAP_GND':'C150','PUMP_OUTPUT_CAP_GND':'C152'}[v['key']]
    q=pp[ref];doc=m['m']['docs']['FOOTPRINT',q['footprintUuid']];pts=[]
    for (k,r),(_,b) in doc.items():
        if k=='LINE' and b.get('layerId')==9:pts +=[(b['startX']*.0254,b['startY']*.0254),(b['endX']*.0254,b['endY']*.0254)]
        elif k=='POLY' and b.get('layerId')==9:pts +=h['G']['ring_path'](b['path'])
    if not pts:
        # Verifiedexisting0805libraryhasnosavedassemblyoutline; use the
        # conservativepad-envelope asabody-enclosingbound, not inventedbodydata.
        fps,_=h['footprint'](doc)
        bounds=[s.bounds for s,b in fps.values()]
        pts=[(min(b[0] for b in bounds),min(b[1] for b in bounds)),(max(b[2] for b in bounds),max(b[3] for b in bounds))]
        v['bodyBoundEvidence']='Noassemblylayer9; conservativeentirePAD-envelope enclosingbodyusedinstead.'
    else:v['bodyBoundEvidence']='Nativeassemblylayer9outline'
    local=box(min(a for a,b in pts),min(b for a,b in pts),max(a for a,b in pts),max(b for a,b in pts))
    body=h['world'](local,q['xyMm'],q['angle']);via=Point(v['xyMm']).buffer(.225,resolution=64)
    assert via.distance(body)>.05,(ref,via.distance(body))
    v['nativeAssemblyLayer9BodyBoundsMm']=list(body.bounds)
    v['viaCopperToNativeAssemblyBodyGapMm']=via.distance(body)
    v['minimumAnyPadCopperEdgeGapMm']=min(via.distance(s) for k,s in allpads)
report['status']='PASS_PROSPECTIVE_ROOT_REVIEW_REQUIRED'
report['nativeBodyProof']='EverycandidateviaCopperliesoutsideactualnativeassemblylayer9bodyorbody-enclosingentirePAD-envelope>0.05mm; conservativecourtyardoverlapisnotclaimedbodyoverlap.'
p.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'finalPath':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':report['status'],'bodyGaps':[{'key':v['key'],'bodyGapMm':v['viaCopperToNativeAssemblyBodyGapMm'],'padGapMm':v['minimumAnyPadCopperEdgeGapMm']} for v in report['newViaCreates']]}))
