const ROOT = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const PROJECT_UUID = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const PLAN_PATH = ROOT + '/output/validation/native-component-link-rebind-plan.json';
const OUTPUT = ROOT + '/output/validation/';
const EPSILON = 0.001;
const SYMBOL_DOCUMENT_TYPES = new Set([2, 7, 17, 18, 19, 20, 21, 22, 25, 32]);

const offset = Number(__taskArgs[0] ?? 0);
const count = Number(__taskArgs[1] ?? 5);
if (!Number.isInteger(offset) || offset < 0) throw new Error('offset must be a non-negative integer');
if (!Number.isInteger(count) || count < 1 || count > 10) throw new Error('count must be an integer from 1 through 10');

function parseSource(source) {
  const rows = [];
  for (const line of String(source).split(/\r?\n/)) {
    if (!line.trim()) continue;
    const divider = line.indexOf('||');
    if (divider < 0) throw new Error('Malformed native record without || delimiter');
    const head = JSON.parse(line.slice(0, divider));
    let rawBody = line.slice(divider + 2);
    if (rawBody.endsWith('|')) rawBody = rawBody.slice(0, -1);
    rows.push({ head, body: rawBody ? JSON.parse(rawBody) : null });
  }
  return rows;
}

function serializeSource(rows) {
  return rows.map(({ head, body }) =>
    JSON.stringify(head) + '||' + (body === null ? '' : JSON.stringify(body))
  ).join('|\n');
}

function docHead(rows) {
  const record = rows.find(row => row.head?.type === 'DOCHEAD');
  if (!record?.body) throw new Error('Native source has no DOCHEAD body');
  return record.body;
}

function symbolEditorType(value) {
  if (SYMBOL_DOCUMENT_TYPES.has(Number(value))) return true;
  return typeof value === 'string' && value.toUpperCase().includes('SYMBOL');
}

function isFilledPdfPoly(row) {
  const body = row.body || {};
  if (row.head?.type !== 'POLY' || body.fillStyle !== 'SOLID' || !body.fillColor) return false;
  const width = body.strokeWidth;
  const unrepaired = width === null || width === undefined || Number(width) === 0 || !body.strokeColor;
  const alreadyRepaired = Number(width) === EPSILON && body.strokeColor === body.fillColor;
  return unrepaired || alreadyRepaired;
}

function valueKey(value) {
  return JSON.stringify(value === undefined ? null : value);
}

function pinContract(rows) {
  const pins = new Map();
  const numbers = new Map();
  const types = new Map();
  for (const row of rows) {
    if (row.head?.type === 'PIN') {
      const body = row.body || {};
      pins.set(row.head.id, {
        x: body.x, y: body.y, rotation: body.rotation, pinShape: body.pinShape,
        partId: body.partId, display: body.display, color: body.color,
      });
    } else if (row.head?.type === 'ATTR' && row.body) {
      if (row.body.key === 'NUMBER' || row.body.key === 'Pin Number') {
        const list = numbers.get(row.body.parentId) || [];
        list.push(String(row.body.value ?? ''));
        numbers.set(row.body.parentId, list);
      } else if (row.body.key === 'Pin Type') {
        const list = types.get(row.body.parentId) || [];
        list.push(String(row.body.value ?? ''));
        types.set(row.body.parentId, list);
      }
    }
  }
  return { pins, numbers, types };
}

function assertSamePinContract(before, after, symbolUuid) {
  if (before.pins.size !== after.pins.size) throw new Error(symbolUuid + ': PIN count changed');
  for (const [pinId, expected] of before.pins) {
    const actual = after.pins.get(pinId);
    if (!actual) throw new Error(symbolUuid + ': PIN disappeared: ' + pinId);
    for (const key of Object.keys(expected)) {
      if (valueKey(actual[key]) !== valueKey(expected[key])) {
        throw new Error(symbolUuid + ': PIN ' + pinId + ' changed ' + key);
      }
    }
    if (valueKey(after.numbers.get(pinId) || []) !== valueKey(before.numbers.get(pinId) || [])) {
      throw new Error(symbolUuid + ': PIN numbers changed: ' + pinId);
    }
    if (valueKey(after.types.get(pinId) || []) !== valueKey(before.types.get(pinId) || [])) {
      throw new Error(symbolUuid + ': PIN type changed: ' + pinId);
    }
  }
}

