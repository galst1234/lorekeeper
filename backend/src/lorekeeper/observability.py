import logging

import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider  # noqa: PLC2701
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter  # noqa: PLC2701
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler  # noqa: PLC2701
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor  # noqa: PLC2701
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from lorekeeper.config import settings


class _DualCounter:
    def __init__(self, name: str, inner: metrics.Counter) -> None:
        self._name = name
        self._inner = inner

    def add(self, value: int | float, attributes: dict | None = None) -> None:
        self._inner.add(value, attributes or {})
        sentry_sdk.metrics.count(self._name, value, attributes=attributes or {})


class _DualUpDownCounter:
    def __init__(self, name: str, inner: metrics.UpDownCounter) -> None:
        self._name = name
        self._inner = inner
        self._totals: dict[tuple, int | float] = {}

    def add(self, value: int | float, attributes: dict | None = None) -> None:
        attrs = attributes or {}
        self._inner.add(value, attrs)
        key = tuple(sorted(attrs.items()))
        self._totals[key] = self._totals.get(key, 0) + value
        sentry_sdk.metrics.gauge(self._name, self._totals[key], attributes=attrs)


class _DualHistogram:
    def __init__(self, name: str, inner: metrics.Histogram) -> None:
        self._name = name
        self._inner = inner

    def record(self, value: int | float, attributes: dict | None = None) -> None:
        self._inner.record(value, attributes or {})
        sentry_sdk.metrics.distribution(self._name, value, attributes=attributes or {})


class DualMeter:
    def __init__(self, inner: metrics.Meter) -> None:
        self._inner = inner

    def create_counter(self, name: str, *, description: str = "", unit: str = "") -> _DualCounter:
        return _DualCounter(name, self._inner.create_counter(name, description=description, unit=unit))

    def create_up_down_counter(self, name: str, *, description: str = "", unit: str = "") -> _DualUpDownCounter:
        return _DualUpDownCounter(name, self._inner.create_up_down_counter(name, description=description, unit=unit))

    def create_histogram(self, name: str, *, description: str = "", unit: str = "") -> _DualHistogram:
        return _DualHistogram(name, self._inner.create_histogram(name, description=description, unit=unit))


def setup_observability(service_name: str) -> tuple[trace.Tracer, DualMeter]:
    logging.basicConfig()  # idempotent; ensures stdout logging for services that don't call it

    if not settings.enable_tracing:
        # no exporters initialized — all metric and trace calls are no-ops
        return trace.get_tracer(service_name), DualMeter(metrics.get_meter(service_name))

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=1.0,
        server_name=service_name,
    )

    resource = Resource({SERVICE_NAME: service_name})
    auth_header = {"Authorization": f"Basic {settings.open_observe_api_key}"}

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{settings.open_observe_url}/api/default/v1/traces",
                headers=auth_header,
            ),
        ),
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=f"{settings.open_observe_url}/api/default/v1/metrics",
                    headers=auth_header,
                ),
            ),
        ],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=f"{settings.open_observe_url}/api/default/v1/logs",
                headers={**auth_header, "stream-name": "python"},
            ),
        ),
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider))

    return trace.get_tracer(service_name), DualMeter(metrics.get_meter(service_name))
