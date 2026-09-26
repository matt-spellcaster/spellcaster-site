// The few pieces of Python the tool's text depends on, so the demo writes the same bytes.
// Python counts and compares strings by code point; JavaScript by UTF-16 unit. The two
// differ once a string holds a character outside the Basic Multilingual Plane (an emoji).

/** len(): the number of code points. */
export function len(text: string): number {
  return Array.from(text).length;
}

/** Python's string order: by code point, not by UTF-16 unit. */
export function cmp(a: string, b: string): number {
  const x = Array.from(a, (c) => c.codePointAt(0) ?? 0);
  const y = Array.from(b, (c) => c.codePointAt(0) ?? 0);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = (x[i] ?? 0) - (y[i] ?? 0);
    if (d) return d;
  }
  return x.length - y.length;
}

// str.isspace(): what Python's strip() removes. Not JavaScript's trim(), which also removes
// U+FEFF and keeps U+001C to U+001F and U+0085.
// eslint-disable-next-line no-control-regex -- matching control characters is the point
const SPACE = /^[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/;

export function strip(text: string): string {
  const chars = Array.from(text);
  let start = 0;
  let end = chars.length;
  while (start < end && SPACE.test(chars[start] ?? '')) start++;
  while (end > start && SPACE.test(chars[end - 1] ?? '')) end--;
  return chars.slice(start, end).join('');
}

/** attest.check_text: strip, then refuse empty (when required), too long, or any \p{C}. */
export function checkText(value: string, what: string, limit: number, required: boolean): string {
  const text = strip(value);
  if (required && !text) throw new RangeError(`${what} can't be empty`);
  if (len(text) > limit) throw new RangeError(`${what} is longer than ${limit} characters`);
  if (/\p{C}/u.test(text)) {
    throw new RangeError(`${what} can't contain line breaks or control characters`);
  }
  return text;
}

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function sortedKeys(value: { [key: string]: Json }): string[] {
  return Object.keys(value).sort(cmp);
}

/**
 * json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False). JSON.stringify escapes a
 * string the same way (only ", \ and control characters), given no lone surrogates.
 */
export function dumps(value: unknown, indent = 2, depth = 0): string {
  const v = value as Json;
  if (v === null || typeof v !== 'object') {
    if (typeof v === 'number' && !Number.isInteger(v)) throw new TypeError('floats are not used');
    return JSON.stringify(v);
  }
  const pad = ' '.repeat(indent * (depth + 1));
  const end = ' '.repeat(indent * depth);
  if (Array.isArray(v)) {
    if (!v.length) return '[]';
    return `[\n${v.map((x) => pad + dumps(x, indent, depth + 1)).join(',\n')}\n${end}]`;
  }
  const keys = sortedKeys(v);
  if (!keys.length) return '{}';
  const body = keys.map((k) => `${pad}${JSON.stringify(k)}: ${dumps(v[k], indent, depth + 1)}`);
  return `{\n${body.join(',\n')}\n${end}}`;
}

/** json.dumps(value, separators=(",", ":"), sort_keys=True): ASCII only, like Python's default. */
export function compact(value: unknown): string {
  const v = value as Json;
  if (v === null || typeof v !== 'object') {
    return JSON.stringify(v).replace(
      /[\u007f-\uffff]/g,
      (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`,
    );
  }
  if (Array.isArray(v)) return `[${v.map(compact).join(',')}]`;
  return `{${sortedKeys(v)
    .map((k) => `${compact(k)}:${compact(v[k])}`)
    .join(',')}}`;
}
