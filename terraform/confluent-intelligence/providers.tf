provider "confluent" {
  cloud_api_key    = var.confluent_cloud_api_key
  cloud_api_secret = var.confluent_cloud_api_secret
}

# Only touched when enable_bedrock_model = true (see bedrock_iam.tf).
# Standard AWS credential resolution (AWS_PROFILE, or AWS_ACCESS_KEY_ID/
# AWS_SECRET_ACCESS_KEY, + AWS_REGION) from the environment -- deploy.py
# exports these from credentials.env, the same ones already required for
# --stage app. Deliberately independent from app-hosting's provider.
provider "aws" {}
