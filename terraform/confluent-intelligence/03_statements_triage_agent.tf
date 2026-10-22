# Single TRIAGEAGENT (PROJECT_SPEC.md section 2.5, simplified from four
# chained agents to one -- Confluent Streaming Agents has no native
# agent-to-agent handoff/branching primitive, confirmed during planning).
#
# Two independent gates:
#   - var.intelligence_enable_bedrock_model provisions just the Bedrock connection +
#     CREATE MODEL below, so that piece can be stood up and verified on
#     its own.
#   - var.intelligence_enable_agent provisions the rest of the pipeline (UDF, MCP
#     connection, tools, CREATE AGENT, run_triage_agent) and additionally
#     requires enable_bedrock_model = true plus the deployed app's public
#     URL and the check_status UDF JAR.
#
# IMPORTANT -- everything in this file is more speculative than the rest
# of this Terraform and MUST be re-verified against
# registry.terraform.io/providers/confluentinc/confluent/latest/docs and
# docs.confluent.io before applying with enable_agent = true:
#   - The installed provider (2.86.0) has NO confluent_flink_agent or
#     confluent_flink_tool resource type (checked via `terraform
#     providers schema -json`) -- CREATE TOOL/CREATE AGENT/CREATE
#     FUNCTION are run as raw SQL via confluent_flink_statement.
#   - A native confluent_flink_connection resource DOES exist, but its
#     schema (type/endpoint/credentials/api_key/username/password/aws_*)
#     has no field for the 'transport-type' WITH-option the MCP
#     connection needs -- so CREATE CONNECTION is also raw SQL here
#     rather than that native resource, deliberately.
#   - The confluent-artifact:// URI format in CREATE FUNCTION below is
#     an educated guess at the reference syntax, not a confirmed one.
#   - AI_RUN_AGENT's exact lateral-join column shape is not confirmed.
#   - The Bedrock connection/model below follows the pattern from
#     github.com/confluentinc/demo-confluent-intelligence-f1
#     (terraform/aws/main.tf's bedrock_textgen_connection + llm_textgen_model).
#     The reference repo defaults to us-east-1 and uses the `us.` cross-
#     region inference profile; this project has run in both eu-west-1
#     (`eu.` prefix) and us-east-1 (`us.` prefix) -- both confirmed live
#     via `aws bedrock list-inference-profiles` + a direct bedrock-runtime
#     invoke-model call against this account/region. local.bedrock_
#     inference_profile_prefix below maps region -> prefix; if var.region
#     is ever set to something outside that map, re-confirm the prefix
#     live before adding it (AWS's own geography-prefix convention isn't
#     a reliable guess -- e.g. APAC profiles use `apac.`, not `ap.`).
#     CREATE MODEL's exact syntax is still otherwise unconfirmed against
#     current docs.confluent.io.

locals {
  bedrock_inference_profile_prefix = {
    "eu-west-1" = "eu"
    "us-east-1" = "us"
  }[local.region]
}

resource "confluent_flink_connection" "bedrock_textgen_connection" {
  count = var.intelligence_enable_bedrock_model ? 1 : 0

  # Unlike other display_names in this project, confluent_flink_connection
  # rejects underscores ("name needs to contain lowercase alphanumeric
  # characters and hyphens only") -- confirmed live -- so name_prefix (which
  # allows underscores, e.g. "dpetisme_dswt2026") needs sanitizing here.
  display_name = "${replace(local.name_prefix, "_", "-")}-triage-agent-llm-connection"
  type         = "BEDROCK"
  endpoint     = "https://bedrock-runtime.${local.region}.amazonaws.com/model/${local.bedrock_inference_profile_prefix}.anthropic.claude-sonnet-4-5-20250929-v1:0/invoke"

  aws_access_key = aws_iam_access_key.bedrock_invoker[0].id
  aws_secret_key = aws_iam_access_key.bedrock_invoker[0].secret
  # No aws_session_token: bedrock_iam.tf creates a permanent IAM user
  # key, not an STS token -- there's no temporary-credential case to
  # support.

  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [time_sleep.bedrock_iam_propagation]
}

