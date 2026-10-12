import { spawn } from 'node:child_process';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';
import { strictSchema, validate, restoreOptional } from './workflow-schema.mjs';

const aborted = signal => {
  if (signal?.aborted) throw signal.reason || new Error('workflow cancelled');
};
const jsonFile = (path, value) => writeFile(path, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });

class Semaphore {
  constructor(limit) { this.limit = limit; this.active = 0; this.queue = []; }
  async run(task, signal) {
    aborted(signal);
    if (this.active >= this.limit) {
      await new Promise((resolve, reject) => {
        const entry = { resolve, reject };
        const cancel = () => {
          const i = this.queue.indexOf(entry);
          if (i >= 0) this.queue.splice(i, 1);
          reject(signal.reason || new Error('workflow cancelled'));
        };
        entry.resolve = () => { signal?.removeEventListener('abort', cancel); resolve(); };
        this.queue.push(entry);
        signal?.addEventListener('abort', cancel, { once: true });
      });
    } else this.active++;
    try { aborted(signal); return await task(); }
    finally {
      const next = this.queue.shift();
      if (next) next.resolve(); // transfer the slot without incrementing active
      else this.active--;
    }
  }
}

export function compileWorkflow(source, filename = 'workflow.js') {
  // This is a trusted local scripting format, NOT a security sandbox. The only
  // supported module export is metadata; top-level return/await need a wrapper.
  const body = source.replace(/^export\s+const\s+meta\s*=/m, 'meta = __workflowMeta.value =');
  return new vm.Script(`(async function(args, agent, parallel, pipeline, phase, log, __workflowMeta) {
    'use strict'; let meta;
    ${body}
  })`, { filename }).runInNewContext({ URL }, { timeout: 1000 });
}

