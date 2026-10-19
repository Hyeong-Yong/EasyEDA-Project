const mode = __taskArgs[0];
const key = __taskArgs[1];
const libraryUuid = __taskArgs[2] || undefined;
const available = { search: typeof eda.lib_Footprint.search === 'function', get: typeof eda.lib_Footprint.get === 'function', getDocumentSource: typeof eda.lib_Footprint.getDocumentSource === 'function' };
if (!key) throw new Error('Expected search keyword or footprint UUID');
if (mode === 'search') return { readOnly: true, mode, key, available, footprints: await eda.lib_Footprint.search(key, undefined, undefined, 30, 1) };
try {
if (mode === 'get') return { readOnly: true, mode, key, libraryUuid, available, footprint: await eda.lib_Footprint.get(key, libraryUuid) };
if (mode === 'source') return { readOnly: true, mode, key, libraryUuid, available, source: available.getDocumentSource ? await eda.lib_Footprint.getDocumentSource(key, libraryUuid) : null };
if (mode === 'file') { const ids = key.startsWith('[') ? JSON.parse(key) : key; if (Array.isArray(ids) && (!ids.length || ids.length > 30 || !ids.every(id => /^[a-f0-9]{32}$/.test(id)))) throw new Error('Invalid read-only footprint UUID batch'); const file = await eda.sys_FileManager.getFootprintFileByFootprintUuid(ids, libraryUuid, 'elibz2'); return { readOnly: true, mode, key, libraryUuid, file: file ? { name: file.name, size: file.size, type: file.type, hex: Array.from(new Uint8Array(await file.arrayBuffer()), x => x.toString(16).padStart(2, '0')).join('') } : null }; }
} catch(error) { return { readOnly: true, mode, key, libraryUuid, available, error: { name: error?.name, message: error?.message, string: String(error), properties: Object.getOwnPropertyNames(error || {}).reduce((o, k) => { try { o[k] = error[k]; } catch {} return o; }, {}) } }; }
throw new Error('Read-only query mode must be search, get, source, or file');
