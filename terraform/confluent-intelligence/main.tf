# Reads the base phase's state directly (both phases use local state) so
# IDs, keys, and the name prefix never need manual copy/paste between
# `terraform apply` runs in the two directories. Also reads app-hosting's
# state to auto-derive app_public_url below, once that phase exists.
data "terraform_remote_state" "base" {
  backend = "local"

  config = {
    path = "../base/terraform.tfstate"
  }
}

data "terraform_remote_state" "app_hosting" {
  backend = "local"

  config = {
    path = "../app-hosting/terraform.tfstate"
  }
}

locals {
  name_prefix                 = data.terraform_remote_state.base.outputs.name_prefix
  region                      = data.terraform_remote_state.base.outputs.region
  environment_id              = data.terraform_remote_state.base.outputs.environment_id
  environment_resource_name   = data.terraform_remote_state.base.outputs.environment_resource_name
  environment_display_name    = data.terraform_remote_state.base.outputs.environment_display_name
  cluster_display_name        = data.terraform_remote_state.base.outputs.cluster_display_name
  cluster_id                  = data.terraform_remote_state.base.outputs.cluster_id
  service_account_id          = data.terraform_remote_state.base.outputs.service_account_id
  service_account_api_version = data.terraform_remote_state.base.outputs.service_account_api_version
  service_account_kind        = data.terraform_remote_state.base.outputs.service_account_kind

  # Auto-wired from app-hosting's app_public_url (the stable CloudFront
  # domain, not the raw/unstable Express ingress hostname -- see
  # terraform/app-hosting/cloudfront.tf) once that phase has been
  # applied. try() is required (not just style): terraform_remote_state
  # against a local backend whose target file doesn't exist yet returns
  # an *empty* outputs map rather than erroring, so referencing
  # `.outputs.app_public_url` directly on a fresh checkout (app-hosting
  # not yet applied) would fail with "this object does not have an
  # attribute named app_public_url". var.app_public_url remains available
  # as a manual override, e.g. for testing against an app hosted
  # elsewhere.
  app_hosting_public_url = try(data.terraform_remote_state.app_hosting.outputs.app_public_url, null)
  app_public_url         = var.app_public_url != "" ? var.app_public_url : coalesce(local.app_hosting_public_url, "")

  # Basic auth password for portal_mcp_connection -- Terraform-generated
  # in app-hosting (random_password.mcp_password) and read here the same
  # way app_public_url is, via terraform_remote_state.
  mcp_password = try(data.terraform_remote_state.app_hosting.outputs.mcp_password, null)

  # Shared by every confluent_flink_statement in this phase.
  flink_statement_context = {
    compute_pool_id = confluent_flink_compute_pool.main.id
    principal_id    = local.service_account_id
    rest_endpoint   = data.confluent_flink_region.main.rest_endpoint
    api_key         = confluent_api_key.app_flink.id
    api_secret      = confluent_api_key.app_flink.secret
    organization_id = data.confluent_organization.main.id
    properties = {
      "sql.current-catalog"  = local.environment_display_name
      "sql.current-database" = local.cluster_display_name
    }
  }

  # statement_name only allows lowercase alphanumeric + hyphens (confirmed
  # against docs.confluent.io) -- same class of constraint already worked
  # around for confluent_flink_connection.display_name elsewhere in this
  # phase (see bedrock_textgen_connection in 03_statements_triage_agent.tf).
  flink_name_prefix = replace(local.name_prefix, "_", "-")
}

# One shared suffix appended to every confluent_flink_statement's
# statement_name in this phase, so a human-readable name never collides
# with a stale, not-yet-dropped statement of the same name still
# registered in Confluent Cloud's catalog -- the same class of
# "already exists in catalog" issue this phase's own comments already
# document for portal_mcp_connection.
resource "random_id" "flink_statement_suffix" {
  byte_length = 4
}

data "confluent_organization" "main" {}

resource "confluent_flink_compute_pool" "main" {
  display_name = "${local.name_prefix}-flink-pool"
  cloud        = "AWS"
  region       = local.region
  max_cfu      = var.intelligence_flink_max_cfu

  environment {
    id = local.environment_id
  }
}

data "confluent_flink_region" "main" {
  cloud  = "AWS"
  region = local.region
}

# Confluent's documented prerequisite for Flink compute pool access,
# connection creation, and agent operations -- reuses the app service
# account from the platform phase (it already has CloudClusterAdmin on
# the cluster) rather than creating a second identity.
resource "confluent_role_binding" "app_flink_developer" {
  principal   = "User:${local.service_account_id}"
  role_name   = "FlinkDeveloper"
  crn_pattern = local.environment_resource_name
}

resource "confluent_api_key" "app_flink" {
  display_name = "${local.name_prefix}-flink-key"
  description  = "Flink API key for the ticket enrichment/metrics statements and the TRIAGEAGENT."

  owner {
    id          = local.service_account_id
    api_version = local.service_account_api_version
    kind        = local.service_account_kind
  }

  managed_resource {
    id          = data.confluent_flink_region.main.id
    api_version = data.confluent_flink_region.main.api_version
    kind        = data.confluent_flink_region.main.kind

    environment {
      id = local.environment_id
    }
  }

  depends_on = [confluent_role_binding.app_flink_developer]
}
