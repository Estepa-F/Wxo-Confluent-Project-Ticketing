# Dedicated, narrowly-scoped IAM identity for the Flink Bedrock
# connection in 03_statements_triage_agent.tf -- created here (not
# app-hosting) so this stack's AWS footprint is fully independent:
# enable_bedrock_model = false (the common case) never touches the aws
# provider or requires AWS credentials at all.
#
# Long-lived access key, not an assumed role: confirmed via `terraform
# providers schema -json` that confluent_flink_connection's BEDROCK type
# only exposes aws_access_key/aws_secret_key/aws_session_token -- no
# role-ARN/assume-role field -- so a static key is the only integration
# path.

data "aws_caller_identity" "current" {
  count = var.intelligence_enable_bedrock_model ? 1 : 0
}

resource "aws_iam_user" "bedrock_invoker" {
  count = var.intelligence_enable_bedrock_model ? 1 : 0
  name  = "${local.name_prefix}-bedrock-invoker"
  path  = "/"

  tags = {
    Purpose   = "Confluent Flink Bedrock connection - TRIAGEAGENT model"
    ManagedBy = "terraform/confluent-intelligence"
  }
}

# Scoped to Anthropic models only, and not pinned to the specific model
# ID in 03_statements_triage_agent.tf -- future model upgrades there
# don't require a policy edit here. bedrock:InvokeModel only: this
# connection's endpoint is .../invoke (non-streaming), not
# .../invoke-with-response-stream.
resource "aws_iam_user_policy" "bedrock_invoker" {
  count = var.intelligence_enable_bedrock_model ? 1 : 0
  name  = "${local.name_prefix}-bedrock-invoke"
  user  = aws_iam_user.bedrock_invoker[0].name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Region wildcarded, not pinned to local.region -- confirmed live
        # (AccessDeniedException on arn:...:us-east-2::foundation-model/...)
        # and per AWS's own Bedrock docs: a geographic cross-Region
        # inference profile (the "us."/"eu." prefix) transparently routes
        # each request to any one of several *destination* regions (e.g.
        # "us." can land on us-east-1, us-east-2, or us-west-2), and IAM
        # checks bedrock:InvokeModel against whichever underlying
        # foundation-model ARN it actually lands on, not just the
        # inference-profile's own region/ARN below. Scoping this to
        # local.region alone only works by chance, whenever a given
        # invocation happens to route back to the same region the profile
        # was created in.
        Sid      = "InvokeAnthropicFoundationModels"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "arn:aws:bedrock:*::foundation-model/anthropic.*"
      },
      {
        # Cross-region inference profiles (the eu./us./apac. prefix in
        # the model ID) additionally require permission on the profile
        # resource itself, per AWS's Bedrock IAM docs -- the
        # foundation-model grant above alone is not sufficient. The
        # account ID here is the calling account's, not Anthropic's or
        # AWS's.
        Sid      = "InvokeAnthropicInferenceProfiles"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "arn:aws:bedrock:${local.region}:${data.aws_caller_identity.current[0].account_id}:inference-profile/*.anthropic.*"
      }
    ]
  })
}

resource "aws_iam_access_key" "bedrock_invoker" {
  count      = var.intelligence_enable_bedrock_model ? 1 : 0
  user       = aws_iam_user.bedrock_invoker[0].name
  depends_on = [aws_iam_user_policy.bedrock_invoker]
}

# A freshly-created access key can have a brief IAM eventual-consistency
# delay before it's usable for signing requests -- same class of issue
# terraform/app-hosting/main.tf works around with time_sleep.iam_propagation
# for a freshly-created role, just a shorter window here (access keys
# propagate faster than roles).
resource "time_sleep" "bedrock_iam_propagation" {
  count           = var.intelligence_enable_bedrock_model ? 1 : 0
  depends_on      = [aws_iam_access_key.bedrock_invoker]
  create_duration = "10s"
}