export function createCodexBackend({ cwd, runDir, codexBin = 'codex', model,
  modelMap = {}, web = true, sandbox = 'read-only', timeoutMs = 300000,
  signal: parentSignal, emit = () => {} }) {
  const controller = new AbortController();
  const signal = controller.signal;
  const parentCancel = () => controller.abort(parentSignal.reason || new Error('workflow cancelled'));
  parentSignal?.addEventListener('abort', parentCancel, { once: true });
  if (parentSignal?.aborted) parentCancel();
  const vendorAliases = /^(haiku|sonnet|opus|claude(?:-|$))/i;
  function resolveModel(requested) {
    if (!requested) return model;
    if (Object.hasOwn(modelMap, requested)) {
      const mapped = modelMap[requested];
      if (typeof mapped !== 'string' || !mapped.trim() || vendorAliases.test(mapped)) {
        throw new Error(`model-map must map ${requested} to an actual Codex model id`);
      }
      return mapped;
    }
    if (vendorAliases.test(requested)) {
      throw new Error(`unmapped Claude model '${requested}': provide --model-map, or explicitly use workflow tier:'inherit'`);
    }
    return requested;
  }

  async function run(prompt, options, id) {
    aborted(signal);
    const selected = resolveModel(options.model);
    const schema = options.schema && strictSchema(options.schema);
    const dir = join(runDir, 'agents', String(id).padStart(4, '0'));
    await mkdir(dir, { recursive: true, mode: 0o700 });
    const output = join(dir, 'last-message.txt');
    const argv = ['-a', 'never'];
    if (web) argv.push('--search');
    argv.push('exec', '--json', '--ephemeral', '--color', 'never',
      '--sandbox', sandbox, '--cd', cwd, '--output-last-message', output);
    if (selected) argv.push('--model', selected);
    if (schema) {
      await jsonFile(join(dir, 'schema.json'), schema);
      argv.push('--output-schema', join(dir, 'schema.json'));
    }
    argv.push('-');
    const prefix = '[Workflow compatibility adapter]\n'
      + 'Follow project instructions. Work only on this assigned task; do not launch other agents.\n'
      + (web ? 'WebSearch means your native web_search tool. WebFetch means opening the specified URL with that tool. Use actual tools; never fabricate retrieval or citations.\n'
        : 'Live web access is disabled for this run. Do not claim live retrieval.\n')
      + (schema ? 'Return only JSON matching the provided schema; absent optional fields must be null.\n' : '')
      + '\n[Workflow task]\n';
    aborted(signal);
    emit({ type: 'agent.backend', id, model: selected || '(Codex configured default)', sandbox, web });
    const eventPath = join(dir, 'events.jsonl');
    let buffer = '', total = 0, completed = false, failure, reconnectError, usage;
    let stopReason, killTimer, timer;
    const child = spawn(codexBin, argv, {
      cwd, stdio: ['pipe', 'pipe', 'pipe'], shell: false,
      detached: process.platform !== 'win32',
    });
    function kill(signum) {
      try {
        if (process.platform !== 'win32') process.kill(-child.pid, signum);
        else child.kill(signum);
      } catch (error) { if (error.code !== 'ESRCH') emit({ type: 'agent.kill-error', id, message: error.message }); }
    }
    function stop(message) {
      if (stopReason) return;
      stopReason = message;
      kill('SIGTERM');
      killTimer = setTimeout(() => kill('SIGKILL'), 1000);
    }
    function consume(line) {
      if (!line.trim()) return;
      let event;
      try { event = JSON.parse(line); }
      catch { stop('Codex emitted invalid JSONL'); return; }
      appendFileSync(eventPath, JSON.stringify(event) + '\n', { mode: 0o600 });
      if (event.type === 'turn.completed') { completed = true; usage = event.usage; }
      if (event.type === 'turn.failed') failure = event.error?.message || event.message || event.type;
      if (event.type === 'error') {
        const message = event.error?.message || event.message || event.type;
        // Codex emits error events while reconnecting, then may finish the turn.
        // Only this known recoverable diagnostic can be superseded by completion.
        if (/^Reconnecting\.\.\./i.test(message)) reconnectError = message;
        else failure = message;
      }
      emit({ type: 'agent.event', id, eventType: event.type, itemType: event.item?.type });
    }
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      total += Buffer.byteLength(chunk);
      if (total > 16 * 1024 * 1024) { stop('Codex event output exceeded 16 MiB'); return; }
      buffer += chunk.toString();
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        consume(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1);
      }
    });
    // Keep diagnostics on disk, never echo configuration or credentials to stdout.
    let stderrBytes = 0;
    child.stderr.on('data', chunk => {
      stderrBytes += chunk.length;
      if (stderrBytes <= 1024 * 1024) appendFileSync(join(dir, 'stderr.log'), chunk, { mode: 0o600 });
    });
    const cancel = () => stop('workflow cancelled');
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) cancel();
    timer = setTimeout(() => stop(`agent timeout after ${timeoutMs} ms`), timeoutMs);
    child.stdin.on('error', () => {}); // early CLI exit (e.g. invalid model)
    child.stdin.end(prefix + prompt);
    let code;
    try {
      code = await new Promise((resolve, reject) => {
        child.once('error', reject);
        child.once('close', resolve);
      });
    } finally {
      // A parent can exit on TERM while its descendants ignore it. Kill the
      // remaining process group before clearing the escalation timer.
      if (stopReason && child.pid) kill('SIGKILL');
      clearTimeout(timer); clearTimeout(killTimer);
      signal?.removeEventListener('abort', cancel);
    }
    if (buffer.trim()) consume(buffer);
    aborted(signal);
    if (stopReason) throw new Error(stopReason);
    if (code !== 0 || failure || !completed) {
      throw new Error(failure || reconnectError || `codex exec failed (exit ${code}, turn.completed=${completed}); see agents/${String(id).padStart(4, '0')}/stderr.log`);
    }
    const final = await readFile(output, 'utf8');
    let value = final.trim();
    if (schema) {
      value = JSON.parse(final);
      validate(value, schema);
      value = restoreOptional(value, options.schema);
      validate(value, options.schema);
    } else if (!value) throw new Error('Codex returned an empty final message');
    await jsonFile(join(dir, 'result.json'), value);
    return { value, usage, model: selected || null };
  }
  return { run, resolveModel,
    cancel: reason => controller.abort(reason || new Error('workflow stopped')),
    dispose: () => parentSignal?.removeEventListener('abort', parentCancel) };
}

