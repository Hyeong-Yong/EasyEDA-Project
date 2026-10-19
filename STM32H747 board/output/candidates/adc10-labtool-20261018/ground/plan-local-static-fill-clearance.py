"""Offline bounded static-FILL cuts; never repairs or imports native designs.

Unchanged contours retain original native commands, including arcs.  Only
overlapping clearance holes are unioned, using a conservatively expanded arc
tessellation.  Outer-boundary contact or invalid input blocks that FILL.
"""
import argparse
import copy
import hashlib
import json
import math
import runpy
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / '.tools/adc-geometry-deps'))
import pyclipper as pc
from shapely.geometry import Polygon, Point, box, LineString
from shapely.affinity import rotate, translate, scale
from shapely.ops import unary_union
from shapely.validation import explain_validity

H = runpy.run_path(str(ROOT / 'scripts/build-adc10-strip-operations-20261018.py'))
G = H['G']
G['arc'].__globals__['SAG'] = .0001
MM = .0254
SCALE = H['SCALE']
ip, fp = H['ip'], H['fp']
positive, union = H['positive'], H['union']
intersection, area = H['intersection'], H['area']
expanded, capsule = H['expanded'], H['capsule']
ROUNDING_GUARD_MM = .00001


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def rectangle(bounds):
    x1, y1, x2, y2 = bounds
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def ring_points(ring):
    if ring[0] == 'CIRCLE':
        x, y, r = (float(v) * MM for v in ring[1:4])
        n = max(64, math.ceil(math.pi / math.acos(max(-1, 1 - min(.0001 / max(r, 1e-12), 1)))))
        return [(x + r * math.cos(math.tau * i / n), y + r * math.sin(math.tau * i / n)) for i in range(n)]
    return G['ring_path'](ring)


def difference(a, b):
    if not a:
        return []
    c = pc.Pyclipper()
    c.PreserveCollinear = True
    c.AddPaths(a, pc.PT_SUBJECT, True)
    if b:
        c.AddPaths(b, pc.PT_CLIP, True)
    return c.Execute(pc.CT_DIFFERENCE, pc.PFT_NONZERO, pc.PFT_NONZERO)


def signed_region(paths):
    """Keep winding: unlike convex actor unions, regions can have holes."""
    c = pc.Pyclipper()
    c.PreserveCollinear = True
    c.AddPaths(paths, pc.PT_SUBJECT, True)
    return c.Execute(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)


def signed_original(rings):
    return [positive(rings[0])] + [list(reversed(positive(p))) for p in rings[1:]]


def contour_equivalent(a, b):
    if G['bbox'](a) != G['bbox'](b):
        return False
    return area(difference([positive(a)], [positive(b)])) == 0 and area(difference([positive(b)], [positive(a)])) == 0


def split_local_lobes(rid, body, paths, rings, current, allow_outer_change=False, outer_restore=None):
    """Exact integer subtraction, retaining every resulting copper component."""
    c = pc.Pyclipper()
    c.PreserveCollinear = True
    c.AddPaths(signed_original(rings), pc.PT_SUBJECT, True)
    c.AddPaths(current, pc.PT_CLIP, True)
    tree = c.Execute2(pc.CT_DIFFERENCE, pc.PFT_NONZERO, pc.PFT_NONZERO)
    solids = []

    def visit(node):
        if node.Contour and not node.IsHole:
            solids.append([node.Contour] + [ch.Contour for ch in node.Childs if ch.IsHole])
        for child in node.Childs:
            visit(child)

    visit(tree)
    base = next((s for s in solids if contour_equivalent(s[0], rings[0])), None)
    if base is None:
        if not allow_outer_change:
            raise ValueError('Outer boundary was not preserved by local split')
        base = max(solids, key=lambda s: abs(pc.Area(s[0])))
    solids.remove(base)
    solids = [base] + solids
    retained = []
    unmatched_original = set(range(len(paths)))
    output = []
    for solid in solids:
        out = []
        for contour_index, contour in enumerate(solid):
            match = next((i for i in unmatched_original if contour_equivalent(contour, rings[i])), None)
            if match is not None:
                out.append(copy.deepcopy(paths[match]))
                retained.append(match)
                unmatched_original.remove(match)
            else:
                if contour_index == 0 and outer_restore is not None:
                    out.append(restored_notch_outer(contour, outer_restore))
                else:
                    out.append(native_ring(contour, outer=contour_index == 0))
        output.append(out)
    final_signed = [p for s in solids for p in signed_original(s)]
    original_signed = signed_original(rings)
    expected_signed = difference(original_signed, current)
    symmetric_difference = area(difference(final_signed, expected_signed)) + area(difference(expected_signed, final_signed))
    addition = area(difference(final_signed, original_signed))
    old_void_lost = area(intersection(final_signed, union([positive(p) for p in rings[1:]])))
    invalid = [explain_validity(geom(s)) for s in output if not geom(s).is_valid]
    if addition != 0 or old_void_lost != 0 or symmetric_difference != 0 or invalid:
        raise ValueError(str({'copperAddition': addition, 'oldVoidLost': old_void_lost, 'symmetricDifference': symmetric_difference, 'invalid': invalid}))
    lobes = [{'key': 'LOCAL_STATIC_LOBE_' + rid + '_' + str(i), 'semanticId': 'LOCAL_STATIC_LOBE_' + rid + '_' + str(i), 'sourceParentPrimitiveId': rid,
              'sourceParentBeforeBodySha256': digest(body), 'net': body.get('netName'),
              'layerId': body['layerId'], 'widthMil': body.get('width', 0), 'lineWidthMil': body.get('width', 0), 'fillStyle': body.get('fillStyle'),
              'locked': body.get('locked', False),
              'afterPath': s, 'afterPathsExplicitlyClosedForApi': [close_ring(r) for r in s],
              'areaMm2': geom(s).area, 'boundsMm': list(geom(s).bounds),
              'nativeOuterClockwise': pc.Area(ip(ring_points(s[0]))) < 0,
              'nativeHolesCounterclockwise': all(pc.Area(ip(ring_points(r))) > 0 for r in s[1:]),
              'valid': geom(s).is_valid, 'requiresIndependentPhysicalGroundAnchorAudit': True}
             for i, s in enumerate(output[1:], 1)]
    return output[0], lobes, sorted(retained), sorted(unmatched_original), addition, old_void_lost, symmetric_difference


