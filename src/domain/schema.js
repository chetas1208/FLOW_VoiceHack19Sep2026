/**
 * Minimal structural schema validator.
 *
 * The backend deliberately stays dependency-free, so rather than pulling in Zod we
 * implement the narrow slice of validation FLOW actually needs: shape-checking
 * model output and inbound API payloads, with useful error paths.
 *
 * A schema is a plain object: { type, ...constraints }.
 */

export class ValidationError extends Error {
  constructor(issues) {
    super(`Schema validation failed: ${issues.map((i) => `${i.path || '<root>'}: ${i.message}`).join('; ')}`);
    this.name = 'ValidationError';
    this.issues = issues;
    this.status = 400;
  }
}

const typeOf = (v) => (Array.isArray(v) ? 'array' : v === null ? 'null' : typeof v);

function check(value, schema, path, issues) {
  const fail = (message) => issues.push({ path, message });

  if (value === undefined || value === null) {
    if (schema.optional || schema.nullable) return schema.default !== undefined ? schema.default : value ?? null;
    fail(`is required`);
    return value;
  }

  switch (schema.type) {
    case 'string': {
      if (typeof value !== 'string') { fail(`expected string, received ${typeOf(value)}`); return value; }
      let out = schema.trim === false ? value : value.trim();
      if (schema.minLength !== undefined && out.length < schema.minLength) fail(`must be at least ${schema.minLength} character(s)`);
      if (schema.maxLength !== undefined && out.length > schema.maxLength) {
        if (schema.truncate) out = out.slice(0, schema.maxLength);
        else fail(`must be at most ${schema.maxLength} character(s)`);
      }
      if (schema.enum && !schema.enum.includes(out)) fail(`must be one of: ${schema.enum.join(', ')}`);
      if (schema.pattern && !schema.pattern.test(out)) fail(`has an invalid format`);
      return out;
    }
    case 'number': {
      const n = typeof value === 'string' && schema.coerce ? Number(value) : value;
      if (typeof n !== 'number' || !Number.isFinite(n)) { fail(`expected a finite number, received ${typeOf(value)}`); return value; }
      let out = n;
      if (schema.min !== undefined && out < schema.min) { if (schema.clamp) out = schema.min; else fail(`must be >= ${schema.min}`); }
      if (schema.max !== undefined && out > schema.max) { if (schema.clamp) out = schema.max; else fail(`must be <= ${schema.max}`); }
      if (schema.integer && !Number.isInteger(out)) { if (schema.clamp) out = Math.round(out); else fail(`must be an integer`); }
      return out;
    }
    case 'boolean': {
      if (typeof value !== 'boolean') { fail(`expected boolean, received ${typeOf(value)}`); return value; }
      return value;
    }
    case 'isoDate': {
      if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) { fail(`expected an ISO-8601 timestamp`); return value; }
      return new Date(value).toISOString();
    }
    case 'array': {
      if (!Array.isArray(value)) { fail(`expected array, received ${typeOf(value)}`); return value; }
      if (schema.maxItems !== undefined && value.length > schema.maxItems) fail(`must contain at most ${schema.maxItems} item(s)`);
      return value.map((item, i) => check(item, schema.items, `${path}[${i}]`, issues));
    }
    case 'object': {
      if (typeOf(value) !== 'object') { fail(`expected object, received ${typeOf(value)}`); return value; }
      const out = {};
      for (const [key, sub] of Object.entries(schema.properties)) {
        const childPath = path ? `${path}.${key}` : key;
        const raw = value[key];
        if (raw === undefined && sub.optional) { if (sub.default !== undefined) out[key] = sub.default; continue; }
        out[key] = check(raw, sub, childPath, issues);
      }
      return out;
    }
    case 'any':
      return value;
    default:
      fail(`unsupported schema type "${schema.type}"`);
      return value;
  }
}

/** Validate and normalise `value`. Throws ValidationError on failure. */
export function parse(schema, value) {
  const issues = [];
  const out = check(value, schema, '', issues);
  if (issues.length) throw new ValidationError(issues);
  return out;
}

/** Non-throwing variant: { ok, data } | { ok:false, error }. */
export function safeParse(schema, value) {
  try {
    return { ok: true, data: parse(schema, value) };
  } catch (error) {
    if (error instanceof ValidationError) return { ok: false, error };
    throw error;
  }
}
