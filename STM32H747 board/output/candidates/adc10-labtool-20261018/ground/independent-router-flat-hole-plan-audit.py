"""Read-only comparison of flattened holes to original minus requested voids."""
import hashlib
import json
import runpy
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
ROUTER = HERE.parent / 'routing/all6-local-fill-voids-local332-channelpads-v2.json'
SOURCE = ROOT / 'output/validation/native-adc10-pcb-labtool_place_5-20261018.epru'
PLACEMENT = HERE.parent / 'independent-pcb-placement-short-negative-commonpower-v3-proposal.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def int_region(paths):
    return P['signed_original']([P['ip'](P['ring_points'](p)) for p in paths])


def solid_components(signed_paths):
    c = P['pc'].Pyclipper()
    c.PreserveCollinear = True
    c.AddPaths(signed_paths, P['pc'].PT_SUBJECT, True)
    tree = c.Execute2(P['pc'].CT_UNION, P['pc'].PFT_NONZERO, P['pc'].PFT_NONZERO)
    result = []

    def visit(node):
        if node.Contour and not node.IsHole:
            shape = Polygon(P['fp'](node.Contour), [P['fp'](ch.Contour) for ch in node.Childs if ch.IsHole])
            result.append(shape)
        for child in node.Childs:
            visit(child)

    visit(tree)
    return result