resource "confluent_flink_statement" "create_triage_agent_model" {
  count = var.intelligence_enable_bedrock_model ? 1 : 0

  statement = <<-SQL
    CREATE MODEL `triage_agent_model`
    INPUT (prompt STRING)
    OUTPUT (response STRING)
    WITH (
      'provider' = 'bedrock',
      'task' = 'text_generation',
      'bedrock.connection' = '${confluent_flink_connection.bedrock_textgen_connection[0].display_name}',
      'bedrock.params.max_tokens' = '50000'
    );
  SQL

  statement_name = "${local.flink_name_prefix}-triage-agent-model-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [confluent_flink_connection.bedrock_textgen_connection]
}

# Commented out along with check_status_tool below -- the streaming agent
# relies only on the MCP tools for now, and no UDF JAR has been built
# (var.udf_jar_path/flink_udf_class_name are unset).
# resource "confluent_flink_artifact" "check_status_udf" {
#   count = var.intelligence_enable_agent ? 1 : 0
#
#   display_name     = "${local.name_prefix}-check-status-udf"
#   cloud            = "AWS"
#   region           = local.region
#   artifact_file    = var.udf_jar_path
#   content_format   = "JAR"
#   runtime_language = "JAVA"
#
#   environment {
#     id = local.environment_id
#   }
# }
#
# resource "confluent_flink_statement" "create_check_status_function" {
#   count = var.intelligence_enable_agent ? 1 : 0
#
#   statement = <<-SQL
#     CREATE FUNCTION check_status
#     AS '${var.flink_udf_class_name}'
#     USING JAR 'confluent-artifact://${confluent_flink_artifact.check_status_udf[0].id}';
#   SQL
#
#   properties = local.flink_statement_context.properties
#   compute_pool { id = local.flink_statement_context.compute_pool_id }
#   principal { id = local.flink_statement_context.principal_id }
#   rest_endpoint = local.flink_statement_context.rest_endpoint
#   credentials {
#     key    = local.flink_statement_context.api_key
#     secret = local.flink_statement_context.api_secret
#   }
#   organization { id = local.flink_statement_context.organization_id }
#   environment { id = local.environment_id }
# }

resource "confluent_flink_statement" "create_mcp_connection" {
  count = var.intelligence_enable_agent ? 1 : 0

  # The support_portal app's MCP mount now requires real HTTP Basic auth
  # (app/support_portal/main.py's MCPBasicAuthMiddleware) -- username is
  # fixed ("flink-agent"), password is Terraform-generated in
  # terraform/app-hosting (random_password.mcp_password) and read here
  # via local.mcp_password (main.tf's terraform_remote_state wiring).
  #
  # Confirmed live this session: two of Confluent's four supported
  # mcp_server auth methods (api-key, token) were rejected identically
  # and client-side (never even reaching this app, confirmed via
  # request logging) with a placeholder credential -- Basic auth with a
  # real, checkable credential is the last untested combination.
  #
  # IF NOT EXISTS matters here: destroying this confluent_flink_statement
  # resource only deletes the Terraform-tracked *statement*, it does not
  # run DROP CONNECTION against the Flink catalog -- confirmed live (a
  # taint-triggered replace failed with "Connection portal_mcp_connection
  # already exists in catalog" until the orphaned object was dropped by
  # hand). Without IF NOT EXISTS, any future taint/replace of this
  # resource fails the same way.
  statement = <<-SQL
    CREATE CONNECTION IF NOT EXISTS portal_mcp_connection WITH (
      'type' = 'mcp_server',
      'endpoint' = '${local.app_public_url}/mcp',
      'transport-type' = 'STREAMABLE_HTTP',
      'username' = 'flink-agent',
      'password' = '${local.mcp_password}'
    );
  SQL

  statement_name = "${local.flink_name_prefix}-mcp-connection-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }
}

