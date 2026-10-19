"""Extract PCBA review inventories from explicit durable checkpoints; never release CAM."""
from pathlib import Path
import collections, hashlib, importlib.util, json, re, shutil, zipfile

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('native_io', ROOT/'TEST_DAC8562/scripts/correction-io.py')
io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)

CONFIGS = [
    dict(folder='STM32H747 board', name='STM32H747', count=437, layers=6, size=[100,154],
         source='output/jlcpcb-20261019-review/native/STM32H747_before_pcba_20261019.epro2',gerber=None,
         holds=['Baked footprint rotation: complex/polarized components require canonical pin-map matching before CPL approval.',
                'Some new precision resistor specifications have no confirmed exact MPN. Preserve resistance/tolerance/TCR until sourcing is resolved.',
                'Full copper connectivity/clearance CAM, stackup, silkscreen and JLC assembly-preview review are not completed.']),
    dict(folder='TEST_DAC8562', name='DAC8562', count=154, layers=2, size=[100,100],
         source='output/jlcpcb-20261019-review/native/DAC8562_verified_20261019.epro2', gerber=None,
         holds=['Manual procurement and live JLC stock matching remain pending for exact specified parts.',
                'Silkscreen, assembly polarity/orientation and external manufacturing/assembly DFM review remain pending.'])
]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def refkey(r): return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', r)]
def meta(doc):
    return next((b for (t,i),(_,b) in doc.get('records',{}).items() if t=='META'), {})
def flag(v): return str(v).strip().lower() in ('yes','true','1')
def textvalue(v): return '' if v is None else str(v)
def resolved(v, attrs):
    v=textvalue(v)
    for _ in range(4):
        if not (v.startswith('={') and v.endswith('}')): break
        v=textvalue(attrs.get(v[2:-1]))
    return v

