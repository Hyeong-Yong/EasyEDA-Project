"""Set conservative route widths/clearance on the native EasyEDA DSN export."""
import json,re
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'output/pcb-two-zone'
def parse_sexp(text):
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^()\s]+',text)
    stack=[];root=None
    for t in tokens:
        if t=='(':
            item=[]
            if stack:stack[-1].append(item)
            else:root=item
            stack.append(item)
        elif t==')':stack.pop()
        else:stack[-1].append(t)
    assert not stack
    return root
def serialize(n,depth=0):
    if not isinstance(n,list):return n
    return '('+' '.join(serialize(x,depth+1) for x in n)+')'
if __name__=='__main__':
    tree=parse_sexp((OUT/'two-zone-v4.dsn').read_text(encoding='utf8'))
    structure=next(n for n in tree if isinstance(n,list) and n[0]=='structure')
    layers=[n for n in structure[1:] if isinstance(n,list) and n[0]=='layer']
    structure[:]=['structure',*layers,*[n for n in structure[1:] if n not in layers]]
    for i,(x,y) in enumerate([(5,5),(95,5),(5,95),(95,95)]):
        for layer in ['TopLayer','BottomLayer']:
            structure.append(['keepout','MH'+str(i+1)+layer,['circle',layer,str(7/.0254),str(x/.0254),str(y/.0254)]])
    network=next(n for n in tree if isinstance(n,list) and n[0]=='network')
    network[:]=[n for n in network if not (isinstance(n,list) and n[0] in {'net','class'} and not n[1].strip("'\""))]
    native=json.loads((OUT/'native-placement.json').read_text(encoding='utf8'))
    real_pads={p['id'].replace('e','',1) for p in native['pads']}
    library=next(n for n in tree if isinstance(n,list) and n[0]=='library')
    removed=[]
    for image in library:
        if not isinstance(image,list) or image[0]!='image':continue
        bad=[n for n in image if isinstance(n,list) and n[0]=='pin' and n[2] not in real_pads]
        removed.extend(n[2] for n in bad)
        image[:]=[n for n in image if n not in bad]
    changes=[]
    for n in network:
        if not isinstance(n,list) or n[0]!='class':continue
        name=n[1].strip("'\"")
        width='16' if name in {'SWP','SWN','VIN_SW','VIN_RAW'} else '14' if name in {'VPOS12','VNEG12','VDD5'} else '10'
        for field in n:
            if not isinstance(field,list) or field[0]!='rule':continue
            for r in field:
                if not isinstance(r,list):continue
                if r[0]=='width':r[1]=width
                if r[0] in {'clear','clearance'}:r[1]='6.3'
        changes.append({'net':name,'widthMil':float(width),'clearanceMil':6.3})
    (OUT/'routing-widths.json').write_text(json.dumps(changes,indent=2),encoding='utf8')
    (OUT/'two-zone-widths.dsn').write_text(serialize(tree)+'\n',encoding='utf8')
    print(json.dumps({'classes':len(changes),'excludedNonPadKeepoutPins':removed,'powerWidths':{r['net']:r['widthMil'] for r in changes if r['widthMil']!=10}}))
