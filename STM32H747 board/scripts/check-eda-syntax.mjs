import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
for(const input of process.argv.slice(2)){
  const path=resolve(input);
  const source=await readFile(path,'utf8');
  new AsyncFunction('eda','__taskArgs',source);
  console.log(`Syntax OK: ${path}`);
}
