const mode = __taskArgs[0];
const values = JSON.parse(__taskArgs[1] || '[]');
if (!Array.isArray(values) || values.length < 1 || values.length > 20 || values.some(v => typeof v !== 'string' || !v || v.length > 100)) throw new Error('Expected 1-20 bounded query values');
const results = [];
for (let start = 0; start < values.length; start += 4) {
  results.push(...await Promise.all(values.slice(start, start + 4).map(async value => {
    try {
      if (mode === 'search') return { key: value, models: await eda.lib_3DModel.search(value, undefined, undefined, 30, 1) };
      if (mode === 'get') return { uuid: value, model: await eda.lib_3DModel.get(value) };
      throw new Error('Read-only mode must be search or get');
    } catch (error) { return { key: value, error: { message: error?.message, string: String(error) } }; }
  })));
}
return { readOnly: true, mode, results };
