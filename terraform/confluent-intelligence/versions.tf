terraform {
  required_version = ">= 1.3.0"

  required_providers {
    confluent = {
      source  = "confluentinc/confluent"
      version = ">= 2.73, < 3.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    # For time_sleep.bedrock_iam_propagation in bedrock_iam.tf.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
    # For random_id.flink_statement_suffix in main.tf (same provider
    # terraform/app-hosting already uses for random_password.mcp_password).
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
