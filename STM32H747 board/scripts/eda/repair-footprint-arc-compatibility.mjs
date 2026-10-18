const ROOT = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const PROJECT_NAME = 'STM32H747_MCU_BOARD_v19';
const PROJECT_UUID = '761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const PLAN_PATH = ROOT + '/output/validation/footprint-arc-compatibility-plan.json';
const OUTPUT = ROOT + '/output/validation/';
const WAIT_MS = 250;
const EPSILON = 0.001;

const selector = String(__taskArgs[0] ?? '').trim();
if (!selector) throw new Error('Explicit footprint reference/UUID (or reviewed `all`) is required');

function parseSource(source) {
  const rows = [];
  for (const rawLine of String(source).split(/\r?\n/)) {
    if (!rawLine.trim()) continue;
    const line = rawLine.endsWith('|') ? rawLine.slice(0, -1) : rawLine;
    const divider = line.indexOf('||');
    if (divider < 0) throw new Error('Malformed native record without || delimiter');
    const head = JSON.parse(line.slice(0, divider));
    const bodyText = line.slice(divider + 2);
    rows.push({ head, body: bodyText ? JSON.parse(bodyText) : {} });
  }
  if (!rows.length || rows[0].head?.type !== 'DOCHEAD') {
    throw new Error('Native source does not start with DOCHEAD');
  }
  return rows;
}

