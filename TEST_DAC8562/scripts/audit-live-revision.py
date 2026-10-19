"""Check the EasyEDA-produced netlist against the independently built graph."""
import json,re,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/validated-revision'
summary=[]
for row in json.loads((OUT/'build-manifest.json').read_text(encoding='utf8')):
    folder=OUT/row['name']
    if not (folder/'live-validation.json').exists():continue
    actual=json.loads((folder/'live-validation.json').read_text(encoding='utf8'))
    expected=json.loads((folder/'expected-connectivity.json').read_text(encoding='utf8'))
    nets={}; net=None
    for line in actual['pages'][-1]['netlist'].splitlines():
        t=line.strip()
        if t=='(':net='';continue
        if t==')':net=None;continue
        if net is None:continue
        if not net:net=t;nets.setdefault(net,[])
        elif t:nets[net].append(re.sub(r'^([^-]+)-([^ ]+).*',r'\1.\2',t))
    mismatches=[{'net':n,'actual':sorted(nets.get(n,[])),'expected':sorted(expected['nets'].get(n,[]))} for n in set(nets)|set(expected['nets']) if sorted(nets.get(n,[]))!=sorted(expected['nets'].get(n,[]))]
    missing_mpn=[o['name'] for o in expected['components'] if not o['props'].get('Manufacturer Part')]
    missing_footprint=[o['name'] for o in expected['components'] if not o['props'].get('Footprint')]
    report={'name':row['name'],'liveProjectUuid':actual['uuid'],'pages':len(actual['pages']),
            'allPagesSaved':all(p['saved'] for p in actual['pages']),
            'ercAllPagesPassed':all(p['passed'] and not p['details'] for p in actual['pages']),
            'nets':len(nets),'connectedPins':sum(len(v)for v in nets.values()),'netlistMismatch':mismatches,
            'physicalParts':len({o['name']for o in expected['components']}),'missingManufacturerPart':sorted(set(missing_mpn)),
            'missingFootprint':sorted(set(missing_footprint)),
            'limitations':['Schematic/ERC/netlist verification only; not PCB DRC, thermal, SPICE or measured startup accuracy.','Unexpected fast power failure still requires transient/relay-release qualification.']}
    (folder/'verification-summary.json').write_text(json.dumps(report,indent=2),encoding='utf8');summary.append(report)
    print(json.dumps({k:v for k,v in report.items()if k!='limitations'}))
(OUT/'verification-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
if any(x['netlistMismatch']or x['missingManufacturerPart']or x['missingFootprint']for x in summary):raise SystemExit(1)
