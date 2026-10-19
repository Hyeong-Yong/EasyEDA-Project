"""Read-only native PCB ECO audit; no EasyEDA or bridge calls."""
import collections
import csv
import hashlib
import json
import re
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VAL = ROOT / 'output/validation'
G = runpy.run_path(str(ROOT / 'output/candidates/adc10-dc-buffer-20261017/independent-adc10-candidate-graph-audit.py'))
READER = runpy.run_path(str(ROOT / 'scripts/build-adc10-labtool-libraries-20261018.py'))['read_snapshot']
BEFORE = VAL / 'native-adc10-pcb-labtool_pre_eco-20261018.epru'
AFTER = VAL / 'native-adc10-pcb-labtool_eco_applied-20261018.epru'
CHECK = ROOT / 'output/checkpoints/STM32H747_labtool_schematic_verified_20261018.epro2'
NET = VAL / 'native-adc10-labtool_schematic-Protel2-20261018.net'
CSV = VAL / 'native-adc10-labtool-eco-comparison-20261018.csv'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def natural(ref):
    m = re.fullmatch(r'([^0-9]+)([0-9]+)', ref)
    return (m[1], int(m[2])) if m else (ref, 0)


def owned(rows, owner):
    result = {}
    for (kind, rid), body in rows.items():
        if kind == 'ATTR' and body.get('parentId') == owner:
            result[kind, rid] = body
        elif kind == 'PAD_NET' and json.loads(rid)[1] == owner:
            result[kind, rid] = body
    return result


