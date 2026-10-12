#!/usr/bin/env node
import { readFile, writeFile, mkdir, realpath } from 'node:fs/promises';
import { appendFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { createCodexBackend, runWorkflow } from './lib/codex-workflow-runtime.mjs';

const HELP = `Codex Workflow runner (Node >= 22, authenticated codex CLI)
Usage: node codex-workflow.mjs --name m05-web-research --args '{"question":"...","tier":"inherit"}'
       node codex-workflow.mjs --script-path /absolute/workflow.js --args-file question.json

  --name NAME           Resolve NAME in ../workflows (e.g. m05-web-research)
  --script-path FILE    Run a trusted local injected-API JS workflow
  --args JSON|TEXT      Workflow arguments; objects, arrays and JSON strings parsed
  --args-file FILE      Read arguments from UTF-8 file (exclusive with --args)
  --cwd DIR            Agent working root (default current directory)
  --model ID           Default Codex model (otherwise use CLI configuration)
  --model-map FILE      JSON mapping e.g. {"haiku":"actual-model","sonnet":"actual-model"}
  --concurrency N      Maximum simultaneous agent processes (default 3)
  --max-agents N       Maximum agent calls per workflow (default 64)
  --timeout-ms N       Per-agent timeout including tools (default 300000)
  --no-web             Disable live search (default enabled)
  --sandbox MODE       read-only (default) or workspace-write
  --codex-bin FILE     Codex executable (default codex on PATH)
  --run-dir DIR        New evidence directory; must not already exist
  --output FILE        Also write the workflow result to this JSON file
  --help               Show this help

stdout: workflow result JSON. stderr: progress + evidence directory.
Evidence: result.json, runtime.json, events.jsonl and agents/*.
Exit: 0 completed, 2 partial/degraded, 3 cost decision required, 1 failed, 130 cancelled.
`;

function parse(argv) {
  const o = { cwd: process.cwd(), concurrency: 3, maxAgents: 64, timeoutMs: 300000,
    web: true, sandbox: 'read-only', codexBin: 'codex' };
  const keys = { '--name': 'name', '--script-path': 'scriptPath', '--args': 'rawArgs',
    '--args-file': 'argsFile', '--cwd': 'cwd', '--model': 'model', '--model-map': 'modelMapFile',
    '--concurrency': 'concurrency', '--max-agents': 'maxAgents', '--timeout-ms': 'timeoutMs',
    '--sandbox': 'sandbox', '--codex-bin': 'codexBin', '--run-dir': 'runDir', '--output': 'output' };
  const seen = new Set();
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    if (flag === '--help') return { help: true };
    if (seen.has(flag)) throw new Error(`duplicate option ${flag}`);
    seen.add(flag);
    if (flag === '--no-web') { o.web = false; continue; }
    const key = keys[flag];
    if (!key || i + 1 >= argv.length) throw new Error(`unknown option or missing value: ${flag}`);
    o[key] = argv[++i];
  }
  if (!!o.name === !!o.scriptPath) throw new Error('choose exactly one of --name / --script-path');
  if (o.rawArgs !== undefined && o.argsFile) throw new Error('--args and --args-file are exclusive');
  if (o.name && !/^[a-zA-Z0-9_-]+$/.test(o.name)) throw new Error('invalid workflow name');
  for (const key of ['concurrency', 'maxAgents', 'timeoutMs']) {
    o[key] = Number(o[key]);
    if (!Number.isSafeInteger(o[key]) || o[key] < 1) throw new Error(`${key} must be a positive integer`);
  }
  if (!['read-only', 'workspace-write'].includes(o.sandbox)) throw new Error('unsupported sandbox mode');
  o.cwd = resolve(o.cwd);
  return o;
}