def original_native_points(ring):
    assert all(not isinstance(v, str) or v == 'L' for v in ring), 'Approved outer notch requires an L-only original outer'
    numbers = [v for v in ring if not isinstance(v, str)]
    points = list(zip(numbers[::2], numbers[1::2]))
    if points[-1] == points[0]:
        points.pop()
    return points


def restored_notch_outer(contour, original_ring):
    """Restore every retained old vertex to its exact native source numbers."""
    native = original_native_points(original_ring)
    old_int = ip([(x * MM, y * MM) for x, y in native])
    restore = {tuple(p): n for p, n in zip(old_int, native)}
    points = list(reversed(positive(contour)))
    expanded_points = []
    for a, b in zip(points, points[1:] + points[:1]):
        expanded_points.append(tuple(a))
        dx, dy = b[0] - a[0], b[1] - a[1]
        den = dx * dx + dy * dy
        insert = []
        if den:
            for point in old_int:
                px, py = point[0] - a[0], point[1] - a[1]
                along = px * dx + py * dy
                if px * dy - py * dx == 0 and 0 < along < den:
                    insert.append((along, tuple(point)))
        expanded_points.extend(p for _, p in sorted(set(insert)))
    output = []
    for point in expanded_points:
        xy = restore.get(point, (point[0] / SCALE / MM, point[1] / SCALE / MM))
        if not output:
            output.extend([*xy, 'L'])
        else:
            output.extend(xy)
    output.extend(output[:2])
    return output


def reviewed_notch_proof(paths, after, lobes, mask, original_rings, mask_integer_paths=None):
    old_points = original_native_points(paths[0])
    outputs = [original_native_points(s[0]) for s in [after] + [l['afterPath'] for l in lobes]]
    seen_points = {p for ring in outputs for p in ring}
    edges = {edge for ring in outputs for edge in zip(ring, ring[1:] + ring[:1])}
    missing_points = [i for i, p in enumerate(old_points) if not mask.covers(Point(p[0] * MM, p[1] * MM)) and p not in seen_points]
    untouched_edges = [i for i, (a, b) in enumerate(zip(old_points, old_points[1:] + old_points[:1]))
                       if not mask.intersects(LineString([(a[0] * MM, a[1] * MM), (b[0] * MM, b[1] * MM)]))]
    missing_edges = [i for i in untouched_edges if (old_points[i], old_points[(i + 1) % len(old_points)]) not in edges and
                     (old_points[(i + 1) % len(old_points)], old_points[i]) not in edges]
    new_outer = union([positive(ip(ring_points(s[0]))) for s in [after] + [l['afterPath'] for l in lobes]])
    old_outer = [positive(original_rings[0])]
    mask_int = mask_integer_paths if mask_integer_paths is not None else [ip(list(poly.exterior.coords)[:-1]) for poly in ([mask] if mask.geom_type == 'Polygon' else mask.geoms)]
    removed_outer = difference(old_outer, new_outer)
    outside = area(difference(removed_outer, mask_int))
    added_outer = area(difference(new_outer, old_outer))
    holes_exact = all(any(r == old for s in [after] + [l['afterPath'] for l in lobes] for r in s[1:]) for old in paths[1:])
    return {'originalOuterNativeVertexCount': len(old_points), 'originalOuterArcCount': 0,
            'oldVerticesOutsideApprovedMaskMissing': missing_points,
            'oldSegmentsEntirelyOutsideApprovedMaskCount': len(untouched_edges),
            'oldSegmentsOutsideApprovedMaskMissing': missing_edges, 'allOriginalHolesRetainedByteExact': holes_exact,
            'outerCopperAddedAreaMm2': added_outer, 'outerRemovalOutsideApprovedMasksAreaMm2': outside,
            'outerRemovalWithinApprovedMasksAreaMm2': area(removed_outer),
            'approvedMaskIntegerGeometrySha256': digest(mask_int),
            'approvedMaskUsesExactIntegerActorUnion': mask_integer_paths is not None,
            'passed': not missing_points and not missing_edges and holes_exact and added_outer == outside == 0}


