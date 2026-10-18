import { readFile } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const workspaceDirectory = resolve(scriptDirectory, '..');
const allowedCodeDirectory = resolve(scriptDirectory, 'eda');
const projectConfigPath = resolve(workspaceDirectory, 'config', 'easyeda-project.json');
const portStart = 49620;
const portEnd = 49629;
const serviceId = 'easyeda-bridge';

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

async function requestJson(url, options = {}, timeoutMs = 1500) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });
  const text = await response.text();
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`Non-JSON response from ${url}`);
  }
  if (!response.ok) {
    throw new Error(value?.error || `HTTP ${response.status} from ${url}`);
  }
  return value;
}

async function findBridge() {
  for (let port = portStart; port <= portEnd; port += 1) {
    try {
      const health = await requestJson(`http://127.0.0.1:${port}/health`, {}, 500);
      if (health?.service === serviceId) return { port, health };
    } catch {
      // Keep scanning the dedicated localhost range.
    }
  }
  throw new Error(`EasyEDA bridge not found on ${portStart}-${portEnd}.`);
}

async function execute(port, windowId, code) {
  const body = JSON.stringify({ windowId, code });
  const response = await requestJson(
    `http://127.0.0.1:${port}/execute`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body },
    35000,
  );
  if (!response?.success) throw new Error(response?.error || 'EasyEDA execution failed.');
  return response.result;
}

function projectMatches(project, config) {
  if (!project) return false;
  const nameMatches =
    project.name === config.expectedProjectName ||
    project.friendlyName === config.expectedProjectName;
  if (!nameMatches) return false;
  if (config.expectedProjectUuid && project.uuid !== config.expectedProjectUuid) return false;
  return true;
}

async function locateProjectWindow(port, config) {
  const inventory = await requestJson(`http://127.0.0.1:${port}/eda-windows`);
  const candidates = [];
  const inspected = [];
  for (const item of inventory.windows ?? []) {
    if (!item.connected) continue;
    if (config.expectedWindowId && item.windowId !== config.expectedWindowId) continue;
    try {
      const project = await execute(
        port,
        item.windowId,
        'return await eda.dmt_Project.getCurrentProjectInfo();',
      );
      inspected.push({ windowId: item.windowId, project });
      if (projectMatches(project, config)) candidates.push({ windowId: item.windowId, project });
    } catch (error) {
      inspected.push({ windowId: item.windowId, error: error.message });
    }
  }
  if (candidates.length !== 1) {
    const summary = inspected.map(({ windowId, project, error }) => ({
      windowId,
      projectName: project?.name ?? project?.friendlyName ?? null,
      projectUuid: project?.uuid ?? null,
      error: error ?? null,
    }));
    throw new Error(
      `Expected exactly one connected ${config.expectedProjectName} window; found ${candidates.length}. ` +
      `Inspected: ${JSON.stringify(summary)}`,
    );
  }
  return { ...candidates[0], inspected };
}

function resolveAllowedCodePath(inputPath) {
  const codePath = isAbsolute(inputPath) ? resolve(inputPath) : resolve(workspaceDirectory, inputPath);
  const relation = relative(allowedCodeDirectory, codePath);
  if (relation.startsWith('..') || isAbsolute(relation)) {
    throw new Error(`Execution files must stay under ${allowedCodeDirectory}.`);
  }
  return codePath;
}

function wrapGuardedCode(code, config, taskArgs = []) {
  const expectedName = JSON.stringify(config.expectedProjectName);
  const expectedUuid = JSON.stringify(config.expectedProjectUuid);
  return `const __p=await eda.dmt_Project.getCurrentProjectInfo();const __n=${expectedName};const __u=${expectedUuid};const __taskArgs=${JSON.stringify(taskArgs)};if(!__p||(__p.name!==__n&&__p.friendlyName!==__n)||(__u&&__p.uuid!==__u)){throw new Error('STM32H747 project guard rejected the active project');}return await (async()=>{${code}\n})();`;
}

async function main() {
  const command = process.argv[2] ?? 'status';
  const config = await readJson(projectConfigPath);
  const { port, health } = await findBridge();
  if (health.service !== serviceId) throw new Error('Bridge handshake mismatch.');
  const selection = await locateProjectWindow(port, config);

  if (command === 'status') {
    console.log(JSON.stringify({
      ok: true,
      port,
      windowId: selection.windowId,
      project: selection.project,
      uuidLocked: Boolean(config.expectedProjectUuid),
    }, null, 2));
    return;
  }

  if (command === 'execute-file') {
    if (!config.expectedProjectUuid) throw new Error('Project UUID must be locked before any execution.');
    const requestedPath = process.argv[3];
    if (!requestedPath) throw new Error('Usage: easyeda-safe-client.mjs execute-file scripts/eda/<file>.mjs');
    const codePath = resolveAllowedCodePath(requestedPath);
    const code = await readFile(codePath, 'utf8');
    const result = await execute(port, selection.windowId, wrapGuardedCode(code, config, process.argv.slice(4)));
    console.log(JSON.stringify({ ok: true, port, windowId: selection.windowId, result }, null, 2));
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  console.error(`[SAFE CLIENT ERROR] ${error.message}`);
  process.exitCode = 1;
});