function parseArgs(raw) {
  if (raw === undefined) return {};
  try { return JSON.parse(raw); }
  catch (error) {
    if (/^[\s]*[\[{"]/.test(raw)) throw new Error(`invalid args JSON: ${error.message}`);
    return raw;
  }
}

export async function main(argv = process.argv.slice(2)) {
  const options = parse(argv);
  if (options.help) { process.stdout.write(HELP); return 0; }
  const filename = options.scriptPath ? resolve(options.scriptPath)
    : join(dirname(fileURLToPath(import.meta.url)), '..', 'workflows', `${options.name}.js`);
  const source = await readFile(filename, 'utf8');
  const args = parseArgs(options.argsFile ? await readFile(resolve(options.argsFile), 'utf8') : options.rawArgs);
  const modelMap = options.modelMapFile ? JSON.parse(await readFile(resolve(options.modelMapFile), 'utf8')) : {};
  if (!modelMap || typeof modelMap !== 'object' || Array.isArray(modelMap)
    || Object.values(modelMap).some(v => typeof v !== 'string' || !v.trim())) {
    throw new Error('--model-map must contain an object mapping aliases to model ids');
  }
  const runId = new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8);
  const runDir = options.runDir ? resolve(options.runDir)
    : join(options.cwd, '.harness', 'metrics', 'codex-workflow', runId);
  await mkdir(dirname(runDir), { recursive: true, mode: 0o700 });
  await mkdir(runDir, { mode: 0o700 }); // never overwrite an earlier run
  const emit = event => {
    appendFileSync(join(runDir, 'events.jsonl'), JSON.stringify({ at: new Date().toISOString(), ...event }) + '\n', { mode: 0o600 });
    if (['workflow.phase', 'workflow.log', 'agent.finished'].includes(event.type)) {
      process.stderr.write(`[${event.type}] ${event.title || event.message || `${event.label}: ${event.status}`}\n`);
    }
  };
  process.stderr.write(`Workflow evidence: ${runDir}\n`);
  const controller = new AbortController();
  const cancel = () => controller.abort(new Error('workflow cancelled'));
  process.once('SIGINT', cancel); process.once('SIGTERM', cancel);
  const writeJson = (file, data) => writeFile(file, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
  const common = { runId, scriptPath: filename, cwd: options.cwd, startedAt: new Date().toISOString(),
    model: options.model || null, modelMap, web: options.web, sandbox: options.sandbox };
  let backend;
  try {
    emit({ type: 'workflow.started', ...common });
    backend = createCodexBackend({ ...options, modelMap, runDir, emit, signal: controller.signal });
    const { result, runtime } = await runWorkflow({ source, filename, args, backend,
      concurrency: options.concurrency, maxAgents: options.maxAgents, emit, signal: controller.signal });
    await writeJson(join(runDir, 'result.json'), result ?? null);
    await writeJson(join(runDir, 'runtime.json'), { ...common, ...runtime, endedAt: new Date().toISOString() });
    if (options.output) await writeJson(resolve(options.output), result ?? null);
    emit({ type: 'workflow.finished', status: runtime.status, agentCalls: runtime.agentCalls });
    process.stdout.write(JSON.stringify(result ?? null, null, 2) + '\n');
    return runtime.status === 'completed' ? 0 : runtime.status === 'needs_cost_decision' ? 3
      : runtime.status === 'failed' ? 1 : 2;
  } catch (error) {
    const status = controller.signal.aborted ? 'cancelled' : 'failed';
    emit({ type: 'workflow.finished', status, error: error.message });
    await writeJson(join(runDir, 'runtime.json'), { ...common, ...error.workflowRuntime, status,
      error: error.message, endedAt: new Date().toISOString() });
    process.stderr.write(`Workflow ${status}: ${error.message}\n`);
    return status === 'cancelled' ? 130 : 1;
  } finally {
    backend?.dispose();
    process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === await realpath(resolve(process.argv[1]))) {
  main().then(code => { process.exitCode = code; }, error => {
    process.stderr.write(`Workflow failed: ${error.message}\n`); process.exitCode = 1;
  });
}
