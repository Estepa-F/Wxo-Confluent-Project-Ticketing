output "ecr_repository_url" {
  description = "Read by deploy.py before the image exists, to build and push against a real URI."
  value       = aws_ecr_repository.app.repository_url
}

# ingress_paths' exact shape (how many entries, in what order) isn't
# confirmed from hands-on testing -- this takes the first entry as the
# app's public URL. If that's wrong once applied, print the full list
# instead (`terraform output -json` on aws_ecs_express_gateway_service.app)
# and adjust.
#
# This is the RAW Express ingress endpoint -- direct to the ALB, not
# stable across the service being recreated. Kept for debugging only;
# everything that needs a stable URL should use app_public_url instead.
output "ingress_url" {
  description = "Raw ECS Express ingress URL, direct to the ALB. Changes if the service is recreated -- for debugging only, use app_public_url instead."
  value       = try(aws_ecs_express_gateway_service.app[0].ingress_paths[0].endpoint, null)
}

output "app_public_url" {
  description = "Stable public HTTPS URL for the app, via the CloudFront distribution in cloudfront.tf. Stays fixed even if the Express service is torn down and recreated with a new ingress hostname -- this is what MCP_ALLOWED_HOSTS and confluent-intelligence's app_public_url should use."
  value       = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "admin_token" {
  value     = var.app_admin_token
  sensitive = true
}

output "mcp_password" {
  description = "Basic auth password for the app's /mcp mount -- read by confluent-intelligence's create_mcp_connection statement via terraform_remote_state."
  value       = random_password.mcp_password.result
  sensitive   = true
}
