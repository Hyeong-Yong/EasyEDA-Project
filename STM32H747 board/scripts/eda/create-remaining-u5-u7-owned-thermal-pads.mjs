const root = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const projectUuid = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const projectName = 'STM32H747_MCU_BOARD_v19';
const tolerance = 0.051;
const targets = {
  U5: {
    uuid: 'b098cceac55eab69', padNum: '25', before: 26, sameNumBefore: 2,
    existing: [[0, 0], [-25.5906, -27.5591]],
    missing: [[-25.5906, 27.5591], [25.5906, -27.5591], [25.5906, 27.5591]],
  },
  U7: {
    uuid: '15077d1eac66847c', padNum: '33', before: 33, sameNumBefore: 1,
    existing: [[0, 0]],
    missing: [[-40.3543, -40.3543], [-40.3543, 42.3228], [42.3228, -40.3543], [42.3228, 42.3228]],
  },
};

const reference = __taskArgs[0];
const target = targets[reference];
if (!target) throw new Error('One scoped footprint is required: U5 or U7');
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.uuid !== projectUuid || project?.friendlyName !== projectName) {
  throw new Error('STM32H747 dedicated project identity mismatch');
}

const tab = await eda.lib_Footprint.openInEditor(target.uuid, projectUuid);
if (!tab || tab !== `${target.uuid}@${projectUuid}`) throw new Error(`Wrong ${reference} footprint tab`);
await new Promise(resolve => setTimeout(resolve, 1500));
const source = await eda.sys_FileManager.getDocumentSource();
const first = source.split(/\r?\n/).find(line => line.includes('||'));
const meta = JSON.parse(first.slice(first.indexOf('||') + 2).replace(/\|$/, ''));
if (meta.uuid !== target.uuid || !['FOOTPRINT', 'PCB'].includes(meta.docType)) {
  throw new Error(`Wrong ${reference} footprint identity`);
}

const near = (left, right) => Math.abs(left - right) < tolerance;
const matches = (pad, point) => near(pad.getState_X(), point[0]) && near(pad.getState_Y(), point[1]);
const before = await eda.pcb_PrimitivePad.getAll();
const sameBefore = before.filter(pad => pad.getState_PadNumber() === target.padNum);
if (before.length !== target.before || sameBefore.length !== target.sameNumBefore) {
  throw new Error(`${reference} pre-create pad inventory mismatch`);
}
for (const point of target.existing) {
  if (sameBefore.filter(pad => matches(pad, point)).length !== 1) {
    throw new Error(`${reference} expected existing pad is missing at ${point}`);
  }
}
for (const point of target.missing) {
  if (before.some(pad => matches(pad, point))) throw new Error(`${reference} target center is already occupied at ${point}`);
}
const central = sameBefore.find(pad => matches(pad, [0, 0]));
if (!central || central.getState_Layer() !== 12 || central.getState_SpecialPad()?.length !== 3) {
  throw new Error(`${reference} central exposed-pad special-layer shape is not preserved`);
}

let createError;
for (const [x, y] of target.missing) {
  try {
    await eda.pcb_PrimitivePad.create(
      12, target.padNum, x, y, 0,
      ['ELLIPSE', 23.622047, 23.622047], '', ['ROUND', 11.811],
      0, 0, 0, true, 0,
    );
  } catch (error) {
    createError = String(error?.stack || error);
    break;
  }
}

const after = await eda.pcb_PrimitivePad.getAll();
const beforeIds = new Set(before.map(pad => pad.getState_PrimitiveId()));
const addedObjects = after.filter(pad => !beforeIds.has(pad.getState_PrimitiveId()));
const added = addedObjects.map(pad => ({
  id: pad.getState_PrimitiveId(), num: pad.getState_PadNumber(),
  x: pad.getState_X(), y: pad.getState_Y(), layer: pad.getState_Layer(),
  pad: pad.getState_Pad(), hole: pad.getState_Hole(),
  plated: pad.getState_Metallization(), net: pad.getState_Net(),
}));
const exactGeometry = added.every(item => {
  const expectedPoint = target.missing.find(point => near(item.x, point[0]) && near(item.y, point[1]));
  return expectedPoint && item.num === target.padNum && item.layer === 12 && item.plated === true && item.net === '' &&
    item.pad?.[0] === 'ELLIPSE' && near(item.pad[1], 23.622047) && near(item.pad[2], 23.622047) &&
    item.hole?.[0] === 'ROUND' && near(item.hole[1], 11.811);
});
const eachCenterOnce = target.missing.every(point => added.filter(item => near(item.x, point[0]) && near(item.y, point[1])).length === 1);
const expected = !createError && added.length === target.missing.length && exactGeometry && eachCenterOnce &&
  after.length === target.before + target.missing.length &&
  after.filter(pad => pad.getState_PadNumber() === target.padNum).length === target.sameNumBefore + target.missing.length;
const saved = expected ? await eda.pcb_Document.save() : false;
const receipt = {
  reference, uuid: target.uuid, tab, before: before.length, after: after.length,
  sameNumberBefore: sameBefore.length, expectedExistingCenters: target.existing,
  requestedCenters: target.missing, added, createError, expected, saved,
};
const receiptPath = `${root}/output/validation/native-${reference}-remaining-direct-thermal-pads-receipt.json`;
await eda.sys_FileSystem.saveFileToFileSystem(
  receiptPath, new Blob([JSON.stringify(receipt, null, 2)]), undefined, false,
);
if (!expected || !saved) throw new Error(`${reference} remaining thermal-pad creation not verified; inspect receipt`);
await eda.dmt_EditorControl.closeDocument(tab);
return { ...receipt, receiptPath };
