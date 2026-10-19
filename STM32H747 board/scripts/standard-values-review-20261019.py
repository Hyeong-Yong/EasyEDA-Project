"""Review standard resistor choices and build an identity-preserving metadata plan."""
from pathlib import Path
import cmath,collections,hashlib,itertools,json,math,re,zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/standard-values-20261019'
def docs(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        src=z.read(next(n for n in z.namelist() if n.endswith('.epru'))).decode()
    result={};current=None;client=''
    for line in src.splitlines():
        if '||' not in line:continue
        h,b=line.split('||',1);h=json.loads(h);b=json.loads(b.removesuffix('|')) if b.removesuffix('|') else ''
        if h['type']=='DOCHEAD':
            current=result.setdefault(b['uuid'],{'head':b,'records':{}});current['head']=b;client=b.get('client','');continue
        key=(h['type'],h.get('id',''));old=current['records'].get(key);rank=(h.get('ticket',0),client)
        if old is None or rank[0]>old[0].get('ticket',0) or (rank[0]==old[0].get('ticket',0) and client<=old[2]):current['records'][key]=(h,b,client)
    for d in result.values():d['records']={k:(h,b) for k,(h,b,c) in d['records'].items() if isinstance(b,dict)}
    return result
def attributes(doc):
    r=collections.defaultdict(dict)
    for (kind,rid),(_,b) in doc['records'].items():
        if kind=='ATTR':r[b['parentId']][b['key']]=b.get('value')
    return r
def stock():
    rows=[]
    for code in ['C852810','C2692906','C2103244','C44198','C2693067','C2692924']:
        path=OUT/(code+'-page.html');t=path.read_text(encoding='utf8')
        p=next(json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',t) if json.loads(x).get('@type')=='Product')
        assert p['sku']==code and p['offers']['inventoryLevel']>0
        rows.append({'lcsc':code,'mpn':p['mpn'],'manufacturer':p['brand']['name'],'description':p['description'],'stockAtCheck':p['offers']['inventoryLevel'],'url':'https://www.lcsc.com/product-detail/'+code+'.html','pageSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'reserved':False,'catalogSpecifications':{x['name']:x['value'] for x in p.get('additionalProperty',[])},'manufacturerDatasheetURL':p.get('subjectOf',{}).get('url')})
    (OUT/'selected-stock-evidence.json').write_text(json.dumps({'checkedDate':'2026-10-19','source':'Anonymous live LCSC public product pages, JSON-LD Product/Offer; unreserved','parts':rows},ensure_ascii=False,indent=2),encoding='utf8')
    return {x['lcsc']:x for x in rows}
def model(ri,rf,rt,rb,vin=0):
    gain=rf/ri;offset=2.5*rb/(rt+rb)
    return (1+gain)*offset-gain*vin
def h(f,ri,rf):
    s=2j*math.pi*f;rsource=50*100000/(50+100000)
    return -(100000/(100000+50))*rf/ri/((1+s*(3320+rsource)*10e-9)*(1+s*rf*10e-9)*(1+s*47*10e-9))
def bandwidth(ri,rf):
    lo,hi=1,1e5;target=abs(h(0,ri,rf))/math.sqrt(2)
    for _ in range(80):
        mid=(lo+hi)/2
        if abs(h(mid,ri,rf))>target:lo=mid
        else:hi=mid
    return (lo+hi)/2
def review():
    old=(4000,2800,15800,10000);new=(4020,2800,14700,9310)
    models=[]
    for name,v in [('before',old),('standardValues',new)]:
        g=v[1]/v[0];rt,rb=v[2:];div=2.5*rb/(rt+rb)
        corners={str(vin):[model(*(v[i]*(1+e[i]*.001) for i in range(4)),vin=vin) for e in itertools.product([-1,1],repeat=4)] for vin in [-2,0,2]}
        row={'name':name,'inputResistorOhm':v[0],'feedbackResistorOhm':v[1],'dividerTopOhm':rt,'dividerBottomOhm':rb,'dcSignalGainAtSma':-g,'zeroInputOutputV':model(*v),'dividerBusV':div,'outputsAtSmaInputV':{str(x):model(*v,vin=x) for x in [-2,0,2]},'sourceGeneratorToAdcGain60Hz':abs(h(60,v[0],v[1])),'normalized3dBBandwidthHz':bandwidth(v[0],v[1]),'dividerFilterPoleHz':1/(2*math.pi*(rt*rb/(rt+rb))*4.7e-6),'resistorOnlyCornersV':{k:{'min':min(a),'max':max(a)} for k,a in corners.items()},'dividerDissipationW':{'top':(2.5/(rt+rb))**2*rt,'bottom':div**2/rb},'dividerWorstCaseTcrOutputVPerK':(1+g)*2.5*(rt*rb/(rt+rb)**2)*20e-6}
        models.append(row)
    a,b=models
    signal_pmax=max((vin-b['dividerBusV'])**2/4020 for vin in [-2,2])
    report={'scope':'Analytical resistor-value comparison with ideal amplifiers and fixed nominal capacitors; not hardware noise/startup certification','before':a,'after':b,'delta':{'dcGainRelativePercent':(abs(b['dcSignalGainAtSma']/a['dcSignalGainAtSma'])-1)*100,'zeroInputOutputMv':(b['zeroInputOutputV']-a['zeroInputOutputV'])*1000,'maximumNominalOutputChangeOverPlusMinus2VMv':max(abs(model(*new,vin=x)-model(*old,vin=x))*1000 for x in [-2,2]),'bandwidthRelativePercent':(b['normalized3dBBandwidthHz']/a['normalized3dBBandwidthHz']-1)*100},'checks':{'signalGainChangeWithinHalfPercent':abs(b['dcSignalGainAtSma']/a['dcSignalGainAtSma']-1)<=.005,'zeroShiftBelow3mV':abs(b['zeroInputOutputV']-a['zeroInputOutputV'])<.003,'bandwidthUnchanged':b['normalized3dBBandwidthHz']==a['normalized3dBBandwidthHz'],'resistorCornersWithinAdcRange':all(0<z['min']<=z['max']<3.3 for z in b['resistorOnlyCornersV'].values()),'same0402PadsAndTopology':True},'powerAndTcr':{'inputResistorMaxSteadyPowerW':signal_pmax,'inputResistorRatingW':.0625,'feedbackResistorMaxSteadyPowerW':(2800/4020)**2*max((vin-b['dividerBusV'])**2 for vin in [-2,2])/2800,'supplyFilterResistanceOhm':4.7,'supplyFilterRatingW':.2,'supplyFilterPowerAt60mAW':.06**2*4.7,'supplyFilterTcrPpmK':100,'supplyFilterTcrRationale':'Supply RC does not set signal gain. At 60mA and a 65K change, TCR-only drop change is 1.833mV; startup pulses still require bench verification.','referenceEsrResistorOhm':1.2,'referenceEsrTcrPpmK':400,'referenceEsrTolerance':.01,'referenceEsrResistorRangeMinus40To85C':[1.2*.99*(1-65*400e-6),1.2*1.01*(1+65*400e-6)],'referenceEsrRationale':'TI REF50xxAI recommends total output-capacitor ESR 1 to 1.5 ohm for minimum noise. 1.2 ohm allows MLCC ESR margin; actual assembled transient stability remains a bench check.'},'limitations':['Reference initial error/drift, amplifier offset/noise/GBW, resistor excess noise, capacitor tolerance/DC bias, ADC loading and conversion error are not included in resistor-only corners.','No firmware changed. Existing calibration, if present, must use the new stated slope/intercept.','SMA open input and zero-volt input still produce the nonzero output intercept; no disconnect detector was added.','50-ohm generator loading is included only in generator-to-ADC AC gain; VIN in the DC formula is actual SMA voltage.','Full PCBA rotation/stock reservation and external manufacturing DFM remain separate.'],'sources':[{'title':'REF50xx Rev O','url':'https://www.ti.com/lit/ds/symlink/ref50.pdf','section':'8.5 and 9.4.1.1, ESR 1 to 1.5 ohm recommended'},{'title':'Vishay RCS e3 Rev 2025-06-11','url':'https://www.vishay.com/docs/20065/rcse3.pdf','section':'0402 0.2W, 1% / 100ppm, anti-surge'},{'title':'RESI PTFR family datasheet','url':'https://atta.szlcsc.com/upload/public/pdf/source/20231218/EBECA0901342DCBDB0ABFC8C8F9AFCF5.pdf','section':'0402, B 0.1%, N 10ppm, P 25ppm'}]}
    assert all(report['checks'].values())
    (OUT/'circuit-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return report
def build_plan():
    if (OUT/'standard-resistors-plan.json').exists():raise RuntimeError('Historical plan already exists; use final specs and receipts, never overwrite it')
    d=docs(OUT/'STM32H747_before_standard_values_20261019.epro2');pcb=d['0ac2a19168000d8e'];a=attributes(pcb)
    stockrows=stock();specs=[]
    groups=[([137,138,139,149,150,151,161,162,163,164],'4.00k','4.02k','C852810','0.1%','25 ppm/K','0.0625 W','Thin-film gain input resistor; E96 standard value'),(list(range(187,197)),'2.80k','2.80k','C2692906','0.1%','25 ppm/K','0.06 W','Thin-film gain feedback resistor; nominal unchanged'),([197,200],'4.7','4.7','C2103244','1%','100 ppm/K','0.2 W','Anti-surge supply RC resistor; TCR reviewed independently of gain'),([201],'1.0','1.20','C44198','1%','400 ppm/K','0.0625 W','REF5025 output capacitor series ESR resistor; 1.2 ohm selected for recommended ESR margin'),([202],'15.8k','14.7k','C2693067','0.1%','10 ppm/K','0.06 W','Precision offset divider top, E96'),([203],'10.0k','9.31k','C2692924','0.1%','10 ppm/K','0.06 W','Precision offset divider bottom, E96')]
    for nums,old,new,lcsc,tol,tcr,power,desc in groups:
        m=stockrows[lcsc]
        for n in nums:specs.append({'ref':'R'+str(n),'oldValue':old,'value':new,'mpn':m['mpn'],'lcsc':lcsc,'manufacturer':m['manufacturer'],'Tolerance':tol,'Temperature Coefficient':tcr,'Power Rating':power,'Description':desc+'; '+new+' '+tol+' '+tcr+'; 0402','Datasheet':'https://www.lcsc.com/product-detail/'+lcsc+'.html','Package':'0402'})
    pages={};target_map={x['ref']:x for x in specs}
    for uid,doc in d.items():
        if doc['head']['docType']!='SCH_PAGE':continue
        aa=attributes(doc);targets=[]
        for (k,cid),(_,body) in doc['records'].items():
            if k=='COMPONENT' and aa.get(cid,{}).get('Designator') in target_map:
                ref=aa[cid]['Designator'];sp=target_map[ref];assert aa[cid]['Value']==sp['oldValue'],(ref,aa[cid].get('Value'))
                targets.append({'ref':ref,'componentId':cid,'beforeAttrs':aa[cid],'spec':sp,'geometry':{k:body[k] for k in ['x','y','rotation','isMirror','partId']}})
        if targets:
            texts=[{'id':i,'value':v.get('value')} for (k,i),(_,v) in doc['records'].items() if k=='TEXT']
            pages[uid]={'targets':targets,'textsForReview':texts}
    pcb_targets=[]
    for (k,cid),(_,body) in pcb['records'].items():
        if k=='COMPONENT' and a.get(cid,{}).get('Designator') in target_map:
            ref=a[cid]['Designator'];pcb_targets.append({'ref':ref,'componentId':cid,'beforeAttrs':{**body.get('attrs',{}),**a[cid]},'spec':target_map[ref],'geometry':{k:body[k] for k in ['x','y','angle','layerId']}})
    assert sum(len(x['targets']) for x in pages.values())==len(pcb_targets)==25
    annotation_targets=[('75eae3802c16c27e','10 inputs: SMA ground referenced; DC preserved; open input returns near GND, ADC near 1.645V.'),('bec27b41e3795d57','Nominal VADC = 1.6445832 - 0.6965174 x VIN (50-ohm loading ~0.05%); calibrate gain/offset and sign.')]
    pages['a07bf8e4331877a8']['textEdits']=[{'id':i,'before':next(t['value'] for t in pages['a07bf8e4331877a8']['textsForReview'] if t['id']==i),'after':v} for i,v in annotation_targets]
    plan={'schema':'standard-resistors-20261019-v1','projectName':'STM32H747_MCU_BOARD_v19','projectUuid':'4d4671fe9a78f6b1578521c2dc6be53db20dc0cc6cb10fdfc81febaa87f5af94','pcbUuid':'0ac2a19168000d8e','baselineSHA256':hashlib.sha256((OUT/'STM32H747_before_standard_values_20261019.epro2').read_bytes()).hexdigest(),'pages':pages,'pcbTargets':pcb_targets,'specs':specs,'netGeometryChangesAllowed':False,'sourceDocumentCount':len(d)}
    (OUT/'standard-resistors-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'targets':25,'pages':{k:len(v['targets']) for k,v in pages.items()},'documentCount':len(d),'circuitReview':review()['delta']}))
if __name__=='__main__':
    import sys
    if '--create-plan' in sys.argv:build_plan()
    else:print(json.dumps(review()['delta']))
