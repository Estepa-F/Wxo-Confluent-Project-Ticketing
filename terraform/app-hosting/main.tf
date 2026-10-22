# Amazon ECS Express Mode: one aws_ecs_express_gateway_service gives us a
# Fargate service + ALB + TLS + target group + networking, from just a
# container image and two IAM roles -- see PROJECT plan for why this was
# chosen over a plain aws_ecs_service (the app needs real HTTPS, unlike
# the sibling project's outbound-only ECS task).
#
# Bootstrap order (see deploy.py): (1) `terraform apply
# -target=aws_ecr_repository.app` creates just the registry so the image
# can be built and pushed against a real URI, (2) a full apply with
# var.app_image_uri set creates the service, (3) a second full apply
# with the now-known ingress hostname sets MCP_ALLOWED_HOSTS correctly.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ECS Express Mode's CreateExpressGatewayService API rejects more than
# one subnet per Availability Zone (confirmed live: "Only one subnet per
# Availability zone is allowed") -- the default VPC here has more than
# one subnet in at least one AZ, so dedupe down to one per AZ.
data "aws_subnet" "default" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
}

# "In the default VPC" is NOT a safe proxy for "internet-routable" in
# this account: confirmed live that this default VPC has a second route
# table (no Internet Gateway route, used by other isolated workloads)
# alongside the real public one, with one subnet per AZ on each. Express
# Mode correctly refused to assign task ENIs a public IP on the
# non-routable ones, so tasks timed out pulling from ECR. Filter to
# subnets whose route table actually has an IGW route, rather than
# assuming every default-VPC subnet is public.
#
# aws_route_table's `subnet_id` filter only matches EXPLICIT
# associations (confirmed live: errors with "no matching Route Table
# found" for subnets that rely on the VPC's implicit main table) -- so
# fetch every route table in the VPC by ID instead, and resolve each
# subnet to its table (explicit association, falling back to main) in
# locals below.
data "aws_route_tables" "all" {
  vpc_id = data.aws_vpc.default.id
}

data "aws_route_table" "by_id" {
  for_each       = toset(data.aws_route_tables.all.ids)
  route_table_id = each.value
}

data "terraform_remote_state" "base" {
  backend = "local"

  config = {
    path = "../base/terraform.tfstate"
  }
}

