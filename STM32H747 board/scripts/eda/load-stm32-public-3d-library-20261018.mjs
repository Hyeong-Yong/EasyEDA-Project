const EXPECTED_PROJECT = 'STM32H747_MCU_BOARD_v19';
const EXPECTED_UUID = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const DIRECTORY = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/native-project/model-library/';
const MANIFEST_PATH = DIRECTORY + 'STM32H747_3D_asset_manifest_20261018.json';
const MANIFEST_SHA256 = 'c3e4844d0c840306694b0f83eb3d8e8fb832122b74e145526fc0785f5f0e44b6';
const LIBRARY_TITLE = 'STM32H747_3D_LOCAL5_20261018';
const OWN_STATE_KEY = '__STM32H747_PUBLIC_3D_LIBRARY_20261018_V1__';
const WHITELIST = Object.freeze([
  {ref:'CN1', file:'STM32H747_3D_CN1_PJ051BH_PINREG_ZUP_20261018.step', sha:'99c3113c8bc68d72596ab2f393ca46cb2fa718164f50df20fed13b543b2516ef', bytes:669987},
  {ref:'CN2', file:'STM32H747_3D_CN2_LPJE101_0AHNL_APPROX_ZUP_20261018.step', sha:'326b1712a6c270945055b2ad90fdfaeed0c5880a7064fb503235c3b7462030da', bytes:1711062},
  {ref:'CN3', file:'STM32H747_3D_CN3_USB4105_GF_A_ZUP_20261018.step', sha:'a53b7f178ed7797919c6ded9adc72af16fca40c1682d753f27b6fb5ba3528e67', bytes:3885660},
  {ref:'CN4', file:'STM32H747_3D_CN4_USB4105_GF_A_ZUP_20261018.step', sha:'ca4cb89a521d827f13ad3b2648612064efabfcb22201c47f46289ffb9b02036a', bytes:3885660},
  {ref:'L1', file:'STM32H747_3D_L1_LQM2MPN2R2NG0L_ZUP_20261018.step', sha:'f272e3e5b7b48a97f2b55dcf43bd797141447004af684b9cc663b844cd0fbed3', bytes:161591},
]);
async function projectGuard() {
  const p = await eda.dmt_Project.getCurrentProjectInfo();
  if (!p || (p.name !== EXPECTED_PROJECT && p.friendlyName !== EXPECTED_PROJECT) || p.uuid !== EXPECTED_UUID) {
    throw new Error('STM32H747 exact project guard rejected library request');
  }
  return p;
}
async function digest(file) {
  const source = new Uint8Array(await file.arrayBuffer());
  const length = source.length;
  const padded = new Uint8Array(Math.ceil((length + 9) / 64) * 64);
  padded.set(source);
  padded[length] = 0x80;
  const bitsHigh = Math.floor(length / 0x20000000);
  const bitsLow = (length << 3) >>> 0;
  for (let i=0; i<4; i++) {
    padded[padded.length-8+i] = (bitsHigh >>> (24-i*8)) & 255;
    padded[padded.length-4+i] = (bitsLow >>> (24-i*8)) & 255;
  }
  const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const w = new Uint32Array(64);
  const rotr = (v,n) => (v>>>n)|(v<<(32-n));
  for (let base=0; base<padded.length; base+=64) {
    for (let i=0; i<16; i++) {
      const j=base+i*4;
      w[i] = ((padded[j]<<24)|(padded[j+1]<<16)|(padded[j+2]<<8)|padded[j+3])>>>0;
    }
    for (let i=16; i<64; i++) {
      const x=w[i-15], y=w[i-2];
      w[i] = (w[i-16]+(rotr(x,7)^rotr(x,18)^(x>>>3))+w[i-7]+(rotr(y,17)^rotr(y,19)^(y>>>10)))>>>0;
    }
    let [a,b,c,d,e,f,g,q]=h;
    for (let i=0; i<64; i++) {
      const t1=(q+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+k[i]+w[i])>>>0;
      const t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))>>>0;
      q=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0;
    }
    const work=[a,b,c,d,e,f,g,q];
    for (let i=0; i<8; i++) h[i]=(h[i]+work[i])>>>0;
  }
  return h.map(v=>v.toString(16).padStart(8,'0')).join('');
}
async function verifiedRead(path, expectedSha, expectedBytes) {
  await projectGuard();
  if (path !== MANIFEST_PATH && !WHITELIST.some(a => DIRECTORY + a.file === path)) throw new Error('STEP path is not whitelisted');
  const file = await eda.sys_FileSystem.readFileFromFileSystem(path);
  if (!file || (expectedBytes !== undefined && file.size !== expectedBytes)) throw new Error('Missing/wrong-sized whitelisted file');
  if (await digest(file) !== expectedSha) throw new Error('Whitelisted file SHA256 mismatch');
  await projectGuard();
  return file;
}
await projectGuard();
const manifestFile = await verifiedRead(MANIFEST_PATH, MANIFEST_SHA256);
const manifest = JSON.parse(await manifestFile.text());
const prepared = [];
for (const allowed of WHITELIST) {
  const asset = manifest.entries.find(a => a.ref === allowed.ref);
  if (!asset || asset.sha256 !== allowed.sha || asset.bytes !== allowed.bytes || asset.expectedLibraryTitle + '.step' !== allowed.file ||
      asset.flatAssetAbsolutePath.replaceAll('\\','/') !== DIRECTORY + allowed.file ||
      asset.geometryScaleXYZ.some(v => v !== 1) || asset.expectedNativeRotationZXYdeg.some(v => v !== 0)) {
    throw new Error('Pinned manifest/whitelist geometry mismatch: ' + allowed.ref);
  }
  const data = await verifiedRead(DIRECTORY + allowed.file, allowed.sha, allowed.bytes);
  if (!(await data.slice(0,200).text()).includes('ISO-10303-21')) throw new Error('Whitelisted file is not STEP');
  prepared.push(Object.freeze({
    ...allowed, asset,
    uuid: allowed.sha.slice(0,32),
    name: asset.expectedLibraryTitle,
  }));
}
if (new Set(prepared.map(p => p.uuid)).size !== prepared.length) throw new Error('Deterministic model ID collision');
const prior = globalThis[OWN_STATE_KEY];
if (prior) {
  if (prior.manifestSha256 !== MANIFEST_SHA256 || prior.libraryTitle !== LIBRARY_TITLE || !prior.result?.libraryUuid) throw new Error('Conflicting own loader state');
  await projectGuard();
  return {...prior.result, reusedOwnSessionRegistration:true};
}
let libraryUuid;
const callbacks = {
  getClassificationTree: async () => { await projectGuard(); return []; },
  getList: async (props = {}) => {
    await projectGuard();
    const query = props.query || {};
    const wd = String(query.wd || '').toLowerCase().trim();
    const titles = query.listByTitles;
    if (titles !== undefined && !Array.isArray(titles)) throw new Error('Invalid model title filter');
    const found = prepared.filter(a => (!wd || (a.name + ' ' + a.ref + ' ' + a.asset.modelPart).toLowerCase().includes(wd)) &&
      (!titles || !titles.length || titles.includes(a.name) || titles.includes(a.uuid)));
    const pageSize = Number.isInteger(props.pageSize) ? Math.min(50, Math.max(1,props.pageSize)) : 10;
    const page = Number.isInteger(props.page) ? Math.max(1,props.page) : 1;
    return {count:found.length, lists:found.slice((page-1)*pageSize,page*pageSize).map(a => ({
      uuid:a.uuid, name:a.name, title:a.name, modelType:'step',
      description:a.asset.relation + (a.ref === 'CN2' ? ' APPROXIMATE; not mechanical-fit certified.' : ''),
    })), page, pageSize, totalPage:Math.max(1,Math.ceil(found.length/pageSize))};
  },
  getDetail: async uuid => {
    await projectGuard();
    if (typeof uuid !== 'string') throw new Error('Model ID must be a whitelisted string');
    const asset = prepared.find(a => a.uuid === uuid || a.name === uuid);
    if (!asset) throw new Error('Unknown model ID rejected');
    const data = await verifiedRead(DIRECTORY + asset.file, asset.sha, asset.bytes);
    return {uuid:asset.uuid, name:asset.name, title:asset.name, modelType:'step', data};
  },
};
await projectGuard();
libraryUuid = await eda.lib_LibrariesList.registerExtendLibrary(LIBRARY_TITLE, {model3d:callbacks});
if (typeof libraryUuid !== 'string' || !libraryUuid || libraryUuid.includes('|')) throw new Error('External library API did not return a usable UUID');
await projectGuard();
const applyPlan = {
  schema:'stm32-runtime-external-3d-five-plan-v1',
  status:'REGISTERED_MODELS_ONLY_ROOT_PILOT_AND_COMPONENT_BINDING_REQUIRED',
  expectedProjectName:EXPECTED_PROJECT, expectedProjectUuid:EXPECTED_UUID,
  expectedPcbUuid:'0ac2a19168000d8e', expectedComponentCount:437,
  libraryUuid, libraryTitle:LIBRARY_TITLE, assetManifestSha256:MANIFEST_SHA256,
  nativeTransformAssumption:manifest.nativeTransformAssumption,
  entries:prepared.map(a => ({ref:a.ref,id:a.asset.componentId,footprintUuid:a.asset.footprintUuid,
    model:a.uuid+'|'+libraryUuid,uuid:a.uuid,libraryUuid,title:a.name,
    transform:a.asset.expectedNativeTransformString,sourceSha256:a.sha,
    expectedBboxMm:a.asset.canonicalBoundsMm,relation:a.asset.relation,limitations:a.asset.limitations})),
};
const result = {libraryUuid,libraryTitle:LIBRARY_TITLE,registeredModels:prepared.map(a=>({ref:a.ref,uuid:a.uuid,name:a.name})),
  applyPlan, transientRegistration:true, stableCustomLibraryUuidSupported:false,
  deterministicModelIdsSupported:true, noNativeComponentBindingPerformed:true,
  resume:'Run this same loader in the existing authorized extension after restart. Reuse returned IDs only while that session registration exists. If returned libraryUuid changes, root must rebind these5 3D metadata references using the newly returned applyPlan; do not claim automatic durable portability.',
  callbackProjectGuard:'Every list/classification/detail/read checks exact project name+UUID; unknown model IDs and nonwhitelisted paths are rejected.'};
Object.defineProperty(globalThis, OWN_STATE_KEY, {value:Object.freeze({manifestSha256:MANIFEST_SHA256,libraryTitle:LIBRARY_TITLE,result}),writable:false,configurable:false});
return result;
