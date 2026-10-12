// Workflow schemas are a deliberately bounded JSON Schema subset. Unsupported
// keywords fail before inference rather than silently weakening validation.
const KEYS = new Set(['type', 'properties', 'required', 'additionalProperties',
  'items', 'enum', 'const', 'anyOf', 'minItems', 'maxItems', 'minLength',
  'maxLength', 'pattern', 'minimum', 'maximum', 'description', 'title', '$schema']);
const isObject = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function strictSchema(schema) {
  if (!isObject(schema)) throw new Error('schema must be an object');
  for (const key of Object.keys(schema)) {
    if (!KEYS.has(key)) throw new Error(`unsupported schema keyword: ${key}`);
  }
  const s = structuredClone(schema);
  if (!s.type && s.enum) {
    const types = [...new Set(s.enum.map(x => x === null ? 'null' : typeof x))];
    if (types.some(x => !['string', 'boolean', 'number', 'null'].includes(x))) {
      throw new Error('enum requires primitive values');
    }
    s.type = types.length === 1 ? types[0] : types;
  }
  if (s.anyOf) s.anyOf = s.anyOf.map(strictSchema);
  const types = Array.isArray(s.type) ? s.type : [s.type];
  if (s.properties || types.includes('object')) {
    if (s.additionalProperties && s.additionalProperties !== false) {
      throw new Error('open-ended object schemas are unsupported');
    }
    s.type ||= 'object';
    const required = new Set(s.required || []);
    for (const key of required) {
      if (!Object.hasOwn(s.properties || {}, key)) throw new Error(`required property missing from schema: ${key}`);
    }
    s.properties = Object.fromEntries(Object.entries(s.properties || {}).map(([k, v]) => {
      const normalized = strictSchema(v);
      return [k, required.has(k) ? normalized : { anyOf: [normalized, { type: 'null' }] }];
    }));
    s.required = Object.keys(s.properties);
    s.additionalProperties = false;
  }
  if (types.includes('array')) {
    if (!s.items || Array.isArray(s.items)) throw new Error('array schema requires homogeneous items');
    s.items = strictSchema(s.items);
  }
  if (!s.type && !s.anyOf && !('const' in s)) throw new Error('schema requires type, enum, anyOf or const');
  const allowedTypes = ['object', 'array', 'string', 'number', 'integer', 'boolean', 'null'];
  if (s.type && (Array.isArray(s.type) ? s.type : [s.type]).some(t => !allowedTypes.includes(t))) {
    throw new Error('unsupported schema type');
  }
  return s;
}

export function validate(value, s, path = '$') {
  const fail = message => { throw new Error(`${path}: ${message}`); };
  if (s.anyOf && !s.anyOf.some(branch => {
    try { validate(value, branch, path); return true; } catch { return false; }
  })) fail('does not match anyOf');
  const matches = t => t === 'null' ? value === null : t === 'object' ? isObject(value)
    : t === 'array' ? Array.isArray(value) : t === 'integer' ? Number.isInteger(value)
    : t === 'number' ? typeof value === 'number' && Number.isFinite(value) : typeof value === t;
  if (s.type && !(Array.isArray(s.type) ? s.type : [s.type]).some(matches)) fail(`expected ${s.type}`);
  if (s.enum && !s.enum.some(x => equal(x, value))) fail('not in enum');
  if ('const' in s && !equal(s.const, value)) fail('not equal to const');
  if (isObject(value)) {
    for (const k of s.required || []) if (!(k in value)) fail(`missing required property ${k}`);
    for (const [k, v] of Object.entries(value)) {
      if (s.properties?.[k]) validate(v, s.properties[k], `${path}.${k}`);
      else if (s.additionalProperties === false) fail(`unexpected property ${k}`);
    }
  }
  if (Array.isArray(value)) {
    if (s.minItems !== undefined && value.length < s.minItems) fail('too few items');
    if (s.maxItems !== undefined && value.length > s.maxItems) fail('too many items');
    if (s.items) value.forEach((v, i) => validate(v, s.items, `${path}[${i}]`));
  }
  if (typeof value === 'string') {
    const length = [...value].length;
    if (s.minLength !== undefined && length < s.minLength) fail('string too short');
    if (s.maxLength !== undefined && length > s.maxLength) fail('string too long');
    if (s.pattern && !new RegExp(s.pattern, 'u').test(value)) fail('pattern mismatch');
  }
  if (typeof value === 'number') {
    if (s.minimum !== undefined && value < s.minimum) fail('below minimum');
    if (s.maximum !== undefined && value > s.maximum) fail('above maximum');
  }
  return value;
}

// Codex's strict schema requires optional object keys to be present and nullable.
// Remove ONLY that adapter-added null, then validate against the original schema.
export function restoreOptional(value, schema) {
  if (schema.anyOf) {
    for (const branch of schema.anyOf) {
      try { validate(value, strictSchema(branch)); return restoreOptional(value, branch); } catch {}
    }
  }
  if (Array.isArray(value) && schema.items) return value.map(v => restoreOptional(v, schema.items));
  if (isObject(value) && schema.properties) {
    const result = { ...value };
    for (const [k, s] of Object.entries(schema.properties)) {
      if (!(k in result)) continue;
      if (result[k] === null && !(schema.required || []).includes(k)) {
        try { validate(null, s); } catch { delete result[k]; continue; }
      }
      result[k] = restoreOptional(result[k], s);
    }
    return result;
  }
  return value;
}
