import importlib.util, json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cio', Path(__file__).with_name('correction-io.py'))
cio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cio)
docs = cio.read_export(root/'backups/DAC8562_live_before_ERC_cleanup_2026-10-12.epro2')
targets={'R22','R23','R27','R29','R31','R33','R35','R37','R102','R112','C18','C19','C20','C21'}
for uid in ['e58bcc16379b10f4','e3a1c5f417017755']:
    doc=docs[uid]; attrs=cio.attrs(doc)
    for (typ,pid),(h,p) in doc['records'].items():
        if typ!='COMPONENT': continue
        a=attrs.get(pid,{})
        if a.get('Designator') in targets or pid in {'18093a22ee84d107','012e8b3f44d91252','47b66fd46f635b42','ece0cc04b3540a18'}:
            print(json.dumps({'page':uid,'id':pid,'comp':p,'attributes':a},ensure_ascii=False))
            dev=a.get('Device'); lib=docs.get(dev)
            if lib:
                stock=next(p['attributes'] for h,p in lib['records'].values() if 'attributes' in p)
                print('DIFF',json.dumps({k:[a.get(k),v] for k,v in stock.items() if a.get(k)!=v},ensure_ascii=False))
