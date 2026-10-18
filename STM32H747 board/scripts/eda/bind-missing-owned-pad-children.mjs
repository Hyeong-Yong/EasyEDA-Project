const root = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const pcbUuid = '0ac2a19168000d8e';
const projectUuid = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const projectName = 'STM32H747_MCU_BOARD_v19';
const tolerance = 0.051;
const centerTolerance = 0.11;

const sma = {
  J2:  ['b921a22d4b7579ed', [-100, -100]],
  J3:  ['afef66d437b67df9', [-100, -100]],
  J4:  ['0b5fac9098dce533', [-100, -100]],
  J5:  ['a720c263d59d27d0', [-100, -100]],
  J6:  ['c8db40735c04cd92', [-100, -100]],
  J7:  ['1772c366e461a031', [-100, -100]],
  J8:  ['8b88019d0dcca1ab', [-100, -100]],
  J9:  ['f26bff9701d0729d', [-100, -100]],
  J10: ['f09a8f99f71c453e', [-100, -100]],
  J11: ['fd77caf2157b0c36', [-100, -100]],
  J12: ['fc09065fd9dbbdfb', [100, 100]],
  J13: ['8a697cb3ec6de186', [100, 100]],
  J14: ['7843bf8271627f69', [100, 100]],
  J15: ['c9e806fb8153837f', [100, 100]],
  J16: ['f884fcf9bad6e3a5', [-100, 100]],
  J17: ['60ef92fca4c18be8', [100, 100]],
};
const allSmaCenters = [[-100, -100], [-100, 100], [100, -100], [100, 100]];

