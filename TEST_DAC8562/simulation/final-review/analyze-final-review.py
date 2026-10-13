"""Assess every successfully solved deck; keep numerical failures explicit."""
import json,sys,math,itertools
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]/'.tools/pcb-python'))
import numpy as np
manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
rows=[]
for j in manifest['jobs']:
    row=dict(j)
    if not j['solverPassed']:rows.append(row);continue
    a=np.loadtxt(root/'results'/(j['name']+'.dat'),skiprows=1,ndmin=2)
    assert np.isfinite(a).all(),j['name']
    if j['test']=='loop':
        margins=[]
        for i in range(1,len(a)):
            if a[i-1,1]>0>=a[i,1]:
                f=-a[i-1,1]/(a[i,1]-a[i-1,1]);margins.append(180+a[i-1,2]+f*(a[i,2]-a[i-1,2]))
        row['phaseMarginsDeg']=[float(x) for x in margins];row['screenPassed']=bool(margins) and min(margins)>45
    elif j['test']=='ac':
        row['peakingDb']=float(max(a[:,1])-a[0,1]);row['lowFrequencyGain']=float(10**(a[0,1]/20));expected=100000/(14000 if j['family']=='MCU' else 24300)
        row['screenPassed']=row['peakingDb']<1 and abs(row['lowFrequencyGain']/expected-1)<.01
    elif j['test']=='tran':
        t,v=a[:,0],a[:,2];before=float(np.mean(v[(t>45e-6)&(t<49e-6)]));target=float(np.mean(v[(t>220e-6)&(t<240e-6)]));amp=target-before;sel=(t>=50.02e-6)&(t<249.99e-6);tt,vv=t[sel],v[sel];bad=np.where(abs(vv-target)>.01*abs(amp))[0]
        row['settling1PercentUs']=None if len(bad) and bad[-1]>=len(tt)-2 else float((tt[bad[-1]+1] if len(bad) else tt[0])-50.02e-6)*1e6
        row['overshootPercent']=float((max(vv)-target)/amp*100);row['lateRippleVpp']=float(np.ptp(v[(t>200e-6)&(t<240e-6)]));row['baselineOutputV']=before;row['targetOutputV']=target
        row['screenPassed']=row['settling1PercentUs'] is not None and row['settling1PercentUs']<100 and row['overshootPercent']<20
    elif j['test']=='range':
        t,v=a[:,0],a[:,2];row['negativePlateauV']=float(np.mean(v[(t>300e-6)&(t<340e-6)]));row['positivePlateauV']=float(np.mean(v[(t>700e-6)&(t<740e-6)]));row['peakOutputV']=float(max(abs(v)));row['maxOutputCurrentA']=float(max(abs(a[:,3]-a[:,2]))/100)
        target=10 if j['family']=='MCU' else 100000/24300*2.5
        row['screenPassed']=abs(row['negativePlateauV']+target)<.02 and abs(row['positivePlateauV']-target)<.02 and row['peakOutputV']<11
    if 'screenPassed' in row:row['screenPassed']=bool(row['screenPassed'])
    rows.append(row)
families={}
for family in ['DAC8562','MCU']:
    rr=[r for r in rows if r['family']==family]
    families[family]={'cases':len(rr),'solverFailures':[r['name'] for r in rr if not r['solverPassed']],'screenFailures':[r['name'] for r in rr if not r.get('screenPassed')],'minimumPhaseMarginDeg':min(x for r in rr for x in r.get('phaseMarginsDeg',[])),'maxPeakingDb':max(r.get('peakingDb',0) for r in rr),'maxSettling1PercentUs':max(r['settling1PercentUs'] if r['settling1PercentUs'] is not None else 1e99 for r in rr if r['test']=='tran'),'maxOvershootPercent':max(r.get('overshootPercent',0) for r in rr)}
def transfer(v,ref,ri,rg,rr,rf):return (1+rf/rr)*v*rg/(ri+rg)-ref*rf/rr
resistor_corners={}
for family,ri,reference,inputs in [('DAC8562',24300,2.5,[0,2.5,5]),('MCU',14000,1.65,[.25,1.65,3.05])]:
    errors=[]
    for signs in itertools.product([-1,1],repeat=4):
        values=[base*(1+s*.0005) for base,s in zip([ri,100000,ri,100000],signs)]
        for v in inputs:errors.append(transfer(v,reference,*values)-100000/ri*(v-reference))
    resistor_corners[family]={'resistorOnlyWorstUncalibratedErrorV':max(abs(x) for x in errors),'corners':16,'resistorsTolerance':.0005,'excludes':'DAC offset/gain/INL, reference and divider, op-amp errors, temperature, contact/cable/PCB parasitics'}
thresholds={}
for name,lo,hi in [('positive12',274000,312000),('avdd',116000,127000),('negativeMagnitude',260000,320000)]:
    thresholds[name]={}
    for label,rt in [('lower',lo),('upper',hi)]:
        corners=[.4*(1+c*.01)*(1+rt*(1+a*.001)/(10000*(1+b*.001))) for a,b,c in itertools.product([-1,1],repeat=3)]
        thresholds[name][label]={'nominal':.4*(1+rt/10000),'minimum':min(corners),'maximum':max(corners)}
truth=[{'pgood':pg,'enable':en,'relayCommand':pg&en} for pg,en in itertools.product([0,1],repeat=2)]
result={'passed':all(r.get('screenPassed',False) for r in rows),'caseCount':len(rows),'families':families,'rows':rows,'resistorCorners':resistor_corners,'powerWindowsV':thresholds,'enableTruthTable':truth,'gateReview':{'Q3New':'2N7002LT1G +/-20V','normalGateVoltageV':12.13,'monitoredUpperNominalV':13.2,'oldAO3400ALimitV':12,'optoMinimumCurrentAt10VGateA':(10.8-1.4)/(1800*1.001+13.5),'gatePullupLeakageWorstDropV':100e-9*47000},'limitations':['Nominal TI macro-model, ideal DAC/reference and supply rails, 27C only.','AC uses documented optran 0 0 0 20n 100u 0 initialization; first direct-OP/DC convergence failures are retained, not counted as passing DC sweeps.','Four slow full-range transient plateaus replace failed direct DC sweeps; resistor corners are separate ideal linear algebra.','No validated TPS65131 switching/startup simulation, no relay release/flyback or hot-plug/contact-bounce qualification, no Monte Carlo silicon/thermal hardware proof.','Power-good truth-table/window arithmetic is not a transistor-level power-sequence simulation.']}
(root/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k in ['passed','caseCount','families','resistorCorners','powerWindowsV','gateReview']},indent=2))
