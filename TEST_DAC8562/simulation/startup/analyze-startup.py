import hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];here=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'.tools/pcb-python'))
import numpy as np
startup_only='--startup-only' in sys.argv
manifest=json.loads((here/('manifest-startup-only.json' if startup_only else 'manifest.json')).read_text(encoding='utf8'));rows=[];sequence=[]
for j in manifest['jobs']:
 row=dict(j)
 if not j['solverPassed']:rows.append(row);continue
 a=np.loadtxt(here/'results'/(j['name']+'.dat'),skiprows=1,ndmin=2);assert np.isfinite(a).all()
 t,vp,avdd=a[:,0],a[:,1],a[:,2]
 steady=(t>max(.05,(j['riseMs']+.5)/1000+.035))&(t<.095 if 'brownout' in j['scenario'] else t<.175)
 row.update(steadyAvddV=float(np.median(avdd[steady])),peakAvddV=float(avdd.max()),minimumAvddV=float(avdd.min()))
 # TI model's VREF=1.192, unlike datasheet typical VFB=1.185. Do not edit model.
 row['nominalModelExpectedV']=1.192*(1+34/10)
 indices=np.flatnonzero((vp>=11.36)&(avdd>=5.0));row['firstPositiveAndAvddValidMs']=float(t[indices[0]]*1000) if len(indices) else None
 row['screenPassed']=5.076<row['steadyAvddV']<5.352 and row['peakAvddV']<5.5 and row['minimumAvddV']>-.15
 rows.append(row)
 # Logic screening uses a prescribed negative ramp plus the simulated AVDD.
 neg=12.13*np.minimum(np.maximum((t-.0205)/(j['riseMs']/1000),0),1)
 if j['scenario'] in ('startup_and_shutdown','startup_only'):neg*=np.minimum(np.maximum((.181-t)/.001,0),1)
 else:neg*=np.where((t>=.101)&(t<.14),2/12,np.where((t>=.14)&(t<.141),(2+10*(t-.14)/.001)/12,1));neg*=np.minimum(np.maximum((.251-t)/.001,0),1)
 pg=(vp>=11.36)&(vp<=12.88)&(neg>=10.84)&(neg<=13.2)&(avdd>=5.0)&(avdd<=5.48)
 pg_up=np.flatnonzero(pg&~np.r_[False,pg[:-1]])
 # Deliberately compare correct reinitialization with an early held-high GPIO.
 initialized=np.zeros(len(t),dtype=bool)
 for index in pg_up:
  end=index+np.argmax(~pg[index:]) if np.any(~pg[index:]) else len(t)
  initialized[index:end]=t[index:end]>=t[index]+.007 # 2ms PG dwell + assumed 5ms initialization budget
 correct_enable=initialized;early_enable=np.ones(len(t),dtype=bool)
 early_bad=bool(np.any(pg&early_enable&~initialized));correct_bad=bool(np.any(pg&correct_enable&~initialized))
 sequence.append({'case':j['name'],'firstPgoodMs':float(t[pg_up[0]]*1000) if len(pg_up) else None,'pgoodRisingEdges':len(pg_up),'earlyHeldHighEnableCanExposeUninitializedDac':early_bad,'correctPgoodFallClearAndReinitializePolicyPasses':not correct_bad,'assumptions':'Ideal window logic, no hysteresis/propagation/opto/coil/bounce model. 7ms initialization budget is a test-policy assumption, not a guaranteed DAC specification.'})
report={'ldoCases':len(rows),'ldoSolverFailures':[r['name'] for r in rows if not r['solverPassed']],
        'ldoScreenFailures':[r['name'] for r in rows if r.get('screenPassed') is False],
        'maximumAvddV':max(r.get('peakAvddV',-1) for r in rows),'rows':rows,'sequenceCases':sequence,
        'modelSha256':hashlib.sha256((root/'.tools/TPS7A49_unencrypted/TPS7A4901_TRANS.LIB').read_bytes()).hexdigest(),
        'limitations':['Prescribed positive/negative rails; no TPS65131 transistor/switch-mode model was found in its current TI product resources. No ripple/inrush/current-limit/inductor saturation claim.','TI unmodified LDO model has 1.192V VREF and typical internal parameters; not worst-case silicon or thermal qualification.','Effective MLCC capacitance factors are assumptions; verify manufacturer DC-bias curves and final voltage rating.','Digital PG/ENABLE screening is behavioral logic, not an analog/opto/relay startup simulation.','A held-high OUTPUT_ENABLE can automatically reconnect an uninitialized/reset DAC after power returns. Firmware must clear both enables on PGOOD loss and reinitialize before enabling output.','Relay release including flyback diode and bounce is not bounded by this model. Fast rail collapse can outrun muting; do not assert guaranteed glitch-free shutdown.','Protected R102.1 is still disconnected in the schematic; this is not a manufacturing release.']}
report['ldoScreenPassed']=not(report['ldoSolverFailures'] or report['ldoScreenFailures'])
(here/('summary-startup-only.json' if startup_only else 'summary.json')).write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k not in ('rows','sequenceCases','limitations')},indent=2))
