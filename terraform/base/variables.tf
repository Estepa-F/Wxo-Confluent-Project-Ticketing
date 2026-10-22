variable "confluent_cloud_api_key" {
  description = "Confluent Cloud organization-level API key Terraform authenticates with. Set via TF_VAR_confluent_cloud_api_key, never committed."
  type        = string
  sensitive   = true
}

variable "confluent_cloud_api_secret" {
  description = "Confluent Cloud organization-level API secret Terraform authenticates with. Set via TF_VAR_confluent_cloud_api_secret, never committed."
  type        = string
  sensitive   = true
}

variable "name_prefix" {
  description = "Prefix applied to every Confluent Cloud resource name this project creates, so the same Terraform can be re-applied under a different name without edits."
  type        = string
  default     = "dswt2026"

  validation {
    condition     = can(regex("^[a-z0-9-_]{1,20}$", var.name_prefix))
    error_message = "name_prefix must be lowercase alphanumeric/hyphen/underscore, 1-20 characters."
  }
}

variable "region" {
  description = "AWS region for the Kafka cluster. Must be an AWS region, since RTCE (provisioned in the confluent-intelligence phase) is AWS-only."
  type        = string
  default     = "eu-west-1"
}

variable "existing_environment_id" {
  description = "Optional. ID (env-xxxxx) of an existing Confluent Cloud environment to deploy into instead of creating one. Leave empty to create a dedicated environment (needs OrganizationAdmin)."
  type        = string
  default     = ""
}
