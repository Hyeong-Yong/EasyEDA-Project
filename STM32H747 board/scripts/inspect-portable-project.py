"""Read-only inspection of exported EasyEDA portable project log."""
import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path

def inspect(path,selected=None):
    with zipfile.ZipFile(path) as archive:
        print('Entries:', archive.namelist())
        docs=[]
        for name in archive.namelist():
            if not name.endswith('.epru'):
                continue
            current=None
            for line in archive.read(name).decode('utf8').splitlines():
                if '||' not in line:
                    continue
                a,b=line.split('||',1)
                head=json.loads(a)
                body=json.loads(b.rstrip('|'))
                if head['type']=='DOCHEAD':
                    current={'header':body,'counts':Counter(),'meta':{},'samples':{},'pin_attributes':[]}
                    docs.append(current)
                elif current is not None:
                    current['counts'][head['type']]+=1
                    if head['type']=='META':
                        current['meta']=body
                    elif head['type'] not in current['samples']:
                        current['samples'][head['type']]={k:(v[:160]+'...' if isinstance(v,str) and len(v)>160 else v) for k,v in body.items()}
                    if current['header']['docType']=='SYMBOL' and head['type']=='ATTR':
                        current['pin_attributes'].append(body)
        if selected:docs=[d for d in docs if d['header'].get('uuid')==selected or d['meta'].get('title','').startswith(selected)]
        print(json.dumps(docs,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('path',type=Path)
    parser.add_argument('--select',help='Native UUID or title prefix')
    args=parser.parse_args()
    inspect(args.path,args.select)
