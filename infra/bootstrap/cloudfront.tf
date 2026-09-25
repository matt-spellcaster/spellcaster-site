# Shared by the QA and production distributions, and kept here so CI can't change them.

# CloudFront signs every request to the site buckets; the buckets allow only that.
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "portfolio-s3"
  description                       = "CloudFront to the private site buckets (QA and production)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  # Nothing on the site uses these browser features, so no page (or anything injected into
  # one) may ask for them.
  permissions_policy = join(", ", [
    "accelerometer=()", "browsing-topics=()", "camera=()", "display-capture=()",
    "geolocation=()", "gyroscope=()", "magnetometer=()", "microphone=()",
    "payment=()", "usb=()",
  ])
}

# The same security headers on both sites, plus noindex on QA. The page CSP is Astro's <meta>
# tag, with a hash for every inline script and style in each build; only frame-ancestors has
# to come from a header, because browsers ignore it in <meta>.
resource "aws_cloudfront_response_headers_policy" "site" {
  for_each = local.environments

  name    = "portfolio-${each.key}-headers"
  comment = each.key == "qa" ? "Security headers, plus noindex" : "Security headers"

  security_headers_config {
    # Copies of this value must change with it: infra/modules/site/viewer-request.js (for the
    # function's own redirects) and its test, and SECURITY_HEADERS in scripts/ci/smoke.py.
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true # harmless: .foo is on the preload list as a whole
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    content_security_policy {
      content_security_policy = "frame-ancestors 'none'"
      override                = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = local.permissions_policy
      override = true
    }
    dynamic "items" {
      for_each = each.key == "qa" ? ["noindex, nofollow"] : []
      content {
        header   = "X-Robots-Tag"
        value    = items.value
        override = true
      }
    }
  }
}
