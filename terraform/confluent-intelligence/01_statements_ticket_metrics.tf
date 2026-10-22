# Ticket metrics/forecast statement, per docs/project-spec.md section 2.4.
# This CTAS statement auto-creates its backing topic + Schema Registry
# subject (same pattern as the sibling project's CREATE TABLE statements)
# -- no confluent_kafka_topic needed for tickets.metrics.
#
# Reads directly from `tickets.raw`, so it has no data dependency on the
# ticket_enrichment statement and applies independently.
#
# Partitioned per-service (not one global forecast) -- fixes three
# Confluent Cloud query-health warnings confirmed live against this
# statement (docs.confluent.io/cloud/current/flink/how-to-guides/
# resolve-common-query-problems.html):
#   - UPSERT_AND_PRIMARY_KEYS_DIFFERENT: the declared PRIMARY KEY must
#     match the query's actual GROUP BY key exactly, or Flink inserts an
#     extra state-intensive UpsertMaterialize operator to reconcile them.
#   - MISSING_PARTITION_BY_FOR_OVER_WINDOW: the OVER(...) had no
#     PARTITION BY, so it ran as one non-parallel task computing a single
#     global running forecast. PARTITION BY service gives ML_FORECAST a
#     real partition key -- one running forecast per service instead, and
#     genuine parallelism. minTrainingSize=3 now means 45 minutes of that
#     service's own window history, same wall-clock wait as before.
#   - HIGH_STATE_OPERATOR_WITHOUT_TTL: the OVER(...UNBOUNDED PRECEDING)
#     operator keeps growing state forever with no TTL. Set via
#     'sql.state-ttl' in `properties` below (Confluent Cloud Flink's
#     per-statement equivalent of `SET 'sql.state-ttl' = '...';`) --
#     scoped to just this statement's properties, not the shared
#     flink_statement_context, so it doesn't affect the other statements
#     in this phase.
# The dashboard now shows one actual + one forecast line per service
# instead of a single global line (app/support_portal/dashboard/
# service.py keeps metrics keyed by service, no rollup).
#
# `tickets.raw`'s own `submitted_at` column came in as VARCHAR (from the
# app's JSON Schema), which TUMBLE rejects outright. Tried adding a
# computed watermark column via ALTER TABLE ADD -- confirmed live that
# Confluent Cloud Flink already declares a system-provided watermark on
# every table by default and rejects ADD for this ("Use ALTER TABLE
# MODIFY for custom watermarks"). Simplest correct fix: use that
# system-provided time attribute directly -- Confluent Cloud Flink
# exposes it as the `$rowtime` metadata column (the Kafka record
# timestamp) -- instead of parsing `submitted_at` or touching the
# table's watermark at all.
#
# Switched from AI_FORECAST (Early Access) to ML_FORECAST (GA,
# ARIMA-based) after AI_FORECAST consistently failed with "does not
# exist" even matching its docs' exact syntax multiple ways -- the docs
# state AI_FORECAST access is gated by EA program sign-up with no
# GRANT/RBAC path, and this org isn't enrolled for it (confirmed
# per Daniel's decision to use the GA fallback this project's plan
# already anticipated as a contingency for exactly this risk).
#
# Recurring gotcha along the way: Flink/Calcite infers CHAR(n)
# (fixed-length) for string literals and for JSON_OBJECT(...)'s result,
# not STRING/VARCHAR -- both AI_FORECAST's and ML_FORECAST's config
# parameter only have a STRING overload (no MAP/CHAR overload), so every
# such expression needs an explicit CAST(... AS STRING).
#
# ML_FORECAST returns a ROW (actual_value, aic, forecast_value,
# lower_bound, rmse, timestamp, upper_bound). Tried projecting a single
# field out of it (both `alias.field` and `(alias).field`) and hit
# "Table not found" then "Incompatible types" -- rather than keep
# guessing composite-field-access syntax against a live, billed compute
# pool, keep the whole ROW as-is in the output topic instead of
# decomposing it in SQL. This is arguably better anyway: it preserves
# lower_bound/upper_bound/rmse too, not just the point forecast, which
# the dashboard can destructure client-side from the nested JSON.
#
# Window/horizon/minTrainingSize sized for a live demo, not statistical
# rigor: TUMBLE was widened from 1 to 15 minutes (a 1-minute bucket was
# too fine-grained to read as a trend on the dashboard). horizon=2 means
# the forecast is 2 x 15min = 30 minutes ahead of the current window.
# minTrainingSize was dropped from 10 to 3 -- at 10, ML_FORECAST needs
# 10 x 15min = 2.5h of history before it forecasts anything at all,
# longer than most demo sessions; 3 gets a (less statistically solid)
# forecast after ~45min of the generator running instead.
#
# IMPORTANT: this table already exists from the previous 1-minute
# version, and this CREATE TABLE has no IF NOT EXISTS (same class of
# gotcha as portal_mcp_connection's comment elsewhere in this phase) --
# re-applying with the widened window will fail with "table already
# exists" until `tickets.metrics` is manually dropped first (DROP TABLE
# `tickets.metrics`; in the Flink SQL workspace), since Terraform can't
# safely automate dropping a live table as a side effect of a plain
# statement-text change.
resource "confluent_flink_statement" "ticket_metrics_forecast" {
  # RTCE's query tool rejects this table in its default (planner-inferred)
  # "retract" changelog mode -- confirmed live: the GROUP BY + OVER(...
  # UNBOUNDED PRECEDING) call to ML_FORECAST can revise the forecast for a
  # window+service it already emitted, so the planner conservatively marks
  # the output as retract. RTCE only supports append/upsert. Since a
  # forecast revision for the same window+service is the semantically
  # correct case here, upsert is the right target, not forcing append.
  # This CTAS variant (PRIMARY KEY/WITH in the CREATE part, columns still
  # inferred from the SELECT) is a Confluent-confirmed pattern -- avoids
  # hand-declaring ML_FORECAST's ROW field types, which the comment above
  # already flagged as unreliable to guess.
  #
  # PRIMARY KEY must match the query's actual GROUP BY key exactly
  # (window_end, window_start, service) -- confirmed live via the
  # UPSERT_AND_PRIMARY_KEYS_DIFFERENT warning when it didn't. Key columns
  # must also appear at the beginning of the SELECT, in the same order --
  # confirmed live: "Key columns must appear at the beginning of the table
  # schema."
  #
  # `service` (from tickets.raw's own Optional[str] column) must be
  # wrapped in COALESCE(service, 'unknown') everywhere it's grouped/
  # partitioned/selected -- confirmed live: "Invalid primary key
  # ...Column 'service' is nullable." PRIMARY KEY columns must be NOT
  # NULL, and COALESCE with a non-null literal default is what makes
  # Flink infer that.
  #
  # Unlike tickets.enriched/tickets.agent-actions, this table stays on
  # Flink's default 'avro-registry' value format (no 'value.format'
  # override) -- confirmed live: ML_FORECAST's ROW result carries a
  # TIMESTAMP(6) field, and Confluent Cloud's json-registry format only
  # supports TIMESTAMP precision <= 3, so CREATE TABLE ... WITH
  # ('value.format' = 'json-registry') fails outright ("JSON does not
  # support TIMESTAMP_WITHOUT_TIME_ZONE type with precision 6"). The app's
  # DashboardConsumer (messaging/consumer.py) uses AvroDeserializer for
  # this one topic specifically instead of the shared JSONDeserializer.
  statement = <<-SQL
    CREATE TABLE `tickets.metrics` (
      PRIMARY KEY (window_end, window_start, service) NOT ENFORCED
    ) WITH (
      'changelog.mode' = 'upsert'
    ) AS
    SELECT
      window_end,
      window_start,
      COALESCE(service, 'unknown') AS service,
      COUNT(*) AS ticket_count,
      ML_FORECAST(
        CAST(COUNT(*) AS DOUBLE),
        window_end,
        CAST(JSON_OBJECT('minTrainingSize' VALUE 3, 'enableStl' VALUE false, 'horizon' VALUE 2) AS STRING)
      ) OVER (
        PARTITION BY COALESCE(service, 'unknown')
        ORDER BY window_end
        RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ) AS forecast
    FROM TABLE(
      TUMBLE(TABLE `tickets.raw`, DESCRIPTOR($rowtime), INTERVAL '15' MINUTE)
    )
    GROUP BY window_start, window_end, COALESCE(service, 'unknown');
  SQL

  statement_name = "${local.flink_name_prefix}-ticket-metrics-forecast-${random_id.flink_statement_suffix.hex}"

  # sql.state-ttl bounds the OVER(...UNBOUNDED PRECEDING) operator's state
  # growth (fixes HIGH_STATE_OPERATOR_WITHOUT_TTL) -- scoped to just this
  # statement's properties, not local.flink_statement_context.properties
  # directly, so it doesn't affect the other statements in this phase.
  properties = merge(local.flink_statement_context.properties, {
    "sql.state-ttl" = "1 DAY"
  })

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