resource "confluent_flink_statement" "create_search_known_issues_tool" {
  count = var.intelligence_enable_agent ? 1 : 0

  statement = <<-SQL
    CREATE TOOL search_known_issues_tool USING CONNECTION portal_mcp_connection
    WITH ('type' = 'mcp', 'allowed_tools' = 'search_known_issues');
  SQL

  statement_name = "${local.flink_name_prefix}-search-known-issues-tool-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [confluent_flink_statement.create_mcp_connection]
}

resource "confluent_flink_statement" "create_get_account_context_tool" {
  count = var.intelligence_enable_agent ? 1 : 0

  statement = <<-SQL
    CREATE TOOL get_account_context_tool USING CONNECTION portal_mcp_connection
    WITH ('type' = 'mcp', 'allowed_tools' = 'get_account_context');
  SQL

  statement_name = "${local.flink_name_prefix}-get-account-context-tool-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [confluent_flink_statement.create_mcp_connection]
}

# Commented out for now -- the streaming agent should rely only on the
# MCP tools (search_known_issues_tool, get_account_context_tool), not
# this function-backed tool.
# resource "confluent_flink_statement" "create_check_status_tool" {
#   count = var.intelligence_enable_agent ? 1 : 0
#
#   statement = <<-SQL
#     CREATE TOOL check_status_tool
#     USING FUNCTION check_status
#     WITH ('type' = 'function', 'description' = 'Get current service status/incidents');
#   SQL
#
#   properties = local.flink_statement_context.properties
#   compute_pool { id = local.flink_statement_context.compute_pool_id }
#   principal { id = local.flink_statement_context.principal_id }
#   rest_endpoint = local.flink_statement_context.rest_endpoint
#   credentials {
#     key    = local.flink_statement_context.api_key
#     secret = local.flink_statement_context.api_secret
#   }
#   organization { id = local.flink_statement_context.organization_id }
#   environment { id = local.environment_id }
#
#   depends_on = [confluent_flink_statement.create_check_status_function]
# }

