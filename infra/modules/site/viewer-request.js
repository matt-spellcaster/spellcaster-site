// CloudFront viewer-request function (runtime cloudfront-js-2.0), rendered by Terraform's
// templatefile() with the site's one name. It runs on every request, before the cache.
var HOST = '${host}';
// The same as bootstrap's header policy, which doesn't reach a function's own responses.
var HSTS = 'max-age=31536000; includeSubDomains; preload';

function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var host = request.headers.host ? request.headers.host.value.toLowerCase() : '';

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
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: {
      location: { value: 'https://' + HOST + path },
      'strict-transport-security': { value: HSTS }
    }
  };
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
