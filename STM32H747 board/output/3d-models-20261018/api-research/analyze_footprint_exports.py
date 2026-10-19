import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
INPUTS = [
    'footprint-file-sot23-5-bl2.json',
    'footprint-file-sot23-5-bl-original.json',
    'footprint-file-tsot23-5-bl-original.json',
]
results = []
for name in INPUTS:
    payload = json.loads((ROOT / name).read_text(encoding='utf-8'))
    blob = bytes.fromhex(payload['result']['file']['hex'])
    archive = zipfile.ZipFile(io.BytesIO(blob))
    docs = []
    for member in archive.namelist():
        if not member.endswith('.elibu'):
            continue
        text = archive.read(member).decode('utf-8')
        rows = []
        for line in text.splitlines():
            head, body = line.split('||', 1)
            rows.append((json.loads(head), json.loads(body.rstrip('|'))))
        attrs = {body['key']: body['value'] for head, body in rows if head['type'] == 'ATTR'}
        pads = [
            {'num': body['num'], 'center_mil': [body['centerX'], body['centerY']],
             'center_mm': [body['centerX'] * 0.0254, body['centerY'] * 0.0254]}
            for head, body in rows if head['type'] == 'PAD'
        ]
        docs.append({
            'archive_member': member,
            'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'meta': next(body for head, body in rows if head['type'] == 'META'),
            'attrs': attrs,
            'pads': pads,
            'model_related_rows': [
                {'header': head, 'body': body} for head, body in rows
                if '3D Model' in json.dumps(body) or head['type'] in ['MODEL', 'MODEL3D']
            ],
        })
    results.append({
        'evidence': name, 'uuid': payload['result']['key'],
        'library_uuid': payload['result']['libraryUuid'],
        'archive_size': len(blob), 'archive_sha256': hashlib.sha256(blob).hexdigest(),
        'members': archive.namelist(), 'documents': docs,
        'native_query_timestamp': payload['runner']['timestamp'],
    })

report = {
    'read_only_native_operations': True,
    'native_window': 'c020406e-b1fa-42b2-83be-6df87769a738',
    'expected_project': 'STM32H747_MCU_BOARD_v19',
    'library_uuid': '0819f05c4eef4c71ace90d822a990e87',
    'methods': {
        'search': {'call': "eda.lib_Footprint.search('SOT-23-5', undefined, undefined, 30, 1)", 'outcome': '30 official candidates'},
        'get_default': {'outcome': 'native error [object Object]'},
        'get_explicit_system': {'outcome': 'success, metadata only; no model3D or otherProperty field'},
        'getDocumentSource_default': {'outcome': 'bridge 30000 ms timeout'},
        'getDocumentSource_explicit_system': {'outcome': 'bridge 30000 ms timeout'},
        'getFootprintFileByFootprintUuid_single_explicit_system': {'outcome': 'success, source archive returned; no import/open/save'},
        'getFootprintFileByFootprintUuid_batch_explicit_system': {'outcome': 'undefined; not relied on'},
    },
    'evidence': results,
    'conclusions': {
        'pin1': 'All three exported BL official footprints have pad1 at x<0,y<0, three pads along negative Y and two along positive Y.',
        'model400e88a480ad4616a631bf409c145270_association_proven': False,
        'model400e88a480ad4616a631bf409c145270_bbox_proven': False,
        'no_model_link_in_export': 'All three source archives have only Footprint and Designator attributes; no 3D Model, 3D Model Transform, or 3D payload.',
        'limitation': 'Footprint pad coordinates do not establish independent model mesh default axes, native bbox, or model pin1 marking. No model orientation/scale should be claimed verified from these exports.',
    },
    'documentation': [
        {'path': '.tools/easyeda-api/references/classes/LIB_Footprint.md', 'line': 517, 'topic': 'get signature'},
        {'path': '.tools/easyeda-api/references/classes/LIB_Footprint.md', 'line': 580, 'topic': 'getDocumentSource signature and worker/network remarks'},
        {'path': '.tools/easyeda-api/references/classes/LIB_Footprint.md', 'line': 987, 'topic': 'search signature'},
        {'path': '.tools/easyeda-api/references/interfaces/ILIB_FootprintItem.md', 'line': 210, 'topic': 'model3D optional field added since v4.1.22, absent from installed result'},
        {'path': '.tools/easyeda-api/references/classes/SYS_FileManager.md', 'line': 727, 'topic': 'getFootprintFileByFootprintUuid signature, read-only downloadable archive'},
    ],
}
target = ROOT / 'footprint-sot23-5-readonly-audit.json'
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'output': str(target), 'exported_footprints': len(results), 'model_link_proven': False}, indent=2))