def main():
    router_sha = sha(ROUTER)
    router = json.loads(ROUTER.read_text(encoding='utf8'))
    source = P['G']['PARSE'](SOURCE)
    placement = json.loads(PLACEMENT.read_text(encoding='utf8'))
    route_path = Path(router['routePath'])
    route = json.loads(route_path.read_text(encoding='utf8'))
    assert sha(route_path) == router['routeSha256']
    assert router['channelsOnlyPadVoids'] is True
    common = {'U9', 'U30', 'U31', 'U32', 'D20', 'C103', 'C104', 'C105'} | {f'R{i}' for i in range(197, 205)} | {f'C{i}' for i in range(150, 161)}
    channel_placement = {**placement, 'edits': [e for e in placement['edits'] if e['ref'] not in common]}
    actors = P['actor_paths'](channel_placement, [route], [], set([1, 2, 15, 16, 17, 18]))
    anchors = P['anchor_shapes'](source, placement)
    fills = []
    for op in router['fillPathUpdates']:
        rid = op['id']
        before = source['FILL', rid]
        assert before == op['sourceBodyBefore']
        old = P['geom'](before['path'])
        after = P['geom'](op['afterPath'])
        relevant = [a for a in actors if a['layerId'] == before['layerId'] and (a['net'] or '').casefold() != (before.get('netName') or '').casefold() and
                    P['G']['bb_overlap'](old.bounds, P['H']['bounds'](a['copperPaths']), .2)]
        raw_voids = P['union']([v for a in relevant for s in a['copperPaths'] for v in P['expanded'](s, .17)])
        original_region = int_region(before['path'])
        wanted = P['difference'](original_region, raw_voids)
        got = int_region(op['afterPath'])
        unrequested = P['difference'](wanted, got)
        remaining_under_request = P['difference'](got, wanted)
        added = P['difference'](got, original_region)
        extras = solid_components(unrequested)
        extra_reports = []
        for i, s in enumerate(extras):
            if s.area < 1e-6:
                continue
            hits = [a for a in anchors if before['layerId'] in a['layerIds'] and P['G']['bb_overlap'](s.bounds, a['shape'].bounds) and s.intersection(a['shape']).area > 1e-12]
            extra_reports.append({'component': i, 'areaMm2': s.area, 'boundsMm': list(s.bounds),
                                  'groundPadContacts': [a['id'] for a in hits if a['kind'] == 'PAD'],
                                  'originalGroundViaContacts': [a['id'] for a in hits if a['kind'] == 'VIA'],
                                  'valid': s.is_valid})
        for lobe in extra_reports:
            lobe['groundContactPresent'] = bool(lobe['groundPadContacts'] or lobe['originalGroundViaContacts'])
        fills.append({'primitiveId': rid, 'layerId': before['layerId'], 'net': before['netName'],
                      'beforeBodyExactLatestSource': True, 'outerPathExact': before['path'][0] == op['afterPath'][0],
                      'validBefore': old.is_valid, 'validAfter': after.is_valid, 'validityAfter': explain_validity(after),
                      'copperAddedVsOriginalMm2': P['area'](added),
                      'extraCopperRemovedOutsideRawRequestedVoidMm2': P['area'](unrequested),
                      'copperLeftInsideRawRequestedVoidMm2': P['area'](remaining_under_request),
                      'extraRemovedComponentsOverOneUm2': sorted(extra_reports, key=lambda x: x['areaMm2']),
                      'routerDroppedContainedRingCount': len(op.get('redundantContainedHoleRingsRemoved', [])),
                      'routerReportedNestedUnionAreaChangeMm2': op.get('nestedHoleRemovalUnionAreaChangeMm2'),
                      'affectedOriginalHoleIndexes': op['affectedOriginalHoleIndexes'],
                      'affectedOriginalArcCommands': op['affectedOriginalArcCommands'],
                      'retainedOriginalContourArrayCount': sum(r in op['afterPath'] for r in before['path']),
                      'fillPhysicalPenRadiusMmOmittedByRouterMask': before['width'] * P['MM'] / 2})
    total_extra = sum(f['extraCopperRemovedOutsideRawRequestedVoidMm2'] for f in fills)
    total_added = sum(f['copperAddedVsOriginalMm2'] for f in fills)
    assert sha(ROUTER) == router_sha
    report = {'schema': 'adc10-labtool-independent-router-flat-hole-physical-preservation-audit-v1',
              'passed': total_extra < 1e-5 and total_added < 1e-5 and all(f['validBefore'] and f['validAfter'] and f['outerPathExact'] for f in fills),
              'routerPlan': str(ROUTER), 'routerPlanSha256': router_sha, 'latestSourceSha256': sha(SOURCE),
              'comparisonUsesSameChannelsOnlyPadScopeAsRouter': True, 'placement': str(PLACEMENT), 'placementSha256': sha(PLACEMENT),
              'routeSha256': router['routeSha256'], 'actorCounts': dict(__import__('collections').Counter(a['kind'] for a in actors)),
              'integerGridMm': 1e-6, 'fills': fills,
              'totalExtraCopperRemovedOutsideRawRequestedVoidsMm2': total_extra,
              'totalCopperAddedVsOriginalMm2': total_added,
              'rootCause': 'normalized_holes() drops every contained contour, including negative boundary contours enclosing real GND copper islands created by the requested clearance union. Its validation first flips all contours positive and compares void union areas; that cannot detect loss of those real copper islands.',
              'physicalPenQualification': 'Router mask uses 0.17 mm around actor copper but does not additionally reserve the static FILL 0.2 mil pen radius 0.00254 mm. Clearance remains above the current 0.1524 mm rule by nominal margin; however its declared full 0.17 mm physical gap is not established by that construction.',
              'decision': 'Do not apply the flattened plan as a preservation-equivalent local cut. Preserve copper islands as separate FILL lobes first; any removal needs an explicit frozen list and ground/load contact review.',
              'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False}
    target = HERE / 'independent-router-flat-hole-plan-audit.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': report['passed'], 'report': str(target), 'sha256': sha(target), 'extraRemovedMm2': total_extra, 'addedMm2': total_added,
                      'perLayer': [{'layer': f['layerId'], 'extraRemovedMm2': f['extraCopperRemovedOutsideRawRequestedVoidMm2'], 'extraPieces': len(f['extraRemovedComponentsOverOneUm2'])} for f in fills]}))


if __name__ == '__main__':
    main()
