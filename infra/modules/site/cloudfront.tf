# The distribution in front of the bucket. The origin access control, the header policies and
# the certificate all come from bootstrap, so CI can't change any of them. Every resource here
# carries the provider's Environment tag, which is what lets this environment's CI role
# manage it (infra/bootstrap/ci_roles.tf).

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_function" "viewer_request" {
  name    = "portfolio-${var.environment}-viewer-request"
  runtime = "cloudfront-js-2.0"
  comment = "One host name, index.html for folders, a slash on every page URL"
  publish = true
  code    = templatefile("${path.module}/viewer-request.js", { host = var.domain })
}

resource "aws_cloudfront_distribution" "site" {
  # checkov:skip=CKV2_AWS_32:It has one: response_headers_policy_id below, bootstrap's policy passed in by each root. Checkov can't follow the value through a module input.
  comment             = "portfolio ${var.environment}: ${var.domain}"
  enabled             = true
  aliases             = var.aliases
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = "PriceClass_100" # North America and Europe: the cheapest, and enough

  origin {
    origin_id                = "site-bucket"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = var.origin_access_control_id
  }

  default_cache_behavior {
    target_origin_id           = "site-bucket"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = var.response_headers_policy_id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_request.arn
    }
  }

  # The site's own 404 page, with a 404 status. S3 answers 404 for a missing file (the bucket
  # policy lets CloudFront list it); a 403 would mean something else is wrong, and still
  # shouldn't show S3's XML to a visitor.
  dynamic "custom_error_response" {
    for_each = [403, 404]
    content {
      error_code            = custom_error_response.value
      response_code         = 404
      response_page_path    = "/404.html"
      error_caching_min_ttl = 60
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2025" # the provider's default is TLSv1
  }
}