export async function runWorkflow({ source, filename, args, backend, concurrency = 3,
  maxAgents = 64, signal, emit = () => {} }) {
  const execute = compileWorkflow(source, filename);
  const semaphore = new Semaphore(concurrency);
  const metadata = {};
  const calls = [];
  const pending = new Set();
  let currentPhase = null, fatalError;
  const agent = (prompt, options = {}) => {
    aborted(signal);
    if (typeof prompt !== 'string') throw new Error('agent prompt must be a string');
    if (calls.length >= maxAgents) {
      fatalError = new Error(`maximum agent budget exceeded (${maxAgents})`);
      throw fatalError;
    }
    // Configuration/schema errors are fatal; they are not research abstentions.
    try {
      backend.resolveModel?.(options.model);
      if (options.schema) strictSchema(options.schema);
    } catch (error) { fatalError = error; throw error; }
    const record = { id: calls.length + 1, label: options.label || 'agent',
      phase: options.phase || currentPhase, status: 'queued' };
    calls.push(record);
    const task = semaphore.run(async () => {
      record.status = 'running'; record.startedAt = new Date().toISOString();
      emit({ type: 'agent.started', ...record });
      try {
        const response = await backend.run(prompt, options, record.id);
        aborted(signal);
        record.status = 'completed'; record.usage = response.usage; record.model = response.model;
        return response.value;
      } catch (error) {
        record.status = signal?.aborted ? 'cancelled' : 'failed'; record.error = error.message;
        if (signal?.aborted) throw error;
        return null; // failure = abstention; never a fabricated structured result
      } finally {
        record.endedAt = new Date().toISOString();
        emit({ type: 'agent.finished', ...record });
      }
    }, signal).catch(error => {
      if (record.status === 'queued') {
        record.status = signal?.aborted ? 'cancelled' : 'failed';
        record.error = error.message; record.endedAt = new Date().toISOString();
        emit({ type: 'agent.finished', ...record });
      }
      throw error;
    });
    pending.add(task);
    // Attach a rejection handler even when a trusted script forgets to await.
    task.then(() => pending.delete(task), () => pending.delete(task));
    return task;
  };
  const parallel = tasks => {
    if (!Array.isArray(tasks) || tasks.some(t => typeof t !== 'function')) {
      throw new Error('parallel expects an array of task functions');
    }
    return Promise.all(tasks.map(t => Promise.resolve().then(() => { aborted(signal); return t(); })));
  };
  const pipeline = (items, ...stages) => {
    if (!Array.isArray(items) || stages.some(s => typeof s !== 'function')) {
      throw new Error('pipeline expects an array and stage functions');
    }
    return parallel(items.map((item, i) => async () => {
      let value = item;
      for (const stage of stages) { aborted(signal); value = await stage(value, i); }
      return value;
    }));
  };
  const phase = title => { currentPhase = title; emit({ type: 'workflow.phase', title }); };
  const log = message => emit({ type: 'workflow.log', message: String(message) });
  let result, error;
  try { result = await execute(args, agent, parallel, pipeline, phase, log, metadata); }
  catch (e) { error = e; }
  if (fatalError || error || signal?.aborted) backend.cancel?.(fatalError || error || signal.reason);
  await Promise.allSettled([...pending]);
  const usage = {};
  for (const call of calls) for (const [key, value] of Object.entries(call.usage || {})) {
    if (typeof value === 'number') usage[key] = (usage[key] || 0) + value;
  }
  const status = signal?.aborted ? 'cancelled' : fatalError || error ? 'failed'
    : result?.needsCostDecision ? 'needs_cost_decision' : result?.degraded ? 'degraded'
    : result?.error || result === undefined || result === null ? 'failed'
    : calls.some(c => c.status !== 'completed') ? 'partial' : 'completed';
  const runtime = { backend: 'codex-exec', status, workflow: metadata.value || null,
    concurrency, maxAgents, agentCalls: calls.length, usage, calls };
  const terminal = signal?.aborted ? signal.reason || new Error('workflow cancelled') : fatalError || error;
  if (terminal) { terminal.workflowRuntime = runtime; throw terminal; }
  return { result, runtime };
}
