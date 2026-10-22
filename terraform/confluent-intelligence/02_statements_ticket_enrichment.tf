# Ticket enrichment statement, per docs/project-spec.md section 2.4.
# This CTAS statement auto-creates its backing topic + Schema Registry
# subject (same pattern as the sibling project's CREATE TABLE statements)
# -- no confluent_kafka_topic needed for tickets.enriched.
#
# AI_SENTIMENT(text, ARRAY[service]) is now enabled for this
# environment, replacing the earlier random-pick placeholder that was
# kept during the initial build so the rest of the pipeline --
# TRIAGEAGENT, dashboard -- could be built/tested before AI_SENTIMENT's
# syntax and per-aspect return shape were confirmed.
#
# The aspect argument was originally ARRAY['urgency'] -- wrong per
# docs.confluent.io/cloud/current/ai/builtin-functions/sentiment.html:
# AI_SENTIMENT is aspect-based sentiment analysis, where "aspect" means a
# concrete entity/topic actually discussed in the text (the docs' own
# examples: 'battery', 'screen', 'product', 'shipping', 'support'), not
# an abstract property of the message like "urgency". Passing 'urgency'
# would evaluate sentiment toward a topic customers never actually write
# about. `service` (the ticket's own column) is the real topic being
# discussed, so it's used as a per-row dynamic aspect instead -- confirm
# live that a non-literal expression is accepted here (the docs only
# state the *config* JSON must be constant within a query, not the
# aspects array itself, but this project's own history of Flink/Calcite
# quirks says verify rather than assume).
#
# CONFIRMED: AI_SENTIMENT is only available in us-east-1 at this time --
# the eu-west-1 attempt went to phase DEGRADED with a generic "internal
# system error" (no explicit access-denied message). This whole project
# is being redeployed in us-east-1 to get real AI_SENTIMENT access.
#
# AI_SENTIMENT returns ROW<sentiment ARRAY<ROW<aspect, label, score>>,
# metadata> -- a nested structure, not a plain string. Same class of
# problem this project already hit with ML_FORECAST's ROW result (see
# 01_statements_ticket_metrics.tf's comment: projecting a single field
# out of a function's ROW result hit "Table not found" then
# "Incompatible types" live) -- so this keeps the whole ROW as one
# column (sentiment_analysis) instead of decomposing it in SQL, same as
# that statement does for `forecast`. The app derives a flat `sentiment`
# string (dashboard/service.py's handle_message) from
# sentiment_analysis.sentiment[0].label for the dashboard, which expects
# an exact 'positive'/'negative'/'neutral' match.
#
# IMPORTANT: tickets.enriched already exists from the placeholder
# version and this CREATE TABLE has no IF NOT EXISTS -- re-applying will
# fail with "table already exists" until it's manually dropped first
# (DROP TABLE `tickets.enriched`; in the Flink SQL workspace), same
# gotcha as ticket_metrics_forecast's window-size change. This applies to
# the `subject` column added below too -- and since tickets.agent-actions
# (03_statements_triage_agent.tf) is a CTAS derived from this table's
# schema, it needs the same drop/recreate treatment when this is deployed.
# The CTAS -> CREATE MATERIALIZED TABLE switch (service_status columns,
# see below) is the same kind of type change CREATE OR ALTER MATERIALIZED
# TABLE cannot migrate from a plain CTAS -- it needs this same manual
# DROP TABLE once, after which future column additions can use CREATE OR
# ALTER MATERIALIZED TABLE instead of dropping again.
#
# `subject` added to the SELECT below: tickets.raw already carries it
# (messaging/schemas.py's TicketRaw.subject) but it was previously dropped
# here and never reached the triage agent -- see run_triage_agent's prompt
# input in 03_statements_triage_agent.tf, which now includes it, since
# matching on subject + body text meaningfully improves the triage agent's
# known-issue match rate (subject lines tend to echo the KB's own topic
# more directly than verbose ticket bodies do).
#
# DISTRIBUTED BY (ticket_id) INTO 6 BUCKETS -- without it, this table (a
# plain append-only CTAS, no PRIMARY KEY) produces its Kafka messages
# with a null key, so tickets.raw's own per-ticket_id partition affinity
# (`tickets.raw` has 2 partitions, terraform/base/main.tf's
# partitions_count) is lost on the way out and tickets.enriched's
# messages land round-robin instead. DISTRIBUTED BY hashes ticket_id
# into the same number of buckets, keeping every message for a given
# ticket on one consistent partition through this step. Confirmed live
# against a disposable test CTAS table that this syntax (DISTRIBUTED BY
# with no PRIMARY KEY, on an append-only CTAS) is accepted -- Confluent's
# own docs examples only show it paired with PRIMARY KEY.
#
# Bucket count raised from 2 to 6 (confirmed live 2026-09-24, matching
# tickets.agent-actions' own 6 partitions): run_triage_agent reads
# straight from this table with a plain per-record LATERAL TABLE join
# (no shuffle), so its parallelism -- and therefore how many concurrent
# AI_RUN_AGENT/Bedrock calls it can have in flight -- is capped by this
# table's partition count, not by the compute pool's CFU. At 2 buckets
# the statement was measured at ~13 msgs/min out (Confluent Cloud
# Console's own "Messages behind (total)" metric, growing) while the
# generator produced faster than that -- confirmed via GET
# /admin/generator on the deployed app returning rate=0.5/sec (30/min).
# tickets.raw itself stays at 2 partitions (enrichment's own read side
# isn't the bottleneck -- tickets.enriched's total count tracks
# tickets.raw's closely); only this table's write-side bucket count
# needs to grow, since a single reader can fan out writes across more
# buckets than it reads partitions.
#
# CREATE MATERIALIZED TABLE (not a CREATE TABLE ... AS CTAS like every
# other statement in this project) so future column additions can use
# CREATE OR ALTER MATERIALIZED TABLE instead of the manual DROP
# TABLE/recreate cycle this table has needed every time its query
# changed (see the IMPORTANT note above). This is the first materialized
# table in this project -- CREATE MATERIALIZED TABLE/CREATE OR ALTER
# MATERIALIZED TABLE default to a continuous streaming refresh (no
# FRESHNESS clause needed), confirmed against docs.confluent.io, but
# AI_SENTIMENT + a temporal join coexisting in one materialized-table
# query is NOT confirmed by docs -- EXPLAIN this live before applying.
#
# service_status/service_status_description/service_status_observed_at
# added via a LEFT JOIN ... FOR SYSTEM_TIME AS OF against
# `services.status-current` (below), not against the raw `services.status`
# topic directly. The docs-based auto-upsert-inference theory (an
# inferred table over a compacted, keyed topic gets changelog.mode=
# 'upsert' with the Kafka key as primary key, with no separate
# Flink-computed table needed) did NOT hold live -- confirmed by a real
# failed apply: "Temporal Table Join requires primary key in versioned
# table, but no primary key can be found" when joining directly against
# `services.status`. Falls back to the same intermediate PRIMARY KEY +
# changelog.mode='upsert' CTAS pattern tickets.metrics already uses
# (`services.status-current`, in this same file) -- exactly the
# contingency this comment block's previous version already flagged as
# unconfirmed and untested in this project.
# COALESCE(s.status, 'operational') is a deliberately simple fallback
# for this demo (the app always publishes an initial snapshot for every
# known service at startup, so a genuinely missing row shouldn't happen)
# -- not meant to distinguish "confirmed operational" from "no status
# data yet".
#
# START_MODE = RESUME_OR_FROM_NOW: without it, CREATE MATERIALIZED
# TABLE defaults to RESUME_OR_FROM_BEGINNING, which -- on this table's
# initial creation (no prior job to resume) -- falls back to
# FROM_BEGINNING and replays the *entire* history of tickets.raw through
# AI_SENTIMENT (real Bedrock cost) and straight on into
# tickets.agent-actions' AI_RUN_AGENT (real cost again), regardless of
# that statement's own 'scan.startup.mode'='latest-offset' hint below --
# that hint only bounds run_triage_agent's read position on
# tickets.enriched itself, not how much of tickets.raw's backlog this
# statement replays into it in the first place. RESUME_OR_FROM_NOW
# falls back to FROM_NOW on this initial creation (skip the backlog,
# process only new tickets from here on), while still resuming from the
# job's last position on a future CREATE OR ALTER MATERIALIZED TABLE
# (e.g. adding a column later) instead of skipping straight to "now"
# again, which would create a processing gap. Confirmed against
# docs.confluent.io's CREATE OR ALTER MATERIALIZED TABLE reference for
# the full list of START_MODE values -- re-verify live before applying,
# per this project's own practice for every non-trivial Flink DDL.

