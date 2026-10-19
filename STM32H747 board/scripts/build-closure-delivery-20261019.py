"""Build review evidence and vector assembly drawings from audited, saved CAD data.

Read-only with respect to CAD. Does not place an order or approve sourcing.
"""
from pathlib import Path
import json, math, textwrap, collections, importlib.util
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.colors import HexColor, white

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/jlcpcb-closure-20261019'
load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
dump=lambda name,x:(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
data=load(OUT/'order-data.json');plan=load(OUT/'closure-plan.json');rot=load(OUT/'ROTATION_REVIEW.json')
assert load(OUT/'DURABLE_AUDIT.json')['physicalAndElectricalRecordsPreserved']
assert load(OUT/'CAM_AUDIT.json')['allCopperMaskPasteSilkOutlineAndDrillGeometryPreserved']
assert len(data['cpl'])==412 and len(rot['rows'])==70

# Native EasyEDA Device Standardization table, observed on 2026-10-19 KST.
# LCSC and SMT stocks are separate columns/warehouses; neither is reserved.
stocks={'C59782':(177600,241421),'C1525':(0,29094842),'C3855387':(65715,97872),
 'C3039701':(5720,5794),'C852810':(6500,8715),'C852762':(18740,18757),
 'C25118':(None,1896308),'C852472':(710250,980937),'C2692906':(5935,5939),
 'C852543':(19020,19025),'C190095':(0,629639),'C2103244':(2610,2619),
 'C44198':(None,6941),'C2693067':(4965,5157),'C4137342':(9400,9416),
 'C2692924':(500,501)}
proof=[]
for g in plan['groups']:
 code=g['properties']['Supplier Part'];lcsc,smt=stocks[code]
 proof.append({'mpn':g['mpn'],'supplierId':code,'refs':g['refs'],'qtyPerBoard':len(g['refs']),
  'lcscStock':lcsc,'jlcSmtStock':smt,'observedDateKST':'2026-10-19',
  'source':'JLCEDA Pro 3.2.206 / Device Standardization / LCSC Stock/SMT Stock',
  'snapshotOnly':True,'reserved':False,'note':'Empty LCSC column is unknown, not zero.'})
dump('stock/native-supplier-stock-proof.json',proof)
warnings=[{'Designator':r,'MPN':next(t['properties']['Manufacturer Part']for t in plan['targets']if t['ref']==r),
 'Review':review,'Disposition':'Exact metadata saved; custom library warning remains; factory match required'}for r,review in [
 ('R197','4.7 ohm / 0402 / 1% / 100 ppm/K / 0.2 W; JLC stock 2619'),
 ('R200','4.7 ohm / 0402 / 1% / 100 ppm/K / 0.2 W; same part as R197'),
 ('R201','1.2 ohm / 0402 / 1% / 400 ppm/K / 0.0625 W; TCR retained in prior circuit analysis'),
 ('R202','14.7 kohm / 0402 / 0.1% / 10 ppm/K / 0.06 W'),
 ('R203','9.31 kohm / 0402 / 0.1% / 10 ppm/K / 0.06 W; JLC stock 501')]]
dump('WARNING_REVIEW_5.json',{'originalParts':warnings,'nativeFatal':0,'nativeErrors':0,'nativeWarningGroups':5,
 'warningReason':'Preserved custom symbol/footprint and supplier library definitions differ. Do not claim ERC zero.',
 'standardizationUndeterminedGroups':16,'standardizationTargetParts':132})

spec=importlib.util.spec_from_file_location('nr',ROOT/'scripts/standard-values-review-20261019.py')
nr=importlib.util.module_from_spec(spec);spec.loader.exec_module(nr)
pcb=nr.docs(OUT/'native/final/STM32H747_JLCPCB_20261019.epro2')['0ac2a19168000d8e']
vias=[b for(k,i),(h,b)in pcb['records'].items()if k=='VIA']
settings={'boardMm':[100,154],'copperLayers':6,'thicknessMm':1.6,'surfaceFinish':'ENIG',
 'assemblyService':'Standard PCBA','assemblySides':'Both Sides','assemblyPartsPerBoard':412,
 'topParts':333,'bottomParts':79,'minViaHoleMm':round(min(b['holeDiameter'] for b in vias)*.0254,6),
 'minViaDiameterMm':round(min(b['viaDiameter'] for b in vias)*.0254,3),
 'quantityConfirmed':False,'quoteDraftPCBQty':5,'quoteDraftPCBAQty':5,
 'stackup':'Preserve original 6-layer order; factory confirmation required before production.',
 'confirmProductionFile':True,'confirmPartsPlacement':True,'autoProductionApproval':False,'autoPlacementApproval':False,
 'partsSelection':'Manual Match / exact MPN, no unapproved substitutes',
 'edgeRails':'JLC adds two 5 mm rails; finished board 100x154 mm, process outline 110x154 mm.',
 'sourcingUnmatchedParts':139,'manufacturingReleaseApproved':False}
dump('ORDER_SETTINGS.json',settings)

def ascii_text(s):
 s=str(s).replace('Ω','ohm').replace('µ','u').replace('±','+/-').replace('°',' deg').replace('−','-').replace('–','-').replace('—','-')
 return s.encode('ascii','replace').decode()

W,H=landscape(A3);pdf=OUT/'ASSEMBLY_PIN1_REVIEW.pdf';c=canvas.Canvas(str(pdf),pagesize=(W,H))
c.setTitle('STM32H747 - Pin 1 and assembly review - 2026-10-19');c.setAuthor('STM32H747 engineering review')
NAVY=HexColor('#183e54');BLUE=HexColor('#176f98');RED=HexColor('#ce423c');GRAY=HexColor('#617584');LIGHT=HexColor('#e9f0f4')
page=0
def txt(x,y,s,size=9,color=NAVY,font='Helvetica'):
 c.setFillColor(color);c.setFont(font,size);c.drawString(x,y,ascii_text(s))
def lines(x,y,s,width=95,size=8,leading=11,color=GRAY,maxlines=10):
 for line in textwrap.wrap(ascii_text(s),width=width)[:maxlines]:txt(x,y,line,size,color);y-=leading
 return y
def header(title,sub):
 global page
 page+=1;c.setFillColor(NAVY);c.rect(0,H-78,W,78,fill=1,stroke=0)
 txt(30,H-33,title,21,white,'Helvetica-Bold');txt(30,H-56,sub,10,white)
 txt(30,20,'2026-10-19 | Exact part matching and factory placement preview required before production.',8,GRAY)
 txt(W-72,20,f'Page {page}',8,GRAY)
def arrow(x,y,dx,dy,length=26):
 c.setStrokeColor(BLUE);c.setFillColor(BLUE);c.setLineWidth(1.5);c.line(x,y,x+dx*length,y+dy*length)
 end=(x+dx*length,y+dy*length);p=c.beginPath();p.moveTo(*end);p.lineTo(end[0]-dx*7-dy*3,end[1]-dy*7+dx*3);p.lineTo(end[0]-dx*7+dy*3,end[1]-dy*7-dx*3);p.close();c.drawPath(p,fill=1,stroke=0)

header('Assembly review - verified CAD geometry','412 parts per board | 333 top / 79 bottom | 70 directional parts reviewed | 59 CPL rotation updates')
for side,xbase in [('Top',44),('Bottom',622)]:
 scale=3.85;bx=xbase+72;by=119
 txt(xbase,H-108,side+' - '+('top view'if side=='Top'else'physical bottom view, X mirrored'),15,NAVY,'Helvetica-Bold')
 c.setStrokeColor(GRAY);c.setLineWidth(.8);c.rect(bx,by,100*scale,154*scale,fill=0)
 conv=lambda x,y:(bx+(x if side=='Top' else 100-x)*scale,by+y*scale)
 for r in data['cpl']:
  if r['Layer']!=side:continue
  x,y=conv(float(r['Mid X']),float(r['Mid Y']));c.setFillColor(HexColor('#b1c7d2'));c.circle(x,y,1.5,fill=1,stroke=0)
 for r in rot['rows']:
  if r['side']!=side:continue
  cr=next(p for p in data['cpl']if p['Designator']==r['ref']);x,y=conv(float(cr['Mid X']),float(cr['Mid Y']))
  c.setFillColor(BLUE);c.circle(x,y,2.2,fill=1,stroke=0)
  if r['ref'].startswith(('J','CN')) or r['ref'] in ['U1','U4']:txt(x+3,y+3,r['ref'],6,BLUE)
  if r.get('pin1'):
   px,py=conv(r['pin1']['x'],r['pin1']['y']);c.setFillColor(RED);c.circle(px,py,1.8,fill=1,stroke=0)
 txt(xbase,88,'Red: pin 1 / A1 / cathode. Blue: reviewed centroid.',8)
 txt(xbase,72,'CPL XY uses top view on both sides; never mirror the CPL.',8)
 txt(xbase,56,'Numbered-pad detail pages define orientation.',8)
c.showPage()

byref={r['Designator']:r for r in data['bomParts']};cpl={r['Designator']:r for r in data['cpl']}
for start in range(0,70,12):
 header(f'Numbered-pad direction review {start+1}-{min(start+12,70)}',
  'All detail plots are top view, +X right / +Y up. Red marks pin 1, A1 or LED cathode; plots are not to scale.')
 cw=(W-60)/4;ch=(H-122)/3
 for idx,r in enumerate(rot['rows'][start:start+12]):
  col,row=idx%4,idx//4;x=30+col*cw;y=H-96-row*ch;ref=r['ref'];p=byref[ref];cp=cpl[ref]
  c.setStrokeColor(LIGHT);c.setLineWidth(.7);c.rect(x,y-ch+8,cw-9,ch-8,fill=0)
  txt(x+9,y-20,f'{ref} | CPL {r["rotationDegrees"]} deg | {r["side"]}',12,NAVY,'Helvetica-Bold')
  txt(x+9,y-35,p['Manufacturer Part'],8)
  txt(x+9,y-48,f'XY: {cp["Mid X"]}, {cp["Mid Y"]} mm',8,GRAY)
  pads=r['pads'];xs=[p['x']for p in pads];ys=[p['y']for p in pads];cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
  s=min((cw-64)/max(max(xs)-min(xs),2),91/max(max(ys)-min(ys),2),24)
  pcx=x+(cw-9)/2;pcy=y-111
  for pad in pads:
   px=pcx+(pad['x']-cx)*s;py=pcy+(pad['y']-cy)*s;pin=str(pad['pin']);marked=pin in ['1','A1','A1_B12']
   c.setFillColor(RED if marked else HexColor('#8096a2'));radius=3 if marked else(1.4 if len(pads)>60 else 2.2)
   c.circle(px,py,radius,fill=1,stroke=0)
   label=(len(pads)<35 or marked)
   if ref in ['CN3','CN4']:label=marked or pin.startswith('S')
   if label:txt(px+4,py+2,('K/1' if marked and ref in ['D2','D3','D4','D6'] else pin),6,RED if marked else GRAY)
  if r.get('portDirection'):
   direction=r['portDirection'];dx,dy=(-1,0)if'LEFT'in direction else((1,0)if'RIGHT'in direction else(0,1));arrow(pcx,pcy,dx,dy);txt(x+9,y-164,'Mating port: '+direction,8,BLUE)
  status='Catalog pin mapping checked'if r['supplierZeroConfirmed']else'Exact purchased part / tape zero pending'
  txt(x+9,y-180,status,8,BLUE if r['supplierZeroConfirmed'] else RED)
  detail=' '.join([r['review'].replace('_',' ').lower(),r['factoryAction']])
  lines(x+9,y-195,detail,width=51,size=7.4,leading=10,maxlines=4)
 c.showPage()

header('Factory review and release conditions','Local verification is complete. Sourcing allocation, purchased-part tape zero and production release are pending.')
notes=[
 ('Files and exclusions','Use BOM_JLCPCB.csv and CPL_JLCPCB_REVIEW.csv together. 69 BOM groups total 412 parts/board. Exclude C33, R61, R64, R98, R125, R126 (DNP) and 19 bare test pads. Native CPL has 437 rows and must not be uploaded as the assembly list.'),
 ('Legacy procurement','139 original parts have no verified JLC assembly SKU. Match exact manufacturer part numbers through Manual Match or approved Global Sourcing. U6 STS5PF30L is obsolete per ST. Do not substitute or omit it without a separately reviewed decision.'),
 ('Seven purchased-part direction checks','CN2, D2, D3, D4, D6, J18 and U6: numbered-pad / cathode direction has been checked locally. CPL angles use a documented drawing convention; exact supplier tape zero is not asserted. Match purchased parts to these pad drawings before assembly.'),
 ('Special lands','Y1 NX3215SA: nonpolar X-axis; extended hand-solder lands need contact-coverage DFM. U2 SOT-223 and U6 SO-8 also retain extended native lands. CN2/J18 are manual-insertion references; confirm pin 1, mating direction, insertion side and mechanical fit.'),
 ('SMA orientation','J2-J11: left port, CPL 90 deg. J12-J15 and J17: right port, CPL 270 deg. J16: upper port, CPL 0 deg. Derived from the identical supplier 3D model UUID and its 180 deg canonical orientation, not an arbitrary visual zero.'),
 ('CAD checks','Strict PCB DRC: 0. Native ERC: fatal 0 / error 0, supplier-property warning 5 groups retained. The 132 selected parts use original custom symbols and footprints. All copper, mask, paste, silk, outline and drill manufacturing geometry is preserved.'),
 ('Production settings',f'6 layers, finished 100 x 154 mm, 1.6 mm draft, ENIG, Standard PCBA both sides. Native min via hole {settings["minViaHoleMm"]} mm / diameter {settings["minViaDiameterMm"]} mm. Confirm original stackup, layer order, PCB production files and parts placement. Quantity remains unconfirmed; 5+5 website quote is a draft.'),
 ('Source references','JLCPCB: Pick & Place File for PCB Assembly; PCB Assembly FAQs Part 2. ST: STS5PF30L product page and datasheet. NDK: NX3215SA catalog. Source URLs and exact geometry evidence are included in ROTATION_REVIEW.json and CAM_AUDIT.json.')]
y=H-111
for title,body in notes:
 txt(38,y,title,12,NAVY,'Helvetica-Bold');y=lines(38,y-18,body,width=170,size=10,leading=14,maxlines=5)-21
c.save()
dump('DELIVERY_STATUS.json',{'localFileReviewComplete':True,'originalFiveWarningsReviewed':True,
 'newSelections':107,'totalSelectedNativeParts':132,'x7rCorrections':12,'directionalPartsReviewed':70,
 'cplRotationsChanged':59,'strictPcbDrcViolations':0,'nativeErcFatal':0,'nativeErcErrors':0,'nativeErcWarningGroups':5,
 'bomGroups':69,'assemblyParts':412,'factorySourcingPendingParts':139,'purchasedPartDirectionPending':rot['supplierTapeZeroNotClaimedFor'],
 'factoryPlacementPreviewCompleted':False,'manufacturingReleaseApproved':False,
 'pending':['JLCPCB sign-in and exact BOM matching/stock allocation','U6 obsolete-part procurement decision','Exact purchased-part preview for seven legacy parts','Final quantity, stackup/DFM and production/placement approval'],
 'pdfPages':page})
print(json.dumps({'pdf':str(pdf),'pages':page,'stockGroups':len(proof),'via':settings['minViaHoleMm']}))
