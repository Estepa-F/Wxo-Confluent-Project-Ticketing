# RTCE itself has no Terraform resource type -- enabling it per-topic
# (on tickets.enriched, tickets.metrics, tickets.agent-actions) is a
# manual Console step (Console -> Topics -> Context Engine toggle),
# confirmed against docs.confluent.io during this project's planning.
# This mirrors the sibling project's approach exactly, and is also
# consistent with this demo's own design: the presenter already controls
# the incident/status flip manually so its timing is never automatic --
# a manual RTCE toggle isn't a new inconsistency.
#
# Terraform only provisions the querying credential: a "Global" API key,
# the exact pattern the sibling project uses for RTCE/Lightning Query
# access.
resource "confluent_api_key" "rtce" {
  count = var.intelligence_create_rtce_key ? 1 : 0

  display_name = "${local.name_prefix}-rtce-key"
  description  = "Global API key for RTCE / watsonx Orchestrate's MCP access to tickets.enriched, tickets.metrics, tickets.agent-actions."

  owner {
    id          = local.service_account_id
    api_version = local.service_account_api_version
    kind        = local.service_account_kind
  }

  managed_resource {
    id          = "global"
    api_version = "global/v1"
    kind        = "Global"
  }
}

variable "intelligence_create_rtce_key" {
  description = "Create the Global API key for RTCE. Needs OrganizationAdmin; set false with EnvironmentAdmin only."
  type        = bool
  default     = true
}
