output "flink_compute_pool_id" {
  value = confluent_flink_compute_pool.main.id
}

output "flink_rest_endpoint" {
  value = data.confluent_flink_region.main.rest_endpoint
}

output "rtce_api_key" {
  value     = try(confluent_api_key.rtce[0].id, "")
  sensitive = true
}

output "rtce_api_secret" {
  value     = try(confluent_api_key.rtce[0].secret, "")
  sensitive = true
}

# Endpoint format per docs.confluent.io/cloud/current/ai/real-time-context-engine/get-started.html.
# Confirm against the Console's "Copy topic details to clipboard" action
# (Topics -> Context engine column -> Details) before wiring into
# watsonx Orchestrate -- this composes the same value from Terraform
# state so it doesn't need copy-pasting by hand.
output "rtce_mcp_endpoint" {
  description = "RTCE MCP endpoint for tickets.enriched/tickets.metrics/tickets.agent-actions, for watsonx Orchestrate's MCP connection."
  value       = "https://mcp.${local.region}.aws.confluent.cloud/mcp/v1/context-engine/organizations/${data.confluent_organization.main.id}/environments/${local.environment_id}/kafka-clusters/${local.cluster_id}"
}

# RTCE authenticates over HTTP Basic auth: base64("<api_key>:<api_secret>").
# Precomputed here so it can go straight into an
# "Authorization: Basic <token>" header without a manual base64 step.
output "rtce_basic_auth_token" {
  value     = try(base64encode("${confluent_api_key.rtce[0].id}:${confluent_api_key.rtce[0].secret}"), "")
  sensitive = true
}

output "triage_agent_statement_id" {
  description = "Only set when enable_agent = true."
  value       = var.intelligence_enable_agent ? confluent_flink_statement.create_triage_agent[0].id : null
}

output "resolved_app_public_url" {
  description = "The app_public_url actually used for the MCP connection (manual override if set, else app-hosting's ingress_url, else empty)."
  value       = local.app_public_url
}

output "bedrock_iam_user_name" {
  description = "Name of the dedicated IAM user Terraform creates for the Bedrock Flink connection. Only set when enable_bedrock_model = true."
  value       = var.intelligence_enable_bedrock_model ? aws_iam_user.bedrock_invoker[0].name : null
}

output "bedrock_iam_user_arn" {
  description = "ARN of the dedicated Bedrock IAM user, for audit/reference. Only set when enable_bedrock_model = true."
  value       = var.intelligence_enable_bedrock_model ? aws_iam_user.bedrock_invoker[0].arn : null
}

output "bedrock_iam_access_key_id" {
  description = "Access key ID for the dedicated Bedrock IAM user. Not secret on its own."
  value       = var.intelligence_enable_bedrock_model ? aws_iam_access_key.bedrock_invoker[0].id : null
}

# For a one-off `aws bedrock-runtime invoke-model` smoke test only --
# fetch with `terraform output -raw bedrock_iam_access_key_secret`, use
# once, never persist to a file.
output "bedrock_iam_access_key_secret" {
  description = "Secret access key for the dedicated Bedrock IAM user -- manual verification only."
  value       = var.intelligence_enable_bedrock_model ? aws_iam_access_key.bedrock_invoker[0].secret : null
  sensitive   = true
}