resource "confluent_flink_statement" "create_triage_agent" {
  count = var.intelligence_enable_agent ? 1 : 0

  # PROMPT rewritten twice from the original, based on live evidence once
  # the agent actually ran (everything before this always died earlier
  # in the connection/auth/deserialization chain, so this is the first
  # real feedback on the agent's own behavior):
  #   - The input now carries "User ID: <id>" ahead of the ticket text
  #     (see run_triage_agent's SELECT below) -- real responses showed
  #     the agent asking the human "please provide your user ID" instead
  #     of calling get_account_context, since it was never actually
  #     given one before.
  #   - The old free-form "produce that decision with a short message"
  #     instruction let the model answer however it liked -- some real
  #     responses never stated a decision at all. app/support_portal/
  #     tickets/service.py needs a deterministic decision to drive the
  #     ticket UI/escalation topic, so the prompt now demands an exact,
  #     parseable two-line output instead.
  #   - A third pass added "Subject: <subject>" to the input (see
  #     run_triage_agent below) and told the model to pass it to
  #     search_known_issues alongside the ticket text: measured offline
  #     against tickets.csv/knowledge_base.csv, matching on subject+body
  #     text lifted the auto-resolve rate from ~2% to ~70%, since subject
  #     lines tend to echo a known issue's own topic much more directly
  #     than a verbose, emotionally-worded ticket body does on its own.
  #   - A fourth pass added "Service Status: <status>" (and "Service
  #     Status Description: <description>" when non-empty) ahead of
  #     "Ticket: <text>" -- see run_triage_agent below, which now selects
  #     these straight from tickets.enriched's own service_status/
  #     service_status_description columns (02_statements_ticket_enrichment.tf's
  #     LEFT JOIN against `services.status`). This is plain input text,
  #     not a tool call -- the model never has to decide whether to check
  #     status, it's already there. The prompt tells the model to treat
  #     degraded/outage as evidence of a known, ongoing platform issue in
  #     its own right, on top of (not instead of) search_known_issues/
  #     get_account_context, since a ticket can describe a real outage in
  #     wording that doesn't fuzzy-match any seeded knowledge_base.csv row.
  #   - A fifth pass made get_account_context's result an explicit
  #     decision input instead of the vague "weigh it alongside ...
  #     account history" it was before: gold tier or
  #     recurring_issue_same_service (both fields the tool already
  #     returns, see app/support_portal/mcp/server.py's get_account_context)
  #     now push toward ESCALATE even when search_known_issues matched
  #     confidently -- a repeat complaint or a top-tier customer merits a
  #     human response rather than the same automated fix offered again.
  #     This escalate signal is given precedence over the Service Status
  #     auto-resolve preference above (still mention the ongoing incident
  #     in the message when both apply, but escalate anyway), since
  #     otherwise the two rules would conflict with no stated resolution.
  statement = <<-SQL
    CREATE AGENT triage_agent
      USING MODEL `triage_agent_model`
      USING PROMPT 'You are a support triage agent for an e-commerce
        platform. The input contains "User ID: <id>" then "Subject:
        <subject>" then "Service: <service>" then "Service Status:
        <status>" then optionally "Service Status Description:
        <description>" then "Ticket: <text>". Service is the name of
        the service this ticket is about. Service Status is one of
        operational, degraded, or outage for that same service -- it is
        already known, not something you look up. For each ticket: first call
        search_known_issues with ticket_text set to the Ticket line and
        subject set to the Subject line; then call get_account_context
        passing the User ID from the input as user_id and the service
        from step 1 as service_hint; then decide whether to auto-resolve
        or escalate. If get_account_context returns tier equal to "gold",
        or recurring_issue_same_service equal to true, treat that as a
        signal to escalate rather than auto-resolve, even when
        search_known_issues matched confidently -- a repeat complaint or
        a top-tier customer deserves a human response rather than the
        same automated fix offered again. This escalate signal takes
        precedence over the Service Status rule below: if both apply,
        still mention the ongoing incident in the message, but respond
        with DECISION: ESCALATE. If Service Status is degraded or
        outage and neither escalate signal applies, treat that as strong
        evidence of a known, ongoing platform issue in its own right --
        weigh it alongside the search_known_issues match (not only in
        place of it), and prefer AUTO_RESOLVE with a message that
        explicitly references the ongoing incident and its description,
        even if there is no exact knowledge-base match for this
        ticket''s specific wording. If Service Status is operational and
        neither escalate signal applies, decide using the
        search_known_issues result alone as before. Respond with
        EXACTLY two lines and nothing else -- no other commentary,
        markdown, or headings:
        DECISION: AUTO_RESOLVE
        MESSAGE: <one-paragraph customer-facing message>
        (or DECISION: ESCALATE with its own MESSAGE line).'
      USING TOOLS search_known_issues_tool, get_account_context_tool
      WITH ('max_iterations' = '10', 'max_consecutive_failures' = '3');
  SQL

  statement_name = "${local.flink_name_prefix}-triage-agent-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [
    confluent_flink_statement.create_search_known_issues_tool,
    confluent_flink_statement.create_get_account_context_tool,
    confluent_flink_statement.create_triage_agent_model,
  ]
}

