// Tests for viewer-request.js, rendered the way Terraform's templatefile() renders it.
// Run by CI's Terraform job with the runner's own Node (no packages):
//   node --test infra/modules/site/viewer-request.test.mjs
// It lives here because the dev container can't see infra/.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const HOST = 'spellcaster.foo';
const source = readFileSync(new URL('./viewer-request.js', import.meta.url), 'utf8');
const rendered = source.replaceAll('${host}', HOST);
const handler = new Function(`${rendered}\nreturn handler;`)();

function request(uri, host = HOST, querystring = {}) {
  const headers = host === null ? {} : { host: { value: host } };
  return { request: { method: 'GET', uri, querystring, headers, cookies: {} } };
}

function assertRedirect(result, location) {
  assert.equal(result.statusCode, 301);
  assert.equal(result.headers.location.value, location);
  assert.match(result.headers['strict-transport-security'].value, /^max-age=31536000; includeSubDomains; preload$/);
}

test('templatefile has only the one placeholder', () => {
  // Any other ${ or %{ would be read by templatefile() and break the apply.
  assert.equal(source.split('${host}').length, 2);
  assert.doesNotMatch(rendered, /[$%]\{/);
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
