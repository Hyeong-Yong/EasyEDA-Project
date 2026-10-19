"""Presentation-only consolidation. The protected R102 wire is never merged."""
import copy,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('m',root/'scripts/readability-model.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
sys.path.insert(0,str(root/'.tools/pcb-python'))
from shapely.geometry import LineString,Point
from shapely.ops import unary_union
capture=json.loads((out/'native-validation.json').read_text(encoding='utf8'))
proof=[]
for pg in capture['pages']:
 doc=next(iter(m.io.documents(pg['source']).values()));aa=m.io.attrs(doc)
 old_records=copy.deepcopy(doc['records']);clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100
 def replace(key,p):
  global clock
  clock+=1;h=copy.deepcopy(doc['records'][key][0]);h['ticket']=clock;doc['records'][key]=(h,p)
 wirelines=defaultdict(list)
 for (t,i),(_,p) in doc['records'].items():
  if t=='LINE' and ('WIRE',p.get('lineGroup')) in doc['records']:
   wirelines[p['lineGroup']].append(((p['startX'],p['startY']),(p['endX'],p['endY'])))
 # Merge only physically touching groups with an identical declared net.
 groups=defaultdict(list)
 for wid,lines in wirelines.items():
  net=aa.get(wid,{}).get('NET')
  if net and wid!='2499435c58e74be8':groups[net].append(wid)
 discarded=set();merged=0
 for net,ids in groups.items():
  geoms={wid:unary_union([LineString(seg) for seg in wirelines[wid]]) for wid in ids};parent={wid:wid for wid in ids}
  def r(w):
   while parent[w]!=w:w=parent[w]
   return w
  for i,a in enumerate(ids):
   for b in ids[i+1:]:
    if geoms[a].distance(geoms[b])<1e-5:parent[r(b)]=r(a)
  components=defaultdict(list)
  for wid in ids:components[r(wid)].append(wid)
  for keep,members in components.items():
   if len(members)>1:
    discard=set(members)-{keep};discarded|=discard;merged+=len(discard)
    for key,(_,p) in list(doc['records'].items()):
     if key[0]=='LINE' and p.get('lineGroup') in discard:q=copy.deepcopy(p);q['lineGroup']=keep;replace(key,q)
   segments=[seg for wid in members for seg in wirelines[wid]]
   horizontal=sorted((seg for seg in segments if abs(seg[0][1]-seg[1][1])<1e-5),key=lambda seg:abs(seg[1][0]-seg[0][0]),reverse=True)
   keepattrs=[(k,h,p) for k,(h,p) in doc['records'].items() if k[0]=='ATTR' and p.get('parentId')==keep and p.get('key')=='NET']
   if keepattrs:
    latest=max(keepattrs,key=lambda t:t[1].get('ticket',0))[0]
    for key,h,p in keepattrs:
     if key!=latest:discarded.add(key[1]);continue
     q=copy.deepcopy(p);q['rotation']=0
     # Flags / ports already identify the same conductor. Hidden alias is
     # retained as data; physical continuity lives in the single WIRE parent.
     attached=False
     conductor=unary_union([LineString(seg) for seg in segments])
     for (t,i),(_,cp) in doc['records'].items():
      pr=aa.get(i,{})
      if t!='COMPONENT' or pr.get('Designator') or not pr.get('Symbol'):continue
      label=pr.get('Global Net Name') or (pr.get('Name') if pr['Symbol'] in ('ba868eccc9511b9e','a81d11d7d2be7e62') else None)
      if label!=net:continue
      if any(conductor.distance(Point(pt))<1e-5 for pt in m.pins(cp,pr).values()):attached=True;break
     q['valueVisible']=not attached
     if horizontal:
      seg=horizontal[0];q.update(x=min(seg[0][0],seg[1][0])+8,y=seg[0][1]-8,align='LEFT_BOTTOM',fontSize=6)
     replace(key,q)
 doc['records']={k:v for k,v in doc['records'].items() if k[1] not in discarded and v[1].get('parentId') not in discarded}
 if pg['page']=='e58bcc16379b10f4':
  for key,(_,p) in list(doc['records'].items()):
   if key[0]=='TEXT' and p.get('value','').startswith('TPS7A4901 /'):q=copy.deepcopy(p);q.update(x=1120,y=-2485,fontSize=7,value='TPS7A4901: C14 provides NR / soft start');replace(key,q)
  # Correct pre-existing passive text overlaps, without moving any part.
  for ref,c in m.components(doc).items():
   p=c['item']
   if not ref.startswith(('R','C')) or p.get('y',0)>-1500:continue
   for key,(_,at) in list(doc['records'].items()):
    if key[0]!='ATTR' or at.get('parentId')!=c['id'] or not at.get('valueVisible') or at.get('key') not in ('Designator','Name','Value'):continue
    q=copy.deepcopy(at);isref=q['key']=='Designator'
    if p['rotation'] in (90,270):q.update(x=p['x']+14,y=p['y']+(-6 if isref else 8),align='LEFT_BOTTOM')
    else:q.update(x=p['x'],y=p['y']+(-18 if isref else -8),align='CENTER_BOTTOM')
    q.update(rotation=0,fontSize=7);replace(key,q)
  aa_now=m.io.attrs(doc)
  # Keep the FB name below its own conductor, not on the OUT conductor.
  for key,(_,p) in list(doc['records'].items()):
   q=copy.deepcopy(p)
   if key[0]=='ATTR' and p.get('key')=='NET' and p.get('value')=='DAC_AVDD_FB':q.update(x=1210,y=-2610);replace(key,q)
   if key[0]=='LINE' and p.get('lineGroup')=='a8c65417df1d4f80':
    for field in ('startY','endY'):
     if q.get(field)==-2720:q[field]=-2710
    if q!=p:replace(key,q)
   if key[0]=='COMPONENT' and p.get('x')==1480 and p.get('y')==-2720 and aa_now.get(key[1],{}).get('Name')=='VDD5':
    q['y']=-2710;replace(key,q)
    for ak,(_,ap) in list(doc['records'].items()):
     if ak[0]=='ATTR' and ap.get('parentId')==key[1] and isinstance(ap.get('y'),(float,int)):
      aq=copy.deepcopy(ap);aq['y']+=10;replace(ak,aq)
 # Protected branch and R102 part/attributes are byte-equivalent payloads.
 if pg['page']=='e3a1c5f417017755':
  for key,(_,p) in old_records.items():
   if key==('WIRE','2499435c58e74be8') or p.get('lineGroup')=='2499435c58e74be8' or p.get('parentId')=='2499435c58e74be8':assert doc['records'][key][1]==p
 target=out/('DAC8562.tidied-source.txt' if pg['page']=='e58bcc16379b10f4' else 'DAC_MCU.tidied-source.txt')
 target.write_text(m.io.source_of(doc),encoding='utf8');proof.append({'page':pg['page'],'mergedConnectedWireParents':merged,'protectedR102Unchanged':True})
(out/'label-tidy-plan.json').write_text(json.dumps(proof,indent=2),encoding='utf8');print(json.dumps(proof))
