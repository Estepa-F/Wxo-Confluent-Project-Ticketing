terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    # For the IAM-propagation delay below -- same pattern the sibling
    # project uses for its own async-consistency workarounds.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
    # Generates the MCP Basic auth password (see random_password.mcp_password
    # in main.tf) -- Terraform-generated rather than deploy.py-generated like
    # app_admin_token, so it stays entirely within this stack's state.
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
