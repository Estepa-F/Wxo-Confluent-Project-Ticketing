"""Background consumer feeding feature-owned handlers (dashboard, tickets).
Runs its own thread (confluent-kafka's Consumer.poll is blocking) and hands
decoded messages back to the asyncio event loop via loop.call_soon_threadsafe,
dispatching each message to the handlers registered for its topic instead of
calling every handler unconditionally."""

import asyncio
import datetime
import logging
import threading
from collections import defaultdict
from typing import Callable

from confluent_kafka import OFFSET_BEGINNING, Consumer
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.schema_registry.json_schema import JSONDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext

from support_portal.config import settings
from support_portal.messaging.client import client_config, schema_registry_client

logger = logging.getLogger(__name__)

OnMessage = Callable[[str, dict], None]

# tickets.metrics stays on Flink's default avro-registry format -- its
# ML_FORECAST output carries a TIMESTAMP(6) field, which Confluent Cloud's
# json-registry format can't represent (max precision 3). See
# terraform/confluent-intelligence/01_statements_ticket_metrics.tf.
AVRO_TOPICS = {"tickets.metrics"}


def _json_safe(value):
    """AvroDeserializer decodes Avro logical types (e.g. timestamp-millis)
    into native datetime objects, unlike JSONDeserializer which already
    yields JSON-native strings -- websocket.send_json's plain json.dumps
    can't encode those, so Avro-sourced values need this before dispatch."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        # Avro's timestamp-millis/-micros logical types decode to naive
        # datetimes that are UTC by spec, but isoformat() on a naive
        # datetime omits any offset -- the browser's `new Date(...)` then
        # parses that string as local time instead of UTC, silently
        # shifting every displayed timestamp by the browser's UTC
        # offset. Attach UTC explicitly before formatting so the string
        # carries a "+00:00"/"Z" suffix and parses correctly everywhere.
        if isinstance(value, datetime.datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.isoformat()
    return value


class DashboardConsumer:
    """No-ops when CC_BOOTSTRAP_SERVERS isn't set, so the app can boot and
    serve the REST/MCP surface locally without a real Confluent Cloud
    cluster -- the dashboard just won't receive live updates until real
    credentials are configured."""

    def __init__(self, loop: asyncio.AbstractEventLoop, handlers: dict[str, list[OnMessage]]):
        self._loop = loop
        self._handlers: dict[str, list[OnMessage]] = defaultdict(list, handlers)
        self._running = False
        self._thread: threading.Thread | None = None
        # Gates the from-beginning replay in _on_assign to only the very
        # first partition assignment after this process starts -- a
        # later mid-session rebalance (broker blip, group churn) should
        # just resume normally, not replay full history again.
        self._first_assign = True
        self._enabled = bool(settings.cc_bootstrap_servers)
        if not self._enabled:
            self._consumer = None
            self._deserializer = None
            return

        self._consumer = Consumer(client_config({
            "group.id": settings.kafka_group_id,
            "auto.offset.reset": "latest",
        }))
        sr_client = schema_registry_client()
        # schema_str=None with a schema_registry_client fetches the writer
        # schema by id embedded in the message; verify this matches the
        # installed confluent-kafka version's JSONDeserializer signature.
        self._deserializer = JSONDeserializer(
            schema_str=None,
            from_dict=lambda obj, ctx: obj,
            schema_registry_client=sr_client,
        )
        # schema_str=None + schema_registry_client makes this generic across
        # subjects (the schema id is read from each message's own 5-byte
        # header), so the same instance decodes both values and, for
        # AVRO_TOPICS, the tickets.metrics-key subject below.
        self._avro_deserializer = AvroDeserializer(
            schema_registry_client=sr_client,
            from_dict=lambda obj, ctx: obj,
        )

    def start(self, topics: list[str]) -> None:
        if not self._enabled:
            return
        self._consumer.subscribe(topics, on_assign=self._on_assign)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _on_assign(self, consumer: Consumer, partitions: list) -> None:
        """The dashboard's state (support_portal.dashboard.service) is
        in-memory only and gets wiped on every process restart, so a
        restarted app otherwise stays empty until new messages arrive --
        existing committed offsets just resume near the tip, and
        auto.offset.reset=latest skips a fresh group straight past
        everything already in the topic. Force a full replay from the
        beginning on this process's first assignment so that state gets
        rebuilt from true history immediately; a later rebalance during
        the same run (self._first_assign already False by then) resumes
        normally instead of replaying everything all over again.

        assign() here, not seek() -- confirmed via confluent-kafka's own
        issue tracker that seek(OFFSET_BEGINNING) inside on_assign does
        not reliably take effect; the override has to be applied via
        assign()."""
        if self._first_assign:
            for partition in partitions:
                partition.offset = OFFSET_BEGINNING
            self._first_assign = False
        consumer.assign(partitions)

    def stop(self) -> None:
        if not self._enabled:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._consumer.close()

    def _run(self) -> None:
        while self._running:
            msg = self._consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                is_avro = msg.topic() in AVRO_TOPICS
                deserializer = self._avro_deserializer if is_avro else self._deserializer
                value_ctx = SerializationContext(msg.topic(), MessageField.VALUE)
                value = deserializer(msg.value(), value_ctx)
                if is_avro:
                    # window_end lives in the key for tickets.metrics (see
                    # the comment on self._avro_deserializer above) -- merge
                    # it into the value so downstream handlers see one dict.
                    key_ctx = SerializationContext(msg.topic(), MessageField.KEY)
                    key = self._avro_deserializer(msg.key(), key_ctx)
                    if isinstance(key, dict):
                        value = {**key, **value}
                    value = _json_safe(value)
            except Exception:
                # Never let a bad message crash the dashboard feed on stage,
                # but still log it -- silently swallowing here previously
                # made a deserialization mismatch indistinguishable from no
                # data flowing at all.
                logger.exception("Failed to deserialize message from %s", msg.topic())
                continue
            self._loop.call_soon_threadsafe(self._dispatch, msg.topic(), value)

    def _dispatch(self, topic: str, value: dict) -> None:
        for handler in self._handlers.get(topic, []):
            handler(topic, value)
