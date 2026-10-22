variable "app_image_uri" {
  description = "Full ECR image URI (repo:tag) to deploy. Empty on the first apply pass (deploy.py creates the ECR repo before this is known); required once the image has been built and pushed."
  type        = string
  default     = ""
}

variable "app_admin_token" {
  description = "Shared secret for the app's /admin/* routes (dashboard controls, Support Admin) -- generated once by deploy.py and persisted in credentials.env, so it stays stable across redeploys."
  type        = string
  sensitive   = true
}

variable "app_mcp_allowed_hosts" {
  description = "Comma-separated Host header allowlist for the app's MCP endpoint (mcp 2.x DNS-rebinding protection). Left at the app's own safe default on the first apply pass; deploy.py re-applies with the real ingress hostname once known."
  type        = string
  default     = "localhost:*,127.0.0.1:*"
}

variable "account_pool_size" {
  type    = number
  default = 250
}

variable "match_threshold" {
  type    = number
  default = 50
}

variable "generator_rate" {
  type    = number
  default = 0.5
}

variable "wxo_instance_url" {
  description = "watsonx Orchestrate instance URL (orchestrate env list), e.g. https://api.eu-de.watson-orchestrate.cloud.ibm.com/instances/<id>. Empty = AI reply drafts disabled."
  type        = string
  default     = ""
}

variable "wxo_api_key" {
  description = "IBM Cloud API key allowed to call the Orchestrate instance."
  type        = string
  default     = ""
  sensitive   = true
}

variable "wxo_agent_id" {
  description = "ID of the Orchestrate escalation_agent."
  type        = string
  default     = ""
}

variable "wxo_iam_url" {
  description = "IAM token endpoint used to exchange wxo_api_key for a bearer token."
  type        = string
  default     = "https://iam.cloud.ibm.com/identity/token"
}

variable "wxo_include_synthetic" {
  description = "Also draft replies for synthetic (generator) tickets. Each draft calls the AWS goodwill agent: keep false on a budget."
  type        = bool
  default     = false
}
