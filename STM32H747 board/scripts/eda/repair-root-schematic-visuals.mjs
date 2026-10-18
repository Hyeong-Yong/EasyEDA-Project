const ROOT = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const PROJECT_UUID = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const CONFIG_PATH = ROOT + '/config/easyeda-project.json';
const PLAN_PATH = ROOT + '/output/validation/native-svg-overlay-repair-plan.json';
const OUTPUT = ROOT + '/output/validation/';
const EPSILON = 0.001;

const offset = Number(__taskArgs[0] ?? 0);
const count = Number(__taskArgs[1] ?? 5);
if (!Number.isInteger(offset) || offset < 0 || offset > 4) throw new Error('offset must be an integer from 0 through 4');
if (!Number.isInteger(count) || count < 1 || count > 5) throw new Error('count must be an integer from 1 through 5');

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

function getDocHead(rows) {
  const row = rows.find(record => record.head?.type === 'DOCHEAD');
  if (!row?.body) throw new Error('Native schematic source has no DOCHEAD');
  return row.body;
}

function isRootFillOnlyPoly(row) {
  const body = row.body || {};
  if (row.head?.type !== 'POLY' || body.fillStyle !== 'SOLID' || !body.fillColor || body.partId) return false;
  const width = body.strokeWidth;
  const unrepaired = width === null || width === undefined || Number(width) === 0 || !body.strokeColor;
  const alreadyRepaired = Number(width) === EPSILON && body.strokeColor === body.fillColor;
  return unrepaired || alreadyRepaired;
}

function stablePoints(points) {
  return (points || []).map(point => ({ x: point.x, y: point.y }));
}

function criticalBody(row, visualTargetIds, componentIds) {
  if (row.head?.type === 'DOCHEAD') return null;
  const body = row.body;
  if (body && row.head?.type === 'ATTR' && componentIds.has(body.parentId) &&
      body.keyVisible === false && body.valueVisible === false &&
      ['Symbol', 'Relevance', 'Designator', 'Unique ID', 'Add into BOM', 'Convert to PCB'].includes(body.key) &&
      !Object.prototype.hasOwnProperty.call(body, 'strikeout')) {
    return { ...body, strikeout: false };
  }
  if (!body || row.head?.type !== 'POLY') return body;
  const copy = { ...body, points: stablePoints(body.points) };
  if (visualTargetIds.has(row.head.id)) {
    delete copy.strokeWidth;
    delete copy.strokeColor;
  }
  return copy;
}

function assertCriticalRecords(beforeRows, afterRows, visualTargetIds, pageNumber) {
  const componentIds = new Set(beforeRows.filter(row => row.head?.type === 'COMPONENT').map(row => row.head.id));
  const before = new Map(beforeRows.filter(row => row.head?.id).map(row => [row.head.id, row]));
  const after = new Map(afterRows.filter(row => row.head?.id).map(row => [row.head.id, row]));
  if (before.size !== after.size) throw new Error('Page ' + pageNumber + ': primitive ID count changed');
  for (const [id, expected] of before) {
    const actual = after.get(id);
    if (!actual || actual.head.type !== expected.head.type) throw new Error('Page ' + pageNumber + ': primitive identity changed: ' + id);
    const beforeBody = criticalBody(expected, visualTargetIds, componentIds);
    const afterBody = criticalBody(actual, visualTargetIds, componentIds);
    const ordered = value => value && typeof value === 'object' && !Array.isArray(value) ?
      Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])) : value;
    if (JSON.stringify(ordered(beforeBody)) !== JSON.stringify(ordered(afterBody))) {
      throw new Error('Page ' + pageNumber + ': non-visual source changed: ' + id);
    }
  }
}

async function pause(milliseconds) {
  await new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function assertProject() {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project?.uuid !== PROJECT_UUID) throw new Error('Dedicated STM32H747 project UUID guard failed');
}

async function readExactPage(pageUuid) {
  let last = 'no document information';
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await assertProject();
    const selected = await eda.dmt_Schematic.getCurrentSchematicPageInfo();
    const info = await eda.dmt_SelectControl.getCurrentDocumentInfo();
    const source = await eda.sys_FileManager.getDocumentSource();
    try {
      const rows = parseSource(source);
      const head = getDocHead(rows);
      if (selected?.uuid === pageUuid && info?.uuid === pageUuid && Number(info?.documentType) === 1 &&
          head.uuid === pageUuid && head.docType === 'SCH_PAGE') {
        return { source, rows, info, head };
      }
      last = JSON.stringify({ selected, info, docHead: head });
    } catch (error) {
      last = String(error?.message || error);
    }
    if (attempt < 2) await pause(150);
  }
  throw new Error(pageUuid + ': refused to touch mismatched schematic page: ' + last);
}

async function saveText(path, text) {
  const saved = await eda.sys_FileSystem.saveFileToFileSystem(path, new Blob([text]), undefined, false);
  if (!saved) throw new Error('Failed to save validation artifact: ' + path);
}

