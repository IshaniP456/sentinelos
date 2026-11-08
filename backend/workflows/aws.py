"""AWS transport adapters for the durable workflow. Author: Tishneet.

The Lambda advances one persisted transition at a time. Business decisions stay
in WorkflowService; Step Functions owns scheduling and human-approval waiting.
"""

import json
import os


def _service():
    # Lazy imports keep pure dispatch tests independent of AWS credentials.
    from .factory import create_service

    return create_service(runtime="aws")


def _sfn_client():
    import boto3
    from botocore.config import Config

    # An ambiguous StartExecution/SendTaskSuccess result is reconciled using the
    # same durable plan/token, never by silently starting another execution.
    return boto3.client("stepfunctions", config=Config(
        retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=15
    ))


def callback_sender(client=None):
    """Create a trusted callback sender; tokens never enter a public response.

    The caller persists the decision first and marks delivery only after this
    function succeeds. A timed-out/invalid token remains an explicit failure,
    not evidence that the candidate executed.
    """
    def send(token, decision):
        if decision not in ("APPROVED", "DENIED"):
            raise ValueError("Unsupported approval decision")
        if not isinstance(token, str) or not token:
            raise ValueError("A backend task token is required")
        (client or _sfn_client()).send_task_success(
            taskToken=token,
            output=json.dumps({"decision": decision}, separators=(",", ":")),
        )

    return send


class WorkflowStartError(RuntimeError):
    """Start did not receive confirmation; retain the plan for reconciliation."""

    def __init__(self, plan_id, ambiguous):
        super().__init__("Workflow start was not confirmed; inspect the existing plan.")
        self.plan_id = plan_id
        self.ambiguous = ambiguous


class AwsWorkflowBackend:
    """Start a Standard execution for an existing durable service plan.

    The plan_id is also the execution name. Retrying StartExecution for that
    exact name/input does not create a second Standard execution. Never create
    a new plan to retry an ambiguous network result.
    """

    def __init__(self, service, state_machine_arn, client=None):
        if not state_machine_arn:
            raise ValueError("SENTINEL_STATE_MACHINE_ARN must be configured")
        self.service = service
        self.state_machine_arn = state_machine_arn
        self.client = client

    def start_plan(self, instruction):
        result = self.service.start_plan(instruction)
        self.start_existing(result["plan_id"])
        return result

    def start_image_plan(self, image_b64, mime_type, demo_mode=None):
        result = self.service.start_image_plan(image_b64, mime_type, demo_mode)
        self.start_existing(result["plan_id"])
        return result

    def start_existing(self, plan_id):
        """Reconcile/retry an uncertain start without another candidate or plan."""
        # UUID-based service plan IDs satisfy the Standard execution name rules.
        status = self.service.get_plan_status(plan_id)
        if status["status"] != "PLANNING":
            raise ValueError("Only an unstarted PLANNING request can be started")
        try:
            client = self.client or _sfn_client()
            return client.start_execution(
                stateMachineArn=self.state_machine_arn,
                name=plan_id,
                input=json.dumps({"plan_id": plan_id}, separators=(",", ":")),
            )
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            # These are definite pre-start failures. Transport failures and
            # throttling remain reconcilable; do not claim they never started.
            explicit = code in {
                "AccessDeniedException", "InvalidArn", "InvalidExecutionInput",
                "InvalidName", "StateMachineDoesNotExist", "ValidationException",
            }
            if explicit:
                self.service.fail_plan(plan_id, "WORKFLOW_START_FAILED",
                                       "AWS rejected the workflow start.")
            raise WorkflowStartError(plan_id, ambiguous=not explicit) from exc

    def __getattr__(self, name):
        # Ishani's BackendOps interface can delegate status/approval reads while
        # Mariam supplies warehouse/security operations through the factory.
        return getattr(self.service, name)


def handler(event, context=None, service=None):
    """Lambda entry point: advance, register approval, expire, or inspect state."""
    if not isinstance(event, dict):
        raise ValueError("Workflow event must be an object")
    operation = event.get("operation", "advance")
    supported = {"start", "advance", "status", "register_approval", "expire", "fail", "flush_audit"}
    if operation not in supported:
        raise ValueError("Unsupported workflow operation")
    service = service or _service()
    if operation == "flush_audit":
        return {"events_delivered": service.flush_audit(event.get("plan_id"))}
    if operation == "start":
        return AwsWorkflowBackend(
            service, os.environ.get("SENTINEL_STATE_MACHINE_ARN")
        ).start_plan(event.get("instruction"))
    plan_id = event.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("plan_id is required")
    if operation == "advance":
        service.tick(plan_id=plan_id, owner="stepfunctions")
    elif operation == "register_approval":
        token = event.get("task_token")
        if not isinstance(token, str) or not token:
            raise ValueError("A backend task token is required")
        service.register_callback(plan_id, token)
        # This payload is not the public plan and contains no token.
        return {"plan_id": plan_id, "registered": True}
    elif operation == "expire":
        service.expire_approval(plan_id)
    elif operation == "fail":
        # Do not reflect arbitrary AWS exception messages, inputs, or tokens.
        service.fail_plan(plan_id, "WORKFLOW_TASK_FAILED",
                          "A required workflow task failed.")
    return service.get_plan_status(plan_id)
