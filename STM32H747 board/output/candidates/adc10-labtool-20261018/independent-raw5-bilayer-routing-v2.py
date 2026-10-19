"""Compare short1-2additionalVIA rawfeed withouttouchingzeroviafallbackV1."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
code=(HERE/'independent-raw5-bilayer-routing.py').read_text(encoding='utf8')
code=code.replace("OUT=RT/'independent-raw5-bilayer-route-v1.json'","OUT=RT/'independent-raw5-bilayer-route-v2-shortvia.json'")
code=code.replace("PORT=RT/'six-layer-via-port-candidates-commonpower-v3b.json'","PORT=RT/'six-layer-via-port-candidates-commonpower-v4.json'")
code=code.replace("neighbors.append(((3-l,x,y),12.0))","neighbors.append(((3-l,x,y),3.0))")
code=code.replace("'schema':'independent-raw5-bilayer-route-v1'","'schema':'independent-raw5-bilayer-route-v2-shortvia'")
code=code.replace("if __name__=='__main__':main()",'')
env={'__file__':str(HERE/'independent-raw5-bilayer-routing.py'),'__name__':'raw5_shortvia_v2'}
exec(compile(code,str(HERE/'independent-raw5-bilayer-routing.py'),'exec'),env)
env['main']()
p=HERE/'routing/independent-raw5-bilayer-route-v2-shortvia.json';r=json.loads(p.read_text(encoding='utf8'))
r['reserved43ViaSha256']=r.pop('reserved42ViaSha256')
for via in r['newViaCreates']:
    via['minimumReserved43DrillEdgeGapMm']=via.pop('minimumReserved42DrillEdgeGapMm')
for i,q in enumerate(r['newLineCreates'][:2]):
    q['inheritedOriginalKey']=q['key'];q['key']=f'RAW5_CN1_FEED_{i+1:03d}'
# Explicit graphthroughbothlayers/sourcePTH/reserved2rawports/new2vias.
common=json.loads((HERE/'routing/commonpower-top-local-v5-short-fly-review.json').read_text(encoding='utf8'))
adj={}
def node(layer,xy):return layer,round(xy[0],6),round(xy[1],6)
def edge(a,b):adj.setdefault(a,set()).add(b);adj.setdefault(b,set()).add(a)
for q in r['newLineCreates']+[q for q in common['newLineCreates'] if q['net']=='+5V']:
    edge(node(q['layerId'],q['startXYmm']),node(q['layerId'],q['endXYmm']))
for xy in [r['startR200Port'],r['endR197Port']]+[v['xyMm'] for v in r['newViaCreates']]:edge(node(1,xy),node(2,xy))
start=node(2,r['existingSource']['xyMm']);seen={start};todo=[start]
while todo:
    v=todo.pop()
    for w in adj.get(v,[]):
        if w not in seen:seen.add(w);todo.append(w)
goals=[{'role':q['role'],'pinEndpoint':q['startXYmm'],'reachableFromCN1':node(1,q['startXYmm']) in seen} for q in common['newLineCreates'] if q['net']=='+5V']
assert all(g['reachableFromCN1'] for g in goals)
r['raw5WholeTreeConnectivity']={'CN1toBothInputIsolatorPins':goals,'allPass':True,'viaTransitions':['2existingreservedRAW5ports','2newexplicitall6layerVIAs'],'limits':'Coordinategraphusesexactsharedendpoints; actualnativepadshape/sourcepincontract/DRCfollow-uprequired.'}
r['recommendation']='Preferthis2VIA/17.149mmbridgerouteoverzeroVIA24.886mmTOPfallback: avoidsRAW5routingbeneathC152andU31body/highZFBneighborhood. Notabenchnoiseguarantee.'
r['reservedPortCountChecked']=43
p.write_text(json.dumps(r,indent=2)+'\n',encoding='utf8')
print(json.dumps({'finalPath':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'raw5FullGraph':r['raw5WholeTreeConnectivity'],'newLines':len(r['newLineCreates']),'newVias':len(r['newViaCreates'])}))
