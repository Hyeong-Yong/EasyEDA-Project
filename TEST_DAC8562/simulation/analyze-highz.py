from pathlib import Path
import json
import numpy as np
root=Path(__file__).resolve().parent/'highz'
def metrics(j):
 a=np.loadtxt(root/'results'/(j['name']+'.dat'),skiprows=1,ndmin=2)
 if j['test']=='loop':
  crossings=[]
  for i in range(1,len(a)):
   if (a[i-1,1]>0 and a[i,1]<=0):
    frac=-a[i-1,1]/(a[i,1]-a[i-1,1]); phase=a[i-1,2]+frac*(a[i,2]-a[i-1,2]); f=np.exp(np.log(a[i-1,0])+frac*np.log(a[i,0]/a[i-1,0]))
    crossings.append({'frequencyHz':float(f),'phaseMarginDeg':float(180+phase)})
  return {'crossings':crossings}
 if j['test']=='ac':return {'peakingDb':float(max(a[:,1])-a[0,1])}
 if j['test']=='dc':return {'minV':float(min(a[:,2])),'maxV':float(max(a[:,2])),'transferErrorV':float(max(abs(a[:,2]-100000/24900*(a[:,1]-2.5))))}
 if j['test']=='large':return {'minV':float(min(a[:,2])),'maxV':float(max(a[:,2])),'maximumOutputCurrentA':float(max(abs(a[:,3]-a[:,2]))/j['cfg']['riso'])}
 if j['test']=='tran':
  t=a[:,0]-(j.get('riseTimeUs',50)-50)*1e-6;v=a[:,2];before=float(np.mean(v[(t>45e-6)&(t<49e-6)]));target=float(np.mean(v[(t>220e-6)&(t<240e-6)]));amp=target-before;sel=(t>=50.02e-6)&(t<249.99e-6);tt=t[sel];vv=v[sel];bad=np.where(abs(vv-target)>.01*abs(amp))[0];settle=None if len(bad) and bad[-1]>=len(tt)-2 else float((tt[bad[-1]+1] if len(bad) else tt[0])-50.02e-6)*1e6
  return {'overshootPercent':float((max(vv)-target)/amp*100),'settling1PercentUs':settle,'lateRippleVpp':float(np.ptp(v[(t>200e-6)&(t<240e-6)])),'baselineOutputV':before,'targetOutputV':target}
mode=__import__('sys').argv[1] if len(__import__('sys').argv)>1 else 'screen'
jobs=json.loads((root/f'manifest-{mode}.json').read_text())
if any(j['status']!='passed' for j in jobs):
 raise RuntimeError('Failed cases in manifest; do not silently omit them')
results=[{k:v for k,v in j.items() if k!='deck'}|metrics(j) for j in jobs if j['status']=='passed']
(root/f'summary-{mode}.json').write_text(json.dumps(results,indent=2))
if mode=='screen':
 for name in dict.fromkeys(j['cfg']['name'] for j in results):
  rows=[j for j in results if j['cfg']['name']==name];pm=[c['phaseMarginDeg'] for j in rows if j['test']=='loop' for c in j['crossings']];pk=[j['peakingDb'] for j in rows if j['test']=='ac'];print(name,'minimum PM',round(min(pm),2) if pm else None,'peak dB',round(max(pk),2))
else:
 for j in results:
  if j['cfg']['name'].startswith('dfb_') and (j['test']=='dc' or j['cap'] in [0,5000]):print(j['name'],{k:v for k,v in j.items() if k not in ['name','cfg','cap','test','R','bias','status']})
