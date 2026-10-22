output "name_prefix" {
  description = "Passed through so the confluent-intelligence phase names its resources consistently without re-specifying this."
  value       = var.name_prefix
}

output "region" {
  description = "Passed through so the confluent-intelligence phase's Flink compute pool lands in the same AWS region as the cluster, without re-specifying it."
  value       = var.region
}

output "environment_id" {
  value = local.environment.id
}

output "environment_resource_name" {
  description = "The environment's CRN, for role bindings scoped at the environment level (e.g. FlinkDeveloper, added in the confluent-intelligence phase)."
  value       = local.environment.resource_name
}

output "environment_display_name" {
  description = "Used as Flink SQL's sql.current-catalog in the confluent-intelligence phase."
  value       = local.environment.display_name
}

output "cluster_display_name" {
  description = "Used as Flink SQL's sql.current-database in the confluent-intelligence phase."
  value       = confluent_kafka_cluster.main.display_name
}

output "service_account_id" {
  description = "The app service account's id, reused as the principal for Flink statements/connections in the confluent-intelligence phase instead of creating a second service account."
  value       = confluent_service_account.app.id
}

output "service_account_api_version" {
  value = confluent_service_account.app.api_version
}

output "service_account_kind" {
  value = confluent_service_account.app.kind
}

output "cluster_id" {
  value = confluent_kafka_cluster.main.id
}

output "cluster_rest_endpoint" {
  value = confluent_kafka_cluster.main.rest_endpoint
}

output "bootstrap_servers" {
  value = confluent_kafka_cluster.main.bootstrap_endpoint
}

output "kafka_api_key" {
  value     = confluent_api_key.app_kafka.id
  sensitive = true
}

output "kafka_api_secret" {
  value     = confluent_api_key.app_kafka.secret
  sensitive = true
}

output "schema_registry_id" {
  value = data.confluent_schema_registry_cluster.main.id
}

output "schema_registry_url" {
  value = data.confluent_schema_registry_cluster.main.rest_endpoint
}

output "schema_registry_api_key" {
  value     = confluent_api_key.app_schema_registry.id
  sensitive = true
}

output "schema_registry_api_secret" {
  value     = confluent_api_key.app_schema_registry.secret
  sensitive = true
}

# Matches app/.env.example 1:1 -- `terraform output -json app_env` maps
# directly onto app/.env without Terraform writing into app/ itself.
output "app_env" {
  description = "Values matching app/.env.example, for populating app/.env by hand."
  sensitive   = true
  value = {
    CC_BOOTSTRAP_SERVERS          = confluent_kafka_cluster.main.bootstrap_endpoint
    CC_API_KEY                    = confluent_api_key.app_kafka.id
    CC_API_SECRET                 = confluent_api_key.app_kafka.secret
    CC_SECURITY_PROTOCOL          = "SASL_SSL"
    CC_SASL_MECHANISMS            = "PLAIN"
    CC_SCHEMA_REGISTRY_URL        = data.confluent_schema_registry_cluster.main.rest_endpoint
    CC_SCHEMA_REGISTRY_API_KEY    = confluent_api_key.app_schema_registry.id
    CC_SCHEMA_REGISTRY_API_SECRET = confluent_api_key.app_schema_registry.secret
  }
}
