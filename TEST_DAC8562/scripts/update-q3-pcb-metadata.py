"""Stock Q3 footprint replacement, with explicitly scoped local clearance repair."""
import copy,importlib.util,json,sys,math,uuid
from pathlib import Path
s=importlib.util.spec_from_file_location('m',Path(__file__).with_name('readability-model.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
d=next(iter(m.io.documents(json.loads((m.OUT/'before-pcb.json').read_text(encoding='utf8'))['source']).values()))
aa=m.io.attrs(d);cid=next(i for (t,i) in d['records'] if t=='COMPONENT' and aa.get(i,{}).get('Designator')=='Q3')
seed_doc=next(iter(m.io.documents(json.loads((m.OUT/'q3-loaded-source.json').read_text(encoding='utf8'))['source']).values()))
seed=m.components(seed_doc)['SEED_Q3_REVIEW']
props=dict(next(v['attributes'] for h,v in m.LIB[seed['props']['Device']]['records'].values() if 'attributes' in v))
original=copy.deepcopy(d)
for (t,i),(h,p) in list(d['records'].items()):
    if t=='ATTR' and p.get('parentId')==cid and p['key']=='Device':p['value']=seed['props']['Device']
    if t=='ATTR' and p.get('parentId')==cid and p['key']=='Footprint':p['value']=props['Footprint']
    if t=='COMPONENT' and i==cid:
        for k,v in props.items():
            if k not in ['Symbol','Footprint','Unique ID','Designator','Channel ID','Reuse Block','Group ID','Multi-Part Group','Add into BOM','Convert to PCB']:p['attrs'][k]=v
        p['attrs']['Name']=props['Name']
        h['ticket']+=1000
pn={json.loads(i)[2]:p['padNet'] for (t,i),(_,p) in d['records'].items() if t=='PAD_NET' and json.loads(i)[1]==cid}
d['records']={k:v for k,v in d['records'].items() if not(k[0]=='PAD_NET' and json.loads(k[1])[1]==cid)}
cp=d['records'][('COMPONENT',cid)][1];r=math.radians(cp['angle']);shapes=[]
sys.path.insert(0,str(m.ROOT/'.tools/pcb-python'))
from shapely.geometry import Polygon,box,LineString
from shapely.affinity import rotate,translate
from shapely.ops import unary_union
for (t,i),(_,p) in m.LIB[props['Footprint']]['records'].items():
    if t!='PAD':continue
    key=json.dumps(['PAD_NET',cid,p['num'],i],separators=(',',':'))
    d['records'][('PAD_NET',key)]=({'type':'PAD_NET','id':key,'ticket':200000},{'partitionId':'','padNet':pn[p['num']],'padLen':None,'attrsMap':{}})
    a=p['defaultPad'];assert a['padType']=='RECT'
    g=box(-a['width']/2,-a['height']/2,a['width']/2,a['height']/2)
    g=translate(rotate(g,p['padAngle'],origin=(0,0)),p['centerX']+p.get('padOffsetX',0),p['centerY']+p.get('padOffsetY',0))
    shapes.append(translate(rotate(g,cp['angle'],origin=(0,0)),cp['x'],cp['y']))
changed_tracks={'0a1a937cdf60622b','4199b655269d4beb','ebaa5f1f7dec3723','b3295c68353b68be'}
d['records']={k:v for k,v in d['records'].items() if not(k[0]=='LINE' and k[1] in changed_tracks)}
new_tracks=[]
def trace(net,points,width=.2553):
    for a,b in zip(points,points[1:]):
        ident='q3-route-'+uuid.uuid4().hex[:12]
        p={'partitionId':'','groupId':0,'netName':net,'layerId':1,'startX':a[0]/.0254,'startY':a[1]/.0254,'endX':b[0]/.0254,'endY':b[1]/.0254,'width':width/.0254,'locked':False,'zIndex':-1}
        d['records'][('LINE',ident)]=({'type':'LINE','id':ident,'ticket':200000},p);new_tracks.append(p)
trace('VNEG12',[(27.9952,54.4428),(27.9952,54.15),(32.15,54.15),(32.15,56.9498),(31.7813,56.9498)])
trace('VNEG12',[(32.4467,53.9257),(32.15,54.15)])
trace('GND',[(29.74739,59.0),(29.0,59.0)],.254)
viaid='q3-ground-via'
d['records'][('VIA',viaid)]=({'type':'VIA','id':viaid,'ticket':200000},{'partitionId':'','groupId':0,'netName':'GND','ruleName':'','centerX':29/.0254,'centerY':59/.0254,'holeDiameter':12,'viaDiameter':24.02,'viaType':'NORMAL','topSolderExpansion':None,'bottomSolderExpansion':None,'locked':False,'unusedInnerLayers':[]})
shapes.extend(LineString([(p['startX'],p['startY']),(p['endX'],p['endY'])]).buffer(p['width']/2) for p in new_tracks if p['netName']!='GND')
guard=unary_union(shapes).buffer(.165/.0254,quad_segs=32)
modified_fills=[]
for (t,i),(h,p) in list(d['records'].items()):
    if t!='FILL' or p['layerId']!=1:continue
    def coords(c):
        assert c[2]=='L';v=c[:2]+c[3:];return list(zip(v[::2],v[1::2]))
    poly=Polygon(coords(p['path'][0]),[coords(c) for c in p['path'][1:]])
    if not poly.intersects(guard):continue
    result=poly.difference(guard)
    pieces=[result] if result.geom_type=='Polygon' else list(result.geoms)
    pieces=sorted(pieces,key=lambda g:g.area,reverse=True)
    assert all(g.geom_type=='Polygon' and g.is_valid for g in pieces)
    def path(ring):
        c=list(ring.coords);return [c[0][0],c[0][1],'L',*[v for pt in c[1:] for v in pt]]
    for number,result in enumerate(pieces):
        if number and result.area*.0254**2<1:continue
        pp=p if number==0 else copy.deepcopy(p)
        pp['path']=[path(result.exterior),*[path(c) for c in result.interiors]];pp['refs']=[None]*len(pp['path'])
        if number:
            ident='q3-clearance-'+uuid.uuid4().hex[:12];d['records'][('FILL',ident)]=({'type':'FILL','id':ident,'ticket':200000},pp);modified_fills.append(ident)
    h['ticket']+=1000;modified_fills.append(i)
for k,(h,p) in d['records'].items():
    if k[0] in ['LINE','VIA','POLY','REGION'] and k in original['records']:assert p==original['records'][k][1]
(m.OUT/'PCB_Q3_metadata-source.txt').write_text(m.io.source_of(d),encoding='utf8',newline='\n')
print(json.dumps({'Q3':cid,'manufacturerPart':'2N7002LT1G','supplierPart':'C16338','stockFootprint':props['Footprint'],'replacedVnegSegments':4,'newSegments':len(new_tracks),'addedGroundVias':1,'componentPositionsUnchanged':True,'topGroundFillLocallyClipped':modified_fills}))