function serializeSource(rows) {
  return rows.map(({ head, body }) =>
    JSON.stringify(head) + '||' + JSON.stringify(body)
  ).join('|\n');
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function equalJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function countTypes(rows) {
  const result = {};
  for (const row of rows) {
    const type = row.head?.type;
    result[type] = (result[type] || 0) + 1;
  }
  return result;
}

function rowIndex(rows) {
  const result = new Map();
  for (const row of rows) {
    const id = row.head?.id;
    if (!id) continue;
    if (result.has(id)) throw new Error('Duplicate native record id: ' + id);
    result.set(id, row);
  }
  return result;
}

function getDocHead(rows) {
  const row = rows.find(item => item.head?.type === 'DOCHEAD');
  if (!row?.body) throw new Error('DOCHEAD body is missing');
  return row.body;
}

function normalizedPath(path) {
  if (Array.isArray(path) && path.length === 1 && Array.isArray(path[0])) return path[0];
  return path;
}

function assertNear(actual, expected, context) {
  if (typeof expected === 'number') {
    if (typeof actual !== 'number' || Math.abs(actual - expected) > EPSILON) {
      throw new Error(context + ': expected ' + expected + ', got ' + String(actual));
    }
  } else if (actual !== expected) {
    throw new Error(context + ': expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual));
  }
}

function assertPath(actualPath, expectedPath, context) {
  const actual = normalizedPath(actualPath);
  const expected = normalizedPath(expectedPath);
  if (!Array.isArray(actual) || actual.length !== expected.length) {
    throw new Error(context + ': path length changed');
  }
  for (let index = 0; index < expected.length; index += 1) {
    assertNear(actual[index], expected[index], context + '[' + index + ']');
  }
}

function padContract(rows) {
  return rows.filter(row => row.head?.type === 'PAD').map(row => ({
    id: row.head.id,
    num: row.body.num,
    layerId: row.body.layerId,
    centerX: row.body.centerX,
    centerY: row.body.centerY,
    padAngle: row.body.padAngle,
    hole: row.body.hole,
    defaultPad: row.body.defaultPad,
    specialPad: row.body.specialPad,
    padOffsetX: row.body.padOffsetX,
    padOffsetY: row.body.padOffsetY,
    relativeAngle: row.body.relativeAngle,
    plated: row.body.plated,
    padType: row.body.padType,
  })).sort((left, right) => left.id.localeCompare(right.id));
}

async function pause() {
  await new Promise(resolve => setTimeout(resolve, WAIT_MS));
}

async function sha256Text(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

async function readText(path) {
  const file = await eda.sys_FileSystem.readFileFromFileSystem(path);
  if (!file) throw new Error('File could not be read: ' + path);
  return await file.text();
}

async function saveText(path, text) {
  const saved = await eda.sys_FileSystem.saveFileToFileSystem(
    path,
    new Blob([text]),
    undefined,
    false,
  );
  if (!saved) throw new Error('Validation artifact could not be saved: ' + path);
}

async function assertProject() {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  if (!project || (project.name !== PROJECT_NAME && project.friendlyName !== PROJECT_NAME) || project.uuid !== PROJECT_UUID) {
    throw new Error('Dedicated STM32H747 project name/UUID guard failed');
  }
  return project;
}

function applyArcPlan(rawRows, target) {
  const rows = rawRows.map(clone);
  const byId = rowIndex(rows);
  const replacements = new Map();
  const deleteIds = new Set();
  for (const transform of target.transformations) {
    const originals = transform.original_records || [];
    for (const original of originals) {
      const current = byId.get(original.head?.id);
      if (!current || !equalJson(current, original)) {
        throw new Error(target.reference + ': checkpoint ARC record drifted: ' + String(original.head?.id));
      }
    }
    const replacement = clone(transform.replacement_record);
    if (replacement.head?.type !== 'POLY' || replacement.body?.polyType !== 'NORMAL') {
      throw new Error(target.reference + ': plan contains a non-NORMAL POLY replacement');
    }
    const path = normalizedPath(replacement.body.path);
    const paired = transform.kind === 'reverse_arc_pair_to_circle';
    const unmatched = transform.kind === 'single_arc_to_open_poly_arc';
    if (paired && !(path.length === 4 && path[0] === 'CIRCLE')) {
      throw new Error(target.reference + ': paired replacement is not current four-field CIRCLE');
    }
    if (unmatched && !(path.length === 6 && path[2] === 'ARC' && path[3] === -180)) {
      throw new Error(target.reference + ': unmatched replacement is not an open -180 POLY ARC');
    }
    if (!paired && !unmatched) throw new Error('Unknown transformation kind: ' + transform.kind);
    replacements.set(transform.keep_id, replacement);
    for (const id of transform.delete_ids || []) deleteIds.add(id);
  }
  const normalized = [];
  for (const row of rows) {
    const id = row.head?.id;
    if (id && deleteIds.has(id)) continue;
    normalized.push(id && replacements.has(id) ? replacements.get(id) : row);
  }
  if (normalized.some(row => row.head?.type === 'ARC')) {
    throw new Error(target.reference + ': normalized raw source still contains top-level ARC');
  }
  return normalized;
}

function buildGetterCompatibleSource(liveRows, normalizedRawRows, target) {
  const liveHead = getDocHead(liveRows);
  const rawHead = getDocHead(normalizedRawRows);
  if (liveHead.uuid !== target.imported_uuid || liveHead.docType !== 'PCB') {
    throw new Error(target.reference + ': active footprint getter is not its PCB-format editor source');
  }
  if (rawHead.uuid !== target.imported_uuid || rawHead.docType !== 'FOOTPRINT') {
    throw new Error(target.reference + ': extracted full source identity/type mismatch');
  }

  const authorTypes = new Set(target.author_record_types);
  const rawAuthor = normalizedRawRows.filter(row => authorTypes.has(row.head?.type));
  const rawAuthorIds = new Set();
  for (const row of rawAuthor) {
    const id = row.head?.id;
    if (!id || rawAuthorIds.has(id)) throw new Error(target.reference + ': invalid author record id');
    rawAuthorIds.add(id);
  }
  for (const transform of target.transformations) {
    for (const original of transform.original_records || []) rawAuthorIds.add(original.head.id);
  }

  const liveById = rowIndex(liveRows);
  const liveAuthorExtras = liveRows.filter(row =>
    authorTypes.has(row.head?.type) && row.head?.id && !rawAuthorIds.has(row.head.id)
  );
  if (liveAuthorExtras.length) {
    throw new Error(target.reference + ': live source has unexpected author records: ' +
      liveAuthorExtras.map(row => row.head.id).join(','));
  }

  const authorForWrite = rawAuthor.map(row => {
    if (row.head.type !== 'PAD' && row.head.type !== 'ATTR') return row;
    const live = liveById.get(row.head.id);
    if (!live || live.head.type !== row.head.type) {
      throw new Error(target.reference + ': live getter lacks current ' + row.head.type + ' ' + row.head.id);
    }
    return clone(live);
  });

  const scaffold = liveRows.filter(row => !row.head?.id || !rawAuthorIds.has(row.head.id));
  return [...scaffold, ...authorForWrite];
}

function verifyRebuiltSource(rows, target, preservedPads, stage) {
  const head = getDocHead(rows);
  if (head.uuid !== target.imported_uuid || head.docType !== 'PCB') {
    throw new Error(target.reference + ': ' + stage + ' DOCHEAD identity changed');
  }
  const counts = countTypes(rows);
  if ((counts.ARC || 0) !== 0) throw new Error(target.reference + ': ' + stage + ' still contains ARC');
  for (const type of target.author_record_types) {
    if (type === 'ARC') continue;
    const expected = Number(target.normalized_record_counts[type] || 0);
    const actual = Number(counts[type] || 0);
    if (actual !== expected) {
      throw new Error(target.reference + ': ' + stage + ' ' + type + ' count ' + actual + ' != ' + expected);
    }
  }
  if (!equalJson(padContract(rows), preservedPads)) {
    throw new Error(target.reference + ': ' + stage + ' changed live PAD identities/geometry');
  }
  const byId = rowIndex(rows);
  for (const transform of target.transformations) {
    const row = byId.get(transform.keep_id);
    if (!row || row.head.type !== 'POLY' || row.body.polyType !== 'NORMAL') {
      throw new Error(target.reference + ': ' + stage + ' lacks replacement POLY ' + transform.keep_id);
    }
    assertPath(row.body.path, transform.replacement_record.body.path,
      target.reference + ':' + stage + ':' + transform.keep_id);
    assertNear(row.body.width, transform.replacement_record.body.width,
      target.reference + ':' + stage + ':' + transform.keep_id + ':width');
    assertNear(row.body.layerId, transform.replacement_record.body.layerId,
      target.reference + ':' + stage + ':' + transform.keep_id + ':layer');
    if (row.body.netName !== transform.replacement_record.body.netName ||
        row.body.locked !== transform.replacement_record.body.locked) {
      throw new Error(target.reference + ': ' + stage + ' changed replacement net/locked state');
    }
    for (const deletedId of transform.delete_ids || []) {
      if (byId.has(deletedId)) throw new Error(target.reference + ': ' + stage + ' retained ' + deletedId);
    }
  }
  return counts;
}

async function exactOpen(target) {
  await assertProject();
  const expectedTab = target.imported_uuid + '@' + PROJECT_UUID;
  const tab = await eda.lib_Footprint.openInEditor(target.imported_uuid, PROJECT_UUID);
  if (tab !== expectedTab) throw new Error(target.reference + ': unexpected footprint tab ' + String(tab));
  await pause();
  await assertProject();
  const info = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  const source = await eda.sys_FileManager.getDocumentSource();
  const rows = parseSource(source);
  const head = getDocHead(rows);
  if (info?.uuid !== target.imported_uuid || info?.tabId !== expectedTab || head.uuid !== target.imported_uuid) {
    throw new Error(target.reference + ': refused mismatched active editor document');
  }
  return { tab, source, rows };
}

async function repairOne(target) {
  const opened = await exactOpen(target);
  const rawPath = ROOT + '/' + target.raw_source;
  const rawText = await readText(rawPath);
  const actualHash = await sha256Text(rawText);
  if (actualHash !== target.raw_source_sha256) {
    await eda.dmt_EditorControl.closeDocument(opened.tab);
    throw new Error(target.reference + ': full checkpoint source hash mismatch');
  }
  const rawRows = parseSource(rawText);
  const normalizedRawRows = applyArcPlan(rawRows, target);
  const preservedPads = padContract(opened.rows);
  if (preservedPads.length !== Number(target.raw_record_counts.PAD || 0)) {
    await eda.dmt_EditorControl.closeDocument(opened.tab);
    throw new Error(target.reference + ': live/raw PAD count mismatch');
  }
  const candidateRows = buildGetterCompatibleSource(opened.rows, normalizedRawRows, target);
  const candidate = serializeSource(candidateRows);

  let accepted = false;
  let committed = false;
  try {
    accepted = await eda.sys_FileManager.setDocumentSource(candidate);
    if (!accepted) throw new Error(target.reference + ': setDocumentSource rejected compatibility source');
    const acceptedSource = await eda.sys_FileManager.getDocumentSource();
    const acceptedRows = parseSource(acceptedSource);
    const acceptedCounts = verifyRebuiltSource(acceptedRows, target, preservedPads, 'accepted');
    const libraryUpdated = await eda.lib_Footprint.updateDocumentSource(
      target.imported_uuid,
      PROJECT_UUID,
      acceptedSource,
    );
    if (!libraryUpdated) throw new Error(target.reference + ': project-library source update failed');
    const saved = await eda.pcb_Document.save();
    if (!saved) throw new Error(target.reference + ': footprint document save failed');
    committed = true;
    const closed = await eda.dmt_EditorControl.closeDocument(opened.tab);
    if (!closed) throw new Error(target.reference + ': repaired footprint tab did not close');

    const reopened = await exactOpen(target);
    const reopenedCounts = verifyRebuiltSource(reopened.rows, target, preservedPads, 'reopened');
    const captureName = 'native-footprint-arc-compatible-' + target.reference + '-' +
      target.imported_uuid + '.epru';
    await saveText(OUTPUT + captureName, reopened.source);
    const verificationClosed = await eda.dmt_EditorControl.closeDocument(reopened.tab);
    if (!verificationClosed) throw new Error(target.reference + ': verification tab did not close');
    const result = {
      reference: target.reference,
      uuid: target.imported_uuid,
      accepted,
      libraryUpdated,
      saved,
      closed,
      verificationClosed,
      pads: preservedPads.length,
      transformations: target.transformations.length,
      originalArcs: target.raw_record_counts.ARC,
      replacementPolys: target.transformations.length,
      acceptedCounts,
      reopenedCounts,
      capture: captureName,
    };
    await saveText(
      OUTPUT + 'native-footprint-arc-repair-' + target.reference + '.json',
      JSON.stringify(result, null, 2) + '\n',
    );
    return result;
  } catch (error) {
    if (!committed) {
      try { await eda.sys_FileManager.setDocumentSource(opened.source); } catch {}
    }
    try { await eda.dmt_EditorControl.closeDocument(opened.tab); } catch {}
    throw error;
  }
}

await assertProject();
const plan = JSON.parse(await readText(PLAN_PATH));
if (plan?.schema !== 'stm32h747-footprint-arc-compatibility-plan-v1' ||
    plan?.summary?.target_footprints !== 35 ||
    plan?.summary?.original_top_level_arcs !== 84 ||
    plan?.summary?.replacement_polys !== 43 ||
    plan?.summary?.final_top_level_arcs !== 0) {
  throw new Error('Footprint ARC compatibility plan contract failed');
}
const targets = selector === 'all'
  ? plan.targets
  : plan.targets.filter(item => item.reference === selector || item.imported_uuid === selector);
if (!targets.length || (selector !== 'all' && targets.length !== 1)) {
  throw new Error('Selector did not resolve exactly one verified footprint: ' + selector);
}
const results = [];
for (const target of targets) results.push(await repairOne(target));
return {
  schema: 'stm32h747-footprint-arc-compatibility-runtime-v1',
  selector,
  completed: results.length,
  results,
};