# Intermediate keyed/versioned table -- see the comment above
# ticket_enrichment below for why direct auto-upsert-inference on
# `services.status` didn't work live. Same PRIMARY KEY + changelog.mode=
# 'upsert' CTAS pattern tickets.metrics already uses (01_statements_ticket_metrics.tf),
# reading the app-produced `services.status` topic instead of computing
# an aggregate. Named `services.status-current` (domain.noun, hyphen for
# the multi-word noun) to read clearly as "current status" next to the
# raw `services.status` event log, matching this project's own
# tickets.agent-actions naming convention.
resource "confluent_flink_statement" "services_status_current" {
  statement = <<-SQL
    CREATE TABLE `services.status-current` (
      PRIMARY KEY (service) NOT ENFORCED
    ) WITH (
      'changelog.mode' = 'upsert'
    ) AS
    SELECT service, status, description, updated_at
    FROM `services.status`;
  SQL

  statement_name = "${local.flink_name_prefix}-services-status-current-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties

  compute_pool {
    id = local.flink_statement_context.compute_pool_id
  }

  principal {
    id = local.flink_statement_context.principal_id
  }

  rest_endpoint = local.flink_statement_context.rest_endpoint

  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }

  organization {
    id = local.flink_statement_context.organization_id
  }

  environment {
    id = local.environment_id
  }
}

