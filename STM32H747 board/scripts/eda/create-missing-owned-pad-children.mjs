const root = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const projectUuid = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const projectName = 'STM32H747_MCU_BOARD_v19';
const tolerance = 0.051;

const sma = {
  J2:  ['1a275103229cd0ed', [-100, -100]],
  J3:  ['afd1e7eaea1c6d0b', [-100, -100]],
  J4:  ['3efe64435dd88760', [-100, -100]],
  J5:  ['420752e0b7dd516b', [-100, -100]],
  J6:  ['6cc742d2e9f6287b', [-100, -100]],
  J7:  ['456e5ebcec73f244', [-100, -100]],
  J8:  ['af0f2c62672d4563', [-100, -100]],
  J9:  ['99bc905658c65075', [-100, -100]],
  J10: ['819dad664d54a2aa', [-100, -100]],
  J11: ['247603e988790c9b', [-100, -100]],
  J12: ['4767d4db118c9e30', [100, 100]],
  J13: ['728a108305576e94', [100, 100]],
  J14: ['133a56f0204e267d', [100, 100]],
  J15: ['93edcf417121fbf5', [100, 100]],
  J16: ['ca34008aa681bcb9', [-100, 100]],
  J17: ['d6f78b7294940c71', [100, 100]],
};

const reference = __taskArgs[0];
let target;
if (sma[reference]) {
  const [uuid, existing] = sma[reference];
  const all = [[-100, -100], [-100, 100], [100, -100], [100, 100]];
  target = {
    uuid,
    before: 2,
    evidence: 'native-missing-sma-ground-pth-audit.json@7025ab3611c319c5',
    specs: [{
      num: '2', layer: 12, plated: true,
      pad: ['ELLIPSE', 98.425197, 98.425197],
      hole: ['ROUND', 59.055118],
      existing: [existing],
      missing: all.filter(point => point[0] !== existing[0] || point[1] !== existing[1]),
    }],
  };
} else if (reference === 'SW1') {
  target = {
    uuid: 'bdc7750c34538c7c',
    before: 2,
    evidence: 'native-missing-sw1-duplicate-smd-pad-audit.json@1b430f66b318b337',
    specs: [
      {
        num: '1', layer: 1, plated: true,
        pad: ['RECT', 62.992126, 39.370079, 0], hole: null,
        existing: [[167.3228, -88.5827]], missing: [[-167.3228, -88.5827]],
      },
      {
        num: '2', layer: 1, plated: true,
        pad: ['RECT', 62.992126, 39.370079, 0], hole: null,
        existing: [[167.3228, 88.5827]], missing: [[-167.3228, 88.5827]],
      },
    ],
  };
} else {
  throw new Error('One reviewed reference is required: J2-J17 or SW1');
}

const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.uuid !== projectUuid || project?.friendlyName !== projectName) {
  throw new Error('STM32H747 dedicated project identity mismatch');
}
const tab = await eda.lib_Footprint.openInEditor(target.uuid, projectUuid);
if (!tab || tab !== `${target.uuid}@${projectUuid}`) {
  throw new Error(`Wrong ${reference} footprint tab`);
}
await new Promise(resolve => setTimeout(resolve, 1500));
const source = await eda.sys_FileManager.getDocumentSource();
const first = source.split(/\r?\n/).find(line => line.includes('||'));
const meta = JSON.parse(first.slice(first.indexOf('||') + 2).replace(/\|$/, ''));
if (meta.uuid !== target.uuid || !['FOOTPRINT', 'PCB'].includes(meta.docType)) {
  throw new Error(`Wrong ${reference} footprint identity`);
}

const near = (left, right) => Math.abs(left - right) < tolerance;
const atPoint = (pad, point) => near(pad.getState_X(), point[0]) && near(pad.getState_Y(), point[1]);
const shapeMatches = (actual, expected) => Array.isArray(actual) && actual.length === expected.length &&
  actual[0] === expected[0] && actual.slice(1).every((value, index) => near(value, expected[index + 1]));
const holeMatches = (actual, expected) => expected === null ? actual === null :
  Array.isArray(actual) && actual[0] === expected[0] && near(actual[1], expected[1]);

const before = await eda.pcb_PrimitivePad.getAll();
if (before.length !== target.before) throw new Error(`${reference} pre-create PAD count mismatch`);
for (const spec of target.specs) {
  const sameNumber = before.filter(pad => pad.getState_PadNumber() === spec.num);
  if (sameNumber.length !== spec.existing.length) {
    throw new Error(`${reference}.${spec.num} pre-create physical-child count mismatch`);
  }
  for (const point of spec.existing) {
    if (sameNumber.filter(pad => atPoint(pad, point)).length !== 1) {
      throw new Error(`${reference}.${spec.num} expected existing center is missing at ${point}`);
    }
  }
  for (const point of spec.missing) {
    if (before.some(pad => atPoint(pad, point))) {
      throw new Error(`${reference}.${spec.num} target center is already occupied at ${point}`);
    }
  }
}

let createError;
for (const spec of target.specs) {
  for (const [x, y] of spec.missing) {
    try {
      await eda.pcb_PrimitivePad.create(
        spec.layer, spec.num, x, y, 0, spec.pad, '', spec.hole,
        0, 0, 0, spec.plated, 0,
      );
    } catch (error) {
      createError = String(error?.stack || error);
      break;
    }
  }
  if (createError) break;
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
const missingCount = target.specs.reduce((count, spec) => count + spec.missing.length, 0);
const exactGeometry = added.every(item => {
  const spec = target.specs.find(candidate => candidate.num === item.num &&
    candidate.missing.some(point => near(item.x, point[0]) && near(item.y, point[1])));
  return spec && item.layer === spec.layer && item.plated === spec.plated && item.net === '' &&
    shapeMatches(item.pad, spec.pad) && holeMatches(item.hole, spec.hole);
});
const eachCenterOnce = target.specs.every(spec => spec.missing.every(point =>
  added.filter(item => item.num === spec.num && near(item.x, point[0]) && near(item.y, point[1])).length === 1));
const finalNumberCounts = target.specs.every(spec =>
  after.filter(pad => pad.getState_PadNumber() === spec.num).length === spec.existing.length + spec.missing.length);
const expected = !createError && added.length === missingCount && exactGeometry && eachCenterOnce &&
  finalNumberCounts && after.length === target.before + missingCount;
const saved = expected ? await eda.pcb_Document.save() : false;
const receipt = {
  reference, uuid: target.uuid, tab, evidence: target.evidence,
  before: before.length, after: after.length, specs: target.specs,
  added, createError, expected, saved,
};
const receiptPath = `${root}/output/validation/native-${reference}-missing-owned-pad-create-receipt.json`;
await eda.sys_FileSystem.saveFileToFileSystem(
  receiptPath, new Blob([JSON.stringify(receipt, null, 2)]), undefined, false,
);
if (!expected || !saved) {
  throw new Error(`${reference} missing-owned-pad creation not verified; inspect receipt`);
}
await eda.dmt_EditorControl.closeDocument(tab);
return { ...receipt, receiptPath };