def anchor_shapes(rows, placement, net='GND'):
    """Literal via annuli and native selected-net pads at proposed positions."""
    reader = runpy.run_path(str(ROOT / 'scripts/build-adc10-labtool-libraries-20261018.py'))['read_snapshot']
    docs = reader(Path(placement['checkpointPath']))
    attrs = {}
    padnets = {}
    for (kind, rid), b in rows.items():
        if kind == 'ATTR':
            attrs.setdefault(b.get('parentId'), {})[b.get('key')] = b.get('value')
        elif kind == 'PAD_NET':
            _, cid, num, _ = json.loads(rid)
            padnets[cid, str(num)] = b.get('padNet')
    edits = {e['componentId']: e for e in placement.get('edits', [])}
    shapes = []
    for (kind, rid), b in rows.items():
        if kind == 'VIA' and b.get('netName') == net:
            xy = b['centerX'] * MM, b['centerY'] * MM
            s = Point(xy).buffer(b['viaDiameter'] * MM / 2, resolution=64)
            s = s.difference(Point(xy).buffer(b['holeDiameter'] * MM / 2, resolution=64))
            shapes.append({'kind': 'VIA', 'id': rid, 'layerIds': sorted({1, 2, 15, 16, 17, 18} - set(b.get('unusedInnerLayers', []))), 'shape': s})
        if kind != 'COMPONENT':
            continue
        a = attrs[rid]
        doc = docs['FOOTPRINT', a['Footprint']]
        edit = edits.get(rid)
        xy = edit['xyMm'] if edit else [b['x'] * MM, b['y'] * MM]
        angle = edit['angle'] if edit else b['angle']
        component_layer = edit.get('layerId', b['layerId']) if edit else b['layerId']
        for h, pad in doc.values():
            if h['type'] != 'PAD' or padnets.get((rid, str(pad['num']))) != net:
                continue
            d = pad['defaultPad']
            kind = d.get('padType')
            if kind == 'POLYGON':
                s = Polygon(G['ring_path'](d['path']))
            else:
                w, ht = d.get('width', d.get('diameter', 0)) * MM, d.get('height', d.get('diameter', 0)) * MM
                if kind == 'ELLIPSE':
                    s = scale(Point(0, 0).buffer(1, resolution=64), w / 2, ht / 2)
                elif kind == 'OVAL':
                    rr = min(w, ht) / 2
                    a1, a2 = ((-(w / 2 - rr), 0), (w / 2 - rr, 0)) if w >= ht else ((0, -(ht / 2 - rr)), (0, ht / 2 - rr))
                    s = LineString([a1, a2]).buffer(rr, resolution=64)
                elif kind == 'RECT':
                    radius = min((d.get('radius', 0) or 0) * MM, w / 2, ht / 2)
                    s = box(-w / 2 + radius, -ht / 2 + radius, w / 2 - radius, ht / 2 - radius).buffer(radius, resolution=32) if radius else box(-w / 2, -ht / 2, w / 2, ht / 2)
                else:
                    continue
                s = translate(rotate(s, pad.get('padAngle', 0), origin=(0, 0)), pad['centerX'] * MM, pad['centerY'] * MM)
            s = translate(rotate(s, angle, origin=(0, 0)), *xy)
            if not s.is_valid:
                continue
            layer = pad['layerId']
            if component_layer == 2 and layer in (1, 2):
                layer = 3 - layer
            layers = [1, 2, 15, 16, 17, 18] if layer == 12 else [layer]
            shapes.append({'kind': 'PAD', 'id': a['Designator'] + ':' + str(pad['num']), 'layerIds': layers, 'shape': s,
                           'physicalPadPrimitiveId': h.get('id'), 'physicalOwnerId': rid,
                           'platedThroughPad': layer == 12 and bool(pad.get('plated')),
                           'proposedMovedComponent': edit is not None})
    return shapes


def native_ring(path, outer=False):
    oriented = list(reversed(positive(path))) if outer else positive(path)
    points = fp(oriented)
    out = [points[0][0] / MM, points[0][1] / MM, 'L']
    for x, y in points[1:]:
        out.extend([x / MM, y / MM])
    out.extend(out[:2])
    return out


def close_ring(ring):
    out = copy.deepcopy(ring)
    if out[0] == 'CIRCLE':
        return out
    if out[-2:] != out[:2]:
        out.extend(['L', *out[:2]])
    return out


def geom(paths):
    return Polygon(ring_points(paths[0]), [ring_points(p) for p in paths[1:]])


