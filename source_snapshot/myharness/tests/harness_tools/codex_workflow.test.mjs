import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, mkdir, chmod, rm, symlink } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { strictSchema, validate, restoreOptional } from '../../plugins/harness-core/scripts/lib/workflow-schema.mjs';
import { runWorkflow, createCodexBackend } from '../../plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const runner = join(root, 'plugins/harness-core/scripts/codex-workflow.mjs');
const canonical = process.env.M05_WORKFLOW_PATH || join(root, 'plugins/harness-core/workflows/m05-web-research.js');
const stringSchema = { type: 'object', required: ['value'], properties: { value: { type: 'string' } } };
const fakeBackend = (run = async prompt => ({ value: prompt })) => ({ run });

async function temporary(t) {
  const dir = await mkdtemp(join(tmpdir(), 'codex-workflow-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}
function launch(argv, cwd) {
  const child = spawn(process.execPath, [runner, ...argv], { cwd, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  child.stdout.on('data', c => { stdout += c; });
  child.stderr.on('data', c => { stderr += c; });
  return { child, done: new Promise((res, rej) => {
    child.on('error', rej); child.on('close', code => res({ code, stdout, stderr }));
  }) };
}
async function fixture(t, mode = 'success') {
  const cwd = await temporary(t);
  const bin = join(cwd, 'fake-codex');
  // Test-only process, no network/inference. Check actual argv and schema files.
  await writeFile(bin, `#!${process.execPath}
import { readFileSync, writeFileSync } from 'node:fs';
const argv = process.argv.slice(2);
const mode = ${JSON.stringify(mode)};
let prompt = '';
for await (const chunk of process.stdin) prompt += chunk;
if (mode === 'hang') { writeFileSync('started.pid', String(process.pid)); setInterval(() => {}, 1000); }
else {
  writeFileSync('argv.json', JSON.stringify(argv));
  const schemaPath = argv[argv.indexOf('--output-schema') + 1];
  const schema = schemaPath && schemaPath !== argv[0] ? JSON.parse(readFileSync(schemaPath)) : null;
  let value = { value: 'ok' };
  if (prompt.includes('Decompose this research question')) value = { question: 'fixture question', summary: 'fixture only', angles: [{ label: 'primary', query: 'fixture', rationale: null }] };
  else if (prompt.includes('## Web Searcher')) value = { results: [{ url: 'https://example.com/fixture', title: 'fixture source', relevance: 'high', snippet: null }] };
  else if (prompt.includes('## Source Extractor')) value = { sourceQuality: 'primary', publishDate: null, claims: [{ claim: 'fixture claim', quote: 'fixture quotation', importance: 'central' }] };
  else if (prompt.includes('## Adversarial Claim Verifier')) value = { refuted: false, evidence: 'fixture evidence (not real research)', confidence: 'high', counterSource: null };
  else if (prompt.includes('## Synthesis:')) value = { summary: 'fixture only', findings: [{ claim: 'fixture claim', confidence: 'high', sources: ['https://example.com/fixture'], evidence: 'fixture', vote: null }], caveats: 'fixture is not research', openQuestions: null };
  if (mode === 'invalid') value = { value: 42 };
  writeFileSync(argv[argv.indexOf('--output-last-message') + 1], JSON.stringify(value));
  console.log(JSON.stringify({ type: 'thread.started', thread_id: 'fixture' }));
  if (mode.startsWith('reconnect')) console.log(JSON.stringify({ type: 'error', message: 'Reconnecting... 1/5 (stream disconnected)' }));
  if (mode === 'error-completed') console.log(JSON.stringify({ type: 'error', message: 'unrecoverable fixture error' }));
  if (mode === 'failed' || mode === 'verify-failed' && prompt.includes('Adversarial Claim Verifier')) console.log(JSON.stringify({ type: 'turn.failed', error: { message: 'fixture failure' } }));
  else if (mode !== 'incomplete' && mode !== 'reconnect-incomplete') console.log(JSON.stringify({ type: 'turn.completed', usage: { input_tokens: 10, output_tokens: 5 } }));
}
`);
  await chmod(bin, 0o700);
  return { cwd, bin };
}

test('strict schema restores optional null and validates enum/type/bounds', () => {
  const original = { type: 'object', required: ['kind'], properties: {
    kind: { enum: ['primary', 'secondary'] }, note: { type: 'string' },
    nullable: { type: ['string', 'null'] },
  } };
  const strict = strictSchema(original);
  assert.equal(strict.additionalProperties, false);
  assert.deepEqual(strict.required, ['kind', 'note', 'nullable']);
  const value = { kind: 'primary', note: null, nullable: null };
  validate(value, strict);
  const restored = restoreOptional(value, original);
  assert.deepEqual(restored, { kind: 'primary', nullable: null });
  validate(restored, original);
  assert.throws(() => validate({ kind: 'fake', note: null, nullable: null }, strict), /enum/);
  assert.throws(() => validate({ value: 42 }, strictSchema(stringSchema)), /expected string/);
  assert.throws(() => validate([1, 2], { type: 'array', maxItems: 1 }), /too many/);
  assert.throws(() => strictSchema({ type: 'string', format: 'custom' }), /unsupported/);
  assert.throws(() => strictSchema({ type: 'object', additionalProperties: true }), /open-ended/);
  assert.throws(() => strictSchema({ type: 'object', required: ['missing'], properties: {} }), /missing from schema/);
  validate(null, strictSchema({ type: ['object', 'null'], properties: { n: { type: 'number' } } }));
  assert.throws(() => strictSchema({ type: ['array', 'null'], items: { type: 'string', format: 'custom' } }), /unsupported/);
});

test('injects globals and preserves meta and top-level return/await', async () => {
  const { result, runtime } = await runWorkflow({ backend: fakeBackend(), args: 'question', source:
    `export const meta = {name: 'sample', phases: []}; phase('Scope'); log(args); return await agent(args);` });
  assert.equal(result, 'question'); assert.equal(runtime.workflow.name, 'sample');
  assert.equal(runtime.calls[0].phase, 'Scope');
});

test('nested parallel is bounded at agents and keeps input order without deadlock', async () => {
  let active = 0, peak = 0;
  const backend = fakeBackend(async prompt => {
    active++; peak = Math.max(peak, active); await delay(Number(prompt)); active--;
    return { value: prompt, usage: { input_tokens: 2 } };
  });
  const { result, runtime } = await runWorkflow({ backend, concurrency: 2, source:
    `return await parallel([() => parallel([() => agent('30'), () => agent('2')]), () => parallel([() => agent('1'), () => agent('3')])]);` });
  assert.deepEqual(JSON.parse(JSON.stringify(result)), [['30', '2'], ['1', '3']]);
  assert.equal(peak, 2); assert.equal(runtime.usage.input_tokens, 8);
});

test('pipeline passes fast input downstream before slow input finishes', async () => {
  const trace = [];
  const backend = fakeBackend(async prompt => {
    if (prompt === 'slow') await delay(40);
    trace.push(prompt); return { value: prompt };
  });
  const { result } = await runWorkflow({ backend, source:
    `return await pipeline(['slow','fast'], x => agent(x), x => agent('fetch:' + x));` });
  assert(trace.indexOf('fetch:fast') < trace.indexOf('slow'));
  assert.deepEqual([...result], ['fetch:slow', 'fetch:fast']);
});

test('agent failures abstain and never fabricate a schema result', async () => {
  const { result, runtime } = await runWorkflow({ backend: fakeBackend(async () => { throw new Error('bad response'); }), source: `return await parallel([() => agent('a'), () => agent('b')]);` });
  assert.deepEqual([...result], [null, null]); assert.equal(runtime.status, 'partial');
  assert.equal(runtime.calls[0].error, 'bad response');
});

test('call budget cannot be hidden by workflow try/catch', async () => {
  await assert.rejects(runWorkflow({ backend: fakeBackend(), maxAgents: 1, source:
    `await agent('a'); try { await agent('b'); } catch {} return {ok:true};` }), /budget exceeded/);
});

test('Codex process receives stdin prompt, strict schema and safe flags', async t => {
  const { cwd, bin } = await fixture(t);
  const runDir = join(cwd, 'run'); await mkdir(runDir);
  const backend = createCodexBackend({ cwd, codexBin: bin, runDir });
  const result = await backend.run('literal $(touch injected) `touch injected`', { schema: stringSchema }, 1);
  assert.deepEqual(result.value, { value: 'ok' });
  const argv = JSON.parse(await readFile(join(cwd, 'argv.json')));
  assert(argv.includes('--search')); assert(argv.includes('--ephemeral'));
  assert.equal(argv[argv.indexOf('--sandbox') + 1], 'read-only');
  assert.equal(argv[argv.indexOf('-a') + 1], 'never');
  assert(!argv.some(a => a.includes('touch injected'))); assert(!existsSync(join(cwd, 'injected')));
});

for (const mode of ['failed', 'incomplete', 'invalid', 'reconnect-incomplete', 'error-completed']) {
  test(`reject ${mode} CLI result even when exit code is zero`, async t => {
    const { cwd, bin } = await fixture(t, mode);
    const runDir = join(cwd, 'run'); await mkdir(runDir);
    const backend = createCodexBackend({ cwd, codexBin: bin, runDir });
    await assert.rejects(backend.run('simple', { schema: stringSchema }, 1));
  });
}

test('reconnecting diagnostic is recoverable only with a completed valid turn', async t => {
  const { cwd, bin } = await fixture(t, 'reconnect-completed');
  const runDir = join(cwd, 'run'); await mkdir(runDir);
  const backend = createCodexBackend({ cwd, codexBin: bin, runDir });
  assert.deepEqual((await backend.run('simple', { schema: stringSchema }, 1)).value, { value: 'ok' });
});

test('timeout terminates the agent process', async t => {
  const { cwd, bin } = await fixture(t, 'hang');
  const runDir = join(cwd, 'run'); await mkdir(runDir);
  const backend = createCodexBackend({ cwd, codexBin: bin, runDir, timeoutMs: 3000 });
  await assert.rejects(backend.run('hang', {}, 1), /timeout/);
  const pid = Number(await readFile(join(cwd, 'started.pid')));
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
});

test('model aliases require explicit mapping and preserve actual model', async t => {
  const { cwd, bin } = await fixture(t); const runDir = join(cwd, 'run'); await mkdir(runDir);
  const backend = createCodexBackend({ cwd, codexBin: bin, runDir, modelMap: { sonnet: 'gpt-fixture' } });
  assert.throws(() => backend.resolveModel('haiku'), /unmapped/);
  assert.equal(backend.resolveModel('sonnet'), 'gpt-fixture');
  assert.equal((await backend.run('simple', { model: 'sonnet', schema: stringSchema }, 1)).model, 'gpt-fixture');
});

test('unchanged canonical M0.5 executes five phases through real subprocess adapter', async t => {
  const { cwd, bin } = await fixture(t); const runDir = join(cwd, 'run');
  const out = await launch(['--script-path', canonical, '--cwd', cwd, '--codex-bin', bin,
    '--args', JSON.stringify({ question: 'fixture question', tier: 'inherit', angles: 1, votes: 1, urls: 1, claims: 1 }), '--run-dir', runDir], cwd).done;
  assert.equal(out.code, 0, out.stderr);
  const result = JSON.parse(out.stdout); const runtime = JSON.parse(await readFile(join(runDir, 'runtime.json')));
  assert.equal(result.findings.length, 1); assert.equal(runtime.agentCalls, 5);
  assert.deepEqual(runtime.calls.map(c => c.phase), ['Scope', 'Search', 'Fetch', 'Verify', 'Synthesize']);
  assert.equal(runtime.usage.input_tokens, 50);
  assert(!Object.hasOwn(result, 'openQuestions')); // optional-null compatibility
});

test('M0.5 missing cost decision exits 3 before spawning', async t => {
  const { cwd, bin } = await fixture(t); const runDir = join(cwd, 'run');
  const out = await launch(['--script-path', canonical, '--cwd', cwd, '--codex-bin', bin,
    '--args', '{"question":"fixture"}', '--run-dir', runDir], cwd).done;
  assert.equal(out.code, 3, out.stderr); assert.equal(JSON.parse(out.stdout).needsCostDecision, true);
  assert(!existsSync(join(cwd, 'argv.json')));
});

test('M0.5 unmapped vendor model is configuration failure, not degraded research', async t => {
  const { cwd, bin } = await fixture(t); const runDir = join(cwd, 'run');
  const out = await launch(['--script-path', canonical, '--cwd', cwd, '--codex-bin', bin,
    '--args', '{"question":"fixture","profile":"lite"}', '--run-dir', runDir], cwd).done;
  assert.equal(out.code, 1); assert.match(out.stderr, /unmapped/); assert.equal(out.stdout, '');
  assert(!existsSync(join(cwd, 'argv.json')));
});

test('M0.5 failed verifier abstains, drops claim and marks run partial', async t => {
  const { cwd, bin } = await fixture(t, 'verify-failed'); const runDir = join(cwd, 'run');
  const out = await launch(['--script-path', canonical, '--cwd', cwd, '--codex-bin', bin,
    '--args', '{"question":"fixture","tier":"inherit","angles":1,"votes":1,"claims":1}', '--run-dir', runDir], cwd).done;
  assert.equal(out.code, 2, out.stderr); const result = JSON.parse(out.stdout);
  assert.equal(result.findings.length, 0); assert.equal(result.refuted.length, 1);
  assert.equal(JSON.parse(await readFile(join(runDir, 'runtime.json'))).status, 'partial');
});

test('SIGINT cancels active and queued agents and exits 130', async t => {
  const { cwd, bin } = await fixture(t, 'hang'); const workflow = join(cwd, 'workflow.js');
  await writeFile(workflow, `return await parallel([() => agent('a'), () => agent('b')]);`);
  const runDir = join(cwd, 'run');
  const { child, done } = launch(['--script-path', workflow, '--cwd', cwd, '--codex-bin', bin,
    '--concurrency', '1', '--run-dir', runDir], cwd);
  for (let i = 0; i < 100 && !existsSync(join(cwd, 'started.pid')); i++) await delay(20);
  assert(existsSync(join(cwd, 'started.pid'))); child.kill('SIGINT');
  const out = await done; assert.equal(out.code, 130, out.stderr);
  const pid = Number(await readFile(join(cwd, 'started.pid')));
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
  assert.equal(JSON.parse(await readFile(join(runDir, 'runtime.json'))).status, 'cancelled');
  const runtime = JSON.parse(await readFile(join(runDir, 'runtime.json')));
  assert.equal(runtime.agentCalls, 2); assert(runtime.calls.every(c => c.status === 'cancelled'));
});

test('invalid JSON args rejected before creating a run or calling Codex', async t => {
  const { cwd, bin } = await fixture(t); const runDir = join(cwd, 'run');
  const out = await launch(['--script-path', canonical, '--cwd', cwd, '--codex-bin', bin,
    '--args', '{invalid}', '--run-dir', runDir], cwd).done;
  assert.equal(out.code, 1); assert.match(out.stderr, /invalid args JSON/); assert(!existsSync(runDir));
});

test('CLI entry point also works through a symbolic link', async t => {
  const cwd = await temporary(t); const link = join(cwd, 'runner.mjs');
  await symlink(runner, link);
  const child = spawn(process.execPath, [link, '--help'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = ''; child.stdout.on('data', chunk => { stdout += chunk; });
  const code = await new Promise(resolve => child.on('close', resolve));
  assert.equal(code, 0); assert.match(stdout, /Codex Workflow runner/);
});

test('workflow error cancels pending real subprocess work and preserves audit', async t => {
  const { cwd, bin } = await fixture(t, 'hang'); const runDir = join(cwd, 'run'); await mkdir(runDir);
  const backend = createCodexBackend({ cwd, codexBin: bin, runDir, timeoutMs: 30000 });
  const start = Date.now();
  await assert.rejects(runWorkflow({ backend, source: `agent('unawaited'); throw new Error('workflow bug');` }), error => {
    assert.equal(error.message, 'workflow bug');
    assert.equal(error.workflowRuntime.agentCalls, 1);
    assert.equal(error.workflowRuntime.status, 'failed');
    return true;
  });
  assert(Date.now() - start < 5000);
  assert(!existsSync(join(cwd, 'started.pid')));
});