def main():
    errors = []
    before, after = G['parse'](BEFORE), G['parse'](AFTER)
    ba, br = G['attrs_for'](before)
    aa, ar = G['attrs_for'](after)
    targets = set(json.loads((HERE / 'independent-schematic-audit.json').read_text(encoding='utf8'))['independentExpectedContract'])
    docs = {doc: {(h['type'], h.get('id')): b for h, b in rows.values()} for doc, rows in READER(CHECK).items()}
    sch = {}
    sch_attrs = {}
    csvrows = list(csv.reader(CSV.read_text(encoding='utf-16').splitlines(), delimiter='\t'))
    for doc, rows in docs.items():
        if doc[0] != 'SCH_PAGE':
            continue
        a, refs = G['attrs_for'](rows)
        for ref, cid in refs.items():
            if a[cid].get('Convert to PCB') != 'yes':
                continue
            info = {k: a[cid].get(k) for k in ('Unique ID', 'Device', 'Footprint', 'Value')}
            if ref in sch and sch[ref] != info:
                errors.append({'splitSchematicRefConflict': ref})
            sch[ref] = info
            sch_attrs[ref] = a[cid]
    nettext = NET.read_text(encoding='utf-8-sig')
    nodes = runpy.run_path(str(ROOT / 'scripts/verify-native-netlist.py'))['parse_protel2'](nettext)
    net = {(p['ref'], str(p['number'])): p['net'] for p in nodes}
    blocks = {}
    for block in re.findall(r'(?ms)^\[\s*\n(.*?)^\]', nettext):
        lines = [x.strip() for x in block.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and (not lines[-1] or lines[-1] == '*'):
            lines.pop()
        values = {lines[i]: lines[i + 1] for i in range(0, len(lines) - 1, 2)}
        ref = values.get('DESIGNATOR')
        if not ref or ref in blocks:
            errors.append({'duplicateNetlistRef': ref})
        blocks[ref] = values
    expected_new = ({f'U{i}' for i in range(20, 33)} | {f'R{i}' for i in range(177, 205)} |
                    {f'C{i}' for i in range(120, 150)} | {f'C{i}' for i in range(150, 161)} | {'D20'})
    missing_refs = sorted(set(br) - set(ar), key=natural)
    new_refs = set(ar) - set(br)
    if len(br) != 354 or len(ar) != 437 or set(ar) != set(sch) or set(ar) != set(blocks) or new_refs != expected_new or missing_refs:
        errors.append({'componentMembership': {'before': len(br), 'after': len(ar), 'schematic': len(sch), 'missing': missing_refs, 'unexpectedNew': sorted(new_refs ^ expected_new)}})
    uids = {r: after['COMPONENT', cid].get('attrs', {}).get('Unique ID') for r, cid in ar.items()}
    uid_changes = []
    position_changes = []
    component_structural_changes = []
    remapped = []
    attribute_changes = []
    footprints_changed = []
    non_target_owner_changes = []
    for ref, cid in br.items():
        new_id = ar.get(ref)
        if new_id is None:
            continue
        old, new = before['COMPONENT', cid], after['COMPONENT', new_id]
        if old.get('attrs', {}).get('Unique ID') != uids[ref]:
            uid_changes.append(ref)
        geometry = {f: [old.get(f), new.get(f)] for f in ('x', 'y', 'angle', 'layerId') if old.get(f) != new.get(f)}
        if geometry:
            position_changes.append({'ref': ref, 'fields': geometry})
        if cid != new_id:
            remapped.append({'ref': ref, 'beforePrimitiveId': cid, 'afterPrimitiveId': new_id, 'uniqueId': uids[ref]})
        structure = {f: [old.get(f), new.get(f)] for f in old.keys() | new.keys() if f != 'attrs' and old.get(f) != new.get(f)}
        if structure:
            component_structural_changes.append({'ref': ref, 'fields': structure})
        changes = {f: [old.get('attrs', {}).get(f), new.get('attrs', {}).get(f)] for f in old.get('attrs', {}).keys() | new.get('attrs', {}).keys() if old.get('attrs', {}).get(f) != new.get('attrs', {}).get(f)}
        if changes:
            attribute_changes.append({'ref': ref, 'fields': changes})
            extra = set(changes) - {'Name', 'Value', 'Channel ID'}
            # The comparison explicitly updates this existing reference-output
            # capacitor's voltage-rating metadata.  Check both the independent
            # saved schematic attribute and the actually checked CSV action.
            if extra == {'Voltage Rating'} and ref == 'C104':
                allowed = (new.get('attrs', {}).get('Voltage Rating') == sch_attrs[ref].get('Voltage Rating') == '10 V' and
                           any(len(r) > 4 and r[0] == '\u2713' and r[1:3] == ['Update Property', 'C104:Voltage Rating'] and r[4] == '10 V' for r in csvrows))
                if allowed:
                    extra.clear()
            if ref not in targets or extra:
                errors.append({'unexpectedComponentAttrs': attribute_changes[-1]})
        if ba[cid].get('Footprint') != aa[new_id].get('Footprint'):
            footprints_changed.append(ref)
        if ref not in targets:
            if old != new or cid != new_id or owned(before, cid) != owned(after, new_id):
                non_target_owner_changes.append(ref)
    if uid_changes or position_changes or component_structural_changes or non_target_owner_changes:
        errors.append({'oldComponentPreservation': {'uidChanges': uid_changes, 'positionChanges': position_changes, 'structuralChanges': component_structural_changes, 'nonTargetOwnerChanges': non_target_owner_changes}})
    if set(footprints_changed) != {'U9', 'C105'}:
        errors.append({'unexpectedFootprintReplacement': footprints_changed})
    if len(set(uids.values())) != 437 or None in uids.values():
        errors.append({'missingOrDuplicatePcbUniqueIds': True})
    source_mismatches = []
    values_checked = []
    for ref, cid in ar.items():
        for field in ('Device', 'Footprint'):
            if aa[cid].get(field) != sch[ref][field]:
                source_mismatches.append({'ref': ref, 'field': field, 'schematic': sch[ref][field], 'pcb': aa[cid].get(field)})
        if uids[ref] != sch[ref]['Unique ID'] or uids[ref] != blocks[ref].get('Unique ID'):
            source_mismatches.append({'ref': ref, 'field': 'Unique ID'})
        if ref in targets:
            device = docs['DEVICE', aa[cid]['Device']]
            meta = next(b for (t, _), b in device.items() if t == 'META')
            value = after['COMPONENT', cid].get('attrs', {}).get('Value', meta.get('attributes', {}).get('Value'))
            values_checked.append({'ref': ref, 'schematicValue': sch[ref]['Value'], 'pcbEffectiveValue': value})
            if value != sch[ref]['Value']:
                source_mismatches.append({'ref': ref, 'field': 'Value', 'schematic': sch[ref]['Value'], 'pcb': value})
    if source_mismatches:
        errors.append({'schematicComponentBindingMismatch': source_mismatches})
    reverse = {v: k for k, v in ar.items()}
    padnets = {}
    physical_pad_errors = []
    for (kind, rid), body in after.items():
        if kind != 'PAD_NET':
            continue
        _, cid, num, pad_id = json.loads(rid)
        ref = reverse[cid]
        pin = ref, str(num)
        netname = body.get('padNet')
        if pin in padnets and padnets[pin] != netname:
            physical_pad_errors.append({'conflictingDuplicatePadNumber': pin})
        padnets[pin] = netname
        fp = docs['FOOTPRINT', aa[cid]['Footprint']]
        pad = fp.get(('PAD', pad_id))
        if pad is None or str(pad.get('num')) != str(num):
            physical_pad_errors.append({'pin': pin, 'footprint': aa[cid]['Footprint'], 'padId': pad_id, 'reason': 'missing physical pad or wrong number'})
    connected = {k: v for k, v in padnets.items() if v}
    pin_mismatch = [{'pin': k, 'schematic': net.get(k), 'pcb': connected.get(k)} for k in net.keys() | connected.keys() if net.get(k) != connected.get(k)]
    if len(net) != len(nodes) or len(net) != 1342 or connected != net or physical_pad_errors:
        errors.append({'padNetContract': {'schematicPins': len(net), 'pcbPins': len(connected), 'differences': pin_mismatch, 'physicalPadErrors': physical_pad_errors}})
    protected_kinds = set(k[0] for k in before) - {'DOCHEAD', 'COMPONENT', 'ATTR', 'PAD_NET', 'NET', 'RULE_SELECTOR'}
    protected_before = {k: v for k, v in before.items() if k[0] in protected_kinds}
    protected_after = {k: v for k, v in after.items() if k[0] in protected_kinds}
    protected_diff = [k for k in protected_before.keys() | protected_after.keys() if protected_before.get(k) != protected_after.get(k)]
    net_selector_diff = [k for k, v in before.items() if k[0] in {'NET', 'RULE_SELECTOR'} and after.get(k) != v]
    other_unowned_attrs = [k for k, v in before.items() if k[0] == 'ATTR' and v.get('parentId') not in br.values() and after.get(k) != v]
    if protected_diff or net_selector_diff or other_unowned_attrs:
        errors.append({'protectedRecordsChanged': {'other': protected_diff, 'existingNetsSelectors': net_selector_diff, 'unownedAttrs': other_unowned_attrs}})
    checked = [r for r in csvrows if len(r) > 2 and r[0] == '\u2713']
    unchecked = [r for r in csvrows if len(r) > 2 and not r[0] and r[1]]
    counts = dict(collections.Counter(r[1] for r in checked))
    expected_counts = {'Add Component': 83, 'Modify Device': 10, 'Modify Footprint': 2, 'Update Net': 102, 'Update Property': 85}
    if counts != expected_counts or len(unchecked) != 2 or {r[1] for r in unchecked} != {'Delete Design Rule', 'Modify Design Rule'}:
        errors.append({'unexpectedComparisonActions': {'checked': counts, 'unchecked': unchecked}})
    selectors_added = {k: v for k, v in after.items() if k[0] == 'RULE_SELECTOR' and k not in before}
    default_selector = {'ruleOrder': 4, 'ruleKeyValue': {}, 'copperValue': {}, 'innerPlaneValue': {}}
    bad_selectors = [k for k, v in selectors_added.items() if v != default_selector]
    if len(selectors_added) != 63 or bad_selectors:
        errors.append({'newNetRuleOverrides': bad_selectors})
    baseline = G['parse'](VAL / 'native-adc10-pcb-labtool_before-20261018.epru')
    prior_changes = [k for k in baseline.keys() | before.keys() if k[0] != 'DOCHEAD' and baseline.get(k) != before.get(k)]
    if prior_changes:
        errors.append({'preEcoBaselineChangedSinceLabtoolBefore': prior_changes})
    report = {
        'schema': 'adc10-labtool-native-pcb-eco-independent-audit-20261018-v1', 'passed': not errors,
        'before': str(BEFORE), 'beforeSha256': sha(BEFORE), 'after': str(AFTER), 'afterSha256': sha(AFTER),
        'schematicCheckpoint': str(CHECK), 'schematicCheckpointSha256': sha(CHECK),
        'schematicNetlist': str(NET), 'schematicNetlistSha256': sha(NET), 'comparisonCsvSha256': sha(CSV),
        'countsBefore': dict(collections.Counter(k[0] for k in before)), 'countsAfter': dict(collections.Counter(k[0] for k in after)),
        'fullPhysicalComponents': len(ar), 'originalPhysicalComponentsRetained': len(br), 'newComponentCount': len(new_refs),
        'newComponentRefs': sorted(new_refs, key=natural), 'missingOriginalRefs': missing_refs,
        'all354OriginalUniqueIdsPreserved': not uid_changes, 'all437UniqueIdsMatchSchematicAndNetlist': not source_mismatches and len(set(uids.values())) == 437,
        'oldComponentPhysicalPositionRotationLayerChanges': position_changes,
        'oldComponentNonAttrsBodyChanges': component_structural_changes, 'nativePrimitiveIdReplacements': remapped,
        'footprintReplacements': sorted(footprints_changed), 'targetComponentCount': len(targets),
        'existingOutsideTargetComponentOwnedBodyChanges': non_target_owner_changes,
        'all437SchematicDeviceFootprintBindingsMatch': not source_mismatches,
        'targetEffectiveValuesChecked': values_checked, 'existingComponentAttrsChanges': attribute_changes,
        'connectedLogicalPins': len(connected), 'all1342PcbPinNetsMatchSchematic': connected == net,
        'physicalPadNetRecords': sum(k[0] == 'PAD_NET' for k in after), 'distinctPhysicalPadNumbers': len(padnets),
        'padNetDifferences': pin_mismatch, 'padIdNumberFootprintErrors': physical_pad_errors,
        'ref5025UnconnectedPhysicalPins': {n: padnets.get(('U9', n)) for n in ('1', '3', '7', '8')},
        'protectedKinds': sorted(protected_kinds), 'protectedRecordCount': len(protected_before), 'protectedRecordBodyChanges': protected_diff,
        'allOriginalCopperOutlineRulesStackHolesJ18BodiesExact': not protected_diff,
        'allExistingNetAndRuleSelectorBodiesExact': not net_selector_diff,
        'comparisonCheckedActionCounts': counts, 'comparisonUncheckedRuleActions': unchecked,
        'uncheckedDesignRulesWereNotApplied': not protected_diff and not net_selector_diff,
        'newNetRuleSelectorsDefaultOnly': not bad_selectors, 'newNetRuleSelectors': len(selectors_added),
        'preEcoVsLabtoolBeforeNonHeaderChanges': prior_changes,
        'errors': errors, 'nativeApiCalls': 0, 'nativeFilesModified': False,
        'routingVerified': False, 'drcVerified': False, 'manufacturingApproved': False,
        'limitations': ['ECO connectivity/binding and bounded preservation audit only; 83 new components remain at native off-board default locations.', 'Old routed copper is preserved intentionally, so topology changes require explicit cutback/reroute and fresh strict DRC before completion.']}
    out = HERE / 'independent-native-eco-audit.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': report['passed'], 'report': str(out), 'sha256': sha(out), 'errors': errors}, ensure_ascii=True))


if __name__ == '__main__':
    main()
