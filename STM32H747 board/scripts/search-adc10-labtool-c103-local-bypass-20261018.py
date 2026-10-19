"""Offline exact-footprint C103 local-bypass search against actual V5b and frozen Cu."""
import json,hashlib,runpy,math,copy
from pathlib import Path
from collections import defaultdict
from shapely.geometry import Point,LineString,box
from shapely.affinity import scale
from shapely.strtree import STRtree
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/candidates/adc10-labtool-20261018';HERE=BASE/'routing';MM=.0254;CLR=.1535
M=runpy.run_path(str(BASE/'independent-pcb-placement-proposal.py'));G=M['G'];SRC=ROOT/'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru';PLAN=BASE/'independent-pcb-placement-short-negative-commonpower-v5b-ref-flipped-proposal.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    rows=M['parse'](SRC);attrs=M['attrs_of'](rows);refs={a['Designator']:cid for cid,a in attrs.items() if 'Designator' in a};docs,_=M['READ'](M['CHECK']);plan=json.loads(PLAN.read_text());r=json.loads((HERE/'frozen-combined-routing-v2.json').read_text());cid=refs['C103'];comp=rows['COMPONENT',cid];fp,court=M['footprint'](docs['FOOTPRINT',attrs[cid]['Footprint']]);padnets={}
    for (k,rid),b in rows.items():
        if k=='PAD_NET':p=json.loads(rid);padnets[p[1],str(p[2])]=b['padNet']
    obs=[];courts=[]
    def add(key,net,s):obs.append((key,(net or '').casefold(),s))
    for (k,rid),b in rows.items():
        if k=='COMPONENT' and rid!=cid:
            ref=attrs[rid]['Designator'];xy=b['x']*MM,b['y']*MM;fpp,co=M['footprint'](docs['FOOTPRINT',attrs[rid]['Footprint']])
            if b['layerId']==1:courts.append((ref,M['world'](co,xy,b['angle'])))
            for (pk,pi),(ph,p) in docs['FOOTPRINT',attrs[rid]['Footprint']].items():
                if pk!='PAD' or (b['layerId']!=1 and p['layerId']!=12):continue
                s=M['local_pad'](p)
                if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                add('PAD:'+ref+':'+str(p['num']),padnets.get((rid,str(p['num'])),''),M['world'](s,xy,b['angle']))
        elif k=='VIA':add('VIA:'+rid,b['netName'],Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32))
        elif k in ('LINE','ARC') and b.get('layerId')==1:
            a=(b['startX']*MM,b['startY']*MM);z=(b['endX']*MM,b['endY']*MM);pts=G['arc'](a,z,b['angle']) if k=='ARC' else [a,z];add(k+':'+rid,b.get('netName'),LineString(pts).buffer(b['width']*MM/2,resolution=16))
    for p in r['newLineCreates']:
        if p['layerId']==1 and p['sourceModule']!='query-reference-power-final-v1-layer1.json':add(p['key'],p['net'],LineString([p['startXYmm'],p['endXYmm']]).buffer(p['widthMm']/2,resolution=16))
    for p in r['newViaCreates']:
        if p['key']!='REFERENCE_POWER_RAIL_PORT':add(p['key'],p['net'],Point(p['xyMm']).buffer(p['viaDiameterMm']/2,resolution=32))
    ct=STRtree([p[1] for p in courts]);ot=STRtree([o[2] for o in obs]);vin=(25.465,74.2);out=[];fails=defaultdict(int)
    via_keys={p['key'] for p in r['newViaCreates'] if p['key']!='REFERENCE_POWER_RAIL_PORT'}
    via_shapes=[s for key,net,s in obs if key.startswith('VIA:') or key in via_keys];vt=STRtree(via_shapes)
    for ix in range(110,166):
        for iy in range(350,425):
            xy=ix*.2,iy*.2
            for angle in (0,90,180,270):
                co=M['world'](court,xy,angle)
                if any(co.intersects(courts[int(i)][1]) for i in ct.query(co)):fails['court']+=1;continue
                shapes={pn:M['world'](s,xy,angle) for pn,(s,pb) in fp.items()}
                valid=True
                for pn,s in shapes.items():
                    net=padnets[cid,pn].casefold();probe=s.buffer(CLR,resolution=16)
                    for oi in ot.query(probe):
                        key,on,os=obs[int(oi)]
                        if on!=net and s.distance(os)<CLR:valid=False;break
                    if not valid:break
                if not valid:fails['padCopper']+=1;continue
                # A new capacitor package may not cover any retained/new VIA.
                if any(co.intersects(via_shapes[int(i)]) for i in vt.query(co)):fails['viaCourt']+=1;continue
                pp={pn:(s.centroid.x,s.centroid.y) for pn,s in shapes.items()};feed=LineString([vin,pp['1']]).buffer(.2032/2,resolution=16)
                direct=not any(obs[int(i)][1]!='+5v_afe' and feed.distance(obs[int(i)][2])<CLR for i in ot.query(feed.buffer(CLR))) and feed.distance(shapes['2'])>=CLR
                entry={'xyMm':xy,'angle':angle,'pad1XYmm':pp['1'],'pad2XYmm':pp['2'],'conservativeCourtBoundsMm':list(co.bounds),'directVinFeedClear':direct,'directVinFeedLengthMm':math.dist(vin,pp['1'])}
                out.append(entry)
    out.sort(key=lambda p:(not p['directVinFeedClear'],p['directVinFeedLengthMm'],math.dist(p['pad2XYmm'],(28.005,74.2))))
    report={'sourceSha256':sha(SRC),'frozenV2Sha256':sha(HERE/'frozen-combined-routing-v2.json'),'actualC103ComponentId':cid,'actualC103BeforeBody':comp,'footprintUuid':attrs[cid]['Footprint'],'padNetContract':{pn:padnets[cid,pn] for pn in fp},'candidates':out[:30],'closestCandidatesOnReferenceSide':[p for p in out if p['xyMm'][0]>=24][:30],'validCandidates':len(out),'rejections':dict(fails),'nativeCalls':0,'placementOnlyNoSchematicChange':True,'conditions':['Requires literal GND return/stitch proof.','Requires all-layer new VIA/drill check, final component full-body guards, all 74net/Ground/+3V3 graphs and native strict DRC.'],'manufacturingReady':False}
    target=HERE/'c103-local-bypass-site-search-v6.json';target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'target':str(target),'sha256':sha(target),'valid':len(out),'best':out[:4]}))
if __name__=='__main__':main()
