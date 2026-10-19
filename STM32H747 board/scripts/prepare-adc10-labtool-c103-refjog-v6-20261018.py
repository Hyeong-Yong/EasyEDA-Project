"""Exploratory low-Z REF2V5 one-line detour to reserve local power bridge VIA."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018/routing'
r=json.loads((H/'v6-base-preserved-copper-with-two-ground-ports.json').read_text());r['newLineCreates']=[p for p in r['newLineCreates'] if p['key']!='LABTOOL_LOCAL_0432'];r['newViaCreates'].extend(json.loads((H/'six-layer-via-port-candidates-reference-c103-shortbridge-v6b.json').read_text())['viasProposed']);r['newViaCreates'].extend(json.loads((H/'six-layer-via-port-candidates-reference-c103-shortbridge-v6.json').read_text())['viasProposed']);r['newViaCreates'].extend(json.loads((H/'six-layer-via-port-candidates-reference-c103-rightpower-v6d.json').read_text())['viasProposed']);r['status']='EXPLORATION_NOT_NATIVE_NOT_FINAL';(H/'v6-c103-one-refline-removed-reserved-base.json').write_text(json.dumps(r,indent=2)+'\n')
