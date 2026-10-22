# CloudFront in front of the ECS Express service, purely to get a public
# hostname that stays fixed even when the Express service (and therefore
# its own auto-generated *.ecs.<region>.on.aws ingress hostname) is torn
# down and recreated. CloudFront allocates its *.cloudfront.net domain
# once, at creation, and updating a distribution's origin afterwards is
# an in-place update, not a replacement.
#
# Bootstrap ordering (see deploy.py): this distribution is created in the
# FIRST apply pass (targeted, alongside the ECR repo), before the Express
# service exists at all (count=0, see main.tf), pointed at a placeholder
# origin. That's what makes app_public_url (outputs.tf) knowable before
# the Express service's first-ever creation. The second apply pass
# creates the Express service for real and, in the same apply, flips
# this distribution's origin from the placeholder to the now-known real
# ingress hostname.
#
# CONFIRMED LIVE: Express Mode's ALB routes purely on Host header,
# matching only the exact *.ecs.<region>.on.aws hostname it was created
# with (it supports multiple Express services sharing one ALB this way).
# Forwarding the viewer's own Host header (the CloudFront domain) to the
# origin -- e.g. via the Managed-AllViewer origin request policy --
# doesn't match that rule and the ALB's default action returns a bare
# "Not Found". Managed-AllViewerExceptHostHeader forwards everything else
# unchanged but leaves Host alone, so CloudFront falls back to its
# default behavior of sending the origin's own domain_name as Host --
# which is exactly the hostname the ALB's rule expects.
locals {
  ingress_endpoint_raw = try(aws_ecs_express_gateway_service.app[0].ingress_paths[0].endpoint, null)
  ingress_hostname = local.ingress_endpoint_raw != null ? (
    length(split("://", local.ingress_endpoint_raw)) > 1
    ? split("://", local.ingress_endpoint_raw)[1]
    : local.ingress_endpoint_raw
  ) : "placeholder.invalid.example"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "app" {
  enabled = true

  # Skip waiting for global propagation (~15+ min) -- domain_name is
  # allocated synchronously on creation, which is all deploy.py needs.
  wait_for_deployment = false

  origin {
    domain_name = local.ingress_hostname
    origin_id   = "express-app"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "express-app"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]

    # CachingDisabled + AllViewerExceptHostHeader: a transparent proxy,
    # not a CDN cache -- this is a dynamic app (admin console, /mcp,
    # generator), not static assets. See the Host-header note above for
    # why Host itself is excluded from forwarding.
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