resource "confluent_flink_statement" "run_triage_agent" {
  count = var.intelligence_enable_agent ? 1 : 0

  # Calcite rejects `AS result` + `SELECT result.*` here ("SQL parse
  # failed ... encountered 'result'", confirmed live). docs.confluent.io's
  # own AI_RUN_AGENT examples use an unaliased LATERAL TABLE with a bare
  # `SELECT *` instead, so this matches that confirmed pattern rather
  # than guessing at AI_RUN_AGENT's exact output column names.
  #
  # scan.startup.mode = 'latest-offset' hint on tickets.enriched --
  # confirmed live: this job is a brand-new Flink job every time it's
  # (re)created (no checkpoint carried over), and Confluent Cloud
  # Flink's table default is 'earliest-offset', so without this hint
  # every restart replays tickets.enriched from offset 0. That topic
  # has old records left over from earlier schema versions of
  # 02_statements_ticket_enrichment.tf (from before `ticket_id` was
  # added to its SELECT) that this table's *current* schema can't
  # deserialize -- confirmed by reading partition 1 offset 0 directly:
  # its JSON has no ticket_id field at all. Without this hint the job
  # dies on that record before ever processing a current one. This is
  # also just the correct behavior for a live triage agent anyway -- it
  # should react to new tickets going forward, not replay history.
  # AI_RUN_AGENT's 2nd argument is a single free-text column (confirmed
  # via docs.confluent.io/cloud/current/ai/streaming-agents -- there's no
  # separate structured-input parameter), so user_id has to be baked
  # into that string directly rather than passed alongside it -- see
  # create_triage_agent's prompt above, which tells the model to expect
  # exactly this "User ID: <id>" prefix. A "Subject: <subject>" line was
  # added below the same way, ahead of "Ticket: <text>" -- see
  # create_triage_agent's prompt, which now tells the model to pass both
  # to search_known_issues. "Service Status: <status>" (and, when
  # non-empty, "Service Status Description: <description>") were added
  # the same way, straight from tickets.enriched's own service_status/
  # service_status_description columns -- no tool call, the agent's
  # prompt above already expects these lines in this exact position
  # (between Subject and Ticket). "Service: <service>" was added just
  # ahead of "Service Status: <status>" the same way -- service is
  # already resolved on tickets.enriched (02_statements_ticket_
  # enrichment.tf's join), it was just never actually passed into the
  # prompt text, leaving the model to guess the service name from the
  # ticket's own wording when composing its customer-facing message.
  # Wrapped in COALESCE(..., 'unknown') because tickets.enriched.service
  # is nullable (TicketRaw.service: Optional[str]) and CONCAT returns
  # NULL for the whole expression if any argument is NULL -- same reason
  # service_status_description is guarded by a CASE above, and the same
  # guard tickets.metrics already applies to this same column.
  #
  # decision/message below replicate app/support_portal/tickets/
  # service.py's parse_agent_response() exactly (same DECISION:/MESSAGE:
  # contract, same escalate-by-default fallback), moved into the
  # statement itself so both Python consumers (tickets/service.py,
  # dashboard/service.py) can read pre-computed fields instead of each
  # re-parsing the same raw response text -- same pattern already used
  # for AI_SENTIMENT's sentiment field and ML_FORECAST's forecast.
  statement = <<-SQL
    CREATE TABLE `tickets.agent-actions` WITH (
      'value.format' = 'json-registry'
    ) AS
    SELECT
      *,
      COALESCE(
        LOWER(REGEXP_EXTRACT(response, '(?i)DECISION: *(AUTO_RESOLVE|ESCALATE)', 1)),
        'escalate'
      ) AS decision,
      COALESCE(
        NULLIF(TRIM(REGEXP_EXTRACT(response, '(?i)MESSAGE: *(.+)', 1)), ''),
        response
      ) AS message
    FROM `tickets.enriched` /*+ OPTIONS('scan.startup.mode' = 'latest-offset') */,
    LATERAL TABLE(AI_RUN_AGENT(
      'triage_agent',
      CONCAT(
        'User ID: ', CAST(`tickets.enriched`.user_id AS STRING), CHR(10),
        'Subject: ', `tickets.enriched`.subject, CHR(10),
        'Service: ', COALESCE(`tickets.enriched`.service, 'unknown'), CHR(10),
        'Service Status: ', `tickets.enriched`.service_status,
        CASE WHEN `tickets.enriched`.service_status_description IS NOT NULL AND `tickets.enriched`.service_status_description <> ''
          THEN CONCAT(CHR(10), 'Service Status Description: ', `tickets.enriched`.service_status_description)
          ELSE '' END,
        CHR(10), 'Ticket: ', `tickets.enriched`.text
      ),
      `tickets.enriched`.ticket_id
    ));
  SQL

  statement_name = "${local.flink_name_prefix}-run-triage-agent-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties
  compute_pool { id = local.flink_statement_context.compute_pool_id }
  principal { id = local.flink_statement_context.principal_id }
  rest_endpoint = local.flink_statement_context.rest_endpoint
  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }
  organization { id = local.flink_statement_context.organization_id }
  environment { id = local.environment_id }

  depends_on = [confluent_flink_statement.create_triage_agent]
}
