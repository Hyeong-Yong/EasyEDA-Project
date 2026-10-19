"""Import local SES routing, add verified ground copper/thermal vias and readable labels."""
import copy,hashlib,importlib.util,itertools,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/pcb-two-zone'
sys.path.insert(0,str(ROOT/'.tools/pcb-python'))
from shapely.geometry import Point,LineString,Polygon,box
from shapely.affinity import rotate,translate
from shapely.ops import unary_union
for name,file in [('m','pcb-physical-model.py'),('s','prepare-two-zone-routing.py')]:
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);globals()[name]=module
native=json.loads((OUT/'native-placement.json').read_text(encoding='utf8'))
doc=next(iter(m.io.documents(native['source']).values()));placements=json.loads((OUT/'placement.json').read_text(encoding='utf8'))
expected=json.loads((OUT/'expected-pads.json').read_text(encoding='utf8'))
for (typ,pid),(_,payload) in doc['records'].items():
    if typ!='COMPONENT':continue
    name=next((p['value'] for (t,_),(_,p) in doc['records'].items() if t=='ATTR' and p.get('parentId')==pid and p.get('key')=='Designator'),None)
    if not name:continue
    sch=m.PARTS[name]['attributes']
    for key in ['Name','Multi-Part Group']:
        if sch.get(key) is not None:payload['attrs'][key]=sch[key]
seq=0
def id_for(label):return hashlib.sha256(('two-zone-final:'+label).encode()).hexdigest()[:16]
def add(typ,payload,label):
    global seq
    seq+=1;pid=id_for(label);doc['records'][(typ,pid)]=({'type':typ,'id':pid,'ticket':1},payload);return pid
ses=s.parse_sexp((OUT/'two-zone-route.ses').read_text(encoding='utf8'))
routes=next(n for n in ses if isinstance(n,list) and n[0]=='routes')
res=next(n for n in routes if isinstance(n,list) and n[0]=='resolution')
factor={'mil':1,'um':1/25.4,'mm':1/.0254,'inch':1000}[res[1]]/float(res[2])
layerids={'TopLayer':1,'BottomLayer':2}
network=next(n for n in routes if isinstance(n,list) and n[0]=='network_out')
all_nets={p['net'] for p in expected if p['net']}
tracks=[];vias=[]
for net in network:
    if not isinstance(net,list) or net[0]!='net':continue
    netname=net[1].strip("'\"")
    if netname not in all_nets:raise ValueError('Unknown routed net '+netname)
    for item in net[2:]:
        if not isinstance(item,list):continue
        if item[0]=='wire':
            path=next(n for n in item if isinstance(n,list) and n[0]=='path')
            layer=layerids[path[1]];width=float(path[2])*factor;coords=[float(v)*factor for v in path[3:]]
            for j in range(0,len(coords)-2,2):
                x1,y1,x2,y2=coords[j:j+4]
                if math.hypot(x2-x1,y2-y1)<1e-5:continue
                p={'partitionId':'','groupId':0,'netName':netname,'layerId':layer,'startX':x1,'startY':y1,'endX':x2,'endY':y2,'width':width,'locked':False,'zIndex':-1}
                add('LINE',p,'route-'+str(len(tracks)));tracks.append(p)
        elif item[0]=='via':
            p={'partitionId':'','groupId':0,'netName':netname,'ruleName':'','centerX':float(item[2])*factor,'centerY':float(item[3])*factor,'holeDiameter':12,'viaDiameter':24.02,'viaType':'NORMAL','topSolderExpansion':None,'bottomSolderExpansion':None,'locked':False,'unusedInnerLayers':[]}
            add('VIA',p,'via-'+str(len(vias)));vias.append(p)
def pad_shape(p):
    a=p['defaultPad'];w,h=a['width'],a['height']
    if a['padType']=='ELLIPSE':
        from shapely.affinity import scale
        shape=scale(Point(0,0).buffer(1,quad_segs=24),w/2,h/2)
    elif a['padType']=='RECT':shape=box(-w/2,-h/2,w/2,h/2)
    elif a['padType']=='OVAL' or a['padType']=='ROUND':
        shape=box(-max(0,w-h)/2,-max(0,h-w)/2,max(0,w-h)/2,max(0,h-w)/2).buffer(min(w,h)/2,quad_segs=24)
    else:raise ValueError('Unhandled pad shape '+a['padType'])
    shape=translate(shape,p.get('padOffsetX',0),p.get('padOffsetY',0))
    return translate(rotate(shape,p['padAngle'],origin=(0,0)),p['centerX'],p['centerY'])
pads=[(p,pad_shape(p)) for p in expected]
clearance=.165/.0254
def foreign_shapes(layer,net):
    shapes=[g for p,g in pads if p['layerId'] in [layer,12] and p['net']!=net]
    shapes.extend(LineString([(p['startX'],p['startY']),(p['endX'],p['endY'])]).buffer(p['width']/2,quad_segs=12) for p in tracks if p['layerId']==layer and p['netName']!=net)
    shapes.extend(Point(p['centerX'],p['centerY']).buffer(p['viaDiameter']/2,quad_segs=16) for p in vias if p['netName']!=net)
    return unary_union(shapes)
