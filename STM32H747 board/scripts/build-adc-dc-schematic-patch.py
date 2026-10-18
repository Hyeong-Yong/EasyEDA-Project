"""Create a bounded DC-preserving ADC1 schematic edit plan; never contacts EDA."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/candidates/adc-dc-buffer'
BASE = ROOT / 'output/validation/native-adc-dc-before-page-6-20261016.epru'
LIB = OUT / 'adc-dc-runtime-library-map.json'


def parse(source):
    result = []
    for line in source.splitlines():
        if '||' not in line:
            continue
        head, body = line.split('||', 1)
        result.append({'h': json.loads(head), 'b': json.loads(body.rstrip('|'))})
    return result


def uid(key):
    return hashlib.sha256(('stm32h747-adc-dc-20261016/' + key).encode()).hexdigest()[:16]


def main():
    baseline = BASE.read_text(encoding='utf-8')
    before = parse(baseline)
    rows = copy.deepcopy(before)
    libraries = json.loads(LIB.read_text(encoding='utf-8'))
    index = {r['h'].get('id'): r for r in rows if r['h'].get('id')}
    by_ref = {}
    attrs = {}
    for r in rows:
        if r['h']['type'] == 'ATTR':
            attrs.setdefault(r['b']['parentId'], {})[r['b']['key']] = r
            if r['b']['key'] == 'Designator':
                by_ref[r['b']['value']] = r['b']['parentId']
    ticket = max(r['h'].get('ticket', 0) for r in rows)
    removed = set()
    component_spec = []

    def add(kind, body, key):
        nonlocal ticket
        ticket += 1
        identity = uid(key)
        assert identity not in index, (kind, key)
        r = {'h': {'type': kind, 'id': identity, 'ticket': ticket}, 'b': body}
        rows.append(r)
        index[identity] = r
        return identity

    def attr(parent, key, value, x=None, y=None, visible=False, size=5.5):
        return add('ATTR', {'x': x, 'y': y, 'rotation': 0, 'color': None,
            'fontFamily': None, 'fontSize': size if visible else None,
            'fontWeight': False, 'italic': False, 'underline': False,
            'strikeout': False, 'align': 'LEFT_BOTTOM', 'value': value,
            'keyVisible': False, 'valueVisible': visible, 'key': key,
            'fillColor': None, 'parentId': parent, 'zIndex': 100, 'locked': False},
            f'{parent}/attr/{key}')

    def text(value, x, y, key, size=6, color='#006666'):
        return add('TEXT', {'x': x, 'y': y, 'rotation': 0, 'color': color,
            'fillColor': None, 'fontFamily': 'Arial', 'fontSize': size,
            'fontWeight': False, 'italic': False, 'underline': False,
            'strikeout': False, 'align': 'LEFT_BOTTOM', 'value': value,
            'zIndex': 10000, 'locked': False}, key)

    def wire(net, points, key, label=None):
        w = add('WIRE', {'zIndex': 9000, 'locked': False}, key)
        for i, (a, b) in enumerate(zip(points, points[1:])):
            assert a != b
            add('LINE', {'startX': a[0], 'startY': a[1], 'endX': b[0], 'endY': b[1],
                'lineGroup': w, 'strokeColor': '#009600', 'strokeStyle': 'SOLID',
                'strokeWidth': 0.6, 'fillColor': None, 'fillStyle': None}, f'{key}/line/{i}')
        attr(w, 'NET', net, points[0][0], points[0][1], False)
        attr(w, 'Relevance', '[]')
        if label:
            text(net, label[0], label[1], f'{key}/label', 5.5)
        return w

    def bind(ref, device_key, x, y, rotation=0, existing=True, label=None):
        device = libraries['devices'][device_key]
        symbol = next(s for s in libraries['symbols'].values() if s['uuid'] == device['symbolUuid'])
        footprint = next(f for f in libraries['footprints'].values() if f['uuid'] == device['footprintUuid'])
        packed = lambda obj: json.dumps({'uuid': obj['uuid'], 'name': obj['title'],
            'source': obj.get('source', obj['uuid'] + '|project')}, separators=(',', ':'))
        body = {'partId': 'A', 'x': x, 'y': y, 'rotation': rotation, 'isMirror': False,
            'attrs': {'DeviceName': packed(device), 'SymbolName': packed(symbol),
                      'FootprintName': packed(footprint), 'Devices': '[]',
                      'Symbols': '[]', 'Footprints': '[]'}, 'zIndex': 9100, 'locked': False}
        cid = by_ref[ref] if existing else add('COMPONENT', body, f'component/{ref}')
        if existing:
            index[cid]['b'] = body
        values = dict(device['attributes'])
        values.update({'Device': device['uuid'], 'Symbol': symbol['uuid'],
            'Footprint': footprint['uuid'], 'Designator': ref,
            'Unique ID': attrs[cid]['Unique ID']['b']['value'] if existing else uid('physical/' + ref),
            'Name': values['Value'], 'Add into BOM': 'yes', 'Convert to PCB': 'yes', 'DNP': 'no'})
        lx, ly = label or (x + 7, y - 8)
        for key, value in values.items():
            if existing and key in attrs[cid]:
                r = attrs[cid][key]
                r['b']['value'] = value
                r['b']['keyVisible'] = False
                r['b']['valueVisible'] = key in ('Designator', 'Value')
                if key in ('Designator', 'Value'):
                    r['b'].update(x=lx, y=ly if key == 'Designator' else ly + 7,
                        fontSize=5.5, color='#006666', align='LEFT_BOTTOM')
            else:
                attr(cid, key, value, lx if key in ('Designator', 'Value') else None,
                    (ly if key == 'Designator' else ly + 7) if key in ('Designator', 'Value') else None,
                    key in ('Designator', 'Value'))
        component_spec.append({'ref': ref, 'componentId': cid, 'deviceKey': device_key,
            'deviceUuid': device['uuid'], 'symbolUuid': symbol['uuid'], 'footprintUuid': footprint['uuid'],
            'x': x, 'y': y, 'rotation': rotation, 'new': not existing, 'value': values['Value']})
        return cid

    mix_wires = ['9cbcdfde5f635eb8', '6310f649efc85c6b', '30b085aeb466535e']
    breaks = ['27c945a3c9265f18', 'c8320e9b13265882', '470daad0a8ae54c4']
    power_wires = ['7ddd73c0b38755f1', 'd6843d6273b35f38', 'f6a06b7190d45f7e']
    for i, mix_x in enumerate((345, 680, 1010)):
        ch = i + 1
        input_x = mix_x - 80
        series_x = mix_x + 50
        cap_x = mix_x + 80
        bind(f'R{137+i}', 'R6K8', mix_x, 170, 90, label=(mix_x+7, 165))
        bind(f'R{140+2*i}', 'R6K8', input_x, 190, label=(input_x-12, 177))
        bind(f'R{141+2*i}', 'R47', series_x, 190, label=(series_x-8, 177))
        bind(f'C{80+i}', 'C2N2', cap_x, 210, label=(cap_x+7, 207))
        for r in rows:
            if r['h']['type'] == 'ATTR' and r['b'].get('key') == 'NET':
                if r['b']['parentId'] == mix_wires[i]:
                    r['b']['value'] = f'ADC1_PRE{ch}'
                if r['b']['parentId'] == power_wires[i]:
                    r['b']['value'] = 'ADC_BIAS_2V5'
        for ref in (f'#PWR{97+i:03d}',):
            cid = by_ref[ref]
            removed.add(cid)
            removed.update(r['h']['id'] for r in rows if r['h']['type'] == 'ATTR' and r['b'].get('parentId') == cid)
        index[breaks[i]]['b']['endX'] = mix_x + 15
        text('ADC_BIAS_2V5', mix_x-28, 135, f'bias-label/{ch}', 5.5)
        text(f'ADC1_PRE{ch}', mix_x-18, 246, f'pre-label/{ch}', 5.5)
        wire(f'ADC1_DRV{ch}', [(mix_x+35,190),(mix_x+35,258)], f'driver-to-series/{ch}', (mix_x+37,257))
        text('C0G', cap_x+7, 230, f'c0g-label/{ch}', 4.5)
    # Only replace the obsolete VOUT annotation; retain the correct VIN annotation.
    for r in rows:
        b = r['b']
        if r['h']['type'] == 'POLY' and b.get('fillColor') == '#C20000':
            pts = b.get('points', [])
            if pts and all(454 <= p['x'] <= 528 and 169 <= p['y'] <= 176 for p in pts):
                removed.add(r['h']['id'])
    text('VADC = 0.25 V ... 2.25 V', 450, 172, 'adc-range', 5.3, '#CC0000')
    text('ADC1: DC coupled; CH1/CH2 = DC + 60 Hz; CH3 = DC; 15.6 kS/s/channel', 130, 735, 'header', 6.1)
    text('VIN = 2 x (VADC - 1.25 V), nominal. No series coupling capacitor.', 130, 747, 'transfer', 5.5)
    text('DC passes unchanged except gain/offset. VREF+ remains on existing VDDA supply.', 130, 759, 'limits', 5.0)
    ref_block_start = len(rows)
    ref_spec_start = len(component_spec)
    bind('U9', 'REF3325', 260, 800, existing=False, label=(235, 772))
    bind('C103', 'C1U', 165, 805, existing=False)
    bind('C104', 'C4U7', 390, 805, existing=False)
    bind('C105', 'C100N', 460, 805, existing=False)
    wire('+3V3', [(165,795),(165,790),(215,790)], 'ref-in', (155,785))
    wire('GND', [(165,815),(165,845)], 'ref-in-gnd', (150,851))
    wire('ADC_BIAS_2V5', [(305,790),(460,790),(460,795)], 'ref-out', (310,780))
    wire('ADC_BIAS_2V5', [(390,790),(390,795)], 'ref-out-cap', None)
    wire('GND', [(260,840),(260,845)], 'ref-gnd', (245,851))
    wire('GND', [(390,815),(390,845),(460,845),(460,815)], 'ref-out-gnd', (395,853))
    for r in rows[ref_block_start:]:
        b = r['b']
        for k in ('x', 'startX', 'endX'):
            if b.get(k) is not None:
                b[k] += 900
        for k in ('y', 'startY', 'endY'):
            if b.get(k) is not None:
                b[k] -= 10
    for spec in component_spec[ref_spec_start:]:
        spec['x'] += 900
        spec['y'] -= 10
    text('Dedicated ADC1 bias - do not connect to VDDA/VREF+', 1045, 751, 'ref-header', 5.5)
    for i, y in enumerate((880, 970, 1060)):
        ch = i + 1
        bind(f'U{10+i}', 'OPA320', 270, y, existing=False, label=(235,y-23))
        bind(f'C{97+i}', 'C10N', 175, y+10, existing=False, label=(133,y+8))
        bind(f'C{100+i}', 'C100N', 430, y-25, existing=False, label=(440,y-32))
        wire(f'ADC1_PRE{ch}', [(175,y),(175,y-10),(230,y-10)], f'buffer-input/{ch}', (150,y-17))
        wire('GND', [(175,y+20),(175,y+35)], f'buffer-input-gnd/{ch}', (162,y+41))
        wire(f'ADC1_DRV{ch}', [(315,y),(385,y)], f'buffer-out/{ch}', (327,y-6))
        wire(f'ADC1_DRV{ch}', [(230,y+10),(230,y+27),(335,y+27),(335,y)], f'buffer-feedback/{ch}')
        wire('+3V3', [(270,y-35),(270,y-40),(430,y-40),(430,y-35)], f'buffer-power/{ch}', (285,y-44))
        wire('GND', [(270,y+35),(270,y+40)], f'buffer-gnd/{ch}', (260,y+47))
        wire('GND', [(430,y-15),(430,y-5)], f'buffer-decouple-gnd/{ch}', (437,y-1))
    rows = [r for r in rows if r['h'].get('id') not in removed]
    ids = [r['h'].get('id') for r in rows if r['h'].get('id')]
    assert len(ids) == len(set(ids))
    assert len(component_spec) == 25
    before_map = {(r['h']['type'], r['h'].get('id')): r for r in before}
    after_map = {(r['h']['type'], r['h'].get('id')): r for r in rows}
    changed = []
    deleted = []
    added = []
    for key, r in before_map.items():
        if key not in after_map:
            deleted.append(r)
        elif r['b'] != after_map[key]['b']:
            changed.append({'type': key[0], 'id': key[1], 'before': r['b'], 'after': after_map[key]['b']})
    for key, r in after_map.items():
        if key not in before_map:
            added.append(r)
    source = ''.join(json.dumps(r['h'], separators=(',', ':')) + '||' + json.dumps(r['b'], separators=(',', ':')) + '|\n' for r in rows)
    candidate = OUT / '06_ADC_TIMER_DAC_dc_buffer_candidate.epru'
    candidate.write_text(source, encoding='utf-8', newline='\n')
    plan = {'schema': 'adc1-dc-coupled-three-channel-20261016-v1', 'pageUuid': 'a07bf8e4331877a8',
        'baselineSha256': hashlib.sha256(baseline.encode()).hexdigest(),
        'candidateSha256': hashlib.sha256(source.encode()).hexdigest(),
        'baselinePath': str(BASE), 'candidatePath': str(candidate), 'changes': changed,
        'deleted': deleted, 'added': added, 'components': component_spec,
        'electricalContract': {'channels': [0,1,16], 'dcCoupled': True, 'seriesCouplingCapacitors': 0,
            'sampleRatePerChannel': 15600, 'gain': 0.5, 'offsetV': 1.25,
            'inputRangeV': [-2,2], 'outputRangeV': [0.25,2.25],
            'inputBiasResistorsOhm': [6800,6800], 'biasReferenceV': 2.5,
            'preBufferCapF': 1e-8, 'adcSeriesROhm': 47, 'adcShuntCapF': 2.2e-9,
            'allThreeIndependentBuffers': True, 'vddaAndVrefUnchanged': True,
            'firmwareUnchanged': True, 'pcbAdcEcoNotApplied': True}}
    (OUT / 'adc-dc-schematic-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    print(json.dumps({'changed': len(changed), 'deleted': len(deleted), 'added': len(added),
        'components': len(component_spec), 'candidate': str(candidate), 'hash': plan['candidateSha256']}))


if __name__ == '__main__':
    main()