async function pause(milliseconds) {
  await new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function assertProject() {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project?.uuid !== PROJECT_UUID) {
    throw new Error('Dedicated STM32H747 project UUID guard failed');
  }
  return project;
}

async function readExactSymbol(symbolUuid) {
  let last = 'no document information';
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await assertProject();
    const info = await eda.dmt_SelectControl.getCurrentDocumentInfo();
    const source = await eda.sys_FileManager.getDocumentSource();
    try {
      const rows = parseSource(source);
      const head = docHead(rows);
      const exactTab = info?.tabId === symbolUuid + '@' + PROJECT_UUID;
      if (info?.uuid === symbolUuid && symbolEditorType(info?.documentType) && exactTab &&
          head.uuid === symbolUuid && head.docType === 'SYMBOL') {
        return { info, source, rows, head };
      }
      last = JSON.stringify({ info, docHead: head });
    } catch (error) {
      last = String(error?.message || error);
    }
    if (attempt < 2) await pause(150);
  }
  throw new Error(symbolUuid + ': refused to touch mismatched editor document: ' + last);
}

async function saveText(path, text) {
  const saved = await eda.sys_FileSystem.saveFileToFileSystem(path, new Blob([text]), undefined, false);
  if (!saved) throw new Error('Failed to save validation artifact: ' + path);
}

