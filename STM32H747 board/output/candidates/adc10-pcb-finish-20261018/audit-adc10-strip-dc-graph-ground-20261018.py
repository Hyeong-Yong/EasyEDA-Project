"""Literal copper/pad graph and GND/via proof, planned or actual204 routes."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import runpy
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'output/candidates/adc10-dc-buffer-20261017'
M=runpy.run_path(str(HERE/'audit-adc10-copper-cut-readback-20261018.py'))
BM=runpy.run_path(str(OLD/'independent-adc10-bias-feed-isolation-plan.py'))
DEFAULT_MANIFEST=HERE/'strip/adc10-strip-phase2-rebased-closed-operations-20261018.json'
SPECS=[('J2','R137','R140','R141','U10','C97','C100','ADC1_PRE1','ADC1_DRV1'),
       ('J3','R138','R142','R143','U11','C98','C101','ADC1_PRE2','ADC1_DRV2'),
       ('J4','R139','R144','R145','U12','C99','C102','ADC1_PRE3','ADC1_DRV3'),
       ('J5','R149','R152','R153','U13','C106','C113','ADC2_PRE1','ADC2_DRV1'),
       ('J6','R150','R154','R155','U14','C107','C114','ADC2_PRE2','ADC2_DRV2'),
       ('J7','R151','R156','R157','U15','C108','C115','ADC2_PRE3','ADC2_DRV3'),
       ('J8','R161','R165','R166','U16','C109','C116','ADC3_PRE1','ADC3_DRV1'),
       ('J9','R162','R167','R168','U17','C110','C117','ADC3_PRE2','ADC3_DRV2'),
       ('J10','R163','R169','R170','U18','C111','C118','ADC3_PRE3','ADC3_DRV3'),
       ('J11','R164','R171','R172','U19','C112','C119','ADC3_PRE4','ADC3_DRV4')]
MM=.0254


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def fill_polygon(body):
    rings=[BM['polyline'](p)for p in body['path']]
    p=Polygon(rings[0],rings[1:])
    assert p.is_valid and not p.is_empty,'Actual main TOP GND polygon must be valid; no repair accepted for physical connectivity proof'
    return p


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',default=str(DEFAULT_MANIFEST))
    p.add_argument('--source',default=str(ROOT/'output/validation/native-adc10-pcb-strip_routes_fill-20261018.epru'))
    p.add_argument('--actual-routes',action='store_true')
    p.add_argument('--tag',default='prospective')
    args=p.parse_args();source,manifest=Path(args.source).resolve(),Path(args.manifest).resolve()
    plan=json.loads(manifest.read_text());manifest_sha=sha(manifest)
    rows,headers=M['parse'](source);libs=BM['LM']['read_libs']()
    attrs=defaultdict(dict)
    for(kind,rid),b in rows.items():
        if kind=='ATTR':attrs[b['parentId']][b['key']]=b['value']
    refs={a['Designator']:cid for cid,a in attrs.items()if'Designator'in a};inverse={cid:ref for ref,cid in refs.items()}
    padnets={}
    for(kind,rid),b in rows.items():
        if kind=='PAD_NET':
            _,cid,num,pid=json.loads(rid);padnets[cid,str(num),pid]=b['padNet']
    pads={}
    for ref,cid in refs.items():
        c=rows['COMPONENT',cid]
        for(kind,pid),b in libs['FOOTPRINT',attrs[cid]['Footprint']].items():
            if kind!='PAD'or b['layerId']not in [1,12]or(c['layerId']!=1 and b['layerId']!=12):continue
            n=str(b['num']);net=padnets[cid,n,pid]
            key=ref,n
            s=BM['padshape'](b,c)
            if key in pads:
                assert pads[key]['net']==net
                pads[key]['shape']=unary_union([pads[key]['shape'],s])
            else:pads[key]={'shape':s,'net':net,'componentId':cid,'padPrimitiveId':pid}
    targetnets={s[7]for s in SPECS}|{s[8]for s in SPECS}|{'+3V3','ADC_BIAS_2V5'}
    actors=defaultdict(list)
    for(kind,rid),b in rows.items():
        if kind in ['LINE','ARC','CARC']and b.get('layerId')==1 and b.get('netName')in targetnets:
            actors[b['netName']].append(BM['trackshape'](kind,b))
    planned=[]
    if not args.actual_routes:
        for o in plan['newLineCreates']:
            b={'startX':round(o['startXMil'],4),'startY':round(o['startYMil'],4),'endX':round(o['endXMil'],4),
               'endY':round(o['endYMil'],4),'width':round(o['widthMil'],4)}
            s=BM['trackshape']('LINE',b);actors[o['net']].append(s);planned.append((o['net'],s,o['key']))
    else:
        planned=[(b['netName'],BM['trackshape'](kind,b),rid)for(kind,rid),b in rows.items()
                 if kind=='LINE'and b.get('layerId')==1 and b.get('netName')in targetnets]
    for pin,v in pads.items():
        if v['net']in targetnets:actors[v['net']].append(v['shape'])
    power_vias={rid:Point(b['centerX'],b['centerY']).buffer(b['viaDiameter']/2,quad_segs=128)
        for(kind,rid),b in rows.items()if kind=='VIA'and b['netName']=='+3V3'}
    for s in power_vias.values():actors['+3V3'].append(s)
    unions={net:unary_union(shapes)for net,shapes in actors.items()}
    comps={net:([u]if u.geom_type=='Polygon'else list(u.geoms))for net,u in unions.items()}
    tests=[];errors=[]
    def check(ok,test,detail=None):
        row={'test':test,'passed':bool(ok)}
        if detail is not None:row['detail']=detail
        tests.append(row)
        if not ok:errors.append(row)
    def membership(net,pin):
        assert pin in pads,(net,pin)
        check(pads[pin]['net']==net,'Actual pad assigned expected net '+str(pin))
        return [i for i,c in enumerate(comps[net])if c.intersection(pads[pin]['shape']).area>1e-8]
    chains=[]
    for sma,rb,rin,series,opa,cpre,cdec,pre,drv in SPECS:
        pre_pins=[(rin,'2'),(rb,'1'),(cpre,'1'),(opa,'3')]
        drv_pins=[(opa,'1'),(opa,'4'),(series,'1')]
        pm=[membership(pre,pin)for pin in pre_pins];dm=[membership(drv,pin)for pin in drv_pins]
        pc=set(pm[0]).intersection(*map(set,pm[1:]));dc=set(dm[0]).intersection(*map(set,dm[1:]))
        check(len(pc)==1 and all(len(x)==1 for x in pm),'Literal PRE copper joins Rin2/Rb1/Cpre1/OPA+ '+sma,{'pins':pre_pins,'components':pm})
        check(len(dc)==1 and all(len(x)==1 for x in dm),'Literal DRV copper joins OPAout/INminus/47Rinput '+sma,{'pins':drv_pins,'components':dm})
        gap=unions[pre].distance(unions[drv])*MM
        check(gap>=.1524-1e-8,'PRE never physically shorts/bypasses OPA to DRV '+sma,gap)
        chains.append({'sma':sma,'PRE':pre,'DRV':drv,'PREPins':pre_pins,'DRVPins':drv_pins,
            'PRECopperComponent':list(pc),'DRVCopperComponent':list(dc),'PREtoDRVMinimumCopperGapMm':gap})
    bias_pins=[(s[1],'2')for s in SPECS]+[('U9','2'),('C104','1'),('C105','1')]
    bm=[membership('ADC_BIAS_2V5',pin)for pin in bias_pins]
    common=set(bm[0]).intersection(*map(set,bm[1:]));check(len(common)==1 and all(len(x)==1 for x in bm),'All13 quiet-bias pads join one literal TOP copper component',{'pins':bias_pins,'components':bm})
    power_pins=[(s[4],'5')for s in SPECS]+[(s[6],'1')for s in SPECS]+[('U9','1'),('C103','1')]
    supply=[]
    for pin in power_pins:
        components=membership('+3V3',pin)
        anchors=sorted({vid for i in components for vid,s in power_vias.items()if comps['+3V3'][i].intersection(s).area>1e-8})
        check(bool(anchors),'New supply pin physically reaches existing protected main3V3 VIA '+str(pin),anchors)
        supply.append({'pin':pin,'TOPCopperComponents':components,'existing3V3VIAAnchors':anchors})
    ground=fill_polygon(rows['FILL','e680230ef8d2c5dd'])
    ground_vias={rid:Point(b['centerX'],b['centerY']).buffer(b['viaDiameter']/2,quad_segs=128)
        for(kind,rid),b in rows.items()if kind=='VIA'and b['netName']=='GND'}
    grounded_vias=sorted(vid for vid,s in ground_vias.items()if ground.intersection(s).area>1e-8)
    check(bool(grounded_vias),'Actual connected main TOP GND polygon overlaps existing protected GND VIAs',{'count':len(grounded_vias),'ids':grounded_vias})
    ground_pins=[(s[4],'2')for s in SPECS]+[(s[5],'2')for s in SPECS]+[(s[6],'2')for s in SPECS]
    ground_pins += [('U9','3'),('C103','2'),('C104','2'),('C105','2')]
    ground_report=[]
    for pin in ground_pins:
        pad=pads[pin];area=ground.intersection(pad['shape']).area
        check(pad['net']=='GND'and area>1e-8 and bool(grounded_vias),'New GND pad contacts literal via-anchored GND solid, not just a label '+str(pin),
              {'intersectionAreaMm2':area*MM*MM,'padAreaCoverageRatio':area/pad['shape'].area})
        ground_report.append({'pin':pin,'intersectionAreaMm2':area*MM*MM,'padAreaCoverageRatio':area/pad['shape'].area,
            'groundCopperComponent':'FILL:e680230ef8d2c5dd outer-minus-holes connected Polygon','existingGNDVIAAnchorCount':len(grounded_vias)})
    check(len(ground_pins)==34,'All34 new-component GND pads checked')
    check(sha(manifest)==manifest_sha,'Frozen manifest unchanged during audit')
    out=HERE/f'adc10-strip-{args.tag}-literal-dc-graph-ground-audit-20261018.json'
    report={'schema':'stm32h747-adc10-strip-literal-copper-graph-ground-audit-20261018-v1','passed':not errors,'errors':errors,
        'mode':'ACTUAL_NATIVE_ALL_ROUTES'if args.actual_routes else'PROSPECTIVE_ALL204_PLAN_ROUTES_PLUS_ACTUAL_PLACEMENTS_GND',
        'sourcePath':str(source),'sourceSha256':sha(source),'manifestPath':str(manifest),'manifestSha256':manifest_sha,
        'channelGraphs':chains,'biasPins':bias_pins,'biasCopperCommonComponents':list(common),'supplyPins':supply,
        'groundPads':ground_report,'actualMainGNDFILLAreaMm2':ground.area*MM*MM,'mainGNDPolygonValid':ground.is_valid,
        'mainGNDPolygonIsSingleConnectedComponent':ground.geom_type=='Polygon','existingGNDVIAAnchors':grounded_vias,
        'checks':tests,'limits':['Literal copper/pad overlap graph only, not a same-NET label shortcut. No native/API calls or writes.',
            'Existing protected main3V3 VIAs are physical anchors into unchanged original power distribution; this audit does not re-simulate the regulator.',
            'Single connected Polygon topology is checked. Minimum copper neck width and full-board different-net clearance remain native strict DRC responsibilities.',
            'Prospective mode is a plan proof, not an implementation claim. Actual mode must be rerun after all204LINEs are captured. No fabrication approval.'],
        'liveAPICalls':0,'nativeFilesWritten':0}
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'mode':report['mode'],
        'channels':len(chains),'biasPads':len(bias_pins),'supplyPads':len(power_pins),'groundPads':len(ground_report),
        'existingGNDVIAAnchors':len(grounded_vias),'errorTests':[e['test']for e in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