locals {
  name_prefix = data.terraform_remote_state.base.outputs.name_prefix
  app_env     = data.terraform_remote_state.base.outputs.app_env

  main_route_table_id = one([
    for rt in data.aws_route_table.by_id : rt.route_table_id
    if anytrue([for a in rt.associations : a.main])
  ])

  # subnet_id -> its explicitly-associated route table id (subnets with
  # no explicit association -- i.e. governed by the VPC's implicit main
  # table -- just won't appear as a key here).
  explicit_route_table_by_subnet = merge([
    for rt in data.aws_route_table.by_id : {
      for a in rt.associations : a.subnet_id => rt.route_table_id
      if a.subnet_id != null && a.subnet_id != ""
    }
  ]...)

  route_table_id_by_subnet = {
    for id in data.aws_subnets.default.ids :
    id => lookup(local.explicit_route_table_by_subnet, id, local.main_route_table_id)
  }

  # Subnets whose resolved route table has a route to an Internet
  # Gateway -- gateway_id is "" (empty string, not null) for non-IGW
  # routes (e.g. NAT/peering); startswith("", "igw-") is safely false,
  # no coalesce() needed (and coalesce("", "") itself errors -- learned
  # that live).
  public_subnet_ids = [
    for id in data.aws_subnets.default.ids : id
    if anytrue([
      for r in data.aws_route_table.by_id[local.route_table_id_by_subnet[id]].routes :
      startswith(r.gateway_id, "igw-")
    ])
  ]

  # One subnet ID per AZ, from the internet-routable ones only. Current
  # Terraform rejects a `for`-expression map with duplicate keys outright
  # unless grouped with `...` (no more silent last-value-wins) --
  # confirmed live -- so group into lists per AZ, then take the first
  # subnet from each.
  subnet_ids_by_az = {
    for s in data.aws_subnet.default : s.availability_zone => s.id...
    if contains(local.public_subnet_ids, s.id)
  }
  subnet_ids = [for ids in local.subnet_ids_by_az : ids[0]]

  # confluent_kafka_cluster.bootstrap_endpoint (and therefore app_env's
  # CC_BOOTSTRAP_SERVERS) comes back as "SASL_SSL://host:port" --
  # confluent-kafka's bootstrap.servers wants bare host:port. Same fix
  # as deploy.py's strip_protocol_scheme(), done in HCL here since this
  # container's env vars are set directly by Terraform, not via
  # app/.env.
  bootstrap_raw          = local.app_env["CC_BOOTSTRAP_SERVERS"]
  bootstrap_servers_bare = length(split("://", local.bootstrap_raw)) > 1 ? split("://", local.bootstrap_raw)[1] : local.bootstrap_raw

  container_env = merge(
    local.app_env,
    {
      CC_BOOTSTRAP_SERVERS = local.bootstrap_servers_bare
      ACCOUNT_POOL_SIZE    = tostring(var.account_pool_size)
      MATCH_THRESHOLD      = tostring(var.match_threshold)
      PORT                 = "8000"
      # The deployed instance is the one that should run baseline
      # traffic -- local dev copies run with ENABLE_GENERATOR=false to
      # avoid double baseline traffic (see support_portal/main.py).
      ENABLE_GENERATOR  = "true"
      GENERATOR_RATE    = tostring(var.generator_rate)
      ADMIN_TOKEN       = var.app_admin_token
      MCP_ALLOWED_HOSTS = var.app_mcp_allowed_hosts
      MCP_USERNAME      = "flink-agent"
      MCP_PASSWORD      = random_password.mcp_password.result
    },
    # watsonx Orchestrate escalation-agent drafts (support_portal/orchestrate):
    # only passed when configured, so the feature stays off by default.
    var.wxo_instance_url == "" ? {} : {
      WXO_INSTANCE_URL      = var.wxo_instance_url
      WXO_API_KEY           = var.wxo_api_key
      WXO_AGENT_ID          = var.wxo_agent_id
      WXO_IAM_URL           = var.wxo_iam_url
      WXO_INCLUDE_SYNTHETIC = tostring(var.wxo_include_synthetic)
    }
  )
}

# Basic auth credential for the app's /mcp mount, used by confluent-
# intelligence's portal_mcp_connection. Generated here (not by deploy.py
# like app_admin_token) so it lives entirely in this stack's state and
# stays stable across reapplies -- random_password only regenerates if
# tainted or its own arguments change, never as a side effect of
# unrelated applies.
resource "random_password" "mcp_password" {
  length  = 24
  special = false
}

resource "aws_ecr_repository" "app" {
  name         = "${local.name_prefix}-support-portal"
  force_delete = true
}

resource "aws_iam_role" "execution" {
  name = "${local.name_prefix}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "infrastructure" {
  name = "${local.name_prefix}-ecs-infrastructure"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowAccessInfrastructureForECSExpressServices"
      Effect    = "Allow"
      Principal = { Service = "ecs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "infrastructure" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

# AWS's own docs warn a freshly-created role can fail with "Unable to
# assume the service linked role" for about a minute after creation --
# same class of eventual-consistency issue the sibling project works
# around with time_sleep elsewhere.
resource "time_sleep" "iam_propagation" {
  depends_on = [
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy_attachment.infrastructure,
  ]

  create_duration = "20s"
}

resource "aws_ecs_express_gateway_service" "app" {
  # Empty on the first bootstrap pass (deploy.py hasn't built/pushed the
  # image yet) -- count=0 means this resource simply doesn't exist yet,
  # so referencing it (see local.ingress_hostname below) from the
  # CloudFront distribution's `-target`ed first apply doesn't force it
  # into existence with a blank image. See cloudfront.tf.
  count = var.app_image_uri != "" ? 1 : 0

  service_name = "${local.name_prefix}-support-portal"

  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn

  health_check_path     = "/status"
  wait_for_steady_state = true

  network_configuration {
    subnets = local.subnet_ids
  }

  primary_container {
    image          = var.app_image_uri
    container_port = 8000

    dynamic "environment" {
      for_each = local.container_env
      content {
        name  = environment.key
        value = environment.value
      }
    }
  }

  depends_on = [time_sleep.iam_propagation]
}
