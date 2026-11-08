"""Explicit environment wiring; AWS never falls back to fixtures. Author: Tishneet."""
import importlib
import os

from backend.ai.planner import Planner
from backend.ai.providers import provider_from_env
from .service import WorkflowService
from .store import DynamoStore, MemoryStore


def create_service(runtime=None):
    runtime = runtime or os.environ.get("SENTINEL_RUNTIME", "local")
    if runtime not in {"local", "aws"}:
        raise ValueError("SENTINEL_RUNTIME must be local or aws")
    if runtime == "aws":
        if os.environ.get("SENTINEL_MODEL_PROVIDER") != "bedrock":
            raise ValueError("AWS requires the real Bedrock provider")
        if os.environ.get("DYNAMODB_ENDPOINT_URL"):
            raise ValueError("AWS runtime cannot use DynamoDB Local")
        if os.environ.get("SENTINEL_AUTH_MODE", "prod") != "prod":
            raise ValueError("Open/development admin authentication cannot run in AWS")
    storage = os.environ.get("SENTINEL_STORE", "dynamodb")
    if storage == "memory":
        if runtime == "aws":
            raise ValueError("AWS workflow state must be durable")
        store = MemoryStore()
    elif storage == "dynamodb":
        store = DynamoStore(table_name=os.environ.get("SENTINEL_WORKFLOW_TABLE", "sentinel_workflow"))
        if os.environ.get("DYNAMODB_ENDPOINT_URL"):
            store.create_table()
    else:
        raise ValueError("SENTINEL_STORE must be memory or dynamodb")
    if runtime == "local":
        from .fixtures import FixtureGateway
        gateway = FixtureGateway(store)
        callback = None
        audit_sink = None
    else:
        module_name = os.environ.get("SENTINEL_TRUSTED_ADAPTER_MODULE")
        if not module_name:
            raise ValueError("Mariam's trusted adapter module must be configured for AWS")
        gateway = importlib.import_module(module_name).create_gateway(store)
        if not getattr(gateway, "name", None) or "FIXTURE" in gateway.name.upper():
            raise ValueError("A real trusted security/data gateway is required for AWS")
        for method in ("get_warehouse", "get_agent", "get_run_id", "authorize_plan", "simulate_plan",
                       "execute_plan", "revoke_agent", "reset_demo", "append_audit"):
            if not callable(getattr(gateway, method, None)):
                raise ValueError("Trusted gateway lacks " + method)
        from .aws import callback_sender
        callback = callback_sender()
        audit_sink = gateway.append_audit
    return WorkflowService(store, Planner(provider_from_env()), gateway,
                           approval_seconds=int(os.environ.get("SENTINEL_APPROVAL_TIMEOUT", "120")),
                           callback_sender=callback, audit_sink=audit_sink)
