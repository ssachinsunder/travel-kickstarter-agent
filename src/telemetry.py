import os
import logging
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from google.adk.telemetry.setup import OTelHooks, maybe_set_otel_providers
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter

logger = logging.getLogger(__name__)

def setup_telemetry(db_path: str):
    """Sets up local SQLite telemetry tracing."""
    logger.info(f"Setting up telemetry, exporting to SQLite DB: {db_path}")
    try:
        # SqliteSpanExporter will create the 'spans' table in the target DB if it doesn't exist.
        exporter = SqliteSpanExporter(db_path=db_path)
        # Use BatchSpanProcessor as recommended
        processor = BatchSpanProcessor(exporter)
        hooks = OTelHooks(span_processors=[processor])
        
        maybe_set_otel_providers(otel_hooks_to_setup=[hooks])
        logger.info("ADK telemetry initialized.")
        
        # Try to instrument google-genai if the library is available (optional)
        try:
            from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
            GoogleGenAiSdkInstrumentor().instrument()
            logger.info("Google GenAI SDK instrumented.")
        except ImportError:
            logger.debug("opentelemetry-instrumentation-google-genai not installed. Skipping GenAI SDK auto-instrumentation.")
            
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {e}")