resource "confluent_flink_statement" "ticket_enrichment" {
  statement = <<-SQL
    CREATE MATERIALIZED TABLE `tickets.enriched`
    DISTRIBUTED BY (ticket_id) INTO 6 BUCKETS
    WITH (
      'value.format' = 'json-registry'
    )
    START_MODE = RESUME_OR_FROM_NOW
    AS
    SELECT
      t.ticket_id,
      t.user_id,
      t.service,
      t.subject,
      t.text,
      t.urgency_self_rated,
      %{ if var.intelligence_enable_ai_sentiment ~}
      AI_SENTIMENT(t.text, ARRAY[t.service]) AS sentiment_analysis,
      %{ endif ~}
      COALESCE(s.status, 'operational') AS service_status,
      s.description AS service_status_description,
      s.updated_at AS service_status_observed_at,
      CURRENT_TIMESTAMP AS enriched_at
    FROM `tickets.raw` AS t
    LEFT JOIN `services.status-current` FOR SYSTEM_TIME AS OF t.`$rowtime` AS s
      ON t.service = s.service;
  SQL

  statement_name = "${local.flink_name_prefix}-ticket-enrichment-${random_id.flink_statement_suffix.hex}"

  properties = local.flink_statement_context.properties

  compute_pool {
    id = local.flink_statement_context.compute_pool_id
  }

  principal {
    id = local.flink_statement_context.principal_id
  }

  depends_on = [confluent_flink_statement.services_status_current]

  rest_endpoint = local.flink_statement_context.rest_endpoint

  credentials {
    key    = local.flink_statement_context.api_key
    secret = local.flink_statement_context.api_secret
  }

  organization {
    id = local.flink_statement_context.organization_id
  }

  environment {
    id = local.environment_id
  }
}
