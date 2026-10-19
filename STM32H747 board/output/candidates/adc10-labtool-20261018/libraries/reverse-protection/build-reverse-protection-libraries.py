"""New-only Schottky mini library, offline; writes only this directory."""
import copy
import argparse
import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
CHECK=ROOT/'output/checkpoints/STM32H747_labtool_libraries_20261018.epro2'
PREFIX='STM_H747_ADC_LABTOOL_DIODE_20261018_'
PDF=HERE/'Vishay-BAT54WS-86465.pdf'
URL='https://www.vishay.com/docs/86465/bat54ws.pdf'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def uid(kind,label):return hashlib.sha256(('stm32h747-adc-labtool-reverse-diode-20261018\0'+kind+'\0'+label).encode()).hexdigest()[:16]


def runtime_map(after_path,before_path=None):
    spec=importlib.util.spec_from_file_location('reverse_runtime_reader',ROOT/'scripts/build-adc10-labtool-libraries-20261018.py')
    r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    before_path=before_path or CHECK
    before,after=r.read_snapshot(before_path),r.read_snapshot(after_path)
    manifest=json.loads((HERE/'reverse-protection-library-manifest.json').read_text(encoding='utf8'))
    new=set(after)-set(before)
    output={'schema':'adc10-labtool-reverse-protection-runtime-map-20261018-v1','devices':{},'symbols':{},'footprints':{},
            'checkpoint':str(Path(after_path).resolve()),'checkpointSha256':sha(after_path)}
    mapping={};matched=set()
    for group,kind in [('symbols','SYMBOL'),('footprints','FOOTPRINT'),('devices','DEVICE')]:
        for key,old in manifest[group].items():
            matches=[]
            for identity in new:
                if identity[0]!=kind:continue
                meta=next((b for h,b in after[identity].values() if h['type']=='META'),{})
                if str(meta.get('source','')).split('|')[0]==old['uuid'] or meta.get('title')==old['title']:
                    matches.append((identity,meta))
            assert len(matches)==1,(key,[x[0] for x in matches])
            identity,meta=matches[0]
            info=copy.deepcopy(old);info.update(uuid=identity[1],oldUuid=old['uuid'],source=meta.get('source',''),runtimeMeta=meta)
            output[group][key]=info;mapping[old['uuid']]=identity[1];matched.add(identity)
    for d in output['devices'].values():
        for field,attr in [('symbolUuid','Symbol'),('footprintUuid','Footprint')]:
            d[field]=mapping[d[field]];d['attributes'][attr]=d[field]
            assert d['runtimeMeta']['attributes'][attr]==d[field]
    changes=[]
    ignored={'DOCHEAD','CANVAS','ACTIVE_LAYER'}
    for identity,rows in before.items():
        other=after.get(identity,{})
        for key in rows.keys()|other.keys():
            if key[0] not in ignored and rows.get(key,(None,None))[1]!=other.get(key,(None,None))[1]:changes.append({'doc':identity,'record':key})
    passed=not changes and new==matched and len(new)==3
    output.update(uuidMap=mapping,newDocumentCount=len(new),importPreservationPassed=passed)
    audit={'passed':passed,'beforeCheckpoint':str(before_path),'beforeSha256':sha(before_path),'afterCheckpoint':str(Path(after_path).resolve()),
        'afterSha256':sha(after_path),'existingDocuments':len(before),'newDocuments':sorted(new),'existingNonViewChanges':changes,
        'excludedViewTypes':sorted(ignored),'newOnly':True,'nativeApiCalled':False}
    (HERE/'independent-runtime-map.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (HERE/'independent-import-preservation-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':passed,'newDocuments':len(new),'protectedExistingChanges':len(changes),'map':str(HERE/'independent-runtime-map.json')},indent=2))
    assert passed


def main():
    spec=importlib.util.spec_from_file_location('reverse_diode_serializer',ROOT/'scripts/build-adc-dc-libraries.py')
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.PREFIX,m.STAMP,m.uid=PREFIX,1792281600000,uid
    spec2=importlib.util.spec_from_file_location('labtool_snapshot_reader',ROOT/'scripts/build-adc10-labtool-libraries-20261018.py')
    r=importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(r)
    base=r.read_snapshot(CHECK)
    before_sha=sha(CHECK)
    sym=m.Doc('SYMBOL','SCHOTTKY',PREFIX+'SCHOTTKY_K1_A2')
    sym.add('META',{'title':sym.title,'source':sym.uuid+'|project','docType':2,'tags':['ADC_LABTOOL_REVERSE_PROTECTION_20261018'],
        'description':'Single Schottky diode: physical pin1 cathode, pin2 anode'},'META')
    sym.add('CANVAS',{'originX':0,'originY':0},'CANVAS')
    sym.add('PART',{'title':'A'},'A')
    m.poly(sym,[(10,-10),(10,10),(-10,0)],True,'#FFFFC2')
    m.poly(sym,[(-6,-6),(-6,-10),(-10,-10),(-10,10),(-14,10),(-14,6)],False)
    pins=[m.pin(sym,'1','K',-25,0,15,0,'Passive',show_name=False),m.pin(sym,'2','A',25,0,15,180,'Passive',show_name=False)]
    m.attr(sym,'','Designator','D?',-15,-22,True)
    m.attr(sym,'','Value','BAT54WS',-15,20,True)
    sinfo={'uuid':sym.uuid,'title':sym.title,'partId':'A','pins':pins,'coordinateUnit':'0.01inch, symbol Y-down'}
    template,_=m.sot_footprint('LAYER_TEMPLATE','LAYER_TEMPLATE','DBV5')
    foot=m.Doc('FOOTPRINT','SOD323',PREFIX+'VISHAY_SOD323_K1_A2')
    foot.add('META',{'title':foot.title,'source':foot.uuid+'|project','tags':['ADC_LABTOOL_REVERSE_PROTECTION_20261018'],
        'description':'Vishay86465 Rev1.1 p4 recommended SOD323 land; assembler approval pending'},'META')
    for h,b in template.records:
        if h['type'] in {'CANVAS','ACTIVE_LAYER','LAYER'}:foot.add(h['type'],copy.deepcopy(b),h['id'])
    cv=lambda x:round(x/.0254,6)
    pad_template=next(copy.deepcopy(b) for h,b in template.records if h['type']=='PAD')
    pads=[]
    for number,x in [('1',-1.2),('2',1.2)]:
        b=copy.deepcopy(pad_template)
        b.update(num=number,centerX=cv(x),centerY=0,zIndex=int(number),
                 defaultPad={'padType':'RECT','width':cv(.8),'height':cv(.6),'radius':0})
        foot.add('PAD',b,uid('SOD323','pad/'+number))
        pads.append({'number':number,'name':'K' if number=='1' else 'A','centerMm':[x,0],
                     'copperSizeMm':[.8,.6],'nativeBody':b})
    for layer,hx,hy,width in [(9,.975,.75,.1),(48,1.85,1.0,.05)]:
        xy=[(-hx,-hy),(hx,-hy),(hx,hy),(-hx,hy)]
        for a,b in zip(xy,xy[1:]+xy[:1]):
            foot.add('LINE',{'groupId':0,'netName':'','layerId':layer,'startX':cv(a[0]),'startY':cv(a[1]),
                'endX':cv(b[0]),'endY':cv(b[1]),'lineWidth':cv(width),'locked':False,'zIndex':len(foot.records)})
    foot.add('LINE',{'groupId':0,'netName':'','layerId':3,'startX':cv(-.55),'startY':cv(-.45),
        'endX':cv(-.55),'endY':cv(.45),'lineWidth':cv(.12),'locked':False,'zIndex':len(foot.records)})
    finfo={'uuid':foot.uuid,'title':foot.title,'pads':pads,'bodyMaximumSizeMm':[1.95,1.5],
        'courtyardMm':[3.7,2.0],'coordinateUnit':'mil, positive Y-up, top view; cathode band left',
        'drawing':'Vishay S8-V-3910.02-001(4) Rev6 2016-09-23, BAT54WS86465 PDF p4',
        'landPatternInnerGapMm':1.6,'landPatternOuterSpanMm':3.2,'manufacturingApproved':False}
    device,dinfo=m.device('BAT54WS','VISHAY_BAT54WS_E3_08',sinfo,finfo,'BAT54WS','D?',
        {'Manufacturer':'Vishay Semiconductors','Part Number':'BAT54WS-E3-08','Datasheet':URL,
         'Description':'30V single Schottky; TPS723 negative-LDO reverse-current bypass; A2=raw IN, K1=regulated OUT',
         'Voltage Rating':'30 V','Forward Continuous Current':'200 mA','Datasheet Revision':'86465 Rev1.1 2025-05-12'})
    next(b for h,b in device.records if h['type']=='META')['tags']=['STM32H747_MCU_BOARD_v19','ADC_LABTOOL_REVERSE_PROTECTION_20261018']
    docs=[sym,foot,device]
    old_ids={str(h.get('id','')) for rows in base.values() for h,b in rows.values() if re.fullmatch('[0-9a-f]{16}',str(h.get('id','')))}
    new_ids=[h['id'] for d in docs for h,b in d.records if re.fullmatch('[0-9a-f]{16}',str(h.get('id','')))]
    assert not set(new_ids)&old_ids and len(new_ids)==len(set(new_ids))
    assert len({d.uuid for d in docs})==3 and not {d.uuid for d in docs}&{k[1] for k in base}
    assert {p['number'] for p in pins}=={p['number'] for p in pads}=={'1','2'}
    source=''.join(d.source() for d in docs)
    source_path=HERE/'reverse-protection-new-libraries-20261018.epru'
    source_path.write_text(source,encoding='utf8',newline='\n')
    for d in docs:
        ext={'SYMBOL':'esym','FOOTPRINT':'efoo','DEVICE':'edevice'}[d.kind]
        (HERE/f'{d.label}_{d.uuid}.{ext}').write_text(d.source(),encoding='utf8',newline='\n')
    package=HERE/'STM32H747_labtool_reverse_protection_new_libraries_20261018.epro2'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        payloads={'project2.json':json.dumps({'title':'STM32H747_MCU_BOARD_v19','cbb_project':False,'editorVersion':'3.2.206','description':'Only3 new Schottky library documents','tags':'[]'}),
                  'STM32H747_MCU_BOARD_v19.epru':source}
        for name,data in payloads.items():
            zi=zipfile.ZipInfo(name,date_time=(2026,10,18,0,0,0));zi.compress_type=zipfile.ZIP_DEFLATED;z.writestr(zi,data)
    manifest={'schema':'adc10-labtool-reverse-protection-new-libraries-20261018-v1','newOnly':True,
        'counts':{'SYMBOL':1,'FOOTPRINT':1,'DEVICE':1},'symbols':{'SCHOTTKY':sinfo},'footprints':{'SOD323':finfo},'devices':{'BAT54WS':dinfo},
        'packagePath':str(package),'packageSha256':sha(package),'sourcePath':str(source_path),'sourceSha256':sha(source_path),
        'checkpointPath':str(CHECK),'checkpointSha256':before_sha,'sourcePdfPath':str(PDF),'sourcePdfSha256':sha(PDF),'sourceUrl':URL,
        'datasheetPinPage':1,'datasheetLandPage':4,'pinAndLandPagesVisuallyInspected':True,
        'polarityContract':{'1':'K: -3V_AFE / TPS723 OUT','2':'A: AFE_VNEG_RAW / TPS723 IN'},
        'validation':{'allDocumentAndHexPrimitiveUuidsNewNoCollision':True,'allSymbolPinPadNumbersMatch':True,'nativeImportPending':True},
        'nativeApiCalled':False,'existingLibrariesModified':False,'manufacturingApproved':False,
        'notes':['Manufacturer is explicitly Vishay BAT54WS-E3-08, not an unverified onsemi variant; onsemi and Nexperia PDF requests returned403.',
                 'SOD323 land pads0.8x0.6mm, inner gap1.6mm, centres+-1.2mm; arbitrary footprint orientation puts cathode/band at left.',
                 'Solder-mask expansion0.07mm is inherited project practice, not an independent assembly approval.',
                 'Protection path magnitude/power-down waveforms still require hardware validation.']}
    (HERE/'reverse-protection-library-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    assert sha(CHECK)==before_sha
    print(json.dumps({'package':str(package),'sha256':manifest['packageSha256'],'manifest':str(HERE/'reverse-protection-library-manifest.json'),'newDocs':3},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-checkpoint',type=Path);parser.add_argument('--runtime-before-checkpoint',type=Path);args=parser.parse_args()
    runtime_map(args.runtime_checkpoint,args.runtime_before_checkpoint) if args.runtime_checkpoint else main()
