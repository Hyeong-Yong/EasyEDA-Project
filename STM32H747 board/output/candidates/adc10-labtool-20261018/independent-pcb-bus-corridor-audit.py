"""Literal Cu screening of proposed vertical rail corridors; no EDA writes."""
import hashlib
import json
import runpy
from pathlib import Path
from shapely.geometry import LineString, Point, Polygon
from shapely.affinity import scale
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'independent-pcb-placement-proposal.py'))
ROOT, MM, G = M['ROOT'], M['MM'], M['G']
SOURCE, CHECK = M['SOURCE'], M['CHECK']
CLR = .1535


def main():
    rows = M['parse'](SOURCE)
    attrs = M['attrs_of'](rows)
    docs, _ = M['READ'](CHECK)
    obs = {1: [], 2: []}
    allowed = []
    fills = {1: [], 2: []}
    for (kind, rid), b in rows.items():
        if kind == 'COMPONENT':
            side = b['layerId']
            pads, _ = M['footprint'](docs['FOOTPRINT', attrs[rid]['Footprint']])
            xy = b['x'] * MM, b['y'] * MM
            for pn, (s, pb) in pads.items():
                if side == 2: s = scale(s, xfact=1, yfact=-1, origin=(0, 0))
                s = M['world'](s, xy, b['angle'])
                if s.bounds[0] > 18 or s.bounds[2] < 12: continue
                for layer in ((1, 2) if pb['layerId'] == 12 else (side,)):
                    if layer in obs: obs[layer].append(('PAD', attrs[rid]['Designator'] + ':' + pn, '', s))
        elif kind == 'VIA':
            s = Point(b['centerX'] * MM, b['centerY'] * MM).buffer(b['viaDiameter'] * MM / 2, resolution=24)
            if s.bounds[0] > 18 or s.bounds[2] < 12: continue
            for layer in obs: obs[layer].append((kind, rid, b.get('netName'), s))
        elif kind in ('LINE', 'ARC') and b['layerId'] in obs:
            a, z = (b['startX'] * MM, b['startY'] * MM), (b['endX'] * MM, b['endY'] * MM)
            pts = G['arc'](a, z, b['angle']) if kind == 'ARC' else [a, z]
            s = LineString(pts).buffer(b['width'] * MM / 2, resolution=8)
            if s.bounds[0] > 18 or s.bounds[2] < 12: continue
            net = b.get('netName', '')
            item = (kind, rid, net, s)
            if b['layerId'] == 1 and (('PRE' in net or 'DRV' in net or net == 'ADC_BIAS_2V5') and s.bounds[2] < 28): allowed.append(item)
            else: obs[b['layerId']].append(item)
        elif kind == 'FILL' and b['layerId'] in obs:
            rings = [G['ring_path'](p) for p in b['path']]
            s = Polygon(rings[0], rings[1:])
            if not s.is_valid: continue
            if b.get('netName') == 'GND': fills[b['layerId']].append((rid, s))
            elif b.get('netName') != 'ADC_BIAS_2V5': obs[b['layerId']].append((kind, rid, b.get('netName'), s))
    proposal_path = HERE / 'independent-pcb-placement-rebased-eco-proposal.json'
    proposal = json.loads(proposal_path.read_text(encoding='utf8'))
    # New and relocated SMT pads are top-only; preserve their exact intended nets.
    moving = {p['ref'] for p in proposal['edits'] if not p['newPart']}
    obs[1] = [q for q in obs[1] if not(q[0] == 'PAD' and q[1].split(':')[0] in moving)]
    for p in proposal['edits']:
        for pad in p['pads']:
            from shapely.geometry import box
            obs[1].append(('PROPOSED_PAD', p['ref'] + ':' + pad['number'], pad['net'], box(*pad['boundsMm'])))
    out = []
    for layer in (1, 2):
        shapes = [q[3] for q in obs[layer]]
        tree = STRtree(shapes)
        for x in [round(12.8 + .1 * i, 2) for i in range(39)]:
            center = LineString([(x, 8.5), (x, 142.5)])
            probe = center.buffer(.125 + CLR, cap_style=2)
            hit = []
            for i in tree.query(probe):
                k, rid, net, s = obs[layer][int(i)]
                if not probe.intersects(s): continue
                # A+5Topbus may intentionally contact its own+5pads. Negative
                # Bottombus has no old native-3Vobjects or newSMTpads onthatlayer.
                if layer == 1 and net == '+5V_AFE': continue
                hit.append({'kind': k, 'id': rid, 'net': net, 'boundsMm': list(s.intersection(probe).bounds)})
            out.append({'layerId': layer, 'xMm': x, 'widthMm': .25, 'yRangeMm': [8.5, 142.5], 'protectedConflictCount': len(hit), 'protectedConflicts': hit, 'requiresOldTargetRouteRework': [{'kind':k,'id':rid,'net':net} for k,rid,net,s in allowed if layer == 1 and probe.intersects(s)], 'requiresLocalGroundFillVoidIds': [fid for fid,s in fills[layer] if probe.intersects(s)]})
    good = [q for q in out if q['protectedConflictCount'] == 0]
    report = {'schema':'adc10-labtool-independent-rail-corridor-audit-20261018-v1', 'status':'READONLY_CORRIDOR_SCREEN_NOT_ROUTED', 'sourceSha256':M['sha'](SOURCE), 'placementProposalSha256':M['sha'](proposal_path), 'nativeCalls':0, 'candidates':out, 'zeroProtectedConflictCandidates':[{k:q[k] for k in ('layerId','xMm','widthMm','yRangeMm','requiresLocalGroundFillVoidIds')} for q in good], 'limitations':['Onlyverticalcenterlinescreened;commonpowerfanout,eachchannelpowerstubandnewviasareNOTproven.', 'AlloldviasandPTHpadsareobstaclesevenifsamenet;doNOTdeleteviastoforceabus.', 'GNDfillrequiresboundedlocalclearanceeditsandpostcutanchorreachproof;noentirepourregeneration.', 'TwoBottomrailtrunkswouldneedexplicitnewVIAstubsand6layerantipads;baseline640vias/799drillsmustallremainunchanged.', 'ThecentralREFislandmayblockreuseofx26.5oldbiastrunk;reviewproposedSOICpadsandjoglocaloffsetbusratherthanshortingNC/REFoutputpads.']}
    path = HERE / 'independent-pcb-bus-corridor-rebased-eco-audit.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'path':str(path),'sha256':M['sha'](path),'zeroConflicts':[{k:q[k] for k in ('layerId','xMm')} for q in good]},ensure_ascii=False))


if __name__ == '__main__': main()
