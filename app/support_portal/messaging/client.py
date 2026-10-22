"""Shared Confluent Cloud client config, used by both the producer and
the dashboard consumer so the credential wiring lives in one place."""

from confluent_kafka.schema_registry import SchemaRegistryClient

from support_portal.config import settings


def client_config(extra: dict | None = None) -> dict:
    config = {
        "bootstrap.servers": settings.cc_bootstrap_servers,
        "security.protocol": settings.cc_security_protocol,
        "sasl.mechanisms": settings.cc_sasl_mechanisms,
        "sasl.username": settings.cc_api_key,
        "sasl.password": settings.cc_api_secret,
    }
    if extra:
        config.update(extra)
    return config


def schema_registry_client() -> SchemaRegistryClient | None:
    if not settings.cc_schema_registry_url:
        return None
    return SchemaRegistryClient({
        "url": settings.cc_schema_registry_url,
        "basic.auth.user.info": f"{settings.cc_schema_registry_api_key}:{settings.cc_schema_registry_api_secret}",
    })