async function repairPage(page, repair) {
  const pageNumber = page.sourcePdfPage;
  const companyIds = new Set([
    ...(repair?.strict_company_repair?.target_ids || []),
    ...(repair?.strict_company_repair?.already_absent_ids || []),
  ]);
  if (companyIds.size !== 15) throw new Error('Page ' + pageNumber + ': exact 15-glyph company omission contract missing');

  const openedTab = await eda.dmt_EditorControl.openDocument(page.uuid);
  if (!openedTab) throw new Error('Page ' + pageNumber + ': openDocument returned no tab');
  const opened = await readExactPage(page.uuid);
  await saveText(OUTPUT + 'native-root-visual-before-page-' + pageNumber + '.epru', opened.source);
  const openedIds = new Set(opened.rows.filter(row => row.head?.id).map(row => row.head.id));
  for (const id of companyIds) {
    if (openedIds.has(id)) throw new Error('Page ' + pageNumber + ': removed company glyph is present: ' + id);
  }

  const wireIds = new Set(opened.rows.filter(row => row.head?.type === 'WIRE').map(row => row.head.id));
  const wireNets = opened.rows.filter(row => row.head?.type === 'ATTR' && row.body?.key === 'NET' && wireIds.has(row.body.parentId));
  for (const row of wireNets) {
    if (Number(row.body.fontSize) !== EPSILON) throw new Error('Page ' + pageNumber + ': durable wire NET font repair missing: ' + row.head.id);
  }
  const wireContract = new Map(wireNets.map(row => [row.head.id, {
    parentId: row.body.parentId, value: row.body.value, fontSize: row.body.fontSize,
  }]));

  const targetIds = new Set();
  for (const row of opened.rows) {
    if (!isRootFillOnlyPoly(row)) continue;
    row.body.strokeWidth = EPSILON;
    row.body.strokeColor = row.body.fillColor;
    targetIds.add(row.head.id);
  }
  if (!targetIds.size) throw new Error('Page ' + pageNumber + ': no root fill-only POLY records found');

  if (!await eda.sys_FileManager.setDocumentSource(serializeSource(opened.rows))) {
    throw new Error('Page ' + pageNumber + ': root visual source update rejected');
  }
  const accepted = await readExactPage(page.uuid);
  await saveText(OUTPUT + 'native-root-visual-accepted-page-' + pageNumber + '.epru', accepted.source);
  assertCriticalRecords(opened.rows, accepted.rows, targetIds, pageNumber);
  if (!await eda.sch_Document.save()) throw new Error('Page ' + pageNumber + ': schematic save rejected');
  await eda.dmt_EditorControl.closeDocument(openedTab);

  const reopenedTab = await eda.dmt_EditorControl.openDocument(page.uuid);
  if (!reopenedTab) throw new Error('Page ' + pageNumber + ': verification reopen returned no tab');
  const reopened = await readExactPage(page.uuid);
  assertCriticalRecords(opened.rows, reopened.rows, targetIds, pageNumber);
  const reopenedById = new Map(reopened.rows.filter(row => row.head?.id).map(row => [row.head.id, row]));
  for (const id of companyIds) {
    if (reopenedById.has(id)) throw new Error('Page ' + pageNumber + ': company glyph reappeared after save: ' + id);
  }
  for (const id of targetIds) {
    const poly = reopenedById.get(id);
    if (!poly || Number(poly.body?.strokeWidth) !== EPSILON || poly.body?.strokeColor !== poly.body?.fillColor) {
      throw new Error('Page ' + pageNumber + ': filled root POLY repair did not persist: ' + id);
    }
  }
  for (const [id, expected] of wireContract) {
    const actual = reopenedById.get(id);
    if (!actual || actual.body?.parentId !== expected.parentId || actual.body?.value !== expected.value ||
        Number(actual.body?.fontSize) !== EPSILON) {
      throw new Error('Page ' + pageNumber + ': wire NET contract changed: ' + id);
    }
  }

  const capture = 'native-root-visual-repair-page-' + pageNumber + '.epru';
  await saveText(OUTPUT + capture, reopened.source);
  const result = {
    pdfPage: pageNumber,
    pageUuid: page.uuid,
    rootFillPolys: targetIds.size,
    omittedCompanyGlyphIds: companyIds.size,
    wireNetAttrsPreserved: wireContract.size,
    capture,
  };
  await eda.dmt_EditorControl.closeDocument(reopenedTab);
  return result;
}

await assertProject();
const configFile = await eda.sys_FileSystem.readFileFromFileSystem(CONFIG_PATH);
const config = JSON.parse(await configFile.text());
const planFile = await eda.sys_FileSystem.readFileFromFileSystem(PLAN_PATH);
const plan = JSON.parse(await planFile.text());
if (!Array.isArray(config.pages) || config.pages.length !== 5 || !Array.isArray(plan.pages) || plan.pages.length !== 5) {
  throw new Error('Expected the verified five-page schematic and visual plan');
}
const selected = config.pages.slice(offset, Math.min(config.pages.length, offset + count));
const results = [];
for (const page of selected) {
  const repair = plan.pages.find(entry => entry.pdf_page === page.sourcePdfPage);
  if (!repair) throw new Error('Missing visual repair evidence for PDF page ' + page.sourcePdfPage);
  results.push(await repairPage(page, repair));
}
const end = offset + results.length - 1;
const manifest = {
  schema: 'stm32h747-root-schematic-visual-repair-batch-v1',
  projectUuid: PROJECT_UUID,
  offset,
  completedCount: results.length,
  nextOffset: end + 1 < config.pages.length ? end + 1 : null,
  epsilon: EPSILON,
  results,
};
const manifestName = 'native-root-visual-repair-batch-' + offset + '-' + end + '.json';
await saveText(OUTPUT + manifestName, JSON.stringify(manifest, null, 2) + '\n');
return { manifest: manifestName, ...manifest };