def actor_paths(placement, routing, extra, layers):
    actors = []
    for edit in placement.get('edits', []):
        layer = edit.get('layerId', 1)
        if layer not in layers:
            continue
        for pad in edit.get('pads', []):
            copper = pad.get('rectangleXYmm')
            if copper is None:
                copper = rectangle(pad['boundsMm'])
            actors.append({'kind': 'PAD', 'key': edit['ref'] + ':' + str(pad['number']), 'layerId': layer,
                           'net': pad.get('net', ''), 'copperPaths': [ip(copper)],
                           'shapeQualification': 'conservative axis-aligned copper bounds; preserves rounded corners by over-cutting, not under-cutting'})
    for route in routing:
        for i, line in enumerate(route.get('newLineCreates', route.get('lineCreates', []))):
            layer = line['layerId']
            if layer not in layers:
                continue
            start = line.get('startXYmm') or [v * MM for v in line['startXYmil']]
            end = line.get('endXYmm') or [v * MM for v in line['endXYmil']]
            width = line.get('widthMm', line.get('widthMil', 0) * MM)
            actors.append({'kind': 'LINE', 'key': line.get('key', 'line-' + str(i)), 'layerId': layer,
                           'net': line.get('net', ''), 'copperPaths': capsule(start, end, width / 2)})
        vias = route.get('viaCreates', route.get('newViaCreates', route.get('viasProposed', route.get('plannedVias', []))))
        if isinstance(vias, int):
            if vias:
                raise ValueError('Via count supplied without actual via geometry')
            vias = []
        for i, via in enumerate(vias):
            if not isinstance(via, dict):
                continue
            xy = via.get('xyMm') or [v * MM for v in via['xyMil']]
            diameter = via.get('diameterMm', via.get('viaDiameterMm', via.get('diameterMil', 0) * MM))
            if diameter <= 0:
                raise ValueError('Via diameter missing: ' + str(via))
            for layer in layers:
                actors.append({'kind': 'VIA', 'key': via.get('key', 'via-' + str(i)), 'layerId': layer,
                               'net': via['net'], 'xyMm': xy, 'diameterMm': diameter,
                               'copperPaths': capsule(xy, xy, diameter / 2)})
    for item in extra:
        for layer in item.get('layerIds', [item.get('layerId', 1)]):
            if layer in layers:
                actors.append({'kind': 'EXTRA', 'key': item['key'], 'layerId': layer, 'net': item.get('net', ''),
                               'copperPaths': [ip(item['copperPolygonMm'])]})
    unique = {}
    for actor in actors:
        key = actor['kind'], actor['key'], actor['layerId']
        if key in unique:
            old = unique[key]
            if old['net'] != actor['net'] or old['copperPaths'] != actor['copperPaths']:
                raise ValueError('Conflicting repeated actor definition: ' + str(key))
        else:
            unique[key] = actor
    return list(unique.values())


def notch_authorization_errors(approval, body, touch_actors, clearance, fill_pen_radius):
    if not approval:
        return ['No reviewed outer-notch scope supplied']
    errors = []
    if approval.get('beforeBodySha256') != digest(body):
        errors.append('Original FILL body hash is outside reviewed scope')
    allowed = set(approval.get('allowedOuterActorKeys', [])) | set(approval.get('allowedConnectedInteriorActorKeys', []))
    if any(a['key'] not in allowed for a in touch_actors):
        errors.append('Outer-touching actor key is outside reviewed scope')
    for name, actual in [('clearanceMm', clearance), ('fillPenRadiusMm', fill_pen_radius),
                         ('roundingReserveMm', ROUNDING_GUARD_MM)]:
        if name in approval and abs(approval[name] - actual) > 1e-12:
            errors.append(name + ' differs from reviewed scope')
    for actor in touch_actors:
        definition = approval.get('expectedActors', {}).get(actor['key'])
        if definition:
            for name in ('kind', 'net'):
                if actor.get(name) != definition.get(name):
                    errors.append(actor['key'] + ' ' + name + ' differs from reviewed scope')
            if definition.get('copperPathsSha256') != digest(actor['copperPaths']):
                errors.append(actor['key'] + ' literal copper geometry differs from reviewed scope')
            if definition.get('maskSha256') != actor.get('outerMaskPathsSha256'):
                errors.append(actor['key'] + ' literal expanded mask differs from reviewed scope')
        expected_xy = approval.get('portCentersMm', {}).get(actor['key'])
        expected_diameter = approval.get('viaCopperDiameterMm')
        if expected_xy is not None and (actor.get('kind') != 'VIA' or
                len(actor.get('xyMm', [])) != 2 or
                any(abs(a - b) > 1e-9 for a, b in zip(actor['xyMm'], expected_xy))):
            errors.append(actor['key'] + ' center/kind differs from reviewed scope')
        if expected_diameter is not None and (actor.get('kind') != 'VIA' or
                abs(actor.get('diameterMm', 0) - expected_diameter) > 1e-12):
            errors.append(actor['key'] + ' copper diameter differs from reviewed scope')
    return errors


