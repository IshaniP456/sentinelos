"""The integration seam between Ishani's HTTP layer and the trusted backend.

Handlers call a ``BackendOps`` instance; they never talk to Bedrock, Step
Functions, DynamoDB, or Verified Permissions directly. This keeps the security
boundary clean (contract §5.2): the HTTP layer authenticates/authorizes and
forwards to trusted operations owned by Mariam and Tishneet.

Two implementations:

* ``LocalBackendOps`` — a self-contained reference that mirrors the frozen
  contract and the three judged demos (D1/D2/D3) with exact inventory
  outcomes. Use it to run and test the real handler code *today*, before the
  AWS backend exists. It is the "temporary trusted backend handler using the
  same API contract" the timeline calls for at the 4 PM milestone.

* ``AwsBackendOps`` — TODO stub. Each method documents exactly which trusted
  function / service it will invoke. Fill these in as teammates' pieces land;
  the HTTP layer and the frontend do not change.
"""

import copy
import os
import time

from .responses import ApiError

# ---------------------------------------------------------------------------
# Frozen seed state (contract §2). Kept in sync with the frontend mock.
# ---------------------------------------------------------------------------
SEED_WAREHOUSE = {
    "warehouse_id": "demo-warehouse",
    "version": 1,
    "zones": {
        "A": {"inventory": 20, "capacity": 30},
        "B": {"inventory": 8, "capacity": 10},
        "C": {"inventory": 5, "capacity": 20},
    },
    "restricted_zones": ["HAZMAT"],
}
SEED_AGENT = {
    "agent_id": "inventory-agent-01",
    "status": "ACTIVE",
    "role": "INVENTORY_MANAGER",
    "max_transfer": 10,
}
TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "EXPIRED"}


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class BackendOps:
    """Interface the HTTP handlers depend on."""

    def start_plan(self, instruction):  # -> {"plan_id", "status"}
        raise NotImplementedError

    def get_plan_status(self, plan_id):  # -> PlanStatus (§5.1)
        raise NotImplementedError

    def get_warehouse(self):  # -> WarehouseState (§2.1)
        raise NotImplementedError

    def get_agent(self):  # -> AgentRecord (§2.2)
        raise NotImplementedError

    def get_audit(self, plan_id=None):  # -> {"events": [AuditEvent]}
        raise NotImplementedError

    def record_approval(self, approval_id, decision, admin):  # -> {"approval_id","status"}
        raise NotImplementedError

    def revoke_agent(self, admin):  # -> AgentRecord
        raise NotImplementedError

    def reset_demo(self, admin):  # -> WarehouseState
        raise NotImplementedError