const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.uuid !== projectUuid || project?.friendlyName !== projectName) {
  throw new Error('STM32H747 dedicated project identity mismatch');
}
await eda.dmt_EditorControl.openDocument(pcbUuid);
if ((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid !== pcbUuid) {
  throw new Error('Wrong final PCB for missing-owned-pad net assignment');
}
const pads = await eda.pcb_PrimitivePad.getAll();
if (pads.length !== 1238) throw new Error(`Expected 1238 runtime PADs after 50 restores, got ${pads.length}`);

const near = (left, right, epsilon = tolerance) => Math.abs(left - right) < epsilon;
const shapeMatches = (actual, expected) => Array.isArray(actual) && actual.length === expected.length &&
  actual[0] === expected[0] && actual.slice(1).every((value, index) => near(value, expected[index + 1]));
const holeMatches = (actual, expected) => expected === null ? actual === null :
  Array.isArray(actual) && actual[0] === expected[0] && near(actual[1], expected[1]);
const results = [];

const bindChild = async (reference, pad, expected) => {
  const id = pad.getState_PrimitiveId();
  const beforeNet = pad.getState_Net();
  if (!['', expected.net].includes(beforeNet)) {
    throw new Error(`${reference} ${id}: unexpected pre-bind net ${beforeNet}`);
  }
  if (beforeNet === '') await eda.pcb_PrimitivePad.modify(id, { net: expected.net });
  const refreshed = await eda.pcb_PrimitivePad.get(id);
  if (refreshed?.getState_Net() !== expected.net) {
    throw new Error(`${reference} ${id}: explicit net binding did not persist in runtime`);
  }
  results.push({
    reference, id, padNumber: refreshed.getState_PadNumber(),
    beforeNet, afterNet: refreshed.getState_Net(),
    x: refreshed.getState_X(), y: refreshed.getState_Y(),
    layer: refreshed.getState_Layer(), pad: refreshed.getState_Pad(),
    hole: refreshed.getState_Hole(), plated: refreshed.getState_Metallization(),
  });
};

for (const [reference, [parent, existingLocal]] of Object.entries(sma)) {
  const receiptFile=await eda.sys_FileSystem.readFileFromFileSystem(`${root}/output/validation/native-${reference}-missing-owned-pad-create-receipt.json`);
  if(!receiptFile)throw new Error(`${reference}: actual native creation receipt missing`);
  const creation=JSON.parse(await receiptFile.text());
  if(creation.reference!==reference||!creation.expected||!creation.saved||creation.added?.length!==3)throw new Error(`${reference}: native creation receipt changed`);
  const createdIds=new Set(creation.added.map(p=>parent+p.id));
  const centralId = `${parent}e2`;
  const central = pads.find(pad => pad.getState_PrimitiveId() === centralId);
  if (!central || central.getState_PadNumber() !== '2' || central.getState_Net() !== 'GND') {
    throw new Error(`${reference}: existing e2/GND identity changed`);
  }
  const children = pads.filter(pad => pad.getState_PrimitiveId().startsWith(parent) &&
    pad.getState_PrimitiveId() !== centralId && pad.getState_PadNumber() === '2');
  if (children.length !== 3) throw new Error(`${reference}: expected three restored GND posts`);
  if(createdIds.size!==3||children.some(p=>!createdIds.has(p.getState_PrimitiveId())))throw new Error(`${reference}: child ID not in verified native creation receipt`);
  const missingLocal = allSmaCenters.filter(point =>
    point[0] !== existingLocal[0] || point[1] !== existingLocal[1]);
  const unmatched = [...missingLocal];
  for (const child of children) {
    const local = unmatched.find(point =>
      near(child.getState_X(), central.getState_X() + point[0] - existingLocal[0], centerTolerance) &&
      near(child.getState_Y(), central.getState_Y() + point[1] - existingLocal[1], centerTolerance));
    if (!local || child.getState_Layer() !== 12 || child.getState_Metallization() !== true ||
      !shapeMatches(child.getState_Pad(), ['ELLIPSE', 98.425197, 98.425197]) ||
      !holeMatches(child.getState_Hole(), ['ROUND', 59.055118])) {
      throw new Error(`${reference}: restored post geometry/world-center mismatch`);
    }
    unmatched.splice(unmatched.indexOf(local), 1);
    await bindChild(reference, child, { net: 'GND' });
  }
  if (unmatched.length) throw new Error(`${reference}: one or more Gerber post centers are missing`);
}

const swParent = 'a628f3517e8fe1d3';
const swReceiptFile=await eda.sys_FileSystem.readFileFromFileSystem(`${root}/output/validation/native-SW1-missing-owned-pad-create-receipt.json`);
if(!swReceiptFile)throw new Error('SW1 actual native creation receipt missing');
const swCreation=JSON.parse(await swReceiptFile.text());
if(swCreation.reference!=='SW1'||!swCreation.expected||!swCreation.saved||swCreation.added?.length!==2)throw new Error('SW1 native creation receipt changed');
const swCreatedIds=new Set(swCreation.added.map(p=>swParent+p.id));
for (const spec of [
  { num: '1', centralSuffix: 'e1', existing: [167.3228, -88.5827], missing: [-167.3228, -88.5827], net: 'Net-(D1-K)' },
  { num: '2', centralSuffix: 'e2', existing: [167.3228, 88.5827], missing: [-167.3228, 88.5827], net: 'GND' },
]) {
  const centralId = `${swParent}${spec.centralSuffix}`;
  const central = pads.find(pad => pad.getState_PrimitiveId() === centralId);
  if (!central || central.getState_PadNumber() !== spec.num || central.getState_Net() !== spec.net) {
    throw new Error(`SW1.${spec.num}: existing child/net identity changed`);
  }
  const children = pads.filter(pad => pad.getState_PrimitiveId().startsWith(swParent) &&
    pad.getState_PrimitiveId() !== centralId && pad.getState_PadNumber() === spec.num);
  if (children.length !== 1) throw new Error(`SW1.${spec.num}: expected one restored SMD child`);
  const child = children[0];
  if(!swCreatedIds.has(child.getState_PrimitiveId()))throw new Error('SW1 child ID not in verified native creation receipt');
  const expectedX = central.getState_X() + spec.missing[0] - spec.existing[0];
  const expectedY = central.getState_Y() + spec.missing[1] - spec.existing[1];
  if (!near(child.getState_X(), expectedX, centerTolerance) || !near(child.getState_Y(), expectedY, centerTolerance) ||
    child.getState_Layer() !== 1 || child.getState_Metallization() !== true ||
    !shapeMatches(child.getState_Pad(), ['RECT', 62.992126, 39.370079, 0]) || child.getState_Hole() !== null) {
    throw new Error(`SW1.${spec.num}: restored SMD geometry/world-center mismatch`);
  }
  await bindChild('SW1', child, spec);
}

if (results.length !== 50) throw new Error(`Expected 50 explicit child bindings, got ${results.length}`);
if (!await eda.pcb_Document.save()) throw new Error('Final PCB save failed after 50 child net bindings');
const receipt = {
  pcbUuid, expectedAdded: 50, totalRuntimePads: pads.length,
  evidence: {
    sma: 'native-missing-sma-ground-pth-audit.json@7025ab3611c319c5',
    sw1: 'native-missing-sw1-duplicate-smd-pad-audit.json@1b430f66b318b337',
  },
  results,
};
const receiptPath = `${root}/output/validation/native-missing-owned-pad-net-binding-50.json`;
await eda.sys_FileSystem.saveFileToFileSystem(
  receiptPath, new Blob([JSON.stringify(receipt, null, 2)]), undefined, false,
);
return { receiptPath, expectedAdded: 50, results: results.length };
