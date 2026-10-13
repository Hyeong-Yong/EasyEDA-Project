import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const here=import.meta.dirname,root=path.resolve(here,'../..');
const exe=process.env.NGSPICE_BIN||path.join(root,'.tools/ngspice47/Spice64/bin/ngspice_con.exe');
const cm=path.resolve(path.dirname(exe),'../lib/ngspice').replaceAll('\\','/');
await fs.access(path.join(root,'.tools/TPS7A49_unencrypted/TPS7A4901_TRANS.LIB'));
try{await fs.access(path.join(here,'.spiceinit'));}catch{await fs.writeFile(path.join(here,'.spiceinit'),'set ngbehavior=ps\nset num_threads=1\nset filetype=ascii\n'+['analog','spice2poly','table'].map(n=>`codemodel ${cm}/${n}.cm\n`).join(''));}
await fs.mkdir(path.join(here,'cases'),{recursive:true});await fs.mkdir(path.join(here,'results'),{recursive:true});
const jobs=[];
const startupOnly=process.argv.includes('--startup-only');
for(const rise of [.1,1,10,100])for(const load of [2,10,20])for(const capacitanceFactor of [.5,1]){
 const name=`LDO_${startupOnly?'startup_':'rise'}${rise}ms_load${load}mA_c${capacitanceFactor}`;
 const vin=`PWL(0 0 .5m 0 ${rise+.5}m 12 180m 12 181m 0 300m 0)`;
 jobs.push({name,riseMs:rise,loadMa:load,capacitanceFactor,vin,scenario:startupOnly?'startup_only':'startup_and_shutdown'});
}
if(!startupOnly)for(const load of [2,10,20])jobs.push({name:`LDO_brownout_load${load}mA`,riseMs:1,loadMa:load,capacitanceFactor:1,vin:'PWL(0 0 .5m 0 1.5m 12 100m 12 101m 2 140m 2 141m 12 250m 12 251m 0 300m 0)',scenario:'brownout_mcu_stays_powered'});
for(const j of jobs){
 const deck=`TI TPS7A4901 Final 1.2 startup screening ${j.name}\n.include "../../.tools/TPS7A49_unencrypted/TPS7A4901_TRANS.LIB"\n.options reltol=1e-4 abstol=1e-10 vntol=1e-7 itl4=1000\nVIN vp 0 ${j.vin}\nCIN vp 0 10u\nXU2 0 vp fb vp nc nr dnc avdd 0 TPS7A4901_TRANS\nR22 avdd fb 34k\nR23 fb 0 10k\nC14 nr 0 10n\nC27 avdd fb 10n\nCOUT avdd 0 ${10.3*j.capacitanceFactor}u\nRLOAD avdd 0 ${5.214/(j.loadMa/1000)}\n.control\nset wr_singlescale\nset wr_vecnames\nset numdgt=12\ntran 20u 300m 0 20u\nwrdata results/${j.name}.dat v(vp) v(avdd) v(nr) v(fb)\nquit\n.endc\n.end\n`;
 await fs.writeFile(path.join(here,'cases',j.name+'.cir'),startupOnly?deck.replace('tran 20u 300m','tran 20u 175m'):deck);
}
async function run(j){const log=path.join(here,'results',j.name+'.log');j.exitCode=await new Promise((resolve,reject)=>{const child=spawn(exe,['-b','-o',log,path.join(here,'cases',j.name+'.cir')],{cwd:here,windowsHide:true});const timer=setTimeout(()=>child.kill(),60000);child.on('error',reject);child.on('close',code=>{clearTimeout(timer);resolve(code);});});const txt=await fs.readFile(log,'utf8');j.solverPassed=j.exitCode===0&&!/aborted|doAnalyses:|Error:|timestep too small/i.test(txt);if(!j.solverPassed)console.log(j.name,txt.slice(-650));}
for(let i=0;i<jobs.length;i+=3){await Promise.all(jobs.slice(i,i+3).map(run));console.log(`${Math.min(i+3,jobs.length)}/${jobs.length} LDO cases complete`);}
await fs.writeFile(path.join(here,startupOnly?'manifest-startup-only.json':'manifest.json'),JSON.stringify({model:'Unmodified TI TPS7A4901_TRANS Final 1.2, SBVM528A',source:'https://www.ti.com/lit/zip/sbvm528',capacitance:'COUT=10.3uF nominal (C15+C16+C28+C29); 0.5x/1x assumed effective capacity, NOT measured MLCC bias',load:'Resistive loads corresponding to 2/10/20mA at 5.214V; not a dynamic full-board current model',input:'Prescribed ideal VPOS12 ramp, NOT TPS65131 switch-mode simulation',jobs},null,2));
if(jobs.some(j=>!j.solverPassed))process.exitCode=1;
