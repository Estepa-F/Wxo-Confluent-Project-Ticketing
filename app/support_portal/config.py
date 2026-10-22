from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    account_pool_size: int = 250
    # Retuned from 65: real ticket text scores a median of ~47 against the
    # KB's combined title+symptoms+description text (rapidfuzz
    # token_set_ratio), so 65 let through only ~2.4% of tickets. 50 lands
    # auto-resolve at ~66-70% against the real ticket corpus (measured
    # offline against tickets.csv/knowledge_base.csv).
    match_threshold: int = 50
    admin_token: str = "change-me"
    mcp_username: str = "flink-agent"
    mcp_password: str = "change-me"
    port: int = 8000
    enable_generator: bool = True
    # 0.1/sec = 6 tickets/min globally; with 6 services weighted equally
    # when all are healthy (_weighted_service in generator/synthetic.py),
    # that averages to 1 ticket/min per service -- the demo's target rate,
    # so the AI triage step (a shared Flink compute pool) isn't competing
    # with a flood of synthetic traffic for real-time answers.
    generator_rate: float = 0.1

    # mcp 2.x rejects any request whose Host header isn't in this list
    # (DNS-rebinding protection, on by default) -- add the public
    # deployment hostname here once known, e.g. "my-portal.fly.dev".
    mcp_allowed_hosts: str = "localhost:*,127.0.0.1:*"

    # Consumer group of the dashboard/tickets consumer. Give a local copy its
    # own group (e.g. support-portal-local) so it does not split topic
    # partitions with the deployed app and miss half of the agent actions.
    kafka_group_id: str = "support-portal-dashboard"

    cc_bootstrap_servers: str = ""
    cc_api_key: str = ""
    cc_api_secret: str = ""
    cc_security_protocol: str = "SASL_SSL"
    cc_sasl_mechanisms: str = "PLAIN"

    cc_schema_registry_url: str = ""
    cc_schema_registry_api_key: str = ""
    cc_schema_registry_api_secret: str = ""

    # watsonx Orchestrate escalation agent (orchestrate/agents/escalation_agent.yaml).
    # All three must be set for AI reply drafts; otherwise the feature is off.
    wxo_instance_url: str = ""  # e.g. https://api.eu-de.watson-orchestrate.cloud.ibm.com/instances/<id>
    wxo_api_key: str = ""  # IBM Cloud API key allowed to call the instance
    wxo_agent_id: str = ""  # escalation_agent's id
    wxo_iam_url: str = "https://iam.cloud.ibm.com/identity/token"
    wxo_timeout_seconds: float = 120
    # Draft automatically on each escalation. Synthetic (generator) tickets
    # are skipped by default: each draft calls the AWS goodwill agent.
    wxo_auto_draft: bool = True
    wxo_include_synthetic: bool = False


settings = Settings()
