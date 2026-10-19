"""Read-only all-new-VIA centre termination/T-junction/plane-only inventory."""
import json,hashlib,math,argparse
from pathlib import Path
from shapely.geometry import Point,LineString
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018/routing';FP=H/'frozen-combined-routing-v4.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--routes',type=Path,default=FP);ap.add_argument('--output',type=Path);ap.add_argument('--plane-via-key',action='append',default=[]);args=ap.parse_args();FP=args.routes
r=json.loads(FP.read_text());rows=[];fails=[]
for v in r['newViaCreates']:
    endpoints=[];tees=[];near=[];xy=v['xyMm']
    for p in r['newLineCreates']:
        if p['net'].casefold()!=v['net'].casefold():continue
        ds=[math.dist(xy,p[k]) for k in ('startXYmm','endXYmm')]
        if min(ds)<.00002:endpoints.append({'key':p['key'],'layerId':p['layerId'],'endpointErrorMm':min(ds)})
        else:
            d=Point(xy).distance(LineString([p['startXYmm'],p['endXYmm']]))
            if d<.00002:tees.append({'key':p['key'],'layerId':p['layerId'],'centrelineGapMm':d})
            elif d<v['viaDiameterMm']/2+p['widthMm']/2:near.append({'key':p['key'],'layerId':p['layerId'],'centrelineGapMm':d,'nearestEndpointMm':min(ds)})
    plane_only=v['key'] in {'BOTTOM70_GND_LOBE_STITCH',*args.plane_via_key} and v['net']=='GND'
    item={'viaKey':v['key'],'net':v['net'],'actualSelectedCenterMm':xy,'exactNewLineEndpointContacts':endpoints,'exactNewLineCentreTJunctions':tees,'nonCenteredCopperOverlapsInformational':near,'intentionalPlaneOnly':plane_only,'classification':'CENTRED_ENDPOINT' if endpoints else 'EXACT_CENTRE_T' if tees else 'EXPLICIT_GROUND_PLANE_STITCH' if plane_only else 'UNQUALIFIED'}
    rows.append(item)
    if not(endpoints or tees or plane_only):fails.append(item)
report={'routingSha256':sha(FP),'sourceSha256':r['sourceSha256'],'newViasChecked':len(rows),'allSelectedCoordinatesRatherThanSearchPreferencesUsed':not fails,'centredEndpointVias':sum(bool(x['exactNewLineEndpointContacts']) for x in rows),'tOnlyVias':sum(not x['exactNewLineEndpointContacts'] and bool(x['exactNewLineCentreTJunctions']) for x in rows),'planeOnlyVias':sum(x['intentionalPlaneOnly'] for x in rows),'failures':fails,'vias':rows,'nativeCalls':0,'note':'Plane-only Bottom70 stitch must be proved against the authoritative final preserved Ground masks. Endpoint matching tolerance 0.00002mm covers native coordinate rounding only.'}
target=args.output or H/'via-center-termination-v4-audit.json';target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'target':str(target),'sha256':sha(target),'checked':len(rows),'centred':report['centredEndpointVias'],'teeOnly':report['tOnlyVias'],'planeOnly':report['planeOnlyVias'],'fails':len(fails)}))
if fails:raise SystemExit(2)
