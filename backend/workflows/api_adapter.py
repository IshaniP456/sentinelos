"""Tishneet's durable BackendOps adapter for Ishani's handlers. Author: Tishneet."""
import os

from backend.api.responses import ApiError
from .errors import WorkflowError
from .gateway_contracts import gateway_failure
from .factory import create_service


def _api_error(error):
    converted = ApiError(error.code, error.message, status=error.status)
    converted.retryable = error.retryable
    return converted


class WorkflowBackendOps:
    """Public operations delegate to trusted workflow/data services, never a browser model."""
    def __init__(self, service=None):
        self.service = service or create_service()
        self.starter = self.service
        if os.environ.get("SENTINEL_RUNTIME", "local") == "aws":
            from .aws import AwsWorkflowBackend
            self.starter = AwsWorkflowBackend(self.service, os.environ.get("SENTINEL_STATE_MACHINE_ARN"))

    @staticmethod
    def _call(function, *args):
        try:
            return function(*args)
        except WorkflowError as exc:
            raise _api_error(exc) from exc
        except Exception as exc:
            converted = gateway_failure(exc)
            if converted is None:
                raise
            raise _api_error(converted) from exc

    def start_plan(self, instruction):
        return self._start(self.starter.start_plan, instruction)

    def start_image_plan(self, image_b64, mime_type, demo_mode=None):
        return self._start(self.starter.start_image_plan, image_b64, mime_type, demo_mode)

    def _start(self, operation, *args):
        from .aws import WorkflowStartError
        try:
            return self._call(operation, *args)
        except WorkflowStartError as exc:
            if exc.ambiguous:
                # Preserve the ID for polling/reconciliation. A generic retryable
                # 500 here would encourage submitting a second independent plan.
                return {"plan_id": exc.plan_id, "status": "PLANNING", "start_confirmed": False}
            raise ApiError("WORKFLOW_START_FAILED", "AWS rejected this workflow start.", status=503) from exc

    def get_plan_status(self, plan_id):
        return self._call(self.service.get_plan_status, plan_id)

    def get_warehouse(self):
        return self._call(self.service.gateway.get_warehouse)

    def get_agent(self):
        return self._call(self.service.gateway.get_agent)

    def get_audit(self, plan_id=None):
        return self._call(self.service.get_audit, plan_id)

    def record_approval(self, approval_id, decision, admin):
        return self._call(self.service.record_approval, approval_id, decision, admin)

    def revoke_agent(self, admin):
        try:
            return self._call(self.service.gateway.revoke_agent, admin)
        except ApiError:
            raise
        except Exception:
            raise _api_error(WorkflowError(
                "GATEWAY_UNCONFIRMED", "Revocation outcome is unconfirmed; refresh agent status before retrying.",
                status=502)) from None

    def reset_demo(self, admin):
        return self._call(self.service.reset_demo, admin)
