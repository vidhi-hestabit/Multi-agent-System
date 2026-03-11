from __future__ import annotations
from contextlib import contextmanager
from typing import Generator, Optional
from common.config import get_settings
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer = None
def init_tracing(service_name: str) -> None:
    settings = get_settings()
    if not settings.otel_enabled:
        return
    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        global _tracer
        _tracer = trace.get_tracer(service_name)
    except ImportError:
        pass

@contextmanager
def trace_span(name: str, attributes: Optional[dict] = None) -> Generator:
    settings = get_settings()
    if not settings.otel_enabled or _tracer is None:
        yield None
        return
    from opentelemetry import trace
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        yield span