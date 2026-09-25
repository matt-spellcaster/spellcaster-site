// Tests for viewer-request.js, rendered the way Terraform's templatefile() renders it.
// Run by CI's Terraform job with the runner's own Node (no packages):
//   node --test infra/modules/site/viewer-request.test.mjs
// It lives here because the dev container can't see infra/.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const HOST = 'spellcaster.foo';
const source = readFileSync(new URL('./viewer-request.js', import.meta.url), 'utf8');

// What templatefile() does, for production (no password) or QA.
function render({ host = HOST, authSha256 = '', noindex = false } = {}) {
  return source
    .replaceAll('${host}', host)
    .replaceAll('${auth_sha256}', authSha256)
    .replaceAll('${noindex}', String(noindex));
}
function load(rendered) {
  return new Function('require', `${rendered}\nreturn handler;`)(createRequire(import.meta.url));
}
const rendered = render();
const handler = load(rendered);

const QA_HOST = `qa.${HOST}`;
const QA_HEADER = `Basic ${Buffer.from('qa:correct horse battery staple').toString('base64')}`;
const qa = load(
  render({
    host: QA_HOST,
    authSha256: createHash('sha256').update(QA_HEADER).digest('hex'),
    noindex: true,
  }),
);

function request(uri, host = HOST, querystring = {}, authorization = null) {
  const headers = host === null ? {} : { host: { value: host } };
  if (authorization !== null) headers.authorization = { value: authorization };
  return { request: { method: 'GET', uri, querystring, headers, cookies: {} } };
}

function assertRedirect(result, location) {
  assert.equal(result.statusCode, 301);
  assert.equal(result.headers.location.value, location);
  assert.match(result.headers['strict-transport-security'].value, /^max-age=31536000; includeSubDomains; preload$/);
}

test('templatefile has only the three placeholders, once each', () => {
  // Any other ${ or %{ would be read by templatefile() and break the apply.
  for (const name of ['host', 'auth_sha256', 'noindex']) {
    assert.equal(source.split(`\${${name}}`).length, 2, name);
  }
  assert.doesNotMatch(rendered, /[$%]\{/);
});

test('production asks for no password and sends no noindex', () => {
  const result = handler(request('/projects/x'));
  assert.equal(result.statusCode, 301);
  assert.equal(result.headers['x-robots-tag'], undefined);
  assert.equal(handler(request('/')).uri, '/index.html');
});

test('QA without the password gets 401, whatever it asks for', () => {
  for (const [uri, host, authorization] of [
    ['/', QA_HOST, null],
    ['/', QA_HOST, `${QA_HEADER}x`],
    ['/', QA_HOST, QA_HEADER.toLowerCase()],
    ['/', QA_HOST, `Basic ${Buffer.from('qa:wrong').toString('base64')}`],
    ['/projects/x', QA_HOST, null], // no redirect first
    ['/', 'd111111abcdef8.cloudfront.net', null],
  ]) {
    const result = qa(request(uri, host, {}, authorization));
    assert.equal(result.statusCode, 401, `${host}${uri} ${authorization}`);
    assert.equal(result.headers['www-authenticate'].value, 'Basic realm="QA", charset="UTF-8"');
    assert.equal(result.headers['cache-control'].value, 'no-store');
    assert.equal(result.headers['x-robots-tag'].value, 'noindex, nofollow');
    assert.match(result.headers['strict-transport-security'].value, /^max-age=31536000; /);
  }
});

test('QA with the password works like production, with noindex on its redirects', () => {
  assert.equal(qa(request('/', QA_HOST, {}, QA_HEADER)).uri, '/index.html');
  for (const [uri, host, location] of [
    ['/projects/x', QA_HOST, `https://${QA_HOST}/projects/x/`],
    ['/', 'd111111abcdef8.cloudfront.net', `https://${QA_HOST}/`],
  ]) {
    const result = qa(request(uri, host, {}, QA_HEADER));
    assertRedirect(result, location);
    assert.equal(result.headers['x-robots-tag'].value, 'noindex, nofollow');
  }
});

test('other host names move to the one name, keeping the path', () => {
  assertRedirect(handler(request('/', `www.${HOST}`)), `https://${HOST}/`);
  assertRedirect(handler(request('/projects/x/', 'd111111abcdef8.cloudfront.net')), `https://${HOST}/projects/x/`);
  assertRedirect(handler(request('/', null)), `https://${HOST}/`); // no Host header
});

test('the host name is matched without regard to case', () => {
  assert.equal(handler(request('/', 'SpellCaster.FOO')).uri, '/index.html');
});

test('a folder is its index.html', () => {
  assert.equal(handler(request('/')).uri, '/index.html');
  assert.equal(handler(request('/projects/x/')).uri, '/projects/x/index.html');
});

test('a page URL without its slash gets one', () => {
  assertRedirect(handler(request('/projects/x')), `https://${HOST}/projects/x/`);
});

test('files are left alone', () => {
  for (const uri of ['/_astro/Base.abc.css', '/favicon.ico', '/og/home.jpg', '/404.html']) {
    assert.equal(handler(request(uri)).uri, uri);
  }
});

test('redirects keep the query string, repeated keys and empty values included', () => {
  const querystring = {
    a: { value: '1', multiValue: [{ value: '1' }, { value: '2' }] },
    b: { value: '' },
    c: { value: 'x%26y' },
  };
  assertRedirect(handler(request('/projects/x', HOST, querystring)), `https://${HOST}/projects/x/?a=1&a=2&b&c=x%26y`);
  assertRedirect(handler(request('/', `www.${HOST}`, { q: { value: 'z' } })), `https://${HOST}/?q=z`);
});