class LocalBackendOps(BackendOps):
    """Reference backend mirroring the contract and the three demos."""

    def __init__(self):
        self.warehouse = copy.deepcopy(SEED_WAREHOUSE)
        self.agent = copy.deepcopy(SEED_AGENT)
        self.plans = {}
        self.audit = []
        self._plan_n = 0
        self._appr_n = 0
        self._seq = 0

    # --- helpers -----------------------------------------------------------
    def _push_audit(self, plan_id, revision, event_type, outcome, reason_code, message, admin=None):
        self._seq += 1
        ev = {
            "plan_id": plan_id,
            "event_id": f"{_iso(time.time())}#{self._seq:04d}",
            "timestamp": _iso(time.time()),
            "revision": revision,
            "event_type": event_type,
            "outcome": outcome,
            "reason_code": reason_code,
            "message": message,
        }
        if admin:
            ev["admin"] = admin
        self.audit.insert(0, ev)

    def _project(self, zones, actions):
        z = copy.deepcopy(zones)
        for a in actions:
            if a["from"] in z:
                z[a["from"]]["inventory"] -= a["count"]
            if a["to"] in z:
                z[a["to"]]["inventory"] += a["count"]
        return z

    def _authorize(self, actions):
        decisions = []
        for i, a in enumerate(actions):
            if self.agent["status"] != "ACTIVE":
                rc, allowed = "AGENT_REVOKED", False
            elif a["count"] > self.agent["max_transfer"]:
                rc, allowed = "LIMIT_EXCEEDED", False
            elif a["to"] in self.warehouse["restricted_zones"]:
                rc, allowed = "RESTRICTED_DESTINATION", False
            else:
                rc, allowed = "POLICY_ALLOWED", True
            decisions.append({"action_index": i, "allowed": allowed, "reason_code": rc})
        return {"allowed": all(d["allowed"] for d in decisions), "decisions": decisions}

    def _simulate(self, actions):
        projected = self._project(self.warehouse["zones"], actions)
        violations = []
        for i, a in enumerate(actions):
            to = projected.get(a["to"])
            frm = projected.get(a["from"])
            if to and to["inventory"] > to["capacity"]:
                violations.append({"code": "CAPACITY_EXCEEDED", "action_index": i,
                                   "zone": a["to"], "projected": to["inventory"], "capacity": to["capacity"]})
            if frm and frm["inventory"] < 0:
                violations.append({"code": "INSUFFICIENT_SOURCE", "action_index": i,
                                   "zone": a["from"], "projected": frm["inventory"], "capacity": frm["capacity"]})
        passed = not violations
        return {
            "passed": passed,
            "warehouse_version": self.warehouse["version"],
            "reason": None if passed else f"Zone {violations[0]['zone']} would exceed capacity",
            "violations": violations,
            "projected_state": projected,
        }

    @staticmethod
    def _risk(actions):
        total = sum(a["count"] for a in actions)
        return {"risk": "ELEVATED" if total >= 5 else "LOW",
                "approval_required": total >= 5, "total_packages": total}

    # --- scenario detection (contract §10) ---------------------------------
    _WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

    def _parse_simple(self, instruction):
        import re
        t = instruction.lower()
        m = re.search(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+packages?", t)
        f = re.search(r"from\s+(?:zone\s+)?([abc])", t)
        d = re.search(r"to\s+(?:zone\s+)?([abc])", t)
        if m and f and d:
            raw = m.group(1)
            count = self._WORDS.get(raw, None) or int(raw)
            return [{"type": "move_packages", "from": f.group(1).upper(),
                     "to": d.group(1).upper(), "count": count}]
        return None

    def _detect(self, instruction):
        t = instruction.lower()
        preflight = "preflight" in t or "a → b x5" in t or "a->b x5" in t
        split = ("preferably" in t and "another zone" in t) or ("out of" in t and "zone b" in t)
        if preflight or split:
            return {"kind": "REPLAN_APPROVE", "candidates": [
                [{"type": "move_packages", "from": "A", "to": "B", "count": 5}],
                [{"type": "move_packages", "from": "A", "to": "B", "count": 2},
                 {"type": "move_packages", "from": "A", "to": "C", "count": 3}],
            ]}
        simple = self._parse_simple(instruction)
        if simple:
            kind = "APPROVE" if self._risk(simple)["approval_required"] else "AUTO"
            return {"kind": kind, "candidates": [simple]}
        return {"kind": "AUTO", "candidates": [[{"type": "move_packages", "from": "A", "to": "C", "count": 1}]]}

    @staticmethod
    def _phase(elapsed, phases):
        acc = 0.0
        for name, dur in phases:
            acc += dur
            if elapsed < acc:
                return name
        return phases[-1][0]

    def _commit(self, plan, idx):
        if plan.get("executed"):
            return
        plan["executed"] = True
        cand = plan["candidates"][idx]
        before = self.warehouse["version"]
        self.warehouse["zones"] = self._project(self.warehouse["zones"], cand["plan"]["actions"])
        self.warehouse["version"] += 1
        plan["execution"] = {
            "plan_id": plan["plan_id"], "revision": cand["revision"], "executed": True,
            "status": "COMPLETED", "warehouse_version_before": before,
            "warehouse_version_after": self.warehouse["version"],
            "warehouse": copy.deepcopy(self.warehouse),
        }

    def _once(self, plan, key, fn):
        seen = plan.setdefault("seen", set())
        if key not in seen:
            seen.add(key)
            fn()

    def _audit_progress(self, plan, status):
        second = len(plan["candidates"]) > 1
        if status == "AUTHORIZING":
            self._once(plan, "sub", lambda: self._push_audit(plan["plan_id"], 1, "PLAN_SUBMITTED", "PENDING", None, "Operator instruction received"))
            self._once(plan, "gen", lambda: self._push_audit(plan["plan_id"], 1, "BEDROCK_PLAN_GENERATED", "PENDING", None, "AI generated candidate plan"))
        elif status == "SIMULATING":
            self._once(plan, "auth1", lambda: self._push_audit(plan["plan_id"], 1, "AUTHORIZATION_ALLOWED", "ALLOWED", "POLICY_ALLOWED", "All actions authorized"))
        elif status == "REPLANNING":
            self._once(plan, "simfail", lambda: self._push_audit(plan["plan_id"], 1, "SIMULATION_FAILED", "REJECTED", "CAPACITY_EXCEEDED", "Projected Zone B inventory is 13, capacity is 10"))
        elif status == "AWAITING_APPROVAL":
            if second:
                self._once(plan, "replan", lambda: self._push_audit(plan["plan_id"], 2, "REPLAN_GENERATED", "PENDING", None, "AI generated revised plan"))
                self._once(plan, "simp2", lambda: self._push_audit(plan["plan_id"], 2, "SIMULATION_PASSED", "ALLOWED", None, "Revised plan respects all capacities"))
            else:
                self._once(plan, "simp1", lambda: self._push_audit(plan["plan_id"], 1, "SIMULATION_PASSED", "ALLOWED", None, "Plan respects all capacities"))
            self._once(plan, "await", lambda: self._push_audit(plan["plan_id"], 2 if second else 1, "AWAITING_APPROVAL", "PENDING", None, "Elevated risk — human approval required"))
        elif status == "COMPLETED":
            self._once(plan, "exec", lambda: self._push_audit(plan["plan_id"], 2 if second else 1, "PLAN_EXECUTED", "COMPLETED", None, "Plan executed; warehouse updated"))
        elif status == "REJECTED" and plan.get("approval_decision") == "DENIED":
            self._once(plan, "deny", lambda: self._push_audit(plan["plan_id"], 2 if second else 1, "APPROVAL_DENIED", "REJECTED", "APPROVAL_DENIED", "Operator denied the plan", plan.get("admin")))

    def _build_status(self, plan):
        elapsed = time.time() - plan["started_at"]
        if plan.get("rejected_auth"):
            return {
                "plan_id": plan["plan_id"], "status": "REJECTED", "agent_id": plan["agent_id"],
                "instruction": plan["instruction"], "attempt": 1,
                "warehouse_version": self.warehouse["version"],
                "candidates": plan["candidates"][:1], "risk": None, "approval": None,
                "execution": None, "updated_at": _iso(time.time()),
            }
        kind = plan["scenario"]["kind"]
        attempt, show, approval = 1, 0, None
        if kind == "AUTO":
            status = self._phase(elapsed, [("PLANNING", 1), ("AUTHORIZING", 1), ("SIMULATING", 1), ("EXECUTING", 1), ("COMPLETED", float("inf"))])
            show = 0 if status == "PLANNING" else 1
            if status == "COMPLETED":
                self._commit(plan, 0)
        elif kind == "APPROVE":
            if plan.get("approval_decision") == "DENIED":
                status, show = "REJECTED", 1
            elif plan.get("approval_decision") == "APPROVED":
                status = self._phase(time.time() - plan["approved_at"], [("REAUTHORIZING", 0.8), ("EXECUTING", 1), ("COMPLETED", float("inf"))])
                show = 1
                if status == "COMPLETED":
                    self._commit(plan, 0)
            else:
                status = self._phase(elapsed, [("PLANNING", 1), ("AUTHORIZING", 1), ("SIMULATING", 1), ("AWAITING_APPROVAL", float("inf"))])
                show = 0 if status == "PLANNING" else 1
        else:  # REPLAN_APPROVE
            if plan.get("approval_decision") == "DENIED":
                status, show = "REJECTED", 2
            elif plan.get("approval_decision") == "APPROVED":
                status = self._phase(time.time() - plan["approved_at"], [("REAUTHORIZING", 0.8), ("EXECUTING", 1), ("COMPLETED", float("inf"))])
                show = 2
                if status == "COMPLETED":
                    self._commit(plan, 1)
            else:
                status = self._phase(elapsed, [("PLANNING", 1), ("AUTHORIZING", 1), ("SIMULATING", 1), ("REPLANNING", 1.5), ("AWAITING_APPROVAL", float("inf"))])
                attempt = 1 if status in ("PLANNING", "AUTHORIZING", "SIMULATING") else 2
                show = 0 if status == "PLANNING" else (2 if status == "AWAITING_APPROVAL" else 1)

        self._audit_progress(plan, status)
        exec_idx = 1 if kind == "REPLAN_APPROVE" else 0
        exec_cand = plan["candidates"][exec_idx]
        if status == "AWAITING_APPROVAL":
            approval = {"approval_id": plan["approval_id"], "status": "PENDING", "revision": exec_cand["revision"]}
        risk = self._risk(exec_cand["plan"]["actions"]) if show > 0 else None
        return {
            "plan_id": plan["plan_id"], "status": status, "agent_id": plan["agent_id"],
            "instruction": plan["instruction"], "attempt": attempt,
            "warehouse_version": self.warehouse["version"],
            "candidates": plan["candidates"][:show],
            "risk": None if status == "PLANNING" else risk,
            "approval": approval, "execution": plan.get("execution"),
            "updated_at": _iso(time.time()),
        }

    # --- BackendOps surface ------------------------------------------------
    def start_plan(self, instruction):
        if not instruction or not instruction.strip():
            raise ApiError("INVALID_REQUEST", "Instruction must not be empty.")
        self._plan_n += 1
        plan_id = f"plan-{self._plan_n:03d}"
        scenario = self._detect(instruction)
        candidates = []
        for i, actions in enumerate(scenario["candidates"]):
            candidates.append({
                "revision": i + 1,
                "plan": {"actions": actions},
                "authorization": self._authorize(actions),
                "simulation": self._simulate(actions),
            })
        self._appr_n += 1
        plan = {
            "plan_id": plan_id, "agent_id": self.agent["agent_id"], "instruction": instruction,
            "scenario": scenario, "candidates": candidates, "started_at": time.time(),
            "approval_id": f"approval-{self._appr_n:03d}", "approval_decision": None,
            "executed": False, "execution": None,
            "rejected_auth": self.agent["status"] != "ACTIVE",
        }
        if plan["rejected_auth"]:
            self._push_audit(plan_id, 1, "AUTHORIZATION_DENIED", "REJECTED", "AGENT_REVOKED", "Agent is revoked; plan denied")
        self.plans[plan_id] = plan
        return {"plan_id": plan_id, "status": "PLANNING"}

    def get_plan_status(self, plan_id):
        plan = self.plans.get(plan_id)
        if not plan:
            raise ApiError("NOT_FOUND", "Unknown plan_id.")
        return self._build_status(plan)

    def get_warehouse(self):
        return copy.deepcopy(self.warehouse)

    def get_agent(self):
        return copy.deepcopy(self.agent)

    def get_audit(self, plan_id=None):
        events = [e for e in self.audit if e["plan_id"] == plan_id] if plan_id else self.audit
        return {"events": copy.deepcopy(events)}

    def record_approval(self, approval_id, decision, admin):
        if decision not in ("APPROVED", "DENIED"):
            raise ApiError("INVALID_REQUEST", "decision must be APPROVED or DENIED.")
        plan = next((p for p in self.plans.values() if p["approval_id"] == approval_id), None)
        if not plan:
            raise ApiError("NOT_FOUND", "Unknown approval_id.")
        # Idempotent: first decision wins; repeats cannot double-execute (§3.5).
        if not plan.get("approval_decision"):
            plan["approval_decision"] = decision
            plan["admin"] = admin
            if decision == "APPROVED":
                plan["approved_at"] = time.time()
        return {"approval_id": approval_id, "status": "RECORDED"}

    def revoke_agent(self, admin):
        self.agent["status"] = "REVOKED"
        self._push_audit("—", 0, "AGENT_REVOKED", "REVOKED", "ADMIN_REVOCATION",
                         "Administrator revoked inventory-agent-01", admin)
        return copy.deepcopy(self.agent)

    def reset_demo(self, admin):
        # FR13: refuse while any workflow is active or awaiting approval.
        for p in self.plans.values():
            st = self._build_status(p)["status"]
            if st not in TERMINAL:
                raise ApiError("VERSION_CONFLICT", "Cannot reset while a plan is active.", status=409)
        self.__init__()
        return copy.deepcopy(self.warehouse)


class AwsBackendOps(BackendOps):
    """Production seam — fill in as teammates' services land. Each method notes
    the trusted operation it must invoke. The HTTP layer never changes."""

    def start_plan(self, instruction):
        # TODO(Tishneet): StartExecution on the planning Step Functions state
        # machine with input {"instruction": instruction, "agent_id": <trusted>}.
        # Return {"plan_id": <execution name>, "status": "PLANNING"}.
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def get_plan_status(self, plan_id):
        # TODO(Tishneet): read workflow status + candidate history; shape to §5.1.
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def get_warehouse(self):
        # TODO(Mariam): get_warehouse() from DynamoDB (§2.1).
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def get_agent(self):
        # TODO(Mariam): get_agent() from DynamoDB (§2.2).
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def get_audit(self, plan_id=None):
        # TODO(Mariam): query sentinel_audit (indexed, not a full scan — §5.2).
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def record_approval(self, approval_id, decision, admin):
        # TODO(Tishneet/Mariam): resolve approval_id -> stored task token and
        # SendTaskSuccess/Failure on Step Functions. Token stays server-side
        # (contract §8/NFR01). Record deciding admin in the approval record.
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def revoke_agent(self, admin):
        # TODO(Mariam): trusted revoke_agent() — set status REVOKED in DynamoDB.
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)

    def reset_demo(self, admin):
        # TODO(Mariam): reset only when no active workflows (FR13).
        raise ApiError("INTERNAL_ERROR", "AWS backend not wired yet.", status=501)


_SINGLETON = None


def get_backend():
    """Return the configured BackendOps. ``SENTINEL_BACKEND=local`` (default)
    uses the in-process reference; ``aws`` uses the production seam."""
    global _SINGLETON
    if _SINGLETON is None:
        mode = os.environ.get("SENTINEL_BACKEND", "local")
        _SINGLETON = AwsBackendOps() if mode == "aws" else LocalBackendOps()
    return _SINGLETON