foreign_ground={l:foreign_shapes(l,'GND') for l in [1,2]}
thermal=[]
for name,minimum in [('U1',4),('U2',3)]:
    ep=next(p for p in expected if p['designator']==name and p['num']==('25' if name=='U1' else '9'))
    candidates=[(dx,dy) for dx,dy in itertools.product([-.65,0,.65],repeat=2)] if name=='U1' else [(dx,dy) for dx,dy in itertools.product([-.42,.42],[-.32,.32])]
    picked=[]
    for dx,dy in candidates:
        x,y=ep['centerX']+dx/.0254,ep['centerY']+dy/.0254
        cu=Point(x,y).buffer(12.01)
        if any(cu.distance(foreign_ground[l])<clearance for l in [1,2]):continue
        if any(math.hypot(x-p['centerX'],y-p['centerY'])<24.2 for p in vias):continue
        if any(math.hypot(x-p['centerX'],y-p['centerY'])<24.2 for p in picked):continue
        p={'partitionId':'','groupId':0,'netName':'GND','ruleName':'','centerX':x,'centerY':y,'holeDiameter':12,'viaDiameter':24.02,'viaType':'NORMAL','topSolderExpansion':None,'bottomSolderExpansion':None,'locked':False,'unusedInnerLayers':[]}
        add('VIA',p,'thermal-'+name+'-'+str(len(picked)));picked.append(p)
        if len(picked)>=minimum:break
    vias.extend(picked);thermal.append({'part':name,'requested':minimum,'added':len(picked),'locationsMm':[[p['centerX']*.0254,p['centerY']*.0254] for p in picked]})
def contour(coords):
    c=list(coords);return [c[0][0]/10,c[0][1]/10,'L',*[v/10 for pt in c[1:] for v in pt]]
pour_stats=[]
for layer in [1,2]:
    copper=box(.5/.0254,.5/.0254,99.5/.0254,99.5/.0254).difference(foreign_ground[layer].buffer(clearance,quad_segs=16))
    for hx,hy in [(5,5),(95,5),(5,95),(95,95)]:copper=copper.difference(Point(hx/.0254,hy/.0254).buffer(3.51/.0254,quad_segs=32))
    gndpads=[(p,g) for p,g in pads if p['net']=='GND' and p['layerId'] in [layer,12]]
    for p,g in gndpads:
        if p['layerId']!=12:continue
        gap=.254/.0254;spoke=.30/.0254
        copper=copper.difference(g.buffer(gap).difference(g))
        b=g.bounds;cx,cy=p['centerX'],p['centerY']
        cross=unary_union([box(b[0]-gap,cy-spoke/2,b[2]+gap,cy+spoke/2),box(cx-spoke/2,b[1]-gap,cx+spoke/2,b[3]+gap)])
        copper=copper.union(cross.intersection(box(.5/.0254,.5/.0254,99.5/.0254,99.5/.0254)).difference(foreign_ground[layer].buffer(clearance)))
    connectors=unary_union([g for p,g in gndpads]+[Point(p['centerX'],p['centerY']).buffer(p['viaDiameter']/2) for p in vias if p['netName']=='GND'])
    polygons=[g.simplify(.06,preserve_topology=True) for g in (list(copper.geoms) if hasattr(copper,'geoms') else [copper]) if isinstance(g,Polygon) and g.area>.2/.0254**2 and g.intersects(connectors)]
    border_id=add('POUR',{'partitionId':'','groupId':0,'netName':'GND','layerId':layer,'width':.2,'name':'GND_TOP' if layer==1 else 'GND_BOTTOM','order':1,'path':[[.5/.0254,.5/.0254,'L',.5/.0254,99.5/.0254,99.5/.0254,99.5/.0254,99.5/.0254,.5/.0254,.5/.0254,.5/.0254]],'pourType':{'pourType':'SOLID','fineness':8},'keepIsland':False,'locked':False,'zIndex':-1},'gnd-border-'+str(layer))
    pid=json.dumps(['POURED',border_id],separators=(',',':'))
    fill=[{'id':id_for('pour-fill-'+str(layer)+'-'+str(i)),'strokeWidth':0,'fill':True,'path':[contour(poly.exterior.coords),*[contour(r.coords) for r in poly.interiors]]} for i,poly in enumerate(polygons)]
    doc['records'][('POURED',pid)]=({'type':'POURED','id':pid,'ticket':1},{'pourFill':fill})
    for i,poly in enumerate(polygons):
        path=[[v*10 if isinstance(v,(int,float)) else v for v in c] for c in [contour(poly.exterior.coords),*[contour(r.coords) for r in poly.interiors]]]
        add('FILL',{'partitionId':'','groupId':0,'netName':'GND','layerId':layer,'width':.2,'fillStyle':'SOLID','path':path,'locked':False,'zIndex':-1,'isBridgingCopper':False,'networkList':[],'refs':[None]*len(path)},'ground-solid-'+str(layer)+'-'+str(i))
    pour_stats.append({'layer':layer,'areaMm2':sum(p.area for p in polygons)*.0254**2,'islands':len(polygons)})
summary={'tracks':len(tracks),'vias':len(vias),'routeVias':len(vias)-sum(t['added'] for t in thermal),'thermalVias':thermal,'groundPours':pour_stats,'sesResolution':res,'sesToMil':factor,'routedNets':len({p['netName'] for p in tracks}|{p['netName'] for p in vias})}
(OUT/'routed-source.txt').write_text(m.io.source_of(doc),encoding='utf8',newline='\n')
(OUT/'routing-import-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
print(json.dumps(summary,indent=2))
