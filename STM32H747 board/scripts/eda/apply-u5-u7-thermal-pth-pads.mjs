const root = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const projectUuid = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const projectName = 'STM32H747_MCU_BOARD_v19';
const targets = {
  U5: {
    uuid: 'b098cceac55eab69', padNum: '25', centralId: 'e25', count: 64,
    sha256: '0d8c356f37ea37ae13473661aeb0bd0a15fa757ed733b9d87cb48e0a9a62f887',
    ids: ['e36', 'e37', 'e38', 'e39'],
    firstTickets: [59, 60, 61, 62],
    centers: [[-25.5906, -27.5591], [-25.5906, 27.5591], [25.5906, -27.5591], [25.5906, 27.5591]],
  },
  U7: {
    uuid: '15077d1eac66847c', padNum: '33', centralId: 'e33', count: 72,
    sha256: 'ecf53a27147008d5a51499789596148c163b1bff6a176733b54eb5ceb8ea2d09',
    ids: ['e44', 'e45', 'e46', 'e47'],
    firstTickets: [67, 68, 69, 70],
    centers: [[-40.3543, -40.3543], [-40.3543, 42.3228], [42.3228, -40.3543], [42.3228, 42.3228]],
  },
};

const reference = __taskArgs[0];
const target = targets[reference];
if (!target) throw new Error('One scoped thermal-PTH footprint is required: U5 or U7');
const project = await eda.dmt_Project.getCurrentProjectInfo();
if (project?.uuid !== projectUuid || project?.friendlyName !== projectName) {
  throw new Error('STM32H747 dedicated project identity mismatch');
}

const path = `${root}/output/validation/native-${reference}-thermal-pth-pad-candidate.epru`;
const file = await eda.sys_FileSystem.readFileFromFileSystem(path);
if (!file) throw new Error(`Reviewed ${reference} thermal-PTH source is missing`);
const source = await file.text();
const digest = Array.from(
  new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source))),
  value => value.toString(16).padStart(2, '0'),
).join('');
if (digest !== target.sha256) throw new Error(`${reference} thermal-PTH source hash mismatch`);

const rows = source.split(/\r?\n/).filter(line => line.includes('||')).map(line => {
  const split = line.indexOf('||');
  return {
    head: JSON.parse(line.slice(0, split)),
    body: JSON.parse(line.slice(split + 2).replace(/\|$/, '')),
  };
});
if (rows.length !== target.count || rows[0]?.body?.uuid !== target.uuid || rows[0]?.body?.docType !== 'FOOTPRINT') {
  throw new Error(`${reference} footprint identity or record-count mismatch`);
}
if (rows.some(row => row.head.type === 'VIA' || row.head.type === 'PAD_NET')) {
  throw new Error('Library footprint candidate unexpectedly contains board VIA/PAD_NET records');
}

const sameNumber = rows.filter(row => row.head.type === 'PAD' && String(row.body.num) === target.padNum);
if (sameNumber.length !== 5) throw new Error(`${reference} must contain central plus four same-number thermal PADs`);
const central = sameNumber.find(row => row.head.id === target.centralId);
if (!central || central.body.centerX !== 0 || central.body.centerY !== 0 || central.body.specialPad?.length !== 3) {
  throw new Error(`${reference} central exposed-pad/specialPad contract changed`);
}
const expected = new Map(target.ids.map((id, index) => [id, target.centers[index]]));
const additions = sameNumber.filter(row => expected.has(row.head.id));
if (additions.length !== 4) throw new Error(`${reference} reviewed thermal PAD IDs are incomplete`);
for (const row of additions) {
  const [x, y] = expected.get(row.head.id);
  const elementIndex = target.ids.indexOf(row.head.id);
  const body = row.body;
  if (
    row.head.firstTicket !== target.firstTickets[elementIndex] ||
    body.centerX !== x || body.centerY !== y || body.netName !== '' || body.layerId !== 12 || body.plated !== true ||
    body.hole?.holeType !== 'ROUND' || body.hole?.width !== 11.811 || body.hole?.height !== 11.811 ||
    body.defaultPad?.padType !== 'ELLIPSE' || body.defaultPad?.width !== 23.622047 || body.defaultPad?.height !== 23.622047 ||
    body.specialPad?.length !== 0 || body.unusedInnerLayers?.length !== 0
  ) throw new Error(`${reference} ${row.head.id} thermal-PTH geometry contract failed`);
}

await eda.dmt_EditorControl.closeDocument(`${target.uuid}@${projectUuid}`);
const updated = await eda.lib_Footprint.updateDocumentSource(target.uuid, projectUuid, source);
if (!updated) throw new Error(`${reference} thermal-PTH library update failed`);
const receiptPath = `${root}/output/validation/native-${reference}-thermal-pth-pad-update-receipt.json`;
const receipt = {
  reference, uuid: target.uuid, updated, sourceSha256: digest,
  centralPadId: target.centralId, addedPadIds: target.ids,
  requiredPostReopenProof: 'each new child has an explicit GND PAD_NET row; U5-only runtime pads=1184 and Connection=8, U5+U7 pads=1188 and Connection=0',
};
const saved = await eda.sys_FileSystem.saveFileToFileSystem(
  receiptPath, new Blob([JSON.stringify(receipt, null, 2)]), undefined, false,
);
return { ...receipt, saved, receiptPath };
