import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const here=import.meta.dirname;
const exe=process.env.NGSPICE_BIN||path.resolve(here,'../../.tools/ngspice47/Spice64/bin/ngspice_con.exe');
const modelDir=path.resolve(path.dirname(exe),'../lib/ngspice').replaceAll('\\','/');
try{await fs.access(path.join(here,'.spiceinit'));}catch{await fs.writeFile(path.join(here,'.spiceinit'),`set ngbehavior=ps\nset num_threads=1\nset filetype=ascii\noptran 0 0 0 20n 100u 0\n`+['analog','spice2poly','table'].map(x=>`codemodel ${modelDir}/${x}.cm\n`).join(''));}
await fs.mkdir(path.join(here,'cases'),{recursive:true});await fs.mkdir(path.join(here,'results'),{recursive:true});
const jobs=[];
for(const family of ['DAC8562','MCU'])for(const load of [10000,100000,1000000])for(const cap of [0,470,5000])for(const test of ['ac','loop','tran']){
 const name=`${family}_${test}_R${load}_C${cap}`;
 const r=family==='MCU'?14000:24300,ref=family==='MCU'?1.65:2.5,bias=ref;
 const source=test==='tran'?`PWL(0 ${bias} 50u ${bias} 50.02u ${bias+.025} 250u ${bias+.025} 250.02u ${bias} 500u ${bias})`:`DC ${bias}${test==='ac'?' AC 1':''}`;
 const input=family==='MCU'?`RS input received 1000\nRBIAS received ref 10meg\nXBUF received buffered vp vn buffered OPAx277\nRI buffered plus ${r}\n`:`RI input plus ${r}\n`;
 const loop=test==='loop';
 const deck=`Final-current-netlist analog screening ${name}\n.include "../../models/pspice/OPAx277.LIB"\n.options reltol=1e-5 abstol=1e-10 vntol=1e-7 itl1=500 itl4=500\nVCC vp 0 11.97231\nVEE vn 0 -12.13\nVREF ref 0 ${ref}\nVIN input 0 ${source}\n${input}RG plus 0 100000\nRR ref mix ${r}\nRF sense mix 100000\n${loop?'VLOOP minus mix DC 0 AC 1\n':''}XAMP plus ${loop?'minus':'mix'} vp vn raw OPAx277\nRISO raw sense 100\nCF raw mix 22p\nRCONTACT sense out .1\nCOUT out 0 100p\nRL out 0 ${load}\n${cap?`CCABLE out 0 ${cap}p\n`:''}.nodeset v(raw)=0 v(sense)=0 v(out)=0 v(plus)=${ref*100000/(r+100000)} v(mix)=${ref*100000/(r+100000)}${family==='MCU'?` v(buffered)=${ref} v(received)=${ref}`:''}${loop?` v(minus)=${ref*100000/(r+100000)}`:''}\n.control\nset wr_singlescale\nset wr_vecnames\nset numdgt=12\n${loop?'ac dec 150 10 100meg\nlet gd=db(-v(mix)/v(minus))\nlet pd=cph(-v(mix)/v(minus))*180/PI':test==='ac'?'ac dec 150 10 100meg\nlet gd=db(v(out))\nlet pd=cph(v(out))*180/PI':'tran 20n 500u 0 20n'}\nwrdata results/${name}.dat ${test==='tran'?'v(input) v(out) v(raw)':'gd pd'}\nquit\n.endc\n.end\n`;
 jobs.push({name,family,load,cap,test,deck});
}
for(const family of ['DAC8562','MCU'])for(const load of [10000,1000000]){
 const r=family==='MCU'?14000:24300,ref=family==='MCU'?1.65:2.5;
 const name=`${family}_dc_R${load}`;
 const input=family==='MCU'?`RS input received 1000\nRBIAS received ref 10meg\nXBUF received buffered vp vn buffered OPAx277\nRI buffered plus ${r}`:`RI input plus ${r}`;
 jobs.push({name,family,load,cap:0,test:'dc',deck:`Current analog transfer ${name}\n.include "../../models/pspice/OPAx277.LIB"\nVCC vp 0 11.97231\nVEE vn 0 -12.13\nVREF ref 0 ${ref}\nVIN input 0 ${ref}\n${input}\nRG plus 0 100000\nRR ref mix ${r}\nRF sense mix 100000\nXAMP plus mix vp vn raw OPAx277\nRISO raw sense 100\nCF raw mix 22p\nRCONTACT sense out .1\nCOUT out 0 100p\nRL out 0 ${load}\n.nodeset v(raw)=0 v(out)=0 v(sense)=0 v(plus)=${ref*100000/(r+100000)} v(mix)=${ref*100000/(r+100000)}\n.control\nset wr_singlescale\nset wr_vecnames\nset numdgt=12\ndc VIN ${family==='MCU'?'.25 3.05 .01':'0 5 .01'}\nwrdata results/${name}.dat v(input) v(out) v(raw)\nquit\n.endc\n.end\n`});
}
for(const j of jobs){
 if(j.test==='dc'){
  j.test='range';j.name=j.name.replace('_dc_','_range_');
  const mid=j.family==='MCU'?1.65:2.5,lo=j.family==='MCU'?.25:0,hi=j.family==='MCU'?3.05:5;
  j.deck=j.deck.replace(/VIN input 0 [^\n]+/,`VIN input 0 PWL(0 ${mid} 50u ${mid} 150u ${lo} 350u ${lo} 550u ${hi} 750u ${hi} 850u ${mid} 1000u ${mid})`).replace(/dc VIN[^\n]+/,'tran 100n 1000u 0 100n').replace(/results\/[^ ]+\.dat/,`results/${j.name}.dat`);
 }
 await fs.writeFile(path.join(here,'cases',j.name+'.cir'),j.deck);
}
async function run(j){const log=path.join(here,'results',j.name+'.log');j.exitCode=await new Promise((resolve,reject)=>{const child=spawn(exe,['-b','-o',log,path.join(here,'cases',j.name+'.cir')],{cwd:here,windowsHide:true});const timer=setTimeout(()=>child.kill(),60000);child.on('error',reject);child.on('close',code=>{clearTimeout(timer);resolve(code);});});const txt=await fs.readFile(log,'utf8');j.solverPassed=j.exitCode===0&&!/aborted|doAnalyses:|Error:|timestep too small/i.test(txt);delete j.deck;if(!j.solverPassed)console.log(j.name,txt.slice(-900));}
const selected=process.argv.includes('--range-only')?jobs.filter(j=>j.test==='range'):jobs;
for(let i=0;i<selected.length;i+=3){await Promise.all(selected.slice(i,i+3).map(run));console.log(`${Math.min(i+3,selected.length)}/${selected.length} cases complete`);}
if(process.argv.includes('--range-only')){const previous=JSON.parse(await fs.readFile(path.join(here,'manifest.json'),'utf8'));for(const j of jobs){if(j.test==='range')continue;const old=previous.jobs.find(x=>x.name===j.name);Object.assign(j,old);delete j.deck;}}
await fs.writeFile(path.join(here,'manifest.json'),JSON.stringify({model:'TI OPAx277 Final 1.4 (unmodified)',rails:[11.97231,-12.13],temperatureC:27,initialization:'optran 0 0 0 20n 100u 0; confirm physical DC roots and AC gain',limits:'Ideal DAC/reference and rails; nominal relay contact closed at 0.1 ohm. Not a switch-mode power/startup/safety qualification. Both channel topologies are symmetric after R117 schematic repair.',jobs},null,2));
if(jobs.some(j=>!j.solverPassed))process.exitCode=1;
