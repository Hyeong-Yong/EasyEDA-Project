"""Route-only V5: shorterflyingP throughunexposedSOT23bodycentre.
V4reviewfile immutable, componentpositions unchanged.
"""
import contextlib,io,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
code=(HERE/'independent-commonpower-local-routing-v4.py').read_text(encoding='utf8')
code=code.replace('commonpower-top-local-v4-final-review.json','commonpower-top-local-v5-short-fly-review.json')
old="path('AFE_FLY_P','FlyingcapacitorP aroundGNDpad; no signalunderpump',[P('U30',5),(33.35,30.75),(33.35,28.15),(32.7,27.75),P('C151',2)],.4)"
new="path('AFE_FLY_P','FlyingcapacitorP centrechannelbeneathunexposedSOT23body',[P('U30',5),(31.25,29.7),(31.25,28.0),P('C151',2)],.4)"
needle="env={'__file__':str(HERE/'independent-commonpower-local-routing.py'),'__name__':'commonpower_v4_derived'}"
assert needle in code
code=code.replace(needle,"src=src.replace("+repr(old)+","+repr(new)+")\n"+needle)
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(code,str(HERE/'independent-commonpower-local-routing-v4.py'),'exec'),globals())
p=HERE/'routing/commonpower-top-local-v5-short-fly-review.json';report=json.loads(p.read_text(encoding='utf8'))
H=env['H']
report['schema']='independent-commonpower-top-local-route-v5-short-fly-20261018'
report['v5OnlyChange']='OnlyflyingPpathreplacedby3lines throughnativeDBV5unexposedbodycentre; V4componentpositions/other31newlinesgeometriesunchanged. Noanaloginputtraceunderpump.'
report['v5ParentPath']=str(HERE/'routing/commonpower-top-local-v4-final-review.json')
report['v5ParentSha256']=H['sha'](HERE/'routing/commonpower-top-local-v4-final-review.json')
fly=[q for q in report['routedConnections'] if q['net'] in ('AFE_FLY_N','AFE_FLY_P')]
report['flyingTotalWireLengthMm']=sum(x['lengthMm'] for x in fly)
report['knownLoopMetricsNotBenchValidated']=[x for x in report['knownLoopMetricsNotBenchValidated'] if not x.startswith('C151FLYN')]+['C151FLYN2.0797mm/FLYP4.5742mm combined6.6539mm; GNDreturnplaneproofpending']
p.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'path':str(p),'sha256':H['sha'](p),'status':report['status'],'count':len(report['newLineCreates']),'conflicts':report['literalCopperConflicts'],'flyingPaths':fly,'combinedMm':report['flyingTotalWireLengthMm']}))
