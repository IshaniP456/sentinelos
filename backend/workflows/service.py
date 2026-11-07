"""Durable trusted workflow stages shared by Docker and AWS. Author: Tishneet."""
import copy
import time
import uuid
from datetime import datetime, timezone

from backend.ai.intent import parse_instruction, check_intent
from backend.ai.risk import classify_risk
from backend.ai.validation import validate_plan, fingerprint
from .errors import WorkflowError
from .store import Conflict

TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "EXPIRED"}
PUBLIC_FIELDS = ("plan_id", "status", "agent_id", "instruction", "attempt",
                 "warehouse_version", "candidates", "risk", "execution", "updated_at", "error",
                 "reconciliation_required", "decision_latency_ms", "evaluation_ms")
REPLAN_CODES = {"CAPACITY_EXCEEDED", "INSUFFICIENT_INVENTORY", "UNKNOWN_ZONE"}


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class WorkflowService:
    """CAS stages; external execution is protected by the gateway's idempotency."""

    def __init__(self, store, planner, gateway, approval_seconds=600, clock=time.time,
                 callback_sender=None, lease_seconds=90, audit_sink=None):
        if approval_seconds <= 0 or lease_seconds <= 0:
            raise ValueError("Timeouts must be positive")
        self.store, self.planner, self.gateway = store, planner, gateway
        self.approval_seconds, self.clock = approval_seconds, clock
        self.callback_sender, self.lease_seconds = callback_sender, lease_seconds
        self.audit_sink = audit_sink
        version, control = store.read("CONTROL")
        if control is None:
            try:
                store.write("CONTROL", {"run_id": gateway.get_run_id(), "active": []}, version)
            except Conflict:
                pass

    def _event(self, record, event_type, outcome="PENDING", code=None, message=None, admin=None):
        events = record.setdefault("_events", [])
        event = {"plan_id": record["plan_id"], "event_id": "%s#%06d" % (record["plan_id"], len(events) + 1),
                 "timestamp": iso(self.clock()), "revision": record["attempt"],
                 "event_type": event_type, "outcome": outcome, "reason_code": code,
                 "message": message or event_type.replace("_", " ").capitalize()}
        if admin:
            event["admin"] = admin
        events.append(event)

    def _finish(self, record, status, code, message):
        record["status"] = status
        record["error"] = {"code": code, "message": message,
                           "retryable": code in {"VERSION_CONFLICT", "MODEL_ERROR", "DEPENDENCY_ERROR"}}
        self._event(record, "PLAN_" + status, status, code, message)

    def _execution_uncertain(self, record):
        retries = record.get("_execution_retries", 0) + 1
        record["_execution_retries"] = retries
        record["_retry_after"] = self.clock() + min(30, 2 ** retries)
        record["reconciliation_required"] = retries >= 5
        record["error"] = {"code": "EXECUTION_UNCONFIRMED", "retryable": True,
                           "message": "Execution outcome is unconfirmed; reconcile this plan ID before submitting again."}
        self._event(record, "EXECUTION_UNCONFIRMED", "PENDING", "EXECUTION_UNCONFIRMED")

    def start_plan(self, instruction):
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 4000:
            raise WorkflowError("INVALID_REQUEST", "Provide an instruction of 1–4000 characters.")
        try:
            intent = parse_instruction(instruction)
        except ValueError:
            raise WorkflowError("INVALID_REQUEST", "Clarify the source, quantity, and destination using a supported move instruction.")
        plan_id = "plan-" + uuid.uuid4().hex
        now = self.clock()
        for _ in range(8):
            cv, control = self.store.read("CONTROL")
            warehouse = self.gateway.get_warehouse()
            if self.gateway.get_run_id() != control["run_id"]:
                raise WorkflowError("VERSION_CONFLICT", "Demo run changed; retry submission.", True, 409)
            record = {"plan_id": plan_id, "status": "PLANNING", "agent_id": "inventory-agent-01",
                      "instruction": instruction.strip(), "attempt": 0,
                      "warehouse_version": warehouse["version"], "candidates": [],
                      "risk": None, "approval": None, "execution": None, "error": None,
                      "updated_at": iso(now), "_snapshot": warehouse, "_intent": intent,
                      "_run_id": control["run_id"], "_lease": None, "_model_inflight": False,
                      "_events": [], "_created_at": now}
            self._event(record, "PLAN_SUBMITTED")
            control["active"].append(plan_id)
            try:
                self.store.transact([("PLAN#" + plan_id, record, 0), ("CONTROL", control, cv)])
                return {"plan_id": plan_id, "status": "PLANNING"}
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Concurrent submission; retry.", True, 409)

    def _load(self, plan_id):
        version, record = self.store.read("PLAN#" + plan_id)
        if record is None:
            raise WorkflowError("NOT_FOUND", "Unknown plan_id.", status=404)
        return version, record

    def get_plan_status(self, plan_id):
        _, record = self._load(plan_id)
        result = {key: copy.deepcopy(record.get(key)) for key in PUBLIC_FIELDS}
        approval = record.get("approval")
        result["approval"] = ({key: approval[key] for key in
                               ("approval_id", "status", "revision", "expires_at", "decision_at", "admin")
                               if key in approval} if approval else None)
        result["runtime"] = {"provider": self.planner.provider.name, "gateway": self.gateway.name}
        return result

    def _release_active(self, plan_id):
        for _ in range(8):
            version, control = self.store.read("CONTROL")
            if plan_id not in control["active"]:
                return
            control["active"].remove(plan_id)
            try:
                self.store.write("CONTROL", control, version)
                return
            except Conflict:
                continue

    def tick(self, plan_id=None, owner="worker"):
        """Advance one stage, never called by a public read operation."""
        if plan_id is None:
            for active in self.store.read("CONTROL")[1]["active"]:
                if self.tick(active, owner):
                    return True
            return False
        version, record = self._load(plan_id)
        if record["status"] in TERMINAL:
            self._release_active(plan_id)
            return False
        now = self.clock()
        if record.get("reconciliation_required") or record.get("_retry_after", 0) > now:
            return False
        lease = record.get("_lease")
        if lease and lease["until"] > now:
            return False
        if record["status"] == "AWAITING_APPROVAL":
            if now >= record["approval"]["expires_epoch"]:
                self.expire_approval(plan_id)
                return True
            return False
        if record.get("_model_inflight"):
            # The previous invocation may have reached the model. Do not issue an
            # unaccounted extra call after a crash or an expired model lease.
            self._finish(record, "FAILED", "MODEL_ERROR", "Planning was interrupted; submit a fresh evaluation.")
            record["_lease"] = None
            try:
                self.store.write("PLAN#" + plan_id, record, version)
                self._release_active(plan_id)
                return True
            except Conflict:
                return False
        record["_lease"] = {"owner": owner, "until": now + self.lease_seconds}
        if record["status"] in {"PLANNING", "REPLANNING"}:
            if record["attempt"] >= 3:
                self._finish(record, "FAILED", "MAX_ATTEMPTS_REACHED", "Three candidates were evaluated.")
            else:
                record["attempt"] += 1
                record["_model_inflight"] = True
                self._event(record, "CANDIDATE_RESERVED")
        try:
            version = self.store.write("PLAN#" + plan_id, record, version)
        except Conflict:
            return False
        claimed_stage = record["status"]
        try:
            if record["status"] not in TERMINAL:
                self._advance(record)
        except WorkflowError as error:
            no_commit = {"AUTHORIZATION_DENIED", "VERSION_CONFLICT", "APPROVAL_REQUIRED",
                         "SIMULATION_FAILED", "PLAN_VALIDATION_FAILED", "EXECUTION_NOT_COMMITTED"}
            if claimed_stage == "EXECUTING" and error.code not in no_commit:
                self._execution_uncertain(record)
            else:
                status = "REJECTED" if error.code == "AUTHORIZATION_DENIED" else "FAILED"
                self._finish(record, status, error.code, error.message)
        except Exception:
            # Never persist model/provider exception strings, which may carry
            # prompt text, credentials or backend implementation details.
            if claimed_stage == "EXECUTING":
                # The executor may have committed before its response was lost.
                # Keep the original identity/version and reconcile idempotently.
                self._execution_uncertain(record)
            else:
                code = "MODEL_ERROR" if record.get("_model_inflight") else "DEPENDENCY_ERROR"
                self._finish(record, "FAILED", code, "A required service failed before execution.")
        record["_model_inflight"] = False
        record["_lease"] = None
        record["updated_at"] = iso(self.clock())
        changes = [("PLAN#" + plan_id, record, version)]
        if record.get("approval"):
            key = "APPROVAL#" + record["approval"]["approval_id"]
            av, existing = self.store.read(key)
            if existing is None:
                changes.append((key, {"plan_id": plan_id}, av))
        try:
            self.store.transact(changes)
        except Conflict:
            # A competing transition won. Execution remains protected by the
            # executor marker. Never overwrite a newer approval or result.
            return False
        if record["status"] in TERMINAL:
            self._release_active(plan_id)
        self.flush_audit(plan_id)
        return True

    def _candidate(self, record):
        candidate = record["candidates"][-1]
        if candidate.get("fingerprint") != fingerprint(candidate["plan"]):
            raise WorkflowError("PLAN_VALIDATION_FAILED", "Candidate changed after validation.")
        return candidate

    def _advance(self, record):
        stage = record["status"]
        if stage in {"PLANNING", "REPLANNING"}:
            started = self.clock()
            if stage == "PLANNING":
                plan = self.planner.generate_plan(record["instruction"], record["_snapshot"])
            else:
                previous = record["candidates"][-1]
                plan = self.planner.replan(record["instruction"], previous["plan"],
                                           previous["simulation"], record["_snapshot"], record["attempt"])
            record["candidates"].append({"revision": record["attempt"], "plan": copy.deepcopy(plan),
                                         "provenance": self.planner.provider.name,
                                         "authorization": None, "simulation": None,
                                         "metrics": copy.deepcopy(getattr(self.planner.provider, "metrics", {})),
                                         "generation_ms": max(0, (self.clock() - started) * 1000)})
            self._event(record, "PLAN_GENERATED" if stage == "PLANNING" else "REPLAN_GENERATED")
            record["status"] = "VALIDATING"
            return
        if stage == "VALIDATING":
            candidate = record["candidates"][-1]
            result = validate_plan(candidate["plan"])
            candidate["validation"] = result
            if result["valid"]:
                result = check_intent(candidate["plan"], record["_intent"])
                candidate["intent_validation"] = result
            if not result["valid"]:
                raise WorkflowError("PLAN_VALIDATION_FAILED", "Candidate structure or operator intent is invalid.")
            candidate["fingerprint"] = fingerprint(candidate["plan"])
            self._event(record, "VALIDATION_PASSED", "ALLOWED")
            record["status"] = "AUTHORIZING"
            return
        candidate = self._candidate(record)
        plan = candidate["plan"]
        if stage in {"AUTHORIZING", "REAUTHORIZING"}:
            if self.gateway.get_run_id() != record["_run_id"]:
                raise WorkflowError("VERSION_CONFLICT", "Demo run changed; evaluate again.", True, 409)
            result = self.gateway.authorize_plan(plan)
            if type(result.get("allowed")) is not bool or len(result.get("decisions", [])) != len(plan["actions"]):
                raise WorkflowError("AUTHORIZATION_DENIED", "Authorization data unavailable.")
            allowed = result["allowed"] and all(d.get("allowed") is True and d.get("action_index") == i
                                                for i, d in enumerate(result["decisions"]))
            candidate["authorization" if stage == "AUTHORIZING" else "reauthorization"] = result
            self._event(record, "AUTHORIZATION_ALLOWED" if allowed else "AUTHORIZATION_DENIED",
                        "ALLOWED" if allowed else "REJECTED",
                        None if allowed else "AUTHORIZATION_DENIED")
            if not allowed:
                raise WorkflowError("AUTHORIZATION_DENIED", "An action is not authorized.")
            record["status"] = "SIMULATING" if stage == "AUTHORIZING" else "REVALIDATING"
        elif stage in {"SIMULATING", "REVALIDATING"}:
            warehouse = record["_snapshot"] if stage == "SIMULATING" else self.gateway.get_warehouse()
            if warehouse["version"] != record["warehouse_version"]:
                raise WorkflowError("VERSION_CONFLICT", "Warehouse changed; evaluate again.", True, 409)
            result = self.gateway.simulate_plan(plan, warehouse)
            if type(result.get("passed")) is not bool or result.get("warehouse_version") != warehouse["version"]:
                raise WorkflowError("SIMULATION_FAILED", "Simulation data unavailable.")
            candidate["simulation" if stage == "SIMULATING" else "revalidation"] = result
            self._event(record, "SIMULATION_PASSED" if result["passed"] else "SIMULATION_FAILED",
                        "ALLOWED" if result["passed"] else "REJECTED",
                        None if result["passed"] else "SIMULATION_FAILED")
            if not result["passed"]:
                codes = {v.get("code") for v in result.get("violations", [])}
                if stage == "SIMULATING" and codes and codes <= REPLAN_CODES and record["_intent"]["flexible"]:
                    if record["attempt"] < 3:
                        record["status"] = "REPLANNING"
                        return
                    raise WorkflowError("MAX_ATTEMPTS_REACHED", "Three candidates failed simulation.")
                raise WorkflowError("SIMULATION_FAILED", "No permitted safe alternative was found.")
            if stage == "REVALIDATING":
                self._check_approval(record, candidate)
                record["status"] = "EXECUTING"
                return
            record["risk"] = classify_risk(plan)
            record["decision_latency_ms"] = max(0, (self.clock() - record["_created_at"]) * 1000)
            self._event(record, "RISK_CLASSIFIED", "ALLOWED")
            if record["risk"]["approval_required"]:
                deadline = self.clock() + self.approval_seconds
                record["approval"] = {"approval_id": "approval-" + uuid.uuid4().hex,
                                      "status": "PENDING", "revision": candidate["revision"],
                                      "fingerprint": candidate["fingerprint"],
                                      "warehouse_version": record["warehouse_version"],
                                      "run_id": record["_run_id"], "expires_epoch": deadline,
                                      "expires_at": iso(deadline)}
                record["status"] = "AWAITING_APPROVAL"
                self._event(record, "AWAITING_APPROVAL")
            else:
                record["status"] = "REAUTHORIZING"
        elif stage == "EXECUTING":
            self._check_approval(record, candidate)
            result = self.gateway.execute_plan(
                plan_id=record["plan_id"], revision=candidate["revision"], plan=plan,
                warehouse_version=record["warehouse_version"], run_id=record["_run_id"],
                approval=record["approval"])
            if isinstance(result, dict) and result.get("executed") is False and result.get("no_commit") is True:
                raise WorkflowError("EXECUTION_NOT_COMMITTED", "Executor confirmed no inventory commit.")
            if (not isinstance(result, dict) or result.get("executed") is not True
                    or result.get("status") != "COMPLETED"
                    or result.get("plan_id") != record["plan_id"]
                    or result.get("revision") != candidate["revision"]
                    or result.get("warehouse_version_before") != record["warehouse_version"]
                    or result.get("warehouse_version_after") != record["warehouse_version"] + 1):
                raise WorkflowError("EXECUTION_UNCONFIRMED", "Executor acknowledgment is missing or inconsistent.", True, 503)
            record["execution"] = result
            record["status"] = "COMPLETED"
            record["evaluation_ms"] = max(0, (self.clock() - record["_created_at"]
                                               - record.get("_approval_wait_seconds", 0)) * 1000)
            record["error"] = None
            record["reconciliation_required"] = False
            self._event(record, "PLAN_EXECUTED", "COMPLETED")
        else:
            raise WorkflowError("INTERNAL_ERROR", "Unexpected workflow stage.")

    def _check_approval(self, record, candidate):
        if not record["risk"]["approval_required"]:
            return
        approval = record.get("approval") or {}
        if (approval.get("status") != "APPROVED" or approval.get("revision") != candidate["revision"]
                or approval.get("fingerprint") != candidate["fingerprint"]
                or approval.get("warehouse_version") != record["warehouse_version"]
                or approval.get("run_id") != record["_run_id"]):
            raise WorkflowError("APPROVAL_REQUIRED", "A current approval is required.")

    def record_approval(self, approval_id, decision, admin):
        """Called only with identity established by Ishani's trusted HTTP layer."""
        if not isinstance(admin, str) or not admin.strip():
            raise WorkflowError("FORBIDDEN", "Administrator identity required.", status=403)
        if decision not in {"APPROVED", "DENIED"}:
            raise WorkflowError("INVALID_REQUEST", "decision must be APPROVED or DENIED.")
        _, index = self.store.read("APPROVAL#" + approval_id)
        if index is None:
            raise WorkflowError("NOT_FOUND", "Unknown approval_id.", status=404)
        plan_id = index["plan_id"]
        for _ in range(8):
            version, record = self._load(plan_id)
            approval = record["approval"]
            if approval["status"] in {"APPROVED", "DENIED"}:
                if approval["status"] != decision:
                    raise WorkflowError("APPROVAL_CONFLICT", "A different decision was already recorded.", status=409)
                self.deliver_callback(plan_id)
                return {"approval_id": approval_id, "status": "RECORDED"}
            if record["status"] != "AWAITING_APPROVAL":
                raise WorkflowError("APPROVAL_EXPIRED", "Approval is no longer actionable.", status=409)
            if self.clock() >= approval["expires_epoch"]:
                self.expire_approval(plan_id)
                raise WorkflowError("APPROVAL_EXPIRED", "Approval expired.", status=409)
            if (self.gateway.get_run_id() != record["_run_id"]
                    or self.gateway.get_warehouse()["version"] != record["warehouse_version"]):
                self.fail_plan(plan_id, "VERSION_CONFLICT", "Warehouse changed after review; evaluate again.")
                raise WorkflowError("VERSION_CONFLICT", "Warehouse changed after review; evaluate again.", True, 409)
            self._candidate(record)
            approval.update(status=decision, admin=admin, decision_at=iso(self.clock()))
            record["_approval_wait_seconds"] = max(0, self.clock() - (approval["expires_epoch"] - self.approval_seconds))
            record["status"] = "REAUTHORIZING" if decision == "APPROVED" else "REJECTED"
            if decision == "DENIED":
                record["error"] = {"code": "APPROVAL_DENIED", "message": "Administrator denied this plan.", "retryable": False}
            record["updated_at"] = iso(self.clock())
            self._event(record, "APPROVAL_" + decision, decision, admin=admin)
            try:
                self.store.write("PLAN#" + plan_id, record, version)
                if decision == "DENIED":
                    self._release_active(plan_id)
                self.flush_audit(plan_id)
                self.deliver_callback(plan_id)
                return {"approval_id": approval_id, "status": "RECORDED"}
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Approval changed concurrently.", True, 409)

    def register_callback(self, plan_id, token):
        if not token or not isinstance(token, str):
            raise WorkflowError("INVALID_REQUEST", "Callback token required.")
        for _ in range(8):
            version, record = self._load(plan_id)
            approval = record.get("approval") or {}
            decided = approval.get("status") in {"APPROVED", "DENIED"}
            if record["status"] != "AWAITING_APPROVAL" and not decided:
                raise WorkflowError("APPROVAL_EXPIRED", "Plan is not awaiting approval.", status=409)
            if self.gateway.get_run_id() != record["_run_id"]:
                raise WorkflowError("VERSION_CONFLICT", "Demo run changed; callback is invalid.", status=409)
            previous = approval.get("callback_token")
            if previous and previous != token:
                raise WorkflowError("APPROVAL_CONFLICT", "A different callback is already bound.", status=409)
            record["approval"]["callback_token"] = token
            try:
                self.store.write("PLAN#" + plan_id, record, version)
                self.deliver_callback(plan_id)
                return self.get_plan_status(plan_id)
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Callback registration changed concurrently.", True, 409)

    def deliver_callback(self, plan_id):
        """Record first, send second. Repeated delivery never changes the decision."""
        version, record = self._load(plan_id)
        approval = record.get("approval") or {}
        if (not self.callback_sender or not approval.get("callback_token")
                or approval.get("callback_delivered") or approval.get("status") not in {"APPROVED", "DENIED"}):
            return
        self.callback_sender(approval["callback_token"], approval["status"])
        approval["callback_delivered"] = True
        try:
            self.store.write("PLAN#" + plan_id, record, version)
        except Conflict:
            pass  # A retry may redeliver the same token, never a new decision.

    def expire_approval(self, plan_id):
        for _ in range(8):
            version, record = self._load(plan_id)
            if record["status"] != "AWAITING_APPROVAL":
                return self.get_plan_status(plan_id)
            if self.clock() < record["approval"]["expires_epoch"]:
                return self.get_plan_status(plan_id)
            record["approval"]["status"] = "EXPIRED"
            self._finish(record, "EXPIRED", "APPROVAL_EXPIRED", "Administrator approval deadline passed.")
            try:
                self.store.write("PLAN#" + plan_id, record, version)
                self._release_active(plan_id)
                return self.get_plan_status(plan_id)
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Expiry changed concurrently.", True, 409)

    def fail_plan(self, plan_id, code="INTERNAL_ERROR", message="Workflow failed safely."):
        for _ in range(8):
            version, record = self._load(plan_id)
            if record["status"] in TERMINAL:
                return self.get_plan_status(plan_id)
            if record["status"] == "EXECUTING":
                # A timed-out transport cannot cancel an already-running commit.
                record["reconciliation_required"] = True
                record["error"] = {"code": "EXECUTION_UNCONFIRMED", "retryable": True,
                                   "message": "Inspect and reconcile this execution ID; its outcome is unconfirmed."}
                self._event(record, "EXECUTION_UNCONFIRMED", "PENDING", "EXECUTION_UNCONFIRMED")
            else:
                self._finish(record, "FAILED", code, message)
                record["_lease"] = None
            try:
                self.store.write("PLAN#" + plan_id, record, version)
                if record["status"] in TERMINAL:
                    self._release_active(plan_id)
                return self.get_plan_status(plan_id)
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Failure update changed concurrently.", True, 409)

    def reconcile_execution(self, plan_id):
        """Trusted operator recovery: retry the SAME idempotent executor identity.

        Not a public execute endpoint. Wait for any previous lease to expire;
        active/reset protection remains in force until a definitive outcome.
        """
        version, record = self._load(plan_id)
        if record["status"] != "EXECUTING":
            return self.get_plan_status(plan_id)
        if record.get("_lease") and record["_lease"]["until"] > self.clock():
            raise WorkflowError("VERSION_CONFLICT", "Previous executor may still be running; wait for its lease.", True, 409)
        record["reconciliation_required"] = False
        record["_retry_after"] = 0
        self.store.write("PLAN#" + plan_id, record, version)
        self.tick(plan_id, owner="trusted-reconciliation")
        return self.get_plan_status(plan_id)

    def get_audit(self, plan_id=None):
        if plan_id:
            records = [self._load(plan_id)[1]]
        else:
            records = [value for _, _, value in self.store.list("PLAN#")]
        events = [copy.deepcopy(event) for record in records for event in record.get("_events", [])]
        return {"events": sorted(events, key=lambda e: (e["timestamp"], e["event_id"]), reverse=True)[:500]}

    def flush_audit(self, plan_id=None):
        """Deliver the durable event outbox through Mariam's idempotent sink.

        A commit/result is never repeated or relabeled because audit delivery
        failed. Sink deduplicates (plan_id,event_id); its acknowledgement may be
        lost before this delivery cursor is stored. Local fixtures read their
        canonical audit directly from workflow records and need no extra sink.
        """
        if self.audit_sink is None:
            return 0
        ids = [plan_id] if plan_id else [key[5:] for key, _, _ in self.store.list("PLAN#")]
        sent = 0
        for current in ids:
            for _ in range(500 - sent):
                _, record = self._load(current)
                # Delivery coordination must not modify a leased PLAN document:
                # an audit retry can run while a model/commit call is in flight.
                cursor_key = "AUDIT_CURSOR#" + current
                version, cursor = self.store.read(cursor_key)
                offset = cursor["offset"] if cursor else 0
                events = record.get("_events", [])
                if offset >= len(events):
                    break
                try:
                    self.audit_sink(copy.deepcopy(events[offset]))
                except Exception:
                    return sent  # Pending evidence remains durable for retry.
                try:
                    self.store.write(cursor_key, {"offset": offset + 1}, version)
                except Conflict:
                    continue
                sent += 1
        return sent

    def reset_demo(self, admin):
        if not admin:
            raise WorkflowError("FORBIDDEN", "Administrator identity required.", status=403)
        for active in self.store.read("CONTROL")[1]["active"]:
            if self._load(active)[1]["status"] in TERMINAL:
                self._release_active(active)
        version, control = self.store.read("CONTROL")
        if control["active"]:
            raise WorkflowError("VERSION_CONFLICT", "Cannot reset while any plan is active.", status=409)
        try:
            return self.gateway.reset_demo(version, control)
        except Conflict:
            raise WorkflowError("VERSION_CONFLICT", "A plan started during reset; retry later.", True, 409)
