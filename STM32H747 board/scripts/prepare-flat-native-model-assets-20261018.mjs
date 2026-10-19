// Board-scoped file authoring only. No EasyEDA API/UI/library registration.
// Exclusive copies preserve exact derivative bytes; all targets must be absent.
import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import crypto from 'node:crypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputBase = path.join(root, 'output', '3d-models-20261018');
const library = path.join(root, 'native-project', 'model-library');
const manifestPath = path.join(library, 'STM32H747_3D_asset_manifest_20261018.json');
const readJson = async relative => JSON.parse(await fs.readFile(path.join(root, relative), 'utf8'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const pinned = await readJson('output/3d-models-20261018/source-models/canonical-pinregistered-models/canonical-manifest.json');
const canonical = await readJson('output/3d-models-20261018/source-models/canonical-reference-models/canonical-manifest.json');
const manufacturer = await readJson('output/3d-models-20261018/source-models/canonical-manufacturer-models/CN2/canonical-manifest.json');
const inventory = await readJson('output/3d-models-20261018/inventory/components-437.json');
const sources = [
  ['CN1', pinned.models.find(m => m.ref === 'CN1'), 'PJ051BH_PINREG_ZUP'],
  ['CN2', manufacturer, 'LPJE101_0AHNL_APPROX_ZUP'],
  ['CN3', canonical.models.find(m => m.ref === 'CN3'), 'USB4105_GF_A_ZUP'],
  ['CN4', canonical.models.find(m => m.ref === 'CN4'), 'USB4105_GF_A_ZUP'],
  ['L1', canonical.models.find(m => m.ref === 'L1'), 'LQM2MPN2R2NG0L_ZUP'],
  ['J1', pinned.models.find(m => m.ref === 'J1'), 'FTSH107_CONTACTREG_ZUP'],
];
const withinRoot = target => {
  const resolved = path.resolve(target);
  if (!resolved.startsWith(root + path.sep)) throw new Error('Path outside STM32 board scope');
  return resolved;
};
const entries = [];
for (const [ref, model, label] of sources) {
  if (!model?.checks?.pass) throw new Error('Unvalidated canonical model: ' + ref);
  const component = inventory.find(p => p.ref === ref);
  if (!component || component.rotation_deg !== 0 || component.side !== 'top') throw new Error('Frozen component pose mismatch: ' + ref);
  const stem = `STM32H747_3D_${ref}_${label}_20261018`;
  const source = withinRoot(path.join(root, model.path));
  const target = withinRoot(path.join(library, stem + '.step'));
  const bytes = await fs.readFile(source);
  if (hash(bytes) !== model.sha256) throw new Error('Source derivative hash mismatch: ' + ref);
  const bounds = model.canonical_stats.bounds;
  const center = bounds.min_mm.map((v, i) => (v + bounds.max_mm[i]) / 2);
  const offsetMm = [center[0], center[1], bounds.min_mm[2]];
  const sizeMil = bounds.span_mm.map(v => v / 0.0254);
  const offsetMil = offsetMm.map(v => v / 0.0254);
  const tuple = [...sizeMil, 0, 0, 0, ...offsetMil];
  const recoveryErrors = [];
  for (const witness of [bounds.min_mm, bounds.max_mm, [0, 0, 0]]) {
    const normalized = [witness[0] - center[0], witness[1] - center[1], witness[2] - bounds.min_mm[2]];
    recoveryErrors.push(Math.max(...normalized.map((v, i) => Math.abs(v + offsetMm[i] - witness[i]))));
  }
  entries.push({
    ref, componentId: component.component_id, footprintUuid: component.footprint_uuid,
    currentComponentOriginMm: [component.x_mm, component.y_mm], currentComponentRotationDeg: 0,
    modelPart: model.product, optional: ref === 'J1', expectedLibraryTitle: stem,
    lookupAliases: [stem, stem + '.step', `${ref} ${model.product}`, model.product],
    sourceDerivativePath: path.relative(root, source), sourceDerivativeSha256: model.sha256,
    flatAssetPath: path.relative(root, target), flatAssetAbsolutePath: target,
    bytes: bytes.length, sha256: model.sha256,
    geometryScaleXYZ: [1, 1, 1], bakedRigidTransform: model.rigid_transform_local_to_canonical_mm,
    canonicalBoundsMm: bounds, completeBboxCenterMm: center, mountPlaneCanonicalZmm: 0,
    canonicalMinZmm: bounds.min_mm[2], canonicalMaxZmm: bounds.max_mm[2],
    expectedNativeTransformOrder: ['sizeX_mil', 'sizeY_mil', 'sizeZ_mil', 'rotZ_deg', 'rotX_deg', 'rotY_deg', 'offsetX_mil', 'offsetY_mil', 'offsetZ_mil'],
    expectedNativeTransform9tupleMil: tuple,
    expectedNativeTransformString: tuple.map(v => Number(v.toFixed(10))).join(','),
    expectedNativeSizeXYZmm: bounds.span_mm, expectedNativeRotationZXYdeg: [0, 0, 0], expectedNativeOffsetXYZmm: offsetMm,
    normalizationRecoveryMaxErrorMm: Math.max(...recoveryErrors),
    expectedCurrentBoardBboxXYmm: {min: [component.x_mm + bounds.min_mm[0], component.y_mm + bounds.min_mm[1]], max: [component.x_mm + bounds.max_mm[0], component.y_mm + bounds.max_mm[1]]},
    validationStatus: 'FILE_PREPARATION_ONLY_NATIVE_IMPORT_AND_PILOT_REQUIRED',
    relation: ref === 'CN2' ? model.relation : 'Historical exact model label; rigidly registered to current per-reference frozen footprint. Not a manufacturing certification.',
    limitations: ref === 'CN2' ? model.limitations : ref === 'J1' ? ['Optional: root already has a calibrated exact-name system J1 model.', 'Visual pin1 mark not independently verified; SMT contact seating datum is geometry-verified.'] : [],
    sourceProvenance: ref === 'CN2' ? {manufacturerProductPage: model.source_product_page, officialZipUrl: model.source_zip_url, originalStepSha256: model.source_sha256, registrationEvidence: model.registration_evidence} : {sourceReference: pinned.source, originalStepSha256: pinned.source_sha256, extraction: 'OCCT selected-child serialization; original historical source preserved.'},
  });
}
// Fail before copying if any name already exists; COPYFILE_EXCL is still used.
for (const file of [manifestPath, ...entries.map(e => e.flatAssetAbsolutePath)]) {
  try { await fs.access(file); throw new Error('Refusing to overwrite existing target: ' + file); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
}
await fs.mkdir(library, {recursive: true});
for (const entry of entries) {
  await fs.copyFile(path.join(root, entry.sourceDerivativePath), entry.flatAssetAbsolutePath, constants.COPYFILE_EXCL);
  if (hash(await fs.readFile(entry.flatAssetAbsolutePath)) !== entry.sha256) throw new Error('Flat copy hash mismatch');
}
const manifest = {
  schema: 'STM32H747-private-flat-STEP-library-assets-v1',
  operation: 'COPYFILE_EXCL exact derivative byte copies; no source modification; no native APIs/UI/path registration',
  libraryDirectory: library, prefix: 'STM32H747_3D_',
  nativeTransformAssumption: 'Existing board native calibration observes complete-bbox centerXY/minZ normalization. These canonical assets already contain correct per-reference baked rotations and offsets. Apply no additional rotation. Absolute sizeXYZ in mil equals complete physical bbox spans, preserving unity geometry scale.',
  nativeTransformRecovery: 'Native normalized p=(pX-centerX,pY-centerY,pZ-minZ). Offset=(centerX,centerY,minZ) restores canonical pinregistered coordinates. Do not set offsets0 solely because STEP is canonical.',
  nativeValidationRequired: 'Root must verify one imported pilot actual OBJ bounds/pin locations and source-unit handling before batch binding. OCCT analytic bbox can differ from importer mesh extrema by tessellation/float precision; first3 fields are physical dimensions, NOT scale ratios.',
  fileUnits: 'mm, explicit STEP units',
  license: 'Historical/user-supplied source and manufacturer download. No open public redistribution licence assumed. Retain provenance.',
  entries,
};
const handle = await fs.open(manifestPath, 'wx');
try { await handle.writeFile(JSON.stringify(manifest, null, 2) + '\n', 'utf8'); } finally { await handle.close(); }
console.log(JSON.stringify({manifest: manifestPath, assets: entries.map(e => ({ref:e.ref, title:e.expectedLibraryTitle, bytes:e.bytes, sha256:e.sha256, transform:e.expectedNativeTransformString}))}, null, 2));
