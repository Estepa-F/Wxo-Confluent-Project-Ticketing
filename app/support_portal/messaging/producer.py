"""Embedded Kafka producer (no REST Proxy) — produces directly to
Confluent Cloud using confluent-kafka, serializing values as JSON Schema
against Schema Registry so RTCE can later index the output topics."""

import json

from confluent_kafka import Producer
from confluent_kafka.schema_registry.json_schema import JSONSerializer
from confluent_kafka.serialization import MessageField, SerializationContext, StringSerializer
from pydantic import BaseModel

from support_portal.config import settings
from support_portal.messaging.client import client_config, schema_registry_client


class TicketProducer:
    """No-ops when CC_BOOTSTRAP_SERVERS isn't set, so the REST/MCP surface
    can be smoke-tested locally without a real Confluent Cloud cluster --
    actual ticket production still requires real credentials."""

    def __init__(self):
        self._enabled = bool(settings.cc_bootstrap_servers)
        self._producer = Producer(client_config()) if self._enabled else None
        self._key_serializer = StringSerializer("utf_8")
        self._serializers: dict[str, JSONSerializer] = {}
        self._sr_client = schema_registry_client() if self._enabled else None

    def _serializer_for(self, topic: str, model: type[BaseModel]) -> JSONSerializer:
        if topic not in self._serializers:
            schema_str = json.dumps(model.model_json_schema())
            self._serializers[topic] = JSONSerializer(schema_str, self._sr_client)
        return self._serializers[topic]

    def produce_model(self, topic: str, key: str, model_instance: BaseModel) -> None:
        if not self._enabled:
            raise RuntimeError(
                "CC_BOOTSTRAP_SERVERS is not set -- set Confluent Cloud "
                "credentials in .env to actually produce messages."
            )
        serializer = self._serializer_for(topic, type(model_instance))
        ctx = SerializationContext(topic, MessageField.VALUE)
        payload = json.loads(model_instance.model_dump_json())
        self._producer.produce(
            topic=topic,
            key=self._key_serializer(key),
            value=serializer(payload, ctx),
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 5.0) -> None:
        if self._enabled:
            self._producer.flush(timeout)


# Singleton instance (mirrors config.py's `settings = Settings()`) -- both
# main.py and tickets/service.py need the same producer, and instantiating
# it here (rather than in main.py, then importing it back into
# tickets/service.py) avoids a circular import between those two modules.
producer = TicketProducer()