def cut_one(rid, body, actors, clearance, notch_approval=None):
    paths = body['path']
    rings = [ip(ring_points(p)) for p in paths]
    original = geom(paths)
    bb = original.bounds
    relevant_actors = [a for a in actors if a['layerId'] == body['layerId'] and a['net'] != body.get('netName') and
                       G['bb_overlap'](bb, H['bounds'](a['copperPaths']), clearance + .02)]
    if not relevant_actors:
        return None, {'id': rid, 'status': 'UNCHANGED_NO_NEARBY_ACTOR', 'validBefore': original.is_valid,
                      'invalidReason': None if original.is_valid else explain_validity(original), 'beforeBodySha256': digest(body)}
    # The static FILL pen itself adds copper at its contour edge.
    fill_pen_radius = abs(body.get('width', 0) or 0) * MM / 2
    voids = union([p for a in relevant_actors for shape in a['copperPaths']
                   for p in expanded(shape, clearance + fill_pen_radius + ROUNDING_GUARD_MM)])
    clipped = intersection(voids, [positive(rings[0])])
    if not clipped:
        return None, {'id': rid, 'status': 'UNCHANGED_OUTSIDE_OUTER', 'validBefore': original.is_valid,
                      'beforeBodySha256': digest(body)}
    old_holes = union([positive(p) for p in rings[1:]])
    fresh_void = difference(clipped, old_holes)
    if not fresh_void or area(fresh_void) == 0:
        return None, {'id': rid, 'status': 'UNCHANGED_ALREADY_IN_EXISTING_VOID', 'validBefore': original.is_valid,
                      'beforeBodySha256': digest(body)}
    if not original.is_valid:
        return None, {'id': rid, 'status': 'BLOCKED_INVALID_INPUT_REQUIRES_REVIEW', 'validBefore': False,
                      'invalidReason': explain_validity(original), 'potentialNewCutAreaMm2': area(fresh_void),
                      'beforeBodySha256': digest(body), 'noAutomaticRepair': True,
                      'actorKeys': [a['key'] for a in relevant_actors]}
    affected = set()
    current = signed_region(clipped)
    while True:
        more = {i for i in range(1, len(paths)) if i not in affected and
                H['shapes_intersect']([positive(rings[i])], current)}
        if not more:
            break
        affected |= more
        keep = []
        for i in more:
            margin = ROUNDING_GUARD_MM + (.0001 if any(v in ('ARC', 'CARC', 'CIRCLE') for v in paths[i] if isinstance(v, str)) else 0)
            keep.extend(expanded(rings[i], margin))
        current = signed_region(current + keep)
    # For boundary screening only, outer contours cover their contained holes.
    union_geom = unary_union([Polygon(fp(p)) for p in current if pc.Area(p) > 0])
    outer = Polygon(fp(rings[0]))
    outer_touched = outer.boundary.distance(union_geom) <= ROUNDING_GUARD_MM / 2 or not outer.covers(union_geom)
    notch_mask = None
    notch_mask_int = None
    touch_keys = []
    if outer_touched:
        actor_masks = []
        touch_actors = []
        approved_mask_paths = []
        connected_keys = set(notch_approval.get('allowedConnectedInteriorActorKeys', [])) if notch_approval else set()
        for actor in relevant_actors:
            actor_expanded_paths = [p for shape in actor['copperPaths'] for p in expanded(shape, clearance + fill_pen_radius + ROUNDING_GUARD_MM)]
            polygons = [Polygon(fp(p)) for p in actor_expanded_paths]
            actor_mask = unary_union(polygons)
            touches = outer.boundary.intersects(actor_mask)
            if touches or actor['key'] in connected_keys:
                actor_masks.append(actor_mask)
                approved_mask_paths.extend(actor_expanded_paths)
                if touches:
                    touch_keys.append(actor['key'])
                mask_parts = actor_mask.geoms if actor_mask.geom_type == 'MultiPolygon' else [actor_mask]
                mask_paths = [ip(list(p.exterior.coords)[:-1]) for p in mask_parts]
                touch_actors.append({**actor, 'outerMaskPathsSha256': digest(mask_paths)})
        authorization_errors = notch_authorization_errors(notch_approval, body, touch_actors, clearance, fill_pen_radius)
        if authorization_errors:
            return None, {'id': rid, 'status': 'BLOCKED_CUT_TOUCHES_OUTER_BOUNDARY', 'validBefore': True,
                          'distanceToOuterMm': outer.boundary.distance(union_geom), 'beforeBodySha256': digest(body),
                          'outerTouchActorKeys': touch_keys, 'approvedActorKeys': notch_approval.get('allowedOuterActorKeys', []) if notch_approval else [],
                          'authorizationErrors': authorization_errors}
        notch_mask = unary_union(actor_masks)
        notch_mask_int = union(approved_mask_paths)
        assert all(not isinstance(v, str) or v == 'L' for v in paths[0]), 'Reviewed outer notches are restricted to this exact L-only native boundary'
    split = outer_touched or any(pc.Area(p) < 0 for p in current)
    lobes = []
    if split:
        after, lobes, retained, removed, copper_addition, void_lost, symmetry = split_local_lobes(rid, body, paths, rings, current,
                  allow_outer_change=outer_touched, outer_restore=paths[0] if outer_touched else None)
        if set(range(len(paths))) - affected - set(retained) - ({0} if outer_touched else set()):
            raise ValueError('An unaffected original contour was not retained exactly')
    else:
        retained = [i for i in range(len(paths)) if i not in affected]
        after = [copy.deepcopy(paths[i]) for i in retained] + [native_ring(p) for p in current]
    explicit = [close_ring(r) for r in after]
    after_geom = geom(explicit)
    if not after_geom.is_valid:
        native_holes = [Polygon(ring_points(p)) for p in explicit[1:]]
        nested = [{'outerHoleIndex': i + 1, 'innerHoleIndex': j + 1,
                   'outerAreaMm2': p.area, 'innerAreaMm2': q.area,
                   'innerBoundsMm': list(q.bounds)}
                  for i, p in enumerate(native_holes) for j, q in enumerate(native_holes)
                  if i != j and p.contains(q)]
        return None, {'id': rid, 'status': 'BLOCKED_INVALID_OUTPUT', 'invalidReason': explain_validity(after_geom),
                      'beforeBodySha256': digest(body), 'unionPositiveContours': sum(pc.Area(p) > 0 for p in current),
                      'unionNegativeContours': sum(pc.Area(p) < 0 for p in current), 'nestedPairs': nested,
                      'affectedOriginalHoles': sorted(affected)}
    after_holes = union([positive(ip(ring_points(r))) for r in explicit[1:]])
    lost = difference(old_holes, after_holes)
    added = difference(difference([positive(rings[0])], after_holes), difference([positive(rings[0])], old_holes))
    if not split and (area(lost) != 0 or area(added) != 0):
        return None, {'id': rid, 'status': 'BLOCKED_OLD_VOID_LOST_OR_COPPER_ADDED',
                      'oldVoidLostAreaMm2': area(lost), 'copperAdditionAreaMm2': area(added), 'beforeBodySha256': digest(body)}
    all_closed = all(r[0] == 'CIRCLE' or r[-2:] == r[:2] for r in explicit)
    notch_proof = None
    if outer_touched:
        notch_proof = reviewed_notch_proof(paths, after, lobes, notch_mask, rings, notch_mask_int)
        if not notch_proof['passed']:
            return None, {'id': rid, 'status': 'BLOCKED_APPROVED_NOTCH_PRESERVATION_PROOF', **notch_proof}
    entry = {'primitiveId': rid, 'layerId': body['layerId'], 'net': body.get('netName'),
             'beforeBody': body, 'beforeBodySha256': digest(body), 'beforePathSha256': digest(paths),
             'afterPath': after, 'afterPathsExplicitlyClosedForApi': explicit, 'afterPathSha256': digest(after),
             'afterApiPathSha256': digest(explicit), 'allowedChangedFields': ['path'],
             'unaffectedOriginalContourIndexesRetainedAcrossParentAndLobes': retained, 'affectedOriginalHoleIndexes': sorted(affected),
             'outerRetainedExactBeforeClosureSerialization': after[0] == paths[0],
             'unaffectedContoursRetainedExactBeforeClosureSerialization': all(any(r == paths[i] for s in [after] + [l['afterPath'] for l in lobes] for r in s) for i in set(range(len(paths))) - affected - ({0} if outer_touched else set())),
             'onlyApiClosureAddedToRetainedContours': all(any(r == close_ring(paths[i]) for s in [explicit] + [l['afterPathsExplicitlyClosedForApi'] for l in lobes] for r in s) for i in set(range(len(paths))) - affected - ({0} if outer_touched else set())),
             'allApiRingsExplicitlyClosed': all_closed, 'validBefore': True, 'validAfter': after_geom.is_valid,
             'oldVoidLostAreaMm2': void_lost if split else area(lost), 'copperAdditionAreaMm2': copper_addition if split else area(added),
             'localCutSymmetricDifferenceAreaMm2': symmetry if split else 0,
             'newCopperRemovalAreaMm2': original.area - after_geom.area - sum(l['areaMm2'] for l in lobes),
             'preservedCopperLobes': lobes,
             'reviewedLocalOuterNotch': {'scope': notch_approval, 'actualOuterTouchActorKeys': touch_keys, 'proof': notch_proof} if outer_touched else None,
             'actorKeys': [a['key'] for a in relevant_actors], 'clearanceMm': clearance,
             'fillPenRadiusMm': fill_pen_radius, 'arcSagittaBoundMm': .0001,
             'integerScalePerMm': SCALE, 'roundingGuardMm': ROUNDING_GUARD_MM,
             'affectedArcCount': sum(sum(v in ('ARC', 'CARC') for v in paths[i] if isinstance(v, str)) for i in affected),
             'proofQualification': 'Old/new void containment measured on 1 nm integer geometry; affected old contours are conservatively expanded by rounding guard plus arc sagitta. Unaffected native arcs/coordinates are unchanged; API closure is explicit only.',
             'clearanceRequestIncludesConservativeOldContourGuardMm': ROUNDING_GUARD_MM,
             'requiresNativeReadbackAndStrictDrc': True}
    return entry, {'id': rid, 'status': 'PLANNED_BOUNDED_LOCAL_CUT', 'validBefore': True, 'validAfter': True,
                   'affectedHoles': len(affected), 'retainedContours': len(retained), 'newUnionHoles': len(current), 'preservedLocalLobes': len(lobes),
                   'newCopperRemovalAreaMm2': entry['newCopperRemovalAreaMm2']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--placement', type=Path, required=True)
    parser.add_argument('--routes', type=Path, action='append', default=[])
    parser.add_argument('--extra-copper', type=Path)
    parser.add_argument('--approved-outer-notches', type=Path)
    parser.add_argument('--layers', default='1')
    parser.add_argument('--fill-nets', default='GND', help='comma-separated, or * for all differently-netted static fills')
    parser.add_argument('--clearance-mm', type=float, default=.17)
    parser.add_argument('--output-prefix', default='local-static-fill-clearance')
    args = parser.parse_args()
    if Path(args.output_prefix).name != args.output_prefix:
        raise ValueError('Output prefix must be a filename within the ground output folder')
    layers = {int(x) for x in args.layers.split(',')}
    if not layers <= {1, 2, 15, 16, 17, 18}:
        raise ValueError('Only documented six copper layer IDs are supported')
    source_sha = sha(args.source)
    generator_sha = sha(Path(__file__))
    placement_sha = sha(args.placement)
    route_sha = {str(p): sha(p) for p in args.routes}
    approval_sha = sha(args.approved_outer_notches) if args.approved_outer_notches else None
    extra_sha = sha(args.extra_copper) if args.extra_copper else None
    rows = G['PARSE'](args.source)
    placement = json.loads(args.placement.read_text(encoding='utf8'))
    routing = [json.loads(p.read_text(encoding='utf8')) for p in args.routes]
    extra = json.loads(args.extra_copper.read_text(encoding='utf8')) if args.extra_copper else []
    approvals = json.loads(args.approved_outer_notches.read_text(encoding='utf8')) if args.approved_outer_notches else {}
    for rid, approval in approvals.items():
        required_source = approval.get('sourceSha256Required')
        if required_source and required_source != source_sha:
            raise ValueError('Reviewed outer-notch scope requires an explicit source rebase: ' + rid)
    attr_map = {}
    pin_map = {}
    for (kind, rid), body in rows.items():
        if kind == 'ATTR':
            attr_map.setdefault(body.get('parentId'), {})[body.get('key')] = body.get('value')
        elif kind == 'PAD_NET':
            _, cid, number, _ = json.loads(rid)
            pin_map[cid, str(number)] = body.get('padNet')
    for edit in placement.get('edits', []):
        cid = edit['componentId']
        body = rows['COMPONENT', cid]
        if body.get('attrs', {}).get('Unique ID') != edit['uniqueId'] or attr_map[cid].get('Footprint') != edit['footprintUuid']:
            raise ValueError('Placement UID/footprint does not match current source: ' + edit['ref'])
        for pad in edit['pads']:
            if (pin_map.get((cid, str(pad['number']))) or None) != (pad.get('net') or None):
                raise ValueError('Placement pad net does not match current source: ' + edit['ref'] + ':' + str(pad['number']))
    actors = actor_paths(placement, routing, extra, layers)
    operations, audits = [], []
    nets = set(args.fill_nets.split(','))
    for (kind, rid), body in rows.items():
        if kind != 'FILL' or body.get('layerId') not in layers or ('*' not in nets and body.get('netName') not in nets):
            continue
        if body.get('fillStyle') != 'SOLID':
            audits.append({'id': rid, 'status': 'BLOCKED_NON_SOLID_FILL_STYLE', 'beforeBodySha256': digest(body)})
            continue
        try:
            operation, audit = cut_one(rid, body, actors, args.clearance_mm, approvals.get(rid))
        except (AssertionError, ValueError, TypeError, pc.ClipperException) as error:
            operation, audit = None, {'id': rid, 'status': 'BLOCKED_GEOMETRY_OR_UNSUPPORTED_FORMAT',
                                     'beforeBodySha256': digest(body), 'reason': str(error), 'noRepair': True}
        audits.append(audit)
        if operation:
            operations.append(operation)
    anchors = anchor_shapes(rows, placement) if any(o['preservedCopperLobes'] for o in operations) else []
    lobe_creates = []
    for operation in operations:
        for lobe in operation['preservedCopperLobes']:
            shape = geom(lobe['afterPath'])
            contacts = [a for a in anchors if lobe['layerId'] in a['layerIds'] and G['bb_overlap'](shape.bounds, a['shape'].bounds) and shape.intersection(a['shape']).area > 1e-12]
            lobe['originalGroundViaAnnulusContacts'] = [a['id'] for a in contacts if a['kind'] == 'VIA']
            lobe['groundPadContactsAtProposedPositions'] = [a['id'] for a in contacts if a['kind'] == 'PAD']
            lobe['noDirectPadOrViaContactDetected'] = not contacts
            lobe['contactQualification'] = 'Literal nominal copper intersects native via annulus/pad geometry; positive-area contact only. This is not a multi-layer MCU-VSS reach proof and does not include same-layer trace/fill-neighbor chains.'
            lobe_creates.append(lobe)
    blocked = [a for a in audits if a['status'].startswith('BLOCKED')]
    changed_inputs = ([str(args.source)] if sha(args.source) != source_sha else []) + ([str(args.placement)] if sha(args.placement) != placement_sha else []) + [str(p) for p in args.routes if sha(p) != route_sha[str(p)]]
    changed_inputs += [str(Path(__file__))] if sha(Path(__file__)) != generator_sha else []
    if args.approved_outer_notches and sha(args.approved_outer_notches) != approval_sha:
        changed_inputs.append(str(args.approved_outer_notches))
    if args.extra_copper and sha(args.extra_copper) != extra_sha:
        changed_inputs.append(str(args.extra_copper))
    if changed_inputs:
        blocked.append({'status': 'BLOCKED_INPUT_CHANGED_DURING_RUN', 'paths': changed_inputs})
    inputs = {'source': str(args.source.resolve()), 'sourceSha256': source_sha,
              'placement': str(args.placement.resolve()), 'placementSha256': placement_sha,
              'routes': [{'path': str(p.resolve()), 'sha256': route_sha[str(p)]} for p in args.routes]}
    if args.approved_outer_notches:
        inputs['approvedOuterNotchScopePath'] = str(args.approved_outer_notches.resolve())
        inputs['approvedOuterNotchScopeSha256'] = approval_sha
    report = {'schema': 'adc10-labtool-offline-bounded-static-fill-clearance-plan-v1', 'passed': not blocked,
              'generatorPath': str(Path(__file__).resolve()), 'generatorSha256': generator_sha,
              **inputs, 'projectNameRequired': 'STM32H747_MCU_BOARD_v19', 'pcbUuidRequired': '0ac2a19168000d8e',
              'actorCounts': dict(Counter(a['kind'] for a in actors)), 'clearanceMm': args.clearance_mm,
              'layers': sorted(layers), 'fillNets': sorted(nets), 'fillModifyOperations': operations,
              'fillCreateOperations': lobe_creates, 'preservedLobeCount': len(lobe_creates),
              'lobeDirectContactCounts': dict(Counter('NO_DIRECT_CONTACT' if l['noDirectPadOrViaContactDetected'] else 'DIRECT_PAD_OR_VIA_CONTACT' for l in lobe_creates)),
              'fillAudits': audits, 'blocked': blocked,
              'unmodifiedInvalidInputFills': [a for a in audits if a.get('validBefore') is False and not a['status'].startswith('BLOCKED')],
              'scopeOfPassed': 'Offline polygon validity, explicit closure, bounded difference and preserved contour geometry only; does not assert electrical ground anchoring, DRC, or fabrication readiness.',
              'nativeCalls': 0, 'wholePcbSetSource': False,
              'nativeDesignModified': False, 'manufacturingApproved': False,
              'preservationContract': 'Only listed FILL.path may change, after exact beforeBody guards. Other fields and all unaffected holes/arcs remain exact. Old outer boundaries are exact except separately approved primitive/body-hash/actor-key constrained local notches; their native vertices and edges outside approved masks remain exact. Invalid geometry is never repaired. Stop each primitive if an unapproved outer boundary is touched.',
              'limitations': ['Offline local copper subtraction only; parent must rebase exact source body guards after placement/cutback and check native readback geometry.', 'Does not prove every surviving ground region is MCU-VSS anchored; physical ground graph and strict unchanged-rule native DRC are separate mandatory gates.', 'Placement bounding rectangles are conservative copper supersets; no non-GND FILLs are changed by default.']}
    HERE.mkdir(parents=True, exist_ok=True)
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    audit_only = {k: v for k, v in report.items() if k not in {'fillModifyOperations', 'fillCreateOperations'}}
    audit_only['lobeSummary'] = [{k: v for k, v in l.items() if k not in {'afterPath', 'afterPathsExplicitlyClosedForApi'}} for l in lobe_creates]
    audit_only['operationManifestSha256'] = sha(target)
    audit_only['fillOperationCount'] = len(operations)
    audit_target = HERE / (args.output_prefix + '-audit.json')
    audit_target.write_text(json.dumps(audit_only, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': not blocked, 'manifest': str(target), 'sha256': sha(target), 'operations': len(operations),
                      'lobes': len(lobe_creates), 'actorCounts': report['actorCounts'], 'statusCounts': dict(Counter(a['status'] for a in audits)), 'blocked': blocked}, ensure_ascii=True))


if __name__ == '__main__':
    main()
