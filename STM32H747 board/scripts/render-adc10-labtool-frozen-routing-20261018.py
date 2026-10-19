"""Static geometry preview of actual V5b pads plus frozen513/50; no live/UI/API calls."""
import json,math,runpy,hashlib,argparse
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from shapely.geometry import Point,LineString,box
from shapely.affinity import scale

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/candidates/adc10-labtool-20261018';OUT=BASE/'routing/visual-qa';OUT.mkdir(exist_ok=True)
M=runpy.run_path(str(BASE/'independent-pcb-placement-proposal.py'));G=M['G'];MM=.0254
FP=BASE/'routing/frozen-combined-routing-v2.json'
ap=argparse.ArgumentParser();ap.add_argument('--routes',type=Path,default=FP);ap.add_argument('--tag',default='v2');args=ap.parse_args();FP=args.routes
routes=json.loads(FP.read_text(encoding='utf8'));SRC=Path(routes['sourcePath']);assert hashlib.sha256(SRC.read_bytes()).hexdigest()==routes['sourceSha256']
rows=M['parse'](SRC);attrs=M['attrs_of'](rows);docs,_=M['READ'](M['CHECK']);plan=json.loads(Path(routes['placementPath']).read_text(encoding='utf8'))
pn={}
for (k,r),b in rows.items():
    if k=='PAD_NET':p=json.loads(r);pn[p[1],str(p[2])]=b['padNet']
pads=[]
for (k,r),b in rows.items():
    if k!='COMPONENT':continue
    for (pk,pi),(ph,p) in docs['FOOTPRINT',attrs[r]['Footprint']].items():
        if pk!='PAD':continue
        s=M['local_pad'](p)
        if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
        s=M['world'](s,(b['x']*MM,b['y']*MM),b['angle']);pads.append((attrs[r]['Designator'],str(p['num']),pn.get((r,str(p['num'])),''),s,(1,2,15,16,17,18) if p['layerId']==12 else (b['layerId'],)))
