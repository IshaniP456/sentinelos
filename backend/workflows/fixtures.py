"""Explicit LOCAL TEST security/data adapter, not Verified Permissions.

Author: Tishneet. Mariam owns the actual security/data implementation. This
adapter reuses her simulator and stores a synthetic warehouse in one CAS item.
It cannot be selected by the AWS factory.
"""
import copy
import uuid

from backend.core.simulator import simulate_plan
from backend.ai.validation import fingerprint
from .errors import WorkflowError
from .store import Conflict

SEED_WAREHOUSE = {
    "warehouse_id": "demo-warehouse", "version": 1,
    "zones": {"A": {"inventory": 20, "capacity": 30},
              "B": {"inventory": 8, "capacity": 10},
              "C": {"inventory": 5, "capacity": 20}},
    "restricted_zones": ["HAZMAT"],
}
SEED_AGENT = {"agent_id": "inventory-agent-01", "status": "ACTIVE",
              "role": "INVENTORY_MANAGER", "max_transfer": 10}


def seed_world():
    return {"warehouse": copy.deepcopy(SEED_WAREHOUSE),
            "agent": copy.deepcopy(SEED_AGENT), "run_id": uuid.uuid4().hex,
            "executions": {}}


class FixtureGateway:
    """Durable synthetic data, authorization and executor for local tests only."""
    name = "LOCAL_FIXTURE"

    def __init__(self, store):
        self.store = store
        version, world = store.read("WORLD")
        if world is None:
            try:
                store.write("WORLD", seed_world(), version)
            except Conflict:
                pass

    def get_warehouse(self):
        return self.store.read("WORLD")[1]["warehouse"]

    def get_agent(self):
        return self.store.read("WORLD")[1]["agent"]

    def get_run_id(self):
        return self.store.read("WORLD")[1]["run_id"]

    def authorize_plan(self, plan):
        agent = self.get_agent()
        decisions = []
        for i, action in enumerate(plan["actions"]):
            if agent["status"] != "ACTIVE":
                code = "AGENT_REVOKED"
            elif agent.get("role") != "INVENTORY_MANAGER":
                code = "ROLE_DENIED"
            elif action["count"] > agent["max_transfer"]:
                code = "LIMIT_EXCEEDED"
            elif action["to"] == "HAZMAT":
                code = "RESTRICTED_DESTINATION"
            else:
                code = "POLICY_ALLOWED"
            decisions.append({"action_index": i, "allowed": code == "POLICY_ALLOWED",
                              "reason_code": code})
        return {"allowed": all(d["allowed"] for d in decisions), "decisions": decisions}

    def simulate_plan(self, plan, warehouse):
        return simulate_plan(plan, warehouse)

    def execute_plan(self, *, plan_id, revision, plan, warehouse_version,
                     run_id, approval):
        """Atomic fixture commit; marker and inventory share one conditional item."""
        version, world = self.store.read("WORLD")
        if world["run_id"] != run_id:
            raise WorkflowError("VERSION_CONFLICT", "Demo run changed; evaluate again.", True, 409)
        marker = "%s#%s" % (plan_id, revision)
        prior = world["executions"].get(marker)
        digest = fingerprint(plan)
        if prior:
            if prior["fingerprint"] != digest:
                raise WorkflowError("VERSION_CONFLICT", "Execution identity changed.", False, 409)
            return copy.deepcopy(prior["result"])
        if not self.authorize_plan(plan)["allowed"]:
            raise WorkflowError("AUTHORIZATION_DENIED", "Agent is no longer authorized.")
        warehouse = world["warehouse"]
        if warehouse["version"] != warehouse_version:
            raise WorkflowError("VERSION_CONFLICT", "Warehouse changed; evaluate again.", True, 409)
        total = sum(a["count"] for a in plan["actions"])
        if total >= 5 and (not approval or approval.get("status") != "APPROVED"
                           or approval.get("revision") != revision
                           or approval.get("fingerprint") != digest
                           or approval.get("warehouse_version") != warehouse_version
                           or approval.get("run_id") != run_id):
            raise WorkflowError("APPROVAL_REQUIRED", "A current matching approval is required.")
        simulation = simulate_plan(plan, warehouse)
        if not simulation["passed"]:
            raise WorkflowError("SIMULATION_FAILED", "Current inventory does not permit execution.")
        warehouse["zones"] = simulation["projected_state"]
        warehouse["version"] += 1
        result = {"plan_id": plan_id, "revision": revision, "executed": True,
                  "status": "COMPLETED", "warehouse_version_before": warehouse_version,
                  "warehouse_version_after": warehouse["version"],
                  "warehouse": copy.deepcopy(warehouse)}
        world["executions"][marker] = {"fingerprint": digest, "result": result}
        try:
            self.store.write("WORLD", world, version)
        except Conflict:
            # A concurrent execution/revocation must never be overwritten.
            latest = self.store.read("WORLD")[1]
            prior = latest["executions"].get(marker)
            if latest["run_id"] == run_id and prior and prior["fingerprint"] == digest:
                return prior["result"]
            raise WorkflowError("VERSION_CONFLICT", "Warehouse or agent changed during commit.", True, 409)
        return result

    def revoke_agent(self, admin):
        if not admin:
            raise WorkflowError("FORBIDDEN", "Administrator identity required.", status=403)
        for _ in range(8):
            version, world = self.store.read("WORLD")
            world["agent"]["status"] = "REVOKED"
            try:
                self.store.write("WORLD", world, version)
                return world["agent"]
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "Agent changed concurrently.", True, 409)

    def reset_demo(self, control_version, control):
        version, world = self.store.read("WORLD")
        new_world = seed_world()
        control["run_id"] = new_world["run_id"]
        self.store.transact([("WORLD", new_world, version),
                             ("CONTROL", control, control_version)])
        return new_world["warehouse"]
