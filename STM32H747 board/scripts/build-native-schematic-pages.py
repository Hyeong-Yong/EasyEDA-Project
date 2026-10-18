"""Rebuild the reference geometry and electrical wires in the installed 3.2 format.

Native library-linked components are added when the verified library manifest
is supplied. Drafts are explicitly not manufacturing-complete schematics.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import uuid
import time
import zipfile
from collections import Counter
from pathlib import Path
from pypdf import PdfReader
from extract_page1_vectors import extract_vectors

ROOT=Path(__file__).resolve().parent.parent
F=100/72
VISUAL_EPSILON=0.001
# The five authoritative PDF sheets share one title block.  The visual QA
# repair plan proves that draw orders 79..93 are exactly the 15 vector glyphs
# spelling the excluded company name on every sheet; bbox text extraction had
# suppressed only orders 89 and 90 and is not sufficient by itself.
COMPANY_GLYPH_DRAW_ORDERS=frozenset(range(79,94))
TICKET=0

def rid(label):
    return uuid.uuid5(uuid.NAMESPACE_URL,'stm32h747-native/'+label).hex[:16]

def rec(kind,body,identity=None):
    global TICKET
    if kind=='DOCHEAD':
        TICKET=0
        head={'type':kind}
    else:
        TICKET+=1
        head={'type':kind,'ticket':TICKET}
    if identity is not None: head['id']=identity
    return json.dumps(head,separators=(',',':'),ensure_ascii=False)+'||'+json.dumps(body,separators=(',',':'),ensure_ascii=False)+'|'

def attr(parent,key,value,label,font_size=None):
    return rec('ATTR',{'parentId':parent,'key':key,'value':str(value),'keyVisible':False,'valueVisible':False,'x':None,'y':None,'rotation':0,'align':'LEFT_BOTTOM','zIndex':1,'locked':False,'groupId':'','color':None,'fillColor':None,'fontFamily':None,'fontSize':font_size,'fontWeight':None,'italic':None,'underline':None,'strikeout':None},rid(label))

def segment_key(a,b):
    return tuple(sorted((tuple(round(v,4) for v in a),tuple(round(v,4) for v in b))))

def flattened(subpath):
    points=[]
    previous=None
    for seg in subpath['segments']:
        op=seg['op']
        if op in ('M','L'):
            previous=seg['pt_top_left']
            points.append(previous)
        elif op=='C':
            if previous is None: raise ValueError('Curve without start')
            p0=previous
            p1,p2,p3=seg['pt_top_left']
            size=max(math.dist(p0,p1),math.dist(p1,p2),math.dist(p2,p3))
            samples=max(16,min(128,math.ceil(size*4)))
            for i in range(1,samples+1):
                t=i/samples
                points.append([(1-t)**3*p0[k]+3*(1-t)**2*t*p1[k]+3*(1-t)*t*t*p2[k]+t**3*p3[k] for k in (0,1)])
            previous=p3
        else: raise ValueError(op)
    return [round(v*F,8) for point in points for v in point]

def build_page(semantic,config,reader,library=None,electrical=None):
    page_no=semantic['pdf_page']
    item=next(x for x in config['pages'] if x['sourcePdfPage']==page_no)
    width=semantic['size']['width_easyeda']
    height=semantic['size']['height_easyeda']
    vectors,images=extract_vectors(reader,page_no-1)
    output=ROOT/'output'/'native-schematics'
    output.mkdir(exist_ok=True,parents=True)
    stamp=int(time.time()*1000)
    log=[rec('DOCHEAD',{'docType':'SCH_PAGE','uuid':item['uuid'],'client':rid('client'),'editVersion':'3.2.206','updateTime':stamp,'version':str(stamp),'user':{'uuid':config['schematicUuid']}}),rec('META',{'title':item['name'],'schematic':config['schematicUuid'],'source':'','zIndex':page_no-1},'META'),rec('CANVAS',{'originX':0,'originY':0},'CANVAS')]
    log.append(rec('RECT',{'partId':'','groupId':'','locked':True,'zIndex':-100,'dotX1':0,'dotY1':0,'dotX2':width,'dotY2':height,'radiusX':0,'radiusY':0,'rotation':0,'strokeColor':'','strokeStyle':'SOLID','fillColor':'#FFFFFF','strokeWidth':0,'fillStyle':'SOLID'},rid(f'{page_no}/paper')))
    wire_lookup={segment_key(w['p1'],w['p2']):w for w in semantic['wire_segments']}
    suppress=[w['bbox']['top_left_pt'] for w in semantic['suppressed_company_text_words']]
    skipped=[]
    counts=Counter()
    converted=set()
    instances=[i for i in library['instances'] if i['page']==page_no] if library else []
    owned=set()
    if library:
        for instance in instances:
            owned.update(instance.get('owned_vector_orders',[]))
    for vector in vectors:
        label=f"{page_no}/vector/{vector['draw_order']}"
        if vector['draw_order'] in COMPANY_GLYPH_DRAW_ORDERS:
            skipped.append(vector['draw_order'])
            continue
        if vector['draw_order'] in owned:
            continue
        bbox=vector['bounds_pt_top_left']
        if any(bbox[0]>=b[0]-.5 and bbox[1]>=b[1]-.5 and bbox[2]<=b[2]+.5 and bbox[3]<=b[3]+.5 for b in suppress):
            skipped.append(vector['draw_order'])
            continue
        if vector['geometry']=='line' and vector['stroke_hex']=='#009600':
            ends=[s['pt_top_left'] for s in vector['subpaths'][0]['segments']]
            key=segment_key(*ends)
            if key in wire_lookup:
                converted.add(key)
                continue
        for subidx,sub in enumerate(vector['subpaths']):
            if len(vector['subpaths'])>1 and vector['fill']:
                raise ValueError('Compound filled path needs explicit winding preservation')
            points=flattened(sub)
            if sub['closed'] and points[:2]!=points[-2:]: points.extend(points[:2])
            native_points=[{'x':points[i],'y':points[i+1]} for i in range(0,len(points),2)]
            fill_color=vector['fill_hex'] or ''
            stroke_color=(vector['stroke_hex'] or '') if vector['stroke'] else (fill_color if vector['fill'] else '')
            stroke_width=vector['line_width_pt']*F if vector['stroke'] else (VISUAL_EPSILON if vector['fill'] else 0)
            body={'partId':'','groupId':'','locked':False,'zIndex':vector['draw_order'],'points':native_points,'closed':sub['closed'] or vector['fill'],'strokeColor':stroke_color,'strokeStyle':'SOLID','fillColor':fill_color,'strokeWidth':stroke_width,'fillStyle':'SOLID' if vector['fill'] else 'NONE','startShape':None,'endShape':None}
            log.append(rec('POLY',body,rid(label+'/'+str(subidx))))
            counts['POLY']+=1
    if set(skipped)!=COMPANY_GLYPH_DRAW_ORDERS:
        raise ValueError(f'Page {page_no}: exact 15-vector company glyph omission contract changed: {sorted(skipped)}')
    page_links=next((p for p in electrical['pages'] if p['pdf_page']==page_no),None) if electrical else None
    if not page_links:raise ValueError('Verified electrical wire-group plan is required')
    seen_segments=set()
    for group in page_links['wire_groups']:
        wid=group['native_wire_id']
        log.append(rec('WIRE',{'groupId':'','locked':False,'zIndex':len(vectors)+group['index']},wid))
        for idx,line_id in zip(group['segment_indices'],group['line_ids'],strict=True):
            if idx in seen_segments:raise ValueError('Duplicate wire segment')
            seen_segments.add(idx)
            w=semantic['wire_segments'][idx]
            if w.get('net')!=group['net']:raise ValueError('Mixed-net wire group')
            a,b=w['p1_easyeda'],w['p2_easyeda']
            log.append(rec('LINE',{'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],'lineGroup':wid,'strokeColor':'#009600','strokeStyle':'SOLID','strokeWidth':w['line_width_pt']*F,'fillColor':'','fillStyle':'NONE'},line_id))
            counts['LINE']+=1
        net_attr=attr(wid,'NET',group['net'],f'{page_no}/wirenet/{group["index"]}',VISUAL_EPSILON)
        relevance_attr=attr(wid,'Relevance','[]',f'{page_no}/wirerelevance/{group["index"]}')
        log.append(net_attr.replace(rid(f'{page_no}/wirenet/{group["index"]}'),group['native_net_attr_id'],1))
        log.append(relevance_attr.replace(rid(f'{page_no}/wirerelevance/{group["index"]}'),group['native_relevance_attr_id'],1))
        counts['WIRE']+=1
    if seen_segments!=set(range(len(semantic['wire_segments']))):raise ValueError('Missing wire segment')
    for extra in page_links.get('supplemental_wire_groups',[]):
        wid=extra['native_wire_id']
        log.append(rec('WIRE',{'groupId':'','locked':False,'zIndex':len(vectors)+len(page_links['wire_groups'])+extra['index']},wid))
        a,b=extra['p1_easyeda'],extra['p2_easyeda']
        log.append(rec('LINE',{'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],'lineGroup':wid,'strokeColor':'#009600','strokeStyle':'SOLID','strokeWidth':0.6,'fillColor':'','fillStyle':'NONE'},extra['line_id']))
        net_attr=attr(wid,'NET',extra['net'],f'{page_no}/supplement/{extra["index"]}/net',VISUAL_EPSILON)
        relevance_attr=attr(wid,'Relevance','[]',f'{page_no}/supplement/{extra["index"]}/relevance')
        log.append(net_attr.replace(rid(f'{page_no}/supplement/{extra["index"]}/net'),extra['native_net_attr_id'],1))
        log.append(relevance_attr.replace(rid(f'{page_no}/supplement/{extra["index"]}/relevance'),extra['native_relevance_attr_id'],1))
        counts['WIRE']+=1;counts['LINE']+=1;counts['SUPPLEMENTAL_CONNECTION']+=1
    for index,instance in enumerate(instances):
        if 'placement_easyeda' not in instance:
            raise ValueError('Library lacks verified centered placement coordinates')
        cid=rid(f'{page_no}/component/{instance["reference"]}')
        x,y=instance['placement_easyeda']
        base=instance['base_reference']
        info=library['manifest']
        def identity_json(kind,uid):
            if not uid:return ''
            entry=info[kind][base]
            return json.dumps({'uuid':uid,'name':entry['title'],'source':uid+'|project'},separators=(',',':'),ensure_ascii=False)
        names={'DeviceName':identity_json('devices',instance['device_uuid']),'Devices':'[]','SymbolName':identity_json('symbols',instance['symbol_uuid']),'Symbols':'[]','FootprintName':identity_json('footprints',instance.get('footprint_uuid')),'Footprints':'[]'}
        log.append(rec('COMPONENT',{'partId':instance.get('native_part_id',instance['subpart']),'groupId':'','locked':False,'zIndex':len(vectors)+1000+index,'x':x,'y':y,'rotation':0,'isMirror':False,'attrs':names},cid))
        properties={'Device':instance['device_uuid'],'Symbol':instance['symbol_uuid'],'Designator':base,'Unique ID':rid('physical/'+base),'Value':instance['value'],'Name':instance['value'],'Add into BOM':'yes' if instance.get('footprint_uuid') and not instance['dnp'] else 'no','Convert to PCB':'yes' if instance.get('footprint_uuid') else 'no','DNP':'yes' if instance['dnp'] else 'no'}
        if base=='U1': properties['Multi-Part Group']=rid('physical/'+base)
        if instance.get('footprint_uuid'): properties['Footprint']=instance['footprint_uuid']
        if instance.get('is_net_flag'):
            if not instance.get('global_net_name'):raise ValueError('Power flag lacks global net')
            properties['Global Net Name']=instance['global_net_name']
            properties['Name']=instance['global_net_name']
            properties['Relevance']='[]'
        for key,value in properties.items(): log.append(attr(cid,key,value,f'{page_no}/componentattr/{base}/{instance["subpart"]}/{key}'))
        for pin in info['symbols'][base]['pins']:
            if pin['part']!=instance.get('native_part_id',instance['subpart']):continue
            if pin.get('net') is not None:continue
            if not pin.get('primitive_id'):raise ValueError('NC pin lacks native template id')
            parent=cid+'-'+pin['primitive_id']
            line=attr(parent,'NO_CONNECT','yes',f'{page_no}/nc/{base}/{pin["number"]}')
            h,b=line.split('||')
            body=json.loads(b.rstrip('|'))
            body['x']=x+pin['x'];body['y']=y+pin['y']
            log.append(h+'||'+json.dumps(body,separators=(',',':'))+'|')
            counts['NO_CONNECT']+=1
        counts['COMPONENT']+=1
    source='\n'.join(log)+'\n'
    path=output/(item['name']+'.epru')
    path.write_text(source,encoding='utf8')
    return {'pdfPage':page_no,'uuid':item['uuid'],'name':item['name'],'path':str(path),'sha256':hashlib.sha256(source.encode()).hexdigest(),'counts':dict(counts),'imagesSuppressed':len(images),'companyGlyphPathsSuppressed':len(skipped),'nativeComponents':len(instances),'componentOwnedVectorCount':len(owned),'stage':'native library-linked schematic; runtime netlist and ERC verification pending' if library else 'reference-geometry-and-electrical-wires; library components pending','wireVectorMatches':len(converted)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pages',nargs='+',type=int,default=list(range(2,7)))
    parser.add_argument('--with-libraries',action='store_true')
    args=parser.parse_args()
    data=json.loads((ROOT/'output/semantic/schematic-pages-2-6.json').read_text(encoding='utf8'))
    config=json.loads((ROOT/'config/easyeda-project.json').read_text(encoding='utf8'))
    reader=PdfReader(data['source']['path'])
    library=json.loads((ROOT/'output/native-libraries/devices.json').read_text(encoding='utf8')) if args.with_libraries else None
    if library:library['manifest']=json.loads((ROOT/'output/native-libraries/manifest.json').read_text(encoding='utf8'))
    electrical=json.loads((ROOT/'output/semantic/electrical-links.json').read_text(encoding='utf8'))
    manifest=[build_page(page,config,reader,library,electrical) for page in data['pages'] if page['pdf_page'] in args.pages]
    target=ROOT/'output/native-schematics/manifest.json'
    target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    stamp=int(time.time()*1000)
    source=(ROOT/'output/native-libraries/embedded-library.epru').read_text(encoding='utf8') if library else ''
    source+=rec('DOCHEAD',{'docType':'SCH','uuid':config['schematicUuid'],'client':rid('client'),'updateTime':stamp,'version':str(stamp),'user':{'uuid':config['schematicUuid']}})+'\n'+rec('META',{'title':'MCU_BOARD','board':'','source':'','zIndex':1},'META')+'\n'
    source+=''.join(Path(item['path']).read_text(encoding='utf8') for item in manifest)
    name=config['expectedProjectName']
    package=target.parent/(name+('_schematics_native.epro2' if library else '_schematics_draft.epro2'))
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('project2.json',json.dumps({'title':name,'cbb_project':False,'editorVersion':'3.2.206','description':'Latest PDF pages 2–6 reconstruction draft. Library-linked components and PCB verification pending.','tags':'[]'},ensure_ascii=False))
        archive.writestr(name+'.epru',source)
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