colors={'+5V':'#a52d1a','+5V_AFE':'#d84d20','-3V_AFE':'#315bc4','GND':'#287343','ADC_OFFSET_0V97':'#982cad','AFE_REF2V5':'#8b4db2','AFE_OFFSET_FILTER':'#922993','AFE_OFFSET_BUF':'#ba3a88','AFE_PUMP_IN':'#b68b10','AFE_VNEG_RAW':'#13938d','AFE_FLY_N':'#9360a6','AFE_FLY_P':'#627815','AFE_NEG_FB':'#ca3a6c'}
def col(net):
    if net in colors:return colors[net]
    if net.endswith('_RAW') or net.endswith('_FILTER'):return '#178e95'
    if net.endswith('_BUF'):return '#24aaba'
    if net.endswith('_SUM'):return '#c97613'
    if net.endswith('_DRV'):return '#2a8d43'
    return '#4b787a'
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',12);title=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',19)
def render(name,bounds,pxmm,layers):
    x0,y0,x1,y1=bounds;pw=round((x1-x0)*pxmm)+84;ph=round((y1-y0)*pxmm)+120
    im=Image.new('RGB',(pw*len(layers),ph+90),'white');d=ImageDraw.Draw(im)
    for panel,layer in enumerate(layers):
        ox=panel*pw+48;oy=62
        def xy(p):return ox+(p[0]-x0)*pxmm,oy+(y1-p[1])*pxmm
        def poly(s,fill,outline=None):
            if s.is_empty:return
            if s.geom_type=='MultiPolygon':
                for p in s.geoms:poly(p,fill,outline)
                return
            d.polygon([xy(v) for v in s.exterior.coords],fill=fill,outline=outline)
        def intersects(s):return s.intersects(box(*bounds))
        def segment(pts,color,width):
            s=LineString(pts).intersection(box(*bounds))
            if s.is_empty:return
            parts=list(s.geoms) if s.geom_type=='MultiLineString' else [s]
            for part in parts:
                if part.geom_type=='LineString':d.line([xy(p) for p in part.coords],fill=color,width=width)
        for x in range(math.ceil(x0),math.floor(x1)+1):
            if x%2==0:d.line([xy((x,y0)),xy((x,y1))],fill='#ececec');d.text((xy((x,y0))[0]-7,ph-43),str(x),font=small,fill='#555555')
        for y in range(math.ceil(y0),math.floor(y1)+1):
            if y%2==0:d.line([xy((x0,y)),xy((x1,y))],fill='#ececec');d.text((panel*pw+8,xy((x0,y))[1]-5),str(y),font=small,fill='#555555')
        for (k,r),b in rows.items():
            if k in ('LINE','ARC') and b.get('layerId') in (layer,11):
                a=(b['startX']*MM,b['startY']*MM);z=(b['endX']*MM,b['endY']*MM);pts=G['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
                if not LineString(pts).intersects(box(*bounds)):continue
                segment(pts,'#7f7f7f' if b['layerId']==layer else '#444444',max(1,round(b.get('width',0)*MM*pxmm)))
            elif k=='VIA':
                x,y=b['centerX']*MM,b['centerY']*MM
                if x0<=x<=x1 and y0<=y<=y1:
                    rx=b['viaDiameter']*MM*pxmm/2;cx,cy=xy((x,y));d.ellipse((cx-rx,cy-rx,cx+rx,cy+rx),fill='#cccccc',outline='#777777',width=1)
            elif k=='PAD' and b.get('hole'):
                hs=M['world'](box(-b['hole']['width']*MM/2,-b['hole']['height']*MM/2,b['hole']['width']*MM/2,b['hole']['height']*MM/2),(b['centerX']*MM,b['centerY']*MM),b.get('padAngle',0))
                if intersects(hs):poly(hs,'#ffffff','#777777')
        for ref,num,net,s,ls in pads:
            if layer not in ls or not intersects(s):continue
            poly(s,col(net) if ref in {p['ref'] for p in plan['edits']} else '#b8b8b8','#444444')
        for p in routes['newLineCreates']:
            if p['layerId']!=layer:continue
            a,z=p['startXYmm'],p['endXYmm']
            if not LineString([a,z]).intersects(box(*bounds)):continue
            segment([a,z],col(p['net']),max(2,round(p['widthMm']*pxmm)))
        for p in routes['newViaCreates']:
            x,y=p['xyMm']
            if x0<=x<=x1 and y0<=y<=y1:
                cx,cy=xy((x,y));r=p['viaDiameterMm']*pxmm/2;hr=p['holeDiameterMm']*pxmm/2
                d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=col(p['net']),outline='#222222',width=1);d.ellipse((cx-hr,cy-hr,cx+hr,cy+hr),fill='white')
        if layer==1:
            for p in plan['edits']:
                x,y=p['xyMm']
                if x0<=x<=x1 and y0<=y<=y1:
                    b=p['conservativeCourtBoundsMm'];a=xy((b[0],b[3]));z=xy((b[2],b[1]));d.rectangle((*a,*z),outline='#85b7c6',width=1)
                    d.text((xy((x,y))[0]+4,xy((x,y))[1]-17),p['ref'],font=small,fill='#111111')
        d.rectangle((panel*pw,0,(panel+1)*pw,54),fill='white');d.text((panel*pw+15,10),{1:'TOP',2:'BOTTOM (through-TOP projection)',15:'Inner15 existing SIGNAL layer'}[layer],font=title,fill='#111111')
        d.text((panel*pw+48,ph-17),'X / Y in mm',font=small,fill='#444444')
    d.rectangle((0,ph+6,im.width,ph+90),fill='white')
    d.text((15,ph+10),'OFFLINE ONLY - NOT FABRICATED / NOT NATIVE DRC VERIFIED',font=title,fill='#9b211b')
    d.text((15,ph+36),f'Actual saved pads + frozen {len(routes["newLineCreates"])} lines / {len(routes["newViaCreates"])} vias. Grey = retained; colour = proposed.',font=font,fill='#333333')
    d.text((15,ph+58),'Static FILL planes and pending local antipads are deliberately hidden. Bottom not mirrored; aligned to TOP.',font=small,fill='#333333')
    path=OUT/name.replace('-v2.png','-'+args.tag+'.png');im.save(path);return str(path)
paths=[render('analog-left-strip-top-bottom-frozen-v2.png',(3,6,45,145),15,(1,2)),render('reference-top-bottom-frozen-v2.png',(14.5,63.5,33.5,88),43,(1,2)),render('pump-top-bottom-frozen-v2.png',(24.5,19,44,37),48,(1,2)),render('negative-inner15-three-lines-frozen-v2.png',(7,28,43,41),43,(15,))]
report={'sourceSha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'routingSha256':hashlib.sha256(FP.read_bytes()).hexdigest(),'previews':paths,'notLiveNativeRender':True,'noFabricationOrDrcClaim':True,'planesHidden':True}
(OUT/('preview-manifest-'+args.tag+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