summaries=[]
for cfg in CONFIGS:
    base=ROOT/cfg['folder']; out=base/'output/jlcpcb-20261019-review';out.mkdir(exist_ok=True)
    source=base/cfg['source']
    with zipfile.ZipFile(source) as z:
        if z.testzip() is not None: raise ValueError('Corrupt checkpoint')
    docs=io.read_export(source)
    pcb=next(d for d in docs.values() if d['head']['docType']=='PCB')
    pa=io.attrs(pcb); schematics={}
    for d in docs.values():
        if d['head']['docType']!='SCH_PAGE': continue
        a=io.attrs(d)
        for (t,i),(_,body) in d['records'].items():
            if t!='COMPONENT': continue
            x=a.get(i,{})
            if x.get('Designator'): schematics.setdefault(x['Designator'],{}).update(x)
    parts=[]
    for (t,i),(_,body) in pcb['records'].items():
        if t!='COMPONENT': continue
        inst=pa.get(i,{}); ref=inst.get('Designator')
        if not ref: raise ValueError('Missing component ref')
        dev=docs.get(inst.get('Device'),{})
        attrs={**meta(dev).get('attributes',{}),**schematics.get(ref,{}),**body.get('attrs',{}),**inst}
        fp=docs.get(inst.get('Footprint'),{})
        fpname=meta(fp).get('title') or io.attrs(fp).get('',{}).get('Footprint') or ''
        value=resolved(attrs.get('Value') or attrs.get('Name'),attrs)
        package=attrs.get('Package') or attrs.get('Supplier Footprint') or fpname
        custom_package=re.search(r'_ADC_DC_[CR](0402|0603|0805)$', textvalue(package))
        if custom_package: package=custom_package[1]
        mpn=attrs.get('Manufacturer Part') or attrs.get('Part Number') or ''
        supplier_part=textvalue(attrs.get('Supplier Part'))
        lcsc=supplier_part if re.fullmatch(r'C\d+',supplier_part) and attrs.get('Supplier','').upper()=='LCSC' else ''
        is_dnp=flag(attrs.get('DNP'))
        # These 19 test points are bare PCB pads, not purchased test-point terminals.
        bare_tp=bool(re.fullmatch(r'TP\d+',ref) and value.lower()=='testpoint' and not mpn)
        excluded=is_dnp or str(attrs.get('Add into BOM','yes')).lower()=='no' or bare_tp
        pads=[b for (tt,ii),(_,b) in fp.get('records',{}).items() if tt=='PAD']
        notes=[]
        if not mpn and not excluded: notes.append('Exact MPN not specified')
        if not lcsc and not excluded: notes.append('JLCPCB/LCSC part match not confirmed')
        pad_layers={p['layerId'] for p in pads if p['layerId'] in (1,2)}
        if body.get('layerId')==2: pad_layers={3-v for v in pad_layers}
        physical_side='Bottom' if pad_layers=={2} else 'Top' if pad_layers else ('Top' if body.get('layerId')==1 else 'Bottom')
        if cfg['name']=='STM32H747' and ref in {'R78','R93','R79','R92','R80','R87','R81','R84','R82','R83'}: notes.append('Same XY as opposite-side resistor; actual pad-layer CAM audited')
        if body.get('layerId') not in (1,2): notes.append('Unsupported placement side')
        parts.append(dict(ref=ref,value=value,mpn=textvalue(mpn),manufacturer=textvalue(attrs.get('Manufacturer')),
            package=textvalue(package),lcsc=lcsc,supplier=textvalue(attrs.get('Supplier')),description=textvalue(attrs.get('Description')),
            tolerance=textvalue(attrs.get('Tolerance')),voltage=textvalue(attrs.get('Voltage Rating')),tcr=textvalue(attrs.get('Temperature Coefficient')),
            x_mm=round(body['x']*.0254,6),y_mm=round(body['y']*.0254,6),source_angle=body.get('angle',0),
            layer=physical_side,component_id=i,footprint_uuid=inst.get('Footprint'),
            device_uuid=inst.get('Device'),footprint_name=fpname,dnp=is_dnp,bare_test_point=bare_tp,excluded=excluded,
            exclusion_reason='DNP' if is_dnp else 'Bare PCB test pad' if bare_tp else 'Add into BOM=no' if excluded else '',
            source_pad_count=len(pads),notes='; '.join(notes)))
    parts.sort(key=lambda p:refkey(p['ref']))
    assert len(parts)==cfg['count'] and len({p['ref'] for p in parts})==len(parts)
    fitted=[p for p in parts if not p['excluded']]
    grouped=collections.defaultdict(list)
    for p in fitted:
        key=tuple(p[k] for k in ['value','package','mpn','manufacturer','lcsc','tolerance','voltage','tcr'])
        grouped[key].append(p)
    bom=[]
    for key,ps in grouped.items():
        v,pkg,mpn,mfr,lcsc,tol,volt,tcr=key
        bom.append({'Comment':' '.join(x for x in [v,tol,volt,tcr] if x),'Designator':','.join(p['ref'] for p in ps),
                    'Footprint':pkg,'Quantity':len(ps),'Manufacturer Part':mpn,'Manufacturer':mfr,'LCSC Part #':lcsc,
                    'Review status':'Part matching / stock / package not approved'})
    assert sum(p['Quantity'] for p in bom)==len(fitted)
    positions=collections.defaultdict(list)
    for p in fitted: positions[(p['layer'],p['x_mm'],p['y_mm'])].append(p['ref'])
    overlaps=[dict(layer=k[0],x_mm=k[1],y_mm=k[2],refs=v) for k,v in positions.items() if len(v)>1]
    assert not overlaps,overlaps
    summary=dict(board=cfg['name'],date='2026-10-19',manufacturingApproved=False,
                 source=cfg['folder']+'/'+cfg['source'],sourceSHA256=sha(source),checkpointIntegrity='ZIP CRC passed',
                 sourcePcbUuid=pcb['head']['uuid'],sourceEditVersion=pcb['head'].get('editVersion'),
                 physicalParts=len(parts),assemblyParts=len(fitted),excluded=len(parts)-len(fitted),bomGroups=len(bom),
                 noExactMpn=sum(not p['mpn'] for p in fitted),noLcscMatch=sum(not p['lcsc'] for p in fitted),
                 coincidentOrigins=overlaps,layers=cfg['layers'],sizeMm=cfg['size'],
                 holds=cfg['holds'],nativeExportAttempt='Exported successfully with EasyEDA 3.2.206 and approved API interaction enabled',
                 placementQualification='CPL_CANDIDATE.csv uses native centroids and physical pad-side correction. STM32 complex package rotation remains on hold. JLC preview/pin-1 review is required.',
                 stockQualification='No live stock reservation, supplier match approval, quote or order. No substitute MPN invented.',
                 gerber='Fresh native export: native/'+cfg['name']+'_CAM_20261019.zip; bounded CAM_AUDIT.json is not external DFM approval')
    if cfg['name']=='DAC8562':
        summary['placementQualification']='CPL_CANDIDATE.csv uses native centroids and package rotations; all 154 parts are Top. Final polarity and JLC placement-preview approval remain pending.'
    if cfg['gerber']:
        gp=base/cfg['gerber']; dest=out/'reference-only';dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(gp) as z:
            assert z.testzip() is None
            members=z.namelist()
        shutil.copy2(gp,dest/gp.name)
        summary['referenceGerber']=dict(path=cfg['gerber'],sha256=sha(gp),members=len(members),manufacturingApproved=False)
    data=dict(summary=summary,parts=parts,bom=bom,
              sourceCoordinates=[{'Designator':p['ref'],'Source X (mm)':p['x_mm'],'Source Y (mm)':p['y_mm'],'Layer':p['layer'],'Source angle (deg)':p['source_angle'],'Qualification':'Not native centroid CPL'} for p in fitted])
    (out/'review-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'ORDER_HOLD.txt').write_text('NOT FOR ORDER / 주문 보류\n\n'+'\n'.join(summary['holds'])+'\n\n'+summary['placementQualification']+'\n',encoding='utf8')
    summaries.append(summary)
    print(json.dumps({k:summary[k] for k in ['board','physicalParts','assemblyParts','excluded','bomGroups','noExactMpn','noLcscMatch']},ensure_ascii=True))
out=ROOT/'output/jlcpcb-order-20261019';out.mkdir(parents=True,exist_ok=True)
(out/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf8')
