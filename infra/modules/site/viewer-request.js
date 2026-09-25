// CloudFront viewer-request function (runtime cloudfront-js-2.0), rendered by Terraform's
// templatefile() with the site's one name and, on QA, the password's digest. It runs on every
// request, before the cache.
var crypto = require('crypto');

var HOST = '${host}';
// QA only: the SHA-256 (hex) of the whole Authorization header a visitor must send, so the
// function never holds the password itself. Empty on production, which has no password.
var AUTH_SHA256 = '${auth_sha256}';
// The same as bootstrap's header policies, which don't reach a function's own responses.
var HSTS = 'max-age=31536000; includeSubDomains; preload';
var NOINDEX = ${noindex};

function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var host = request.headers.host ? request.headers.host.value.toLowerCase() : '';

  // The password comes first, so nothing on QA answers without it, redirects included.
  if (AUTH_SHA256 !== '') {
    var auth = request.headers.authorization ? request.headers.authorization.value : '';
    if (crypto.createHash('sha256').update(auth).digest('hex') !== AUTH_SHA256) {
      return respond(401, 'Unauthorized', {
        'www-authenticate': { value: 'Basic realm="QA", charset="UTF-8"' },
        'cache-control': { value: 'no-store' }
      });
    }
  }

  // One name only: www and the distribution's own *.cloudfront.net name move to HOST.
  if (host !== HOST) {
    return redirect(uri + query(request.querystring));
  }

  // A folder is its index.html.
  if (uri.charAt(uri.length - 1) === '/') {
    request.uri = uri + 'index.html';
    return request;
  }

  // Every page's URL ends in /, so a path whose last part has no extension gets one.
  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last.indexOf('.') === -1) {
    return redirect(uri + '/' + query(request.querystring));
  }

  return request;
}

function redirect(path) {
  return respond(301, 'Moved Permanently', { location: { value: 'https://' + HOST + path } });
}

function respond(statusCode, statusDescription, headers) {
  headers['strict-transport-security'] = { value: HSTS };
  if (NOINDEX) {
    headers['x-robots-tag'] = { value: 'noindex, nofollow' };
  }
  return { statusCode: statusCode, statusDescription: statusDescription, headers: headers };
}

// The query string as it arrived, so a redirect keeps it.
function query(querystring) {
  var parts = [];
  for (var key in querystring) {
    var entry = querystring[key];
    var values = entry.multiValue ? entry.multiValue : [entry];
    for (var i = 0; i < values.length; i++) {
      parts.push(values[i].value === '' ? key : key + '=' + values[i].value);
    }
  }
  return parts.length ? '?' + parts.join('&') : '';
}
