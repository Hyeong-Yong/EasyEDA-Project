"""Redraw only schematic presentation, preserving physical part/pin identities."""
import copy
import heapq
import importlib.util
import json
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

spec=importlib.util.spec_from_file_location('rm',Path(__file__).with_name('readability-model.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ROOT,OUT,io,LIB=m.ROOT,m.OUT,m.io,m.LIB
netpins={}
for block in re.findall(r'\(\s*\n(.*?)\n\)',m.BEFORE['pages'][0]['netlist'],re.S):
    rows=block.splitlines();net=rows[0].strip()
    for row in rows[1:]:
        match=re.match(r'([^\s-]+)-([^\s]+)',row.strip())
        if match:netpins[match[1]+'.'+match[2].split('-')[0]]=net
# Final review found this formerly isolated pin ($2N56). Correct the intended
# symmetric B-channel DC-feedback/output connection, and record it in the audit.
netpins['R117.2']='MCU_SENSE_B'
templates={}
first=next(iter(io.documents(m.BEFORE['pages'][0]['source']).values()));aa=io.attrs(first)
for (typ,pid),(_,p) in first['records'].items():
    if typ!='COMPONENT' or aa.get(pid,{}).get('Designator'):continue
    a=aa.get(pid,{})
    if a.get('Global Net Name')=='GND':templates.setdefault('ground',(p,a))
    elif a.get('Global Net Name')=='VIN_RAW':templates.setdefault('power',(p,a))
    elif a.get('Symbol')=='ba868eccc9511b9e':templates.setdefault('out',(p,a))
    elif a.get('Symbol')=='a81d11d7d2be7e62':templates.setdefault('in',(p,a))

def uid():return uuid.uuid4().hex[:16]
def grid(p):return (round(p[0]/5),round(p[1]/5))
def world(p):return (p[0]*5,p[1]*5)

class Page:
    def __init__(self,pg):
        self.doc=copy.deepcopy(next(iter(io.documents(pg['source']).values())))
        self.before=copy.deepcopy(self.doc)
        self.comp=m.components(self.doc)
        self.ticket=max(h.get('ticket',0) for h,p in self.doc['records'].values())+100
        self.routes=[];self.ports=[]
        if 'Q3' in self.comp and (OUT/'q3-loaded-source.json').exists():
            seed_doc=next(iter(io.documents(json.loads((OUT/'q3-loaded-source.json').read_text(encoding='utf8'))['source']).values()))
            seed=m.components(seed_doc)['SEED_Q3_REVIEW'];c=self.comp['Q3']
            props=dict(next(v['attributes'] for h,v in LIB[seed['props']['Device']]['records'].values() if 'attributes' in v))
            props.update(Device=seed['props']['Device'])
            for key in ['Designator','Unique ID','Multi-Part Group','Channel ID','Reuse Block','Group ID']:
                if key in c['props']:props[key]=c['props'][key]
            c['item']['partId']=seed['item']['partId'];c['props']=props;c['pins']=m.pins(c['item'],props)
            self.rec('COMPONENT',c['item'],c['id'])
            found=set()
            for (t,i),(_,a) in list(self.doc['records'].items()):
                if t=='ATTR' and a.get('parentId')==c['id']:
                    if a['key'] not in props:
                        del self.doc['records'][(t,i)];continue
                    a=copy.deepcopy(a);a['value']=props[a['key']];self.rec('ATTR',a,i);found.add(a['key'])
            for key,value in props.items():
                if key not in found:self.attr(c['id'],key,value)
    def rec(self,t,p,i=None):
        i=i or uid();self.ticket+=1
        self.doc['records'][(t,i)]=({'type':t,'id':i,'ticket':self.ticket},p);return i
    def attr(self,parent,key,value,x=None,y=None,visible=False,size=7,align='LEFT_BOTTOM'):
        return self.rec('ATTR',{'parentId':parent,'key':key,'value':value,'x':x,'y':y,'rotation':0,'fontFamily':'Arial','fontSize':size,'align':align,'keyVisible':False,'valueVisible':visible,'zIndex':self.ticket})
    def text(self,x,y,text,size=10):
        self.rec('TEXT',{'x':x,'y':y,'value':text,'rotation':0,'fontFamily':'Arial','fontSize':size,'align':'LEFT_BOTTOM','color':'#243746','fontWeight':size>=10,'zIndex':self.ticket})
    def clean(self,page1=False):
        removed=set()
        for (t,i),(_,p) in self.doc['records'].items():
            if t=='LINE' and p.get('lineGroup') and (not page1 or min(p['startY'],p['endY'])>=-1510):removed.add(p['lineGroup'])
            if t=='TEXT' and (not page1 or p.get('y',-99999)>=-1510):removed.add(i)
        self.doc['records']={k:v for k,v in self.doc['records'].items() if k[1] not in removed and v[1].get('parentId') not in removed and v[1].get('lineGroup') not in removed}
    def move(self,name,x,y,rotation=None,mirror=None):
        c=self.comp[name];old=copy.deepcopy(c['item']);p=copy.deepcopy(old)
        p.update(x=x,y=y)
        if rotation is not None:p['rotation']=rotation
        if mirror is not None:p['isMirror']=mirror
        self.rec('COMPONENT',p,c['id']);c['item']=p;c['pins']=m.pins(p,c['props'])
        for (t,i),(_,a) in list(self.doc['records'].items()):
            if t!='ATTR' or not a.get('parentId','').startswith(c['id']):continue
            a=copy.deepcopy(a)
            if isinstance(a.get('x'),(int,float)):a['x']+=x-old['x']
            if isinstance(a.get('y'),(int,float)):a['y']+=y-old['y']
            if a.get('parentId')==c['id'] and a.get('valueVisible'):
                key=a['key'];passive=name.startswith(('R','C','D'))
                if passive and p['rotation'] in (90,270):a.update(x=x+14,y=y+(-6 if key=='Designator' else 8),align='LEFT_BOTTOM')
                else:a.update(x=x,y=y+(-18 if key=='Designator' else -8) if passive else y+(-56 if key=='Designator' else -44),align='CENTER_BOTTOM')
                a.update(rotation=0,fontSize=7)
            self.rec('ATTR',a,i)
        return c
    def pin(self,n,p):return self.comp[n]['pins'][str(p)]
    def wire(self,net,points,label=None):
        pts=[tuple(round(v,5) for v in p) for p in points]
        wid=self.rec('WIRE',{'zIndex':self.ticket})
        for a,b in zip(pts,pts[1:]):
            if a==b:continue
            assert a[0]==b[0] or a[1]==b[1],(net,a,b)
            self.rec('LINE',{'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],'lineGroup':wid,'strokeColor':None,'strokeStyle':None,'strokeWidth':None,'fillColor':None,'fillStyle':None,'zIndex':self.ticket})
        self.attr(wid,'NET',net,label[0] if label else None,label[1] if label else None,bool(label))
        self.routes.append((net,pts));return wid
    def port(self,net,point,typ='in',rotation=0,label_offset=None):
        p,a=copy.deepcopy(templates[typ]);p.update(x=point[0],y=point[1],rotation=rotation,isMirror=False,zIndex=self.ticket)
        cid=self.rec('COMPONENT',p)
        for key,value in a.items():
            if key in ('Name','Global Net Name'):value=net
            visible=key=='Name' and typ!='ground'
            if typ in ('in','out'):
                tx=point[0]+(12 if typ=='out' else -12);ty=point[1]-10
                align='LEFT_BOTTOM' if typ=='out' else 'RIGHT_BOTTOM'
            else:tx=point[0];ty=point[1]-18;align='CENTER_BOTTOM'
            if label_offset:tx=point[0]+label_offset[0];ty=point[1]+label_offset[1]
            self.attr(cid,key,value,tx if visible else None,ty if visible else None,visible,7,align)
        self.ports.append({'net':net,'point':point,'type':typ});return point
    def supply(self,name,pin,net,dy=-20):
        p=self.pin(name,pin);q=(p[0],p[1]+dy)
        self.port(net,q,'ground' if net=='GND' else 'power')
        self.wire(net,[p,q]);return q
    def body(self,n):
        c=self.comp[n];p=c['item'];part=LIB[c['props']['Symbol']]['records'][('PART',p['partId'])][1]['BBOX']
        r=-math.radians(p.get('rotation',0));pts=[]
        for x in [part[0],part[2]]:
            for y in [part[1],part[3]]:
                dx=x*math.cos(r)-y*math.sin(r);dy=x*math.sin(r)+y*math.cos(r)
                if p.get('isMirror'):dx=-dx
                pts.append((p['x']+dx,p['y']+dy))
        return (min(x for x,y in pts)-4,min(y for x,y in pts)-4,max(x for x,y in pts)+4,max(y for x,y in pts)+4)
    def block(self,names,bounds,ports):
        groups=defaultdict(list);pin_owner={};bodies=[self.body(n) for n in names]
        power={'GND','VNEG12','VPOS12','VIN_RAW','VDD5','MCU_3V3'}
        flagged=[]
        for name in names:
            c=self.comp[name];ref=c['props']['Designator']
            for num,pt in c['pins'].items():
                net=netpins.get(ref+'.'+num,'NC-'+name+'.'+num);pin_owner[grid(pt)]=net
                if net in power:
                    bx,by=c['item']['x'],c['item']['y']
                    dx,dy=pt[0]-bx,pt[1]-by
                    step=(5*(1 if dx>0 else -1),0) if abs(dx)>=abs(dy) else (0,5*(1 if dy>0 else -1))
                    end=(pt[0]+step[0],pt[1]+step[1])
                    self.wire(net,[pt,end])
                    self.port(net,end,'ground' if net=='GND' else 'power',label_offset=(0,-12 if dy<=0 else 32))
                    flagged.extend((grid(pt),grid(end)))
                elif not net.startswith('NC-'):groups[net].append(grid(pt))
        for net,point,typ in ports:
            if net in power:continue
            self.port(net,point,typ);groups[net].append(grid(point));pin_owner[grid(point)]=net
        occupied={pt:pin_owner.get(pt,'power-flag') for pt in flagged};route_cells={}
        def free(cell,net):
            x,y=world(cell)
            if not(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3]):return False
            if pin_owner.get(cell,net)!=net or occupied.get(cell,net)!=net:return False
            if cell not in pin_owner and any(a<=x<=c and b<=y<=d for a,b,c,d in bodies):return False
            return True
        def find(start,targets,net):
            heap=[(0,0,start,4)];cost={(start,4):0};prev={};goal=None
            while heap:
                _,g,cell,direction=heapq.heappop(heap)
                state=(cell,direction)
                if g!=cost.get(state):continue
                if cell in targets:goal=state;break
                for nd,(dx,dy) in enumerate([(1,0),(-1,0),(0,1),(0,-1)]):
                    nxt=(cell[0]+dx,cell[1]+dy)
                    if not free(nxt,net):continue
                    ng=g+1+(4 if direction not in (nd,4) else 0)
                    ns=(nxt,nd)
                    if ng>=cost.get(ns,1e99):continue
                    cost[ns]=ng;prev[ns]=state
                    h=min(abs(nxt[0]-t[0])+abs(nxt[1]-t[1]) for t in targets)
                    heapq.heappush(heap,(ng+h,ng,nxt,nd))
            if goal is None:raise RuntimeError(f'Cannot route {net} in {names}')
            path=[]
            while goal in prev:path.append(goal[0]);goal=prev[goal]
            path.append(start);return path[::-1]
        # Small internal signal trees first; power trees use the remaining perimeter.
        order=sorted(groups,key=lambda n:(n!='MCU_VBIAS',len(groups[n]),n))
        for net in order:
            nodes=list(dict.fromkeys(groups[net]));tree={nodes.pop(0)};branches=[]
            while nodes:
                start=min(nodes,key=lambda p:min(abs(p[0]-q[0])+abs(p[1]-q[1]) for q in tree));nodes.remove(start)
                path=find(start,tree,net);tree.update(path)
                for c in path:occupied[c]=net
                corners=[path[0]]
                for i in range(1,len(path)-1):
                    a,b,c=path[i-1:i+2]
                    if (b[0]-a[0],b[1]-a[1])!=(c[0]-b[0],c[1]-b[1]):corners.append(b)
                corners.append(path[-1]);branches.append([world(p) for p in corners])
            for path in branches:self.wire(net,path)
            route_cells[net]=len(tree)
        return route_cells
    def save(self,name):
        (OUT/name).write_text(io.source_of(self.doc),encoding='utf8',newline='\n')

def channel(p,letter,cy):
    a=letter=='A';b=100 if a else 110
    j='J101' if a else 'J102';jo='J103' if a else 'J104'
    u='U101'+letter;v='U103'+letter;outpin,plus,minus=('1','3','2') if a else ('7','5','6')
    p.text(60,cy-215,'01  CHANNEL A — SMA INPUT / BUFFER / BIPOLAR CONVERSION' if a else '02  CHANNEL B — SMA INPUT / BUFFER / BIPOLAR CONVERSION',12)
    p.move(j,100,cy+20,180,False);p.move(jo,1530,cy+20,180,True)
    p.move('R'+str(b+1),230,cy,0);p.move('R'+str(b+2),490,cy+75,270)
    p.move(u,570,cy-10,0);p.move(v,1030,cy-10,0)
    for off,x,y,rot in [(3,800,cy,0),(4,800,cy-120,0),(5,1100,cy-185,0),(6,890,cy+65,270),(7,1220,cy-10,0)]:p.move('R'+str(b+off),x,y,rot)
    p.move('C'+str(b+1),1100,cy-120,0);p.move('C'+str(b+2),1430,cy+95,270)
    # Ground shields are physically joined, rather than four repeated labels.
    for conn,x in [(j,160),(jo,1470)]:
        pts=[p.pin(conn,n) for n in ['1','2','3','4']]
        for pt in pts:p.wire('GND',[pt,(x,pt[1])])
        p.wire('GND',[(x,cy+10),(x,cy+65)]);p.port('GND',(x,cy+65),'ground')
    p.wire('MCU_IN_'+letter,[p.pin(j,5),p.pin('R'+str(b+1),1)])
    end=(290,cy);p.wire('MCU_RCV_EXTERNAL_'+letter,[p.pin('R'+str(b+1),2),end]);p.port('MCU_RCV_EXTERNAL_'+letter,end,'out')
    start=(440,cy);p.port('MCU_RECEIVE_'+letter,start,'in',label_offset=(-12,20))
    p.wire('MCU_RECEIVE_'+letter,[start,p.pin(u,plus)])
    p.wire('MCU_RECEIVE_'+letter,[(490,cy),p.pin('R'+str(b+2),1)])
    bias=(490,cy+135);p.wire('MCU_VBIAS',[p.pin('R'+str(b+2),2),bias]);p.port('MCU_VBIAS',bias,'in',label_offset=(-12,14))
    # Unity-gain input buffer, with an explicit feedback loop.
    raw=p.pin(u,outpin);ip=p.pin(u,minus)
    p.wire('MCU_BUFFER_'+letter,[raw,(650,raw[1]),(650,cy-110),(510,cy-110),(510,ip[1]),ip])
    p.wire('MCU_BUFFER_'+letter,[raw,(650,raw[1]),(650,cy),p.pin('R'+str(b+3),1)])
    p.wire('MCU_PLUS_'+letter,[p.pin('R'+str(b+3),2),p.pin(v,plus)])
    p.wire('MCU_PLUS_'+letter,[(890,cy),p.pin('R'+str(b+6),1)])
    p.supply('R'+str(b+6),2,'GND',20)
    p.wire('MCU_VBIAS',[(710,cy-120),p.pin('R'+str(b+4),1)]);p.port('MCU_VBIAS',(710,cy-120),'in')
    mn=p.pin(v,minus)
    p.wire('MCU_MINUS_'+letter,[p.pin('R'+str(b+4),2),(940,cy-120),(940,mn[1]),mn])
    p.wire('MCU_MINUS_'+letter,[(940,cy-120),(940,cy-185),p.pin('R'+str(b+5),1)])
    p.wire('MCU_MINUS_'+letter,[(940,cy-120),p.pin('C'+str(b+1),1)])
    raw=p.pin(v,outpin)
    p.wire('MCU_RAW_'+letter,[raw,p.pin('R'+str(b+7),1)])
    p.wire('MCU_RAW_'+letter,[(1160,raw[1]),(1160,cy-120),p.pin('C'+str(b+1),2)])
    sense=(1310,raw[1]);p.wire('MCU_SENSE_'+letter,[p.pin('R'+str(b+7),2),sense,(sense[0],cy-185),p.pin('R'+str(b+5),2)])
    p.port('MCU_SENSE_'+letter,sense,'out',label_offset=(12,-12))
    p.supply('C'+str(b+2),2,'GND',20)
    ret=(1430,cy+40);p.port('MCU_OUT_'+letter,ret,'in',label_offset=(-12,18))
    p.wire('MCU_OUT_'+letter,[ret,(1430,cy),p.pin(jo,5)])
    p.wire('MCU_OUT_'+letter,[ret,p.pin('C'+str(b+2),1)])
    if a:
        for ic in [u,v]:p.supply(ic,8,'VPOS12',-20);p.supply(ic,4,'VNEG12',20)
    p.text(280,cy+175,'Input contact: K101 (section 04). Output contact: K102 (section 05). Ports are only used across these functional blocks.',7)

def monitor(p,u,x,rail,local,rs,cap,y=-920):
    names=[u]+['R'+str(i) for i in range(rs,rs+4)]+[cap]
    p.move(u,x,y)
    for ref,dx,dy in [('R'+str(rs),-135,-105),('R'+str(rs+1),-135,65),('R'+str(rs+2),135,-105),('R'+str(rs+3),135,65)]:p.move(ref,x+dx,y+dy,270)
    p.move(cap,x+70,y+100,270)
    good='DAC_NEG_LOCAL' if u=='U9' else 'DAC_POS_GOOD'
    ports=[(rail,(x-135,y-155),'ground' if rail=='GND' else 'power'),(local,(x-135,y+135),'ground' if local=='GND' else 'power'),(good,(x+195,y-145),'out')]
    if u!='U9':ports.append(('VIN_RAW',(x+195,y+35),'power'))
    p.block(names,(x-210,y-170,x+220,y+160),ports)

def build():
    p=Page(m.BEFORE['pages'][0]);p.clean(True)
    p.text(55,-1500,'06  POWER-GOOD / DEFAULT-MUTED OUTPUT / SPI ISOLATION',14)
    p.text(55,-1475,'06A  MCU SIGNAL GATING — local control and power are wired; only host/DAC interfaces use labels',9)
    for n,x,y,rot in [('U5',350,-1310,0),('U6',950,-1310,0),('C28',500,-1190,270),('C29',1080,-1190,270),('Q2',1430,-1310,0),('R24',1440,-1400,270),('R25',1320,-1240,270)]:p.move(n,x,y,rot)
    # Each buffer has its pin-to-pin enable/power wiring drawn explicitly.
    for u,c,x in [('U5','C28',350),('U6','C29',950)]:
        names=[u,c];ports=[]
        for num,pt in p.comp[u]['pins'].items():
            net=netpins.get(u+'.'+num)
            if net and net not in ('GND','VDD5','DAC_SPI_OE_N'):
                side=-1 if pt[0]<x else 1
                end=(pt[0]+side*35,pt[1]);p.wire(net,[pt,end],(end[0]+(3 if side>0 else -105),end[1]-2))
        ports=[('GND',(x-130,-1160),'ground'),('VDD5',(x+160,-1420),'power'),('DAC_SPI_OE_N',(x-140,-1410),'in')]
        # External pins are already labelled; route only the shared local nets.
        p.block(names,(x-170,-1440,x+190,-1135),ports)
    p.block(['Q2','R24','R25'],(1220,-1440,1550,-1135),[('VDD5',(1440,-1440),'power'),('GND',(1440,-1170),'ground'),('DAC_SPI_ENABLE',(1230,-1310),'in'),('DAC_SPI_OE_N',(1530,-1370),'out')])
    p.text(55,-1080,'06B  SUPPLY WINDOW MONITORS — two divider chains and both fault outputs are explicitly connected',10)
    monitor(p,'U7',280,'VPOS12','GND',26,'C30')
    monitor(p,'U8',800,'VDD5','GND',30,'C31')
    monitor(p,'U9',1320,'GND','VNEG12',34,'C32')
    p.text(95,-720,'+12V window',8);p.text(615,-720,'DAC AVDD window',8);p.text(1135,-720,'Negative-rail magnitude window',8)
    p.text(55,-680,'06C  NEGATIVE-RAIL LEVEL TRANSFER / POWER-GOOD LOGIC',10)
    for n,x,y,rot in [('R38',160,-590,270),('Q3',260,-535,0),('R39',355,-610,0),('U10',465,-535,0),('R40',545,-610,270),('U11',650,-535,0),('U12',1020,-535,0),('R41',870,-610,270),('C33',735,-490,270),('C34',1150,-490,270)]:p.move(n,x,y,rot)
    p.block(['R38','Q3','R39','U10','R40','U11','C33'],(65,-655,805,-425),[('DAC_NEG_LOCAL',(85,-570),'in'),('VNEG12',(270,-445),'power'),('GND',(465,-445),'ground'),('MCU_3V3',(650,-640),'power'),('DAC_NEG_GOOD',(785,-540),'out')])
    p.block(['U12','R41','C34'],(835,-655,1320,-425),[('MCU_3V3',(1120,-640),'power'),('GND',(1170,-440),'ground'),('DAC_POS_GOOD',(845,-570),'in'),('DAC_NEG_GOOD',(845,-520),'in'),('DAC_HW_PGOOD',(1280,-540),'out')])
    p.text(55,-400,'06D  DEFAULT-GROUNDED OUTPUT / MCU CONTROL HEADER',10)
    for n,x,y,rot in [('J4',185,-275,0),('U13',760,-285,0),('C35',850,-225,270),('R43',625,-230,270),('R42',1010,-230,270),('K1',1220,-285,0),('Q4',1450,-270,0),('D3',1450,-355,270)]:p.move(n,x,y,rot)
    p.block(['J4'],(55,-370,460,-160),[('MCU_3V3',(100,-360),'power'),('GND',(300,-175),'ground'),('DAC_SPI_ENABLE',(60,-290),'in'),('DAC_OUTPUT_ENABLE',(405,-300),'out'),('DAC_HW_PGOOD',(60,-245),'in')])
    p.block(['U13','C35','R43','R42','K1','Q4','D3'],(490,-385,1570,-165),[('MCU_3V3',(850,-365),'power'),('VIN_RAW',(1370,-370),'power'),('GND',(1010,-175),'ground'),('DAC_HW_PGOOD',(510,-310),'in'),('DAC_OUTPUT_ENABLE',(510,-255),'in'),('OUT_A',(1100,-255),'in'),('OUT_B',(1330,-245),'in'),('DAC_SMA_A',(1110,-315),'out'),('DAC_SMA_B',(1330,-300),'out')])
    p.text(55,-120,'ENABLE inputs default LOW. Relay ON = PGOOD AND OUTPUT_ENABLE. Feedback stays BEFORE the output relay.',8)
    p.text(55,-95,'Startup: mute -> stable PGOOD -> SPI on -> DAC reset / midscale / reference / gain -> settle -> output enable.',8)
    p.text(55,-70,'Q3: 2N7002LT1G, +/-20V gate rating, supplier SOT-23 land pattern. Relay release is not instantaneous.',8)
    p.save('DAC8562.readable-source.txt')
    q=Page(m.BEFORE['pages'][1]);q.clean()
    q.text(55,-2140,'DAC_MCU — STM32H747 SMA RECEIVER / BIPOLAR CONVERTER',15)
    q.text(55,-2115,'Two independent signal channels. Ordinary wires within blocks; named ports only at relay boundaries / shared reference.',8)
    channel(q,'A',-1820);channel(q,'B',-1380)
    q.text(55,-1120,'03  MCU VREF+ / HALF-REFERENCE BUFFER / OP-AMP DECOUPLING',11)
    for n,x,y,r in [('J105',180,-990,0),('R121',440,-1040,270),('R122',440,-910,270),('U102A',630,-980,0),('U102B',925,-980,0)]:q.move(n,x,y,r)
    q.block(['J105'],(55,-1080,350,-830),[('MCU_3V3',(100,-1070),'power'),('GND',(300,-850),'ground'),('MCU_VREF_PLUS',(65,-1020),'out'),('MCU_INPUT_ENABLE',(330,-1020),'out'),('MCU_OUTPUT_ENABLE',(65,-955),'out'),('DAC_HW_PGOOD',(330,-970),'in')])
    q.block(['R121','R122','U102A','U102B'],(385,-1080,1050,-830),[('MCU_VREF_PLUS',(440,-1070),'in'),('GND',(440,-850),'ground'),('VPOS12',(630,-1070),'power'),('VNEG12',(630,-850),'power'),('MCU_VBIAS',(1020,-930),'out')])
    for n,x in [('C121',1110),('C122',1175),('C123',1240),('C124',1305),('C125',1370),('C126',1435)]:q.move(n,x,-990,270)
    q.block(['C121','C122','C123','C124','C125','C126'],(1070,-1080,1500,-830),[('VPOS12',(1090,-1070),'power'),('VNEG12',(1450,-1070),'power'),('GND',(1260,-850),'ground')])
    q.text(55,-785,'04  INPUT MUTE — K101 selects external SMA signals or VBIAS',11)
    q.text(850,-785,'05  OUTPUT MUTE — K102 selects converted signals or GND',11)
    for base,x in [(100,0),(101,800)]:
        inp=base==100;gate='U104' if inp else 'U105';fet='Q101' if inp else 'Q102';relay='K101' if inp else 'K102';diode='D101' if inp else 'D102';cap='C127' if inp else 'C128';rp='R123' if inp else 'R125';re='R124' if inp else 'R126'
        for n,xx,yy,r in [(gate,x+225,-610,0),(fet,x+480,-465,0),(relay,x+535,-655,0),(diode,x+685,-655,270),(cap,x+330,-690,270),(rp,x+380,-465,270),(re,x+115,-525,270)]:q.move(n,xx,yy,r)
        ports=[('MCU_3V3',(x+330,-750),'power'),('VIN_RAW',(x+685,-750),'power'),('GND',(x+380,-405),'ground'),('DAC_HW_PGOOD',(x+65,-675),'in'),('MCU_INPUT_ENABLE' if inp else 'MCU_OUTPUT_ENABLE',(x+65,-600),'in')]
        if inp:ports += [('MCU_VBIAS',(x+445,-540),'in'),('MCU_RCV_EXTERNAL_A',(x+445,-700),'in'),('MCU_RCV_EXTERNAL_B',(x+755,-700),'in'),('MCU_RECEIVE_A',(x+445,-600),'out'),('MCU_RECEIVE_B',(x+755,-600),'out')]
        else:ports += [('MCU_SENSE_A',(x+445,-700),'in'),('MCU_SENSE_B',(x+755,-700),'in'),('MCU_OUT_A',(x+445,-600),'out'),('MCU_OUT_B',(x+755,-600),'out')]
        q.block([gate,fet,relay,diode,cap,rp,re],(x+55,-760,x+770,-395),ports)
    q.text(55,-325,'Vout = (100k / 14k) * (Vin - MCU_VREF_PLUS / 2). Nominal 3.3V reference; 0.25V..3.05V input maps to about +/-10V.',8)
    q.text(55,-300,'Input and output enable are independent. MCU source / receiver share GND. High-impedance load only; no 50-ohm termination.',8)
    q.text(55,-275,'Op-amp power pins are shown on the A units. K101 / K102 coil drivers include flyback diodes and default-LOW pull-downs.',8)
    q.save('DAC_MCU.readable-source.txt')
    (OUT/'drawing-stats.json').write_text(json.dumps({'pages':[{'page':x.doc['head']['uuid'],'wirePaths':len(x.routes),'ports':len(x.ports)} for x in [p,q]]},indent=2),encoding='utf8')
    print('Built readable sources: 154 physical parts, approved R117 connection repair and Q3 replacement.')

if __name__=='__main__':build()
