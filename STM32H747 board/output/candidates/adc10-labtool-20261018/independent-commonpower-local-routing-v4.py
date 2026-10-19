"""Separate V4 handroute with shortpumpOUT and all42reservedVIA obstacles.
Originalv3draft unchanged. No nativecalls/sourcewrites.
"""
from pathlib import Path
HERE=Path(__file__).resolve().parent
src=(HERE/'independent-commonpower-local-routing.py').read_text(encoding='utf8')
src=src.replace('independent-pcb-placement-short-negative-commonpower-v3-proposal.json','independent-pcb-placement-short-negative-commonpower-v4-proposal.json')
src=src.replace('frozen-short-negative-row290-variant-v1b.json','frozen-local-ground-phase332-v2.json')
src=src.replace('commonpower-top-local-v3-draft.json','commonpower-top-local-v4-final-review.json')
src=src.replace("path('AFE_VNEG_RAW','PumpRAW toprotectiondiodeAnode',[P('U30',1),P('D20',2)],.4)","path('AFE_VNEG_RAW','PumpRAW tolocaloutputcapshortpulsedlead',[P('U30',1),P('C152',1)],.4)\n    path('AFE_VNEG_RAW','Outputcapacitor toprotectiondiodeAnode',[P('C152',1),P('D20',2)],.35)")
src=src.replace("path('AFE_VNEG_RAW','PumpRAW tooutputcapacitor; aboveFLYP',[P('U30',1),(29.7,31.75),(34.7,31.75),P('C152',1)],.4)","path('AFE_VNEG_RAW','LDOinputfeedfrompumpoutputcap; lowDCload',[P('C152',1),(35.5,30.75),(35.5,29.8),P('U31',2)],.35)")
src=src.replace("    path('AFE_VNEG_RAW','Localoutputcapacitor toLDOIN',[P('C152',1),(35.5,29.8),P('U31',2)],.4)\n",'')
src=src.replace("[P('C154',1),(40.8,25.6),(40.8,22.4),(35.82,22.4),P('C155',2)]","[P('C154',1),(40.8,25.6),(40.8,21.0),(35.82,21.0),P('C155',2)]")
needle="    conflicts=[];touch=[];shapes=[x[3] for x in obs];tree=STRtree(shapes)"
replacement="""    path('+5V','R197raw5Vpowerportstub',[P('R197',1),(28.9,34.2)],.4)
    path('+5V','R200raw5Vpowerportstub',[P('R200',1),(28.3,22.0)],.4)
    path('+5V_AFE','PositiveoutputBOTTOMrailportstub',[P('C156',1),(31.0,24.5)],.4)
    path('-3V_AFE','NegativeoutputBOTTOMrailportstub',[P('U31',5),(40.3,31.7)],.35)
    portpath=HERE/'routing/six-layer-via-port-candidates-commonpower-v3b.json'
    portplan=json.loads(portpath.read_text(encoding='utf8'))
    for via in portplan['viasProposed']:
        add('RESERVED_VIA',via['key'],via['net'],Point(via['xyMm']).buffer(via['viaDiameterMm']/2,resolution=32))
    conflicts=[];touch=[];shapes=[x[3] for x in obs];tree=STRtree(shapes)"""
assert needle in src;src=src.replace(needle,replacement)
src=src.replace("qq=s.buffer(CLR,resolution=24)","qq=s.buffer(max(CLR,.17),resolution=24)")
src=src.replace("if n!=q['net'] and s.distance(z)<CLR-1e-8:","if n!=q['net'] and s.distance(z)<(.17 if k=='RESERVED_VIA' else CLR)-1e-8:")
src=src.replace("checks.append({'net':net,","checks.append({'net':net,'externalBOTTOMfeedJoinPending':net=='+5V',")
src=src.replace("all(x['allRelevantPadsConnected'] for x in checks)","all(x['allRelevantPadsConnected'] or x['externalBOTTOMfeedJoinPending'] for x in checks)")
src=src.replace("'schema':'independent-commonpower-top-local-route-v3-draft-20261018'","'schema':'independent-commonpower-top-local-route-v4-draft-20261018'")
src=src.replace("'newViasProposedHere':0,","'newViasProposedHere':0,'reservedViaPortPlanPath':str(portpath),'reservedViaPortPlanSha256':H['sha'](portpath),'reservedViaCuClearanceMm':.17,'raw5VTwoPortBottomJoinPending':True,")
# Audit actualsavedV4 copper/pads, not a virtual pre-isolation source. The new
# routecoordinateintent remains fullprecision; realpads are APIround4mil.
src=src.replace("ops={(x['type'],x['id']):x for x in iso['operations']}","ops={}")
src=src.replace("p=pd.get(ref);xy=", "p=None;xy=")
src=src.replace("'manufacturingApproved':False", "'sourceIsActualSavedV4AfterIsolation':True,'knownLoopMetricsNotBenchValidated':['C151FLYN2.0797mm/FLYP5.6236mm,combined7.7033mm','PumpOUTtoC1522.3022mm; LDOINfeed7.0347mm','LDOFB4.6021mm,outputtoCFFleaf13.1213mm','GNDplaneactualreturnandFILLvalidityownedbyseparateplanner'],'manufacturingApproved':False")
src=src.replace("if __name__=='__main__':main()",'')
env={'__file__':str(HERE/'independent-commonpower-local-routing.py'),'__name__':'commonpower_v4_derived'}
exec(compile(src,str(HERE/'independent-commonpower-local-routing.py'),'exec'),env)
env['H']['SOURCE']=env['H']['ROOT']/'output/validation/native-adc10-pcb-labtool_107_placed_v4_saved-20261018.epru'
env['main']()
