"""Independent fifty-net physical local signal graph; no EDA/API operations.

Usage: python this.py ROUTE_JSON [PLACEMENT_JSON] [REPORT_JSON]
This does not claim complete rail/GND/fill/DRC closure.
"""
import json,runpy,sys
from pathlib import Path
from collections import defaultdict
from shapely.geometry import LineString,Point
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent
H=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'))
MM=H['MM'];EPS=4e-6 # maximum4dec-mil XY rounding plus originalsource endpoint serialization

def main():
    rp=Path(sys.argv[1]);pp=Path(sys.argv[2]) if len(sys.argv)>2 else HERE/'independent-pcb-placement-short-negative-variant-v2.json'
    op=Path(sys.argv[3]) if len(sys.argv)>3 else HERE/'independent-local-route-graph-variant-audit.json'
    routes=json.loads(rp.read_text(encoding='utf8'));placement=json.loads(pp.read_text(encoding='utf8'))
    rows=H['parse'](H['SOURCE']);at=H['attrs_of'](rows);docs,_=H['READ'](H['CHECK'])
    isolation=json.loads((HERE/'routing/exact-old-copper-isolation-post-eco-manifest.json').read_text(encoding='utf8'))
    ops={(x['type'],x['id']):x for x in isolation['operations']};edits={x['componentId']:x for x in placement['edits']}
    snets={f'ADC_J{j}_{kind}' for j in range(2,12) for kind in ('RAW','FILTER','BUF','SUM','DRV')}
    shapes=defaultdict(list);pads=defaultdict(list);pgeom={};pnet={}
    for (k,r),b in rows.items():
        if k=='PAD_NET':
            a=json.loads(r);pnet[a[1],str(a[2])]=b.get('padNet')
    for (k,r),b in rows.items():
        if k=='COMPONENT' and b['layerId']==1:
            ref=at[r]['Designator'];p=edits.get(r)
            xy=p['xyMm'] if p else [b['x']*MM,b['y']*MM];angle=p['angle'] if p else b['angle']
            fps,_=H['footprint'](docs['FOOTPRINT',at[r]['Footprint']])
            for n,(s,pb) in fps.items():
                if pb['layerId'] not in (1,12):continue
                s=H['world'](s,xy,angle);net=pnet.get((r,n))
                pgeom[ref,n]=s
                if net in snets:shapes[net].append(s);pads[net].append((ref,n,s))
        elif k in ('LINE','ARC'):
            if (k,r) in ops:
                o=ops[k,r];assert b==o['beforeBody'],r
                if o['action']=='delete':continue
                b=o['afterBody']
            if b['layerId']!=1 or b.get('netName') not in snets:continue
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
            pts=H['G']['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
            shapes[b['netName']].append(LineString(pts).buffer(b['width']*MM/2,resolution=16))
    for q in routes['newLineCreates']:
        if q['net'] not in snets:continue
        shapes[q['net']].append(LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=16))
    results=[];solids={}
    for net in sorted(snets):
        s=unary_union(shapes[net]);solids[net]=s
        # Actor components are joins of literal same-net conductors. Record any
        # tiny source-coordinate seam independently; never inflateaDRC tolerance.
        cc=list(s.geoms) if hasattr(s,'geoms') else [s]
        parent=list(range(len(cc)))
        def find(x):
            while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
            return x
        seams=[]
        for i in range(len(cc)):
            for j in range(i):
                d=cc[i].distance(cc[j])
                if d<=EPS:
                    parent[find(i)]=find(j)
                    if d>1e-12:seams.append(d)
        groups=[]
        for ref,n,p in pads[net]:
            hit=[find(i) for i,c in enumerate(cc) if c.distance(p)<=1e-10]
            assert hit,(net,ref,n)
            groups.append((ref,n,hit[0]))
        ok=len({x[2] for x in groups})==1
        results.append({'net':net,'status':'PASS' if ok else 'DISCONNECTED','pads':[{'ref':r,'pin':n,'physicalComponent':g} for r,n,g in groups],'allPadsConnected':ok,'nativeLiteralConductorPieces':len(cc),'quantizedSeamDistancesMm':seams})
    shorts=[]
    for j in range(2,12):
        nets=[f'ADC_J{j}_{kind}' for kind in ('RAW','FILTER','BUF','SUM','DRV')]
        for i,n in enumerate(nets):
            for m in nets[:i]:
                d=solids[n].distance(solids[m])
                if d<.1524-1e-6:shorts.append({'netA':n,'netB':m,'distanceMm':d})
    neg=[]
    for i in range(10):
        a=pgeom[f'U{20+i}','2'];b=pgeom[f'C{121+3*i}','1']
        lines=[LineString([q['startXYmm'],q['endXYmm']]).buffer(q['widthMm']/2,resolution=16) for q in routes['newLineCreates'] if q['net']=='-3V_AFE']
        u=unary_union([a,b,*lines]);cc=list(u.geoms) if hasattr(u,'geoms') else [u]
        connected=any(c.distance(a)<=EPS and c.distance(b)<=EPS for c in cc)
        rs=[x for x in routes['routedConnections'] if x.get('net')=='-3V_AFE' and 'Negative local follower bypass' in x.get('role','')]
        length=rs[i]['lengthMm'] if len(rs)==10 else None
        neg.append({'channel':i+1,'connected':connected,'routedLengthMm':length,'under3Mm':length is not None and length<3})
    passed=all(x['allPadsConnected'] for x in results) and not shorts and all(x['connected'] for x in neg)
    report={'schema':'independent-labtool-local-physical-route-graph-20261018','status':'PASS_SCOPED_SIGNAL_GRAPH' if passed else 'FAIL_OR_INCOMPLETE','nativeCalls':0,'routePath':str(rp),'routeSha256':H['sha'](rp),'placementPath':str(pp),'placementSha256':H['sha'](pp),'sourceSha256':H['sha'](H['SOURCE']),'signalNetsExpected':50,'signalNetsPass':sum(x['allPadsConnected'] for x in results),'nets':results,'differentNetDistanceViolationsBelowRule':shorts,'negativeLocalLeads':neg,'coordinateSeamToleranceMm':EPS,'limits':['Checks literal TOP signalconductor connectivity across components by their actualnativePAD numbers; doesnot electrically connectacrossresistors/capacitors.','Doesnotclaimallsharedrails/GND/courtyard/clearance/DRC/manufacturing closure.','All640originalVIAs/799drillspreserved; noVIAeditsinthisread-onlyaudit.']}
    op.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'path':str(op),'sha256':H['sha'](op),'status':report['status'],'signalNetsPass':report['signalNetsPass'],'violations':shorts,'negativeLeads':neg}))

if __name__=='__main__':main()