async function repairOne(item, absoluteIndex) {
  const symbolUuid = String(item.imported_uuid || '');
  if (!/^[0-9a-f]{16}$/.test(symbolUuid)) throw new Error('Invalid imported symbol UUID in plan');
  const expectedTabId = symbolUuid + '@' + PROJECT_UUID;

  const openedTab = await eda.lib_Symbol.openInEditor(symbolUuid, PROJECT_UUID);
  if (openedTab !== expectedTabId) throw new Error(symbolUuid + ': unexpected symbol tab id: ' + String(openedTab));
  const opened = await readExactSymbol(symbolUuid);
  const beforeContract = pinContract(opened.rows);
  if (!beforeContract.pins.size) throw new Error(symbolUuid + ': symbol has no electrical PIN records');

  const numberByPin = new Map();
  for (const [pinId, values] of beforeContract.numbers) {
    const value = values.find(entry => entry !== '') || '';
    numberByPin.set(pinId, value);
  }
  const pinOrdinal = new Map(Array.from(beforeContract.pins.keys()).map((pinId, index) => [pinId, index + 1]));
  const targetPolyIds = [];
  let repairedNames = 0;
  for (const row of opened.rows) {
    if (isFilledPdfPoly(row)) {
      row.body.strokeWidth = EPSILON;
      row.body.strokeColor = row.body.fillColor;
      targetPolyIds.push(row.head.id);
    } else if (row.head?.type === 'PIN') {
      row.body.length = EPSILON;
    } else if (row.head?.type === 'ATTR' && row.body &&
               (row.body.key === 'NAME' || row.body.key === 'Pin Name')) {
      if (!String(row.body.value ?? '').trim()) {
        const number = numberByPin.get(row.body.parentId) || '';
        row.body.value = number || ('P' + (pinOrdinal.get(row.body.parentId) || 1));
        repairedNames += 1;
      }
      row.body.keyVisible = false;
      row.body.valueVisible = false;
    }
  }

  const pinNameParents = new Set(opened.rows.filter(row => row.head?.type === 'ATTR' && row.body &&
    (row.body.key === 'NAME' || row.body.key === 'Pin Name')).map(row => row.body.parentId));
  for (const pinId of beforeContract.pins.keys()) {
    if (!pinNameParents.has(pinId)) throw new Error(symbolUuid + ': PIN has no Pin Name attribute: ' + pinId);
  }

  const replacement = serializeSource(opened.rows);
  if (!await eda.sys_FileManager.setDocumentSource(replacement)) {
    throw new Error(symbolUuid + ': setDocumentSource rejected visual repair');
  }
  const accepted = await readExactSymbol(symbolUuid);
  const libraryUpdated = await eda.lib_Symbol.updateDocumentSource(symbolUuid, PROJECT_UUID, accepted.source);
  if (!await eda.sch_Document.save()) throw new Error(symbolUuid + ': symbol editor save rejected');
  await eda.dmt_EditorControl.closeDocument(openedTab);

  const reopenedTab = await eda.lib_Symbol.openInEditor(symbolUuid, PROJECT_UUID);
  if (reopenedTab !== expectedTabId) throw new Error(symbolUuid + ': unexpected verification tab id: ' + String(reopenedTab));
  const reopened = await readExactSymbol(symbolUuid);
  const reopenedById = new Map(reopened.rows.filter(row => row.head?.id).map(row => [row.head.id, row]));
  const afterContract = pinContract(reopened.rows);
  assertSamePinContract(beforeContract, afterContract, symbolUuid);
  for (const [pinId] of beforeContract.pins) {
    const pin = reopenedById.get(pinId);
    if (Number(pin?.body?.length) !== EPSILON) throw new Error(symbolUuid + ': PIN length repair did not persist: ' + pinId);
    const names = reopened.rows.filter(row => row.head?.type === 'ATTR' && row.body?.parentId === pinId &&
      (row.body.key === 'NAME' || row.body.key === 'Pin Name'));
    if (!names.length || names.some(row => !String(row.body.value ?? '').trim() || row.body.keyVisible || row.body.valueVisible)) {
      throw new Error(symbolUuid + ': hidden non-empty Pin Name did not persist: ' + pinId);
    }
  }
  for (const polyId of targetPolyIds) {
    const poly = reopenedById.get(polyId);
    if (!poly || Number(poly.body?.strokeWidth) !== EPSILON || poly.body?.strokeColor !== poly.body?.fillColor) {
      throw new Error(symbolUuid + ': filled POLY repair did not persist: ' + polyId);
    }
  }

  const captureName = 'native-symbol-visual-repair-' + String(absoluteIndex).padStart(4, '0') + '-' + symbolUuid + '.epru';
  await saveText(OUTPUT + captureName, reopened.source);
  const result = {
    index: absoluteIndex,
    title: item.title,
    symbolUuid,
    pins: beforeContract.pins.size,
    filledPolys: targetPolyIds.length,
    repairedEmptyPinNames: repairedNames,
    libraryUpdated,
    parentLibraryUuid: reopened.info?.parentLibraryUuid || null,
    capture: captureName,
  };
  await eda.dmt_EditorControl.closeDocument(reopenedTab);
  return result;
}

await assertProject();
const planFile = await eda.sys_FileSystem.readFileFromFileSystem(PLAN_PATH);
const plan = JSON.parse(await planFile.text());
const symbols = plan?.library_map?.symbol;
if (!Array.isArray(symbols) || symbols.length !== 483) throw new Error('Expected the verified 483-symbol rebind map');
const unique = new Set(symbols.map(item => item.imported_uuid));
if (unique.size !== symbols.length) throw new Error('Imported symbol UUID map is not unique');
if (offset >= symbols.length) throw new Error('offset is beyond the symbol map');
const selected = symbols.slice(offset, Math.min(symbols.length, offset + count));
const results = [];
for (let index = 0; index < selected.length; index += 1) {
  results.push(await repairOne(selected[index], offset + index));
}
const end = offset + results.length - 1;
const manifest = {
  schema: 'stm32h747-project-symbol-visual-repair-batch-v1',
  projectUuid: PROJECT_UUID,
  offset,
  requestedCount: count,
  completedCount: results.length,
  nextOffset: end + 1 < symbols.length ? end + 1 : null,
  totalSymbols: symbols.length,
  epsilon: EPSILON,
  results,
};
const manifestName = 'native-symbol-visual-repair-batch-' + String(offset).padStart(4, '0') + '-' + String(end).padStart(4, '0') + '.json';
await saveText(OUTPUT + manifestName, JSON.stringify(manifest, null, 2) + '\n');
return { manifest: manifestName, ...manifest };
