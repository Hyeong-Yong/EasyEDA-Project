import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const root=path.resolve('simulation'),folder=path.join(root,'highz');
await fs.mkdir(path.join(folder,'cases'),{recursive:true});await fs.mkdir(path.join(folder,'results'),{recursive:true});
const model='models/pspice/OPAx277.LIB';
const exe=process.env.NGSPICE_BIN||path.resolve('tmp/simulation-tools/Spice64/bin/ngspice_con.exe');
const configs=[{name:'original192',model:'models/pspice/OPAx192.LIB',ic:'OPAx192',riso:10,cf:0},{name:'277only',model,ic:'OPAx277',riso:10,cf:0},...[47,100,220].flatMap(riso=>[22,47,100,220,470].map(pf=>({name:`dfb_${riso}_${pf}`,model,ic:'OPAx277',riso,cf:pf*1e-12})))];
const mode=process.argv[2]||'screen';
if(!['screen','verify','corners','refine'].includes(mode))throw Error('Unknown simulation mode: '+mode);
const jobs=[];
function build(cfg,cap,test,R=1e6,bias=2.5){
 const name=`${cfg.name}_${test}_r${R}_c${cap}_v${bias}`;
 const isloop=test==='loop';
 // Voltage injection at the shared op-amp feedback input preserves both feedback branches.
 // Closed-loop AC and transient tests independently check any loop-injection ambiguity.
 const deck=`DAC8562 high-Z stability design comparison ${name}\n.include "${cfg.model}"\n.options reltol=1e-5 abstol=1e-10 vntol=1e-7 itl1=500 itl4=500\nVCC vp 0 11.97231\nVEE vn 0 -12.13\nVREF ref 0 2.5\nVDAC dac 0 ${test==='tran'?`PWL(0 ${bias} 50u ${bias} 50.02u ${bias+.025} 250u ${bias+.025} 250.02u ${bias} 500u ${bias})`:test==='large'?'PWL(0 2.5 50u 2.5 100u 0 300u 0 350u 5 550u 5)':`DC ${bias}${test==='ac'?' AC 1':''}`}\nRI dac plus 24900\nRG plus 0 100000\nRR ref mix 24900\nRF out mix 100000\n${isloop?'VLOOP minus mix DC 0 AC 1\n':''}XU4 plus ${isloop?'minus':'mix'} vp vn raw ${cfg.ic}\nRISO raw out ${cfg.riso}\n${cfg.cf?'CF raw mix '+cfg.cf+'\n':''}COUT out 0 100p\nRL out 0 ${R}\n${cap?'CCABLE out 0 '+cap+'p\n':''}.control\nset wr_singlescale\nset wr_vecnames\nset numdgt=12\n${test==='loop'?'ac dec 200 10 100meg\nlet lg=-v(mix)/v(minus)\nlet gd=db(lg)\nlet pd=cph(lg)*180/PI':test==='ac'?'ac dec 200 10 100meg\nlet gd=db(v(out))\nlet pd=cph(v(out))*180/PI':test==='dc'?'dc VDAC 0 5 0.01':`tran 20n ${test==='large'?'600u':'500u'} 0 20n`}\nwrdata highz/results/${name}.dat ${test==='loop'||test==='ac'?'gd pd':'v(dac) v(out) v(raw)'}\nquit\n.endc\n.end\n`;
 const initial=test==='dc'?0:bias,target=100000/24900*(initial-2.5),plus=initial*100000/124900;
 const seeded=deck.replace('.control',`.nodeset v(raw)=${target*(1+cfg.riso/R)} v(out)=${target} v(plus)=${plus} v(mix)=${plus}${isloop?' v(minus)='+plus:''}\n.control`);
 let finalDeck=seeded;
 const ramped=test==='tran'&&bias!==2.5;
 if(ramped)finalDeck=finalDeck.replace(/VDAC dac 0 PWL\([^\n]+\)/,`VDAC dac 0 PWL(0 2.5 50u 2.5 150u ${bias} 500u ${bias} 500.02u ${bias+.025} 700u ${bias+.025} 700.02u ${bias} 950u ${bias})`).replace(/\.nodeset[^\n]+/,'.nodeset v(raw)=0 v(out)=0 v(plus)=2.00160128 v(mix)=2.00160128').replace('tran 20n 500u','tran 20n 950u');
 jobs.push({name,cfg,cap,test,R,bias,riseTimeUs:ramped?500:50,deck:finalDeck});
}
if(mode==='screen')for(const c of configs)for(const cap of [0,1000,5000]){build(c,cap,'loop');build(c,cap,'ac');}
if(mode==='verify')for(const c of [configs.find(c=>c.name===process.argv[3])]){if(!c)throw Error('Config not found');for(const R of [1e6,100e3,10e3]){build(c,0,'dc',R);for(const cap of [0,100,470,1000,5000]){build(c,cap,'loop',R);build(c,cap,'ac',R);build(c,cap,'tran',R);}}}
if(mode==='corners'){
 const chosen=configs.find(c=>c.name==='dfb_100_22');
 for(const bias of [.05,2.5,4.925])for(const cap of [0,470,5000])for(const test of ['loop','tran'])build(chosen,cap,test,1e6,bias);
 for(const riso of [99,101])for(const cf of [20.9e-12,23.1e-12])for(const cap of [0,470,5000]){const c={...chosen,name:`tolerance_${riso}_${Math.round(cf*1e13)}`,riso,cf};build(c,cap,'loop');build(c,cap,'tran');}
 build(chosen,5000,'large');
}
if(mode==='refine')for(const cap of [0,470,5000]){build(configs.find(c=>c.name==='dfb_100_22'),cap,'tran');const j=jobs.at(-1),oldName=j.name;j.name+='_fine';j.deck=j.deck.replace('tran 20n 500u 0 20n','tran 5n 500u 0 5n').replace(`highz/results/${oldName}.dat`,`highz/results/${j.name}.dat`);}
for(const j of jobs)await fs.writeFile(path.join(folder,'cases',j.name+'.cir'),j.deck);
async function simulate(j){
 const logfile=path.join(folder,'results',j.name+'.log');
 const code=await new Promise((resolve,reject)=>{const p=spawn(exe,['-b','-o',logfile,path.join(folder,'cases',j.name+'.cir')],{cwd:root,windowsHide:true});const t=setTimeout(()=>p.kill(),60000);p.on('error',reject);p.on('close',c=>{clearTimeout(t);resolve(c);});});
 const log=await fs.readFile(logfile,'utf8');j.status=code===0&&!/aborted|doAnalyses:|Error:|timestep too small/i.test(log)?'passed':'failed';delete j.deck;
 if(j.status==='failed')console.log(j.name,log.slice(-500));
}
for(let i=0;i<jobs.length;i+=3)await Promise.all(jobs.slice(i,i+3).map(simulate));
await fs.writeFile(path.join(folder,`manifest-${mode}.json`),JSON.stringify(jobs,null,2));
console.log({mode,cases:jobs.length,failed:jobs.filter(j=>j.status!=='passed').map(j=>j.name)});
if(jobs.some(j=>j.status!=='passed'))process.exitCode=1;
