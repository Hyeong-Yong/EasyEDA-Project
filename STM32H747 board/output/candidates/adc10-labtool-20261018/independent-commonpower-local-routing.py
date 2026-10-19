"""Offline hand-routed commonchargepump/LDO island, exact bounded screening.
No nativecalls, no source/nativePCB replacement. Original640VIAs unchanged.
"""
import json,runpy
from pathlib import Path
from collections import defaultdict
from shapely.geometry import LineString,Point,Polygon,box
from shapely.strtree import STRtree
from shapely.ops import unary_union
HERE=Path(__file__).resolve().parent
H=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'));MM=H['MM'];CLR=H['CLR']
PLACE=HERE/'independent-pcb-placement-short-negative-commonpower-v3-proposal.json'
ROW=HERE/'routing/frozen-short-negative-row290-variant-v1b.json'
OUT=HERE/'routing/commonpower-top-local-v3-draft.json'
def main():
    plan=json.loads(PLACE.read_text(encoding='utf8'));pd={p['ref']:p for p in plan['edits']}
    rows=H['parse'](H['SOURCE']);at=H['attrs_of'](rows);docs,_=H['READ'](H['CHECK'])
    isop=HERE/'routing/exact-old-copper-isolation-post-eco-manifest.json';iso=json.loads(isop.read_text(encoding='utf8'));ops={(x['type'],x['id']):x for x in iso['operations']}
    padnet={}
    for (k,r),b in rows.items():
        if k=='PAD_NET':a=json.loads(r);padnet[a[1],str(a[2])]=b.get('padNet')
    obs=[];allpads=[];gndfills=[];newlines=[];paths=[]
    def add(k,r,n,s):obs.append((k,r,n,s))
    for (k,r),b in rows.items():
        if k=='COMPONENT' and b['layerId']==1:
            ref=at[r]['Designator'];p=pd.get(ref);xy=p['xyMm'] if p else [b['x']*MM,b['y']*MM];ang=p['angle'] if p else b['angle']
            # Keep every native PAD record; duplicate-number SMAgroundpads must
            # not disappear through a dictionary keyed solely by padnumber.
            for (pk,pr),(_,pb) in docs['FOOTPRINT',at[r]['Footprint']].items():
                if pk!='PAD' or pb['layerId'] not in (1,12):continue
                s=H['world'](H['local_pad'](pb),xy,ang);net=padnet.get((r,str(pb['num'])))
                add('PAD',ref+':'+str(pb['num'])+':'+pr,net,s);allpads.append((ref,str(pb['num']),net,s))
        elif k=='VIA':add(k,r,b.get('netName'),Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32))
        elif k in ('LINE','ARC') and b['layerId']==1:
            if (k,r) in ops:
                o=ops[k,r];assert b==o['beforeBody']
                if o['action']=='delete':continue
                b=o['afterBody']
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM);pts=H['G']['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
            add(k,r,b.get('netName'),LineString(pts).buffer(b['width']*MM/2,resolution=24))
        elif k=='FILL' and b['layerId']==1:
            rr=[H['G']['ring_path'](q) for q in b['path']];s=Polygon(rr[0],rr[1:])
            if b.get('netName')=='GND':
                if s.is_valid:gndfills.append((r,s))
            elif s.is_valid:add(k,r,b.get('netName'),s)
    for q in json.loads(ROW.read_text(encoding='utf8'))['newLineCreates']:
        add('ROW_LINE',q['key'],q['net'],LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=24))
    def P(ref,n):return next(p['centerMm'] for p in pd[ref]['pads'] if p['number']==str(n))
    def path(net,role,pts,w):
        keys=[]
        for a,b in zip(pts,pts[1:]):
            if a==b:continue
            key=f'LABTOOL_PWR_{len(newlines)+1:04d}';keys.append(key)
            newlines.append({'key':key,'net':net,'layerId':1,'startXYmm':list(a),'endXYmm':list(b),'widthMm':w,'role':role})
        paths.append({'net':net,'role':role,'lengthMm':LineString(pts).length,'lineKeys':keys})
    path('AFE_FLY_N','FlyingcapacitorN shortestdirectlead',[P('U30',3),P('C151',1)],.4)
    path('AFE_FLY_P','FlyingcapacitorP aroundGNDpad; no signalunderpump',[P('U30',5),(33.35,30.75),(33.35,28.15),(32.7,27.75),P('C151',2)],.4)
    path('AFE_PUMP_IN','PumpIN fromlocalinputcapacitor',[P('U30',2),(28.8,29.8),P('C150',1)],.4)
    path('AFE_PUMP_IN','Inputisolator tolocalinputcapacitor',[P('R197',2),P('C150',1)],.4)
    path('AFE_VNEG_RAW','PumpRAW toprotectiondiodeAnode',[P('U30',1),P('D20',2)],.4)
    path('AFE_VNEG_RAW','PumpRAW tooutputcapacitor; aboveFLYP',[P('U30',1),(29.7,31.75),(34.7,31.75),P('C152',1)],.4)
    path('AFE_VNEG_RAW','Localoutputcapacitor toLDOIN',[P('C152',1),(35.5,29.8),P('U31',2)],.4)
    path('AFE_VNEG_RAW','LDOEN tiedlocallytoIN',[P('U31',2),P('U31',3)],.4)
    path('-3V_AFE','LDOOUT nearestoutputcapacitor',[P('U31',5),P('C153',1)],.35)
    path('-3V_AFE','LDOOUT bulkcapacitor viaquietrightchannel',[P('U31',5),(40.35,30.75),(40.35,26.6),P('C154',1)],.35)
    path('-3V_AFE','Outputbulk toCFF lowimpedanceleaf',[P('C154',1),(40.8,25.6),(40.8,22.4),(35.82,22.4),P('C155',2)],.35)
    path('-3V_AFE','FeedbackdivideroutputKelvinleaf',[P('R198',1),P('C155',2)],.2032)
    path('AFE_NEG_FB','LDOFB todivider',[P('U31',4),(39.3,25.6),P('R199',2)],.2032)
    path('AFE_NEG_FB','DividerGNDside toCFFFBpin',[P('R199',2),P('C155',1)],.2032)
    path('AFE_NEG_FB','Divideroutputside FBjoin',[P('C155',1),P('R198',2)],.2032)
    path('-3V_AFE','ReverseprotectionCathode toLDOOUT',[P('D20',1),(39.3,33.2),P('U31',5)],.35)
    path('+5V_AFE','Positiveisolator tofirstreservoir',[P('R200',2),P('C156',1)],.4)
    path('+5V_AFE','Parallelpositivebulkreservoirs',[P('C156',1),P('C157',1)],.4)
    conflicts=[];touch=[];shapes=[x[3] for x in obs];tree=STRtree(shapes)
    for i,q in enumerate(newlines):
        s=LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=24);qq=s.buffer(CLR,resolution=24)
        for j in tree.query(qq):
            k,r,n,z=obs[int(j)]
            if n!=q['net'] and s.distance(z)<CLR-1e-8:conflicts.append({'line':q['key'],'net':q['net'],'other':[k,r,n],'distanceMm':s.distance(z)})
        for r in newlines[:i]:
            if r['net']==q['net']:continue
            z=LineString([r['startXYmm'],r['endXYmm']]).buffer(r['widthMm']/2,resolution=24)
            if s.distance(z)<CLR-1e-8:conflicts.append({'line':q['key'],'net':q['net'],'other':['NEW_LINE',r['key'],r['net']],'distanceMm':s.distance(z)})
        for fid,gs in gndfills:
            if qq.intersects(gs):touch.append({'line':q['key'],'groundFillId':fid})
    cnet=defaultdict(list)
    for q in newlines:cnet[q['net']].append(LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=24))
    checks=[]
    for net in sorted(cnet):
        shapes=cnet[net]+[s for ref,n,nnet,s in allpads if nnet==net and ref in {'U30','U31','D20','C150','C151','C152','C153','C154','C155','C156','C157','R197','R198','R199','R200'}]
        u=unary_union(shapes);cc=list(u.geoms) if hasattr(u,'geoms') else[u]
        pp=[(ref,n,s) for ref,n,nnet,s in allpads if nnet==net and ref in {'U30','U31','D20','C150','C151','C152','C153','C154','C155','C156','C157','R197','R198','R199','R200'}]
        ok=any(all(c.distance(s)<4e-6 for _,_,s in pp) for c in cc)
        checks.append({'net':net,'pads':[{'ref':r,'pin':n} for r,n,_ in pp],'allRelevantPadsConnected':ok})
    report={'schema':'independent-commonpower-top-local-route-v3-draft-20261018','status':'PASS_SCOPED_LOCAL_ROUTING_GND_AND_FEEDS_PENDING' if not conflicts and all(x['allRelevantPadsConnected'] for x in checks) else 'FAIL_OR_INCOMPLETE','placementPath':str(PLACE),'placementSha256':H['sha'](PLACE),'sourcePath':str(H['SOURCE']),'sourceSha256':H['sha'](H['SOURCE']),'rowRouteSha256':H['sha'](ROW),'isolationSha256':H['sha'](isop),'nativeCalls':0,'newLineCreates':newlines,'routedConnections':paths,'literalCopperConflicts':conflicts,'localNetGraphChecks':checks,'requiresLocalGroundClearanceVoids':touch,'preserved640Vias799Drills':True,'newViasProposedHere':0,'remaining':['Raw+5 source toR197pin1/R200pin1 viaexplicitBOTTOMports','+5AFE/-3AFE outputTOPstubs toreviewednewVIAports andBOTTOMtrunks','GlobalGNDplane/thermalreturnloop andallnewgroundpads anchoredproof','AllnewlocalstaticFILLvoids validated byseparateplanner','NativefullDRC/sourceguards/netlist/reopen'],'manufacturingApproved':False}
    OUT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'path':str(OUT),'sha256':H['sha'](OUT),'status':report['status'],'lineCount':len(newlines),'conflicts':conflicts,'checks':checks,'paths':paths}))
if __name__=='__main__':main()
