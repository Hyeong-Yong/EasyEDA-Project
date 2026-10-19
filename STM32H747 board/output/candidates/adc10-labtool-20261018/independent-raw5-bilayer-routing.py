"""Offline two-layer raw+5 feed with minimal reviewed additionalvias.
Retains native640VIAs/799drills and all fixed332+34TOP routes/42ports.
"""
import ast,copy,hashlib,heapq,json,math,runpy,sys
from pathlib import Path
from collections import defaultdict
import numpy as np
from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union
from shapely import intersects_xy
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];RT=HERE/'routing'
MM=.0254;CLR=.17;WIDTH=.4;VIA_D=.45;HD=.2;HG=.301;GRID=.1
PLACE=HERE/'independent-pcb-placement-short-negative-commonpower-v4-proposal.json'
ROW=RT/'frozen-local-ground-phase332-v2.json'
PWR=RT/'commonpower-top-local-v5-short-fly-review.json'
PORT=RT/'six-layer-via-port-candidates-commonpower-v3b.json'
SOURCE=ROOT/'output/validation/native-adc10-pcb-labtool_107_placed_v4_saved-20261018.epru'
OUT=RT/'independent-raw5-bilayer-route-v1.json'

def main():
    h=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'))
    row=json.loads(ROW.read_text(encoding='utf8'));power=json.loads(PWR.read_text(encoding='utf8'))
    combined={'newLineCreates':row['newLineCreates']+power['newLineCreates']}
    temp=RT/'raw5-model-input-top366.json';temp.write_text(json.dumps(combined,indent=2)+'\n',encoding='utf8')
    # Reuse the independently reviewed allsixlayer physicalmodel, stopping
    # before its portsearch; thisneverexecutes nativecalls or sourcewrites.
    helper=ROOT/'scripts/plan-adc10-labtool-via-ports-20261018.py'
    tree=ast.parse(helper.read_text(encoding='utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    stop=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='tree' for t in n.targets))
    fn.body=fn.body[:stop]+[ast.Return(value=ast.Call(func=ast.Name(id='locals',ctx=ast.Load()),args=[],keywords=[]))]
    tree.body=[n for n in tree.body if not isinstance(n,ast.If)]
    env={'__file__':str(helper),'__name__':'raw5_reused_sixlayer_model'}
    exec(compile(ast.fix_missing_locations(tree),str(helper),'exec'),env)
    oldargv=sys.argv;sys.argv=['sixlayer-model','--placement',str(PLACE),'--routes',str(temp)]
    try:m=env['main']()
    finally:sys.argv=oldargv
    copper=m['copper'];drills=m['drills'];allpads=m['allpads'];fills=m['fills'];M=env['M']
    ports=json.loads(PORT.read_text(encoding='utf8'))['viasProposed']
    for v in ports:
        p=Point(v['xyMm']);copper.append({'key':'RESERVED_VIA:'+v['key'],'net':v['net'].casefold(),'shape':p.buffer(VIA_D/2,resolution=32),'layers':(1,2,15,16,17,18)})
    prior=json.loads((RT/'bottom-buses-commonpower-v3b-draft.json').read_text(encoding='utf8'))
    inherited=[x for x in prior['newLineCreates'] if x['net']=='+5V']
    assert len(inherited)==2,len(inherited)
    for q in inherited:copper.append({'key':q['key'],'net':'+5v','shape':LineString([q['startXYmm'],q['endXYmm']]).buffer(WIDTH/2,resolution=24),'layers':(2,)})
    region=box(22,19,45,38)
    blocks={}
    for layer in (1,2):
        obs=[o['shape'] for o in copper if layer in o['layers'] and o['net']!='+5v' and o['shape'].intersects(region.buffer(2))]
        obs +=[f['shape'] for f in fills if f['layerId']==layer and f['net'].casefold() not in ('gnd','+5v') and f['shape'].is_valid and f['shape'].intersects(region.buffer(2))]
        blocks[layer]=unary_union([s.buffer(CLR+WIDTH/2+.003,resolution=16) for s in obs])
    viaobs=[o['shape'] for o in copper if o['net']!='+5v' and o['shape'].intersects(region.buffer(2))]
    # Copperall6+drills799+reserved42+no-via-in-pad, allindependentconstraints.
    viaobs=[s.buffer(CLR+VIA_D/2+.003,resolution=16) for s in viaobs]
    viaobs +=[s.buffer(VIA_D/2+.06+.003,resolution=16) for k,s in allpads if s.intersects(region.buffer(2))]
    viaobs +=[s.buffer(HD/2+HG+.003,resolution=16) for k,s in drills if s.intersects(region.buffer(2))]
    viaobs +=[Point(v['xyMm']).buffer(HD+HG+.003,resolution=32) for v in ports]
    plan=json.loads(PLACE.read_text(encoding='utf8'))
    viaobs +=[box(*p['conservativeCourtBoundsMm']).buffer(VIA_D/2+.003,join_style=2) for p in plan['edits'] if box(*p['conservativeCourtBoundsMm']).intersects(region)]
    viaBlocked=unary_union(viaobs)
    x0,y0,x1,y1=region.bounds;nx=round((x1-x0)/GRID)+1;ny=round((y1-y0)/GRID)+1
    xs=x0+np.arange(nx)*GRID;ys=y0+np.arange(ny)*GRID;xx,yy=np.meshgrid(xs,ys)
    masks={l:intersects_xy(b.buffer(GRID*.708,resolution=4),xx.ravel(),yy.ravel()).reshape((ny,nx)) for l,b in blocks.items()}
    vm=intersects_xy(viaBlocked,xx.ravel(),yy.ravel()).reshape((ny,nx))
    a=(28.3,22.0);z=(28.9,34.2);ai=(round((a[0]-x0)/GRID),round((a[1]-y0)/GRID));zi=(round((z[0]-x0)/GRID),round((z[1]-y0)/GRID))
    starts=[(l,*ai) for l in (1,2) if not masks[l][ai[1],ai[0]]];goals={(l,*zi) for l in (1,2) if not masks[l][zi[1],zi[0]]}
    assert starts and goals,('ENDPOINT_CONFLICT',starts,goals)
    dxy=[(dx,dy,math.hypot(dx,dy)*GRID) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1))]
    costs={s:0 for s in starts};prev={s:None for s in starts};queue=[]
    for s in starts:heapq.heappush(queue,(math.dist(a,z),0,s))
    hit=None;visited=0
    while queue:
        _,c,v=heapq.heappop(queue)
        if c>costs[v]+1e-10:continue
        if v in goals:hit=v;break
        visited+=1;l,x,y=v
        neighbors=[]
        for dx,dy,d in dxy:
            ix,iy=x+dx,y+dy
            if 0<=ix<nx and 0<=iy<ny and not masks[l][iy,ix]:neighbors.append(((l,ix,iy),d))
        if not vm[y,x] and not masks[3-l][y,x]:neighbors.append(((3-l,x,y),12.0))
        for q,d in neighbors:
            nc=c+d
            if nc>=costs.get(q,math.inf):continue
            costs[q]=nc;prev[q]=v;heapq.heappush(queue,(nc+math.dist((xs[q[1]],ys[q[2]]),z),nc,q))
    assert hit is not None,('NO_BILAYER_PATH',visited)
    chain=[]
    while hit is not None:chain.append(hit);hit=prev[hit]
    chain.reverse();chains=[];vias=[];last=None
    for v in chain:
        l,x,y=v;p=(float(xs[x]),float(ys[y]))
        if last is None or l!=last:
            if last is not None:vias.append(p)
            chains.append((l,[p]));last=l
        else:chains[-1][1].append(p)
    lines=[]
    for l,pts in chains:
        simple=[pts[0]];i=0
        while i<len(pts)-1:
            j=len(pts)-1
            while j>i+1 and LineString([pts[i],pts[j]]).intersects(blocks[l]):j-=1
            assert not LineString([pts[i],pts[j]]).intersects(blocks[l])
            simple.append(pts[j]);i=j
        for p,q in zip(simple,simple[1:]):
            if math.dist(p,q)>1e-8:lines.append({'key':f'RAW5_BRIDGE_{len(lines)+1:03d}','net':'+5V','layerId':l,'widthMm':WIDTH,'startXYmm':list(p),'endXYmm':list(q),'role':'ExistingportR200toR197bilayerbridge'})
    newvias=[]
    for i,p in enumerate(vias):
        s=Point(p).buffer(VIA_D/2,resolution=64);hole=Point(p).buffer(HD/2,resolution=64)
        cu=[{'key':o['key'],'distanceMm':s.distance(o['shape'])} for o in copper if o['net']!='+5v' and s.distance(o['shape'])<CLR]
        assert not cu,cu
        assert min(hole.distance(d) for _,d in drills)>=HG
        assert all(hole.distance(Point(v['xyMm']).buffer(HD/2,resolution=64))>=HG for v in ports)
        assert all(hole.distance(Point(v['xyMm']).buffer(HD/2,resolution=64))>=HG for v in newvias)
        assert not Point(p).intersects(viaBlocked)
        cuts=[{'id':f['id'],'layerId':f['layerId'],'net':f['net'],'valid':f['valid']} for f in fills if f['net'].casefold()!='+5v' and s.buffer(CLR).intersects(f['shape'].envelope) and (not f['valid'] or s.buffer(CLR).intersects(f['shape']))]
        newvias.append({'key':f'RAW5_BILAYER_EXTRA_VIA_{i+1}','net':'+5V','xyMm':list(p),'viaDiameterMm':VIA_D,'holeDiameterMm':HD,'allLayers':[1,2,15,16,17,18],'minimumOriginalDrillEdgeGapMm':min(hole.distance(d) for _,d in drills),'minimumReserved42DrillEdgeGapMm':min(hole.distance(Point(v['xyMm']).buffer(HD/2,resolution=64)) for v in ports),'requiresLocalFillAntipads':cuts})
    conflicts=[]
    for p in lines+inherited:
        s=LineString([p['startXYmm'],p['endXYmm']]).buffer(p['widthMm']/2,resolution=32)
        for o in copper:
            if p['layerId'] in o['layers'] and o['net']!='+5v' and s.distance(o['shape'])<CLR-1e-8:conflicts.append({'line':p['key'],'other':o['key'],'net':o['net'],'distanceMm':s.distance(o['shape'])})
    report={'schema':'independent-raw5-bilayer-route-v1','status':'PASS_SCOPED_RAW5_COPPER_GNDVOIDS_AND_MUTUAL_ROUTING_PENDING' if not conflicts else 'FAIL','nativeCalls':0,'actualSourcePath':str(SOURCE),'actualSourceSha256':h['sha'](SOURCE),'modelBaselineAndVirtualIsolation':True,'placementSha256':h['sha'](PLACE),'fixedRow332Sha256':h['sha'](ROW),'fixedCommon34Sha256':h['sha'](PWR),'reserved42ViaSha256':h['sha'](PORT),'newLineCreates':inherited+lines,'newViaCreates':newvias,'literalCopperConflicts':conflicts,'visitedStates':visited,'bridgeLengthMm':sum(math.dist(p['startXYmm'],p['endXYmm']) for p in lines),'originalCN1toR200InheritedLineCount':2,'original640Vias799DrillsUnchanged':True,'requiredCopperClearanceMm':CLR,'requiredDrillEdgeGapMm':HG,'existingSource':prior['existingRawSource'],'startR200Port':a,'endR197Port':z,'remaining':['All6layernewVIAantipads/localTOP/BOTTOMtraceGNDvoids andunanchoredlobeproof','Mutualclearanceagainstnewsharedplus/minus/offsetroutes byotherowner','Nativeexactguardapply+DRC+netlistreopenaudit'],'manufacturingApproved':False}
    OUT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'path':str(OUT),'sha256':h['sha'](OUT),'status':report['status'],'newLines':len(lines)+len(inherited),'newVias':newvias,'bridgeLengthMm':report['bridgeLengthMm'],'conflicts':conflicts,'states':visited}))
if __name__=='__main__':main()
