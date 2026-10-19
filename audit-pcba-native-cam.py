"""Read-only export checks. Passing these bounded checks is not DFM approval."""
from pathlib import Path
import collections, csv, hashlib, importlib.util, io as stringio, json, math, re, sys, zipfile

ROOT=Path(__file__).resolve().parent
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
io=module('pcba_io',ROOT/'TEST_DAC8562/scripts/correction-io.py')
gp=module('pcba_gerber',ROOT/'STM32H747 board/scripts/extract_gerber_reconstruction.py')
dp=module('pcba_drill',ROOT/'STM32H747 board/scripts/audit-diagnostic-gerber-drill-zip.py')
CONFIG=[('DAC8562','TEST_DAC8562','4e08f91f9a2c4fe4','DAC8562_verified_20261019.epro2',2),('STM32H747','STM32H747 board','0ac2a19168000d8e','STM32H747_before_pcba_20261019.epro2',6)]
COPPER={1:'Gerber_TopLayer.GTL',2:'Gerber_BottomLayer.GBL',15:'Gerber_InnerLayer1.G1',16:'Gerber_InnerLayer2.G2',17:'Gerber_InnerLayer3.G3',18:'Gerber_InnerLayer4.G4'}

for board,folder,pcb_uuid,export,n_layers in CONFIG:
    base=ROOT/folder/'output/jlcpcb-20261019-review';native=base/'native'
    docs=io.read_export(native/export);pcb=docs[pcb_uuid];attrs=io.attrs(pcb)
    zip_path=native/(board+'_CAM_20261019.zip')
    temp=native/'parsed-cam';temp.mkdir(exist_ok=True)
    layers={};drills=[];members=[]
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        for name in z.namelist():
            data=z.read(name);members.append({'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            if name.lower().endswith('.drl') and ('PTH' in name or 'VIA' in name):
                items,detail=dp.parse_excellon(name,data);drills.extend(items)
            if name in COPPER.values() or name.endswith(('.GTS','.GBS','.GTP','.GBP','.GKO')):
                # Legacy KiCad parser expects Dnn; native EasyEDA emits the
                # equivalent G54Dnn selector. Normalize only the derived copy.
                normalized=re.sub(rb'(?m)^G54(D\d+\*)',rb'\1',data)
                path=temp/name;path.write_bytes(normalized);layers[name]=gp.parse_gerber(path,name)
                assert all(o['kind']=='region' or o.get('aperture') in layers[name]['apertures'] for o in layers[name]['objects']),name
    def flashes(name):return [o for o in layers[name]['objects'] if o['kind']=='flash']
    indexes={}
    for name in COPPER.values():
        if name not in layers:continue
        grid=collections.defaultdict(list)
        for f in flashes(name):grid[(round(f['atMm'][0],2),round(f['atMm'][1],2))].append(f)
        indexes[name]=grid
    def near(name,x,y):
        grid=indexes[name];out=[]
        for dx in [-.01,0,.01]:
            for dy in [-.01,0,.01]:
                for f in grid.get((round(x+dx,2),round(y+dy,2)),[]):
                    if math.dist([x,y],f['atMm'])<=.003:out.append(f)
        return out
    components=[];pad_checks=[]
    for (kind,pid),(_,p) in pcb['records'].items():
        if kind!='COMPONENT':continue
        a=attrs[pid];ref=a['Designator'];fp=docs[a['Footprint']]
        pads=[v for (k,i),(_,v) in fp['records'].items() if k=='PAD']
        physical_layers=sorted({v['layerId'] for v in pads if v['layerId'] in (1,2)})
        if p['layerId']==2:physical_layers=[3-v for v in physical_layers]
        side='Bottom' if physical_layers==[2] else 'Top'
        theta=math.radians(p['angle']);co,si=math.cos(theta),math.sin(theta)
        world=[]
        for pad in pads:
            x,y=pad['centerX'],pad['centerY']
            if p['layerId']==2:x=-x
            x,y=(p['x']+x*co-y*si)*.0254,(p['y']+x*si+y*co)*.0254
            layer=pad['layerId'];layer=(3-layer if p['layerId']==2 and layer in (1,2) else layer)
            world.append({'pin':pad['num'],'x':round(x,6),'y':round(y,6),'layer':layer})
            for lid in ([1,2] if layer==12 else [layer]):
                if lid not in COPPER:continue
                name=COPPER[lid];hits=near(name,x,y)
                pad_checks.append({'ref':ref,'pin':pad['num'],'layer':lid,'x':x,'y':y,'centredCopperFlash':bool(hits)})
        components.append({'ref':ref,'componentLayer':p['layerId'],'physicalSide':side,'footprint':a['Footprint'],'pads':world,'sourceAngle':p['angle'],'modelTransform':p['attrs'].get('3D Model Transform','')})
    pairs=[]
    byref={x['ref']:x for x in components}
    if board=='STM32H747':
        for a,b in [('R78','R93'),('R79','R92'),('R80','R87'),('R81','R84'),('R82','R83')]:
            pairs.append({'refs':[a,b],'sides':[byref[a]['physicalSide'],byref[b]['physicalSide']],'distinctPhysicalSides':byref[a]['physicalSide']!=byref[b]['physicalSide'],'pads':[byref[a]['pads'],byref[b]['pads']]})
        assert all(x['distinctPhysicalSides'] for x in pairs)
    # Native CPL's coordinate centres are retained. Embedded bottom pad masters
    # are identified independently; raw component layer metadata is insufficient.
    data=json.loads((base/'review-data.json').read_text(encoding='utf8'))
    selected={p['ref']:p for p in data['parts'] if not p['excluded']}
    raw_bytes=(native/(board+'_CPL_20261019.csv')).read_bytes()
    raw_text=raw_bytes.decode('utf-16' if raw_bytes.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    raw=list(csv.DictReader(stringio.StringIO(raw_text),delimiter='\t'))
    assert len(raw)==len(components)
    cpl=[];rotation_review=[]
    for row in raw:
        ref=row['Designator']
        if ref not in selected:continue
        c=byref[ref];angle=float(row['Rotation']);reason='Native package rotation'
        if board=='STM32H747':
            pins={p['pin']:p for p in c['pads']}
            if len(pins)==2 and set(pins)=={'1','2'} and ref.startswith(('R','C','FB','L')):
                p1,p2=pins['1'],pins['2'];angle=math.degrees(math.atan2(p2['y']-p1['y'],p2['x']-p1['x']))%360
                reason='Baked footprint: pin 1-to-2 axis, zero points right; nonpolar passive'
            else:
                # No guessed canonical package rotation for polarized/complex
                # parts: keep raw angle and explicitly require pin-map review.
                rotation_review.append(ref)
                reason='HOLD: baked footprint; package pin-1 rotation requires JLC preview matching'
        cpl.append({'Designator':ref,'Mid X':float(row['Mid X'].removesuffix('mm')),'Mid Y':float(row['Mid Y'].removesuffix('mm')),'Layer':c['physicalSide'],'Rotation':round(angle,4)})
        c['placementRotation']=angle;c['rotationBasis']=reason
    assert len(cpl)==len(selected) and len({r['Designator'] for r in cpl})==len(selected)
    with (base/'CPL_CANDIDATE.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['Designator','Mid X','Mid Y','Layer','Rotation']);w.writeheader();w.writerows(cpl)
    failures=[p for p in pad_checks if not p['centredCopperFlash']]
    report={'board':board,'scope':'Bounded export and pad-side audit; not manufacturing approval','manufacturingApproved':False,'source':str(native/export),'gerberSHA256':hashlib.sha256(zip_path.read_bytes()).hexdigest(),'gerberZipCrc':'PASS','files':members,'copperLayerCount':sum(n in layers for n in COPPER.values()),'expectedCopperLayerCount':n_layers,'padCentreChecks':len(pad_checks),'padCentreFailures':failures,'components':len(components),'assemblyParts':len(cpl),'assemblySideCounts':dict(collections.Counter(r['Layer'] for r in cpl)),'coincidentPairsResolvedByCopperSide':pairs,'drillFileCounts':dict(collections.Counter((d.member,d.kind) for d in drills)) if False else dict(collections.Counter(d.kind for d in drills)),'drillItemsIncludingCombinedViaDuplicates':len(drills),'drillNote':'Via drill member duplicates the same holes in combined PTH; do not sum these as unique physical drills.','rotationReviewRequired':rotation_review,'limitations':['All copper layers present and component pad centre flashes checked. Full polygon electrical equivalence and external DFM review remain required.','CPL candidate retains native centroid; STM32 complex/polarized package angles are NOT normalized and must be matched to the pin map before order.']}
    physical_drills,_,_=dp.read_candidate_zip(zip_path)
    report['physicalDrillCount']=len(physical_drills)
    report['gerberParserCompatibility']='G54Dnn aperture selectors normalized to Dnn in derived parser copies; all object apertures resolved'
    if board=='DAC8562':
        mask=layers['Gerber_TopSolderMaskLayer.GTS'];u3=byref['U3'];openings=[]
        for pad in u3['pads']:
            hits=[o for o in mask['objects'] if o['kind']=='flash' and math.dist(o['atMm'],[pad['x'],pad['y']])<.003]
            assert len(hits)==1
            ap=mask['apertures'][hits[0]['aperture']];assert ap['template']=='RoundRect';v=ap['paramsMm']
            openings.append({'pin':pad['pin'],'xy':hits[0]['atMm'],'openingWidthMm':abs(v[3]-v[1])+v[0],'macroParameters':v})
        assert len(openings)==10
        pitch=min(math.dist(openings[i]['xy'],openings[j]['xy']) for i in range(10) for j in range(i+1,10))
        web=pitch-max(o['openingWidthMm'] for o in openings)
        assert web>=.1
        report['U3Mask']={'allTenOpeningsPresent':True,'minimumWebMm':web,'above010mm':True,'pads':openings}
        (native/'U3-final-mask-cam.json').write_text(json.dumps(report['U3Mask'],indent=2),encoding='utf8')
    (base/'CAM_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (base/'PLACEMENT_AUDIT.json').write_text(json.dumps(components,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['copperLayerCount']==n_layers
    print(board,json.dumps({k:report[k] for k in ['copperLayerCount','padCentreChecks','padCentreFailures','assemblyParts','assemblySideCounts','rotationReviewRequired']})[:1700])
