"""Own the workflow CONTROL fence around a remote reset. Author: Tishneet.

The gateway owns only the signed remote operation. It must not write CONTROL.
Unknown outcomes remain fenced across restarts; reconciliation never resends a
reset. There is deliberately no automatic fence expiry.
"""
import copy
import uuid
from datetime import datetime, timezone

from .errors import WorkflowError
from .gateway_contracts import normalize_run_id, gateway_failure, ADMIN_REFUSALS
from .store import Conflict

TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "EXPIRED"}


class ResetCoordinator:
    def __init__(self, store, gateway, clock):
        self.store, self.gateway, self.clock = store, gateway, clock

    @staticmethod
    def _admin(admin):
        if not isinstance(admin, str) or not admin.strip():
            raise WorkflowError("FORBIDDEN", "Verified administrator identity required.", status=403)

    def _stamp(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat().replace("+00:00", "Z")

    def _acquire(self, admin):
        for _ in range(8):
            version, control = self.store.read("CONTROL")
            if control.get("reset"):
                raise WorkflowError("RESET_IN_PROGRESS", "A reset is already active or unconfirmed.", status=409)
            active = []
            for plan_id in control["active"]:
                _, record = self.store.read("PLAN#" + plan_id)
                if not record or record["status"] not in TERMINAL:
                    active.append(plan_id)
            if active:
                raise WorkflowError("VERSION_CONFLICT", "Cannot reset while any plan is active.", status=409)
            control["active"] = []
            control["reset"] = {"reset_id": "reset-" + uuid.uuid4().hex,
                                "previous_run_id": control["run_id"], "admin": admin,
                                "requested_at": self._stamp(), "status": "IN_PROGRESS"}
            try:
                version = self.store.write("CONTROL", control, version)
                return version, control
            except Conflict:
                continue
        raise WorkflowError("VERSION_CONFLICT", "A plan or reset started concurrently; retry later.", True, 409)

    @staticmethod
    def _warehouse(value):
        if (not isinstance(value, dict) or not isinstance(value.get("warehouse_id"), str)
                or type(value.get("version")) is not int or value["version"] < 1
                or not isinstance(value.get("zones"), dict) or not value["zones"]):
            raise ValueError("Reset did not return a WarehouseState")
        for zone in value["zones"].values():
            if (not isinstance(zone, dict) or type(zone.get("inventory")) is not int
                    or type(zone.get("capacity")) is not int
                    or not 0 <= zone["inventory"] <= zone["capacity"]):
                raise ValueError("Reset returned invalid inventory")
        restricted = value.get("restricted_zones")
        if not isinstance(restricted, list) or not all(isinstance(zone, str) for zone in restricted):
            raise ValueError("Reset returned invalid restricted zones")
        # Return only the WarehouseState contract, never gateway debug metadata.
        return {"warehouse_id": value["warehouse_id"], "version": value["version"],
                "zones": {name: {"inventory": zone["inventory"], "capacity": zone["capacity"]}
                          for name, zone in value["zones"].items()},
                "restricted_zones": copy.deepcopy(restricted)}

    def _complete(self, reset_id, new_run_id, warehouse):
        for _ in range(8):
            version, control = self.store.read("CONTROL")
            fence = control.get("reset")
            if not fence or fence.get("reset_id") != reset_id:
                prior = control.get("last_reset") or {}
                if prior.get("reset_id") == reset_id:
                    return copy.deepcopy(prior["warehouse"])
                raise WorkflowError("RESET_CONFLICT", "Reset identity changed; inspect workflow state.", status=409)
            if new_run_id == fence["previous_run_id"] or control["active"]:
                raise WorkflowError("RESET_UNCONFIRMED", "Reset run rotation has not been confirmed.", status=503)
            control["run_id"] = new_run_id
            control["last_reset"] = {"reset_id": reset_id, "run_id": new_run_id,
                                     "previous_run_id": fence["previous_run_id"],
                                     "admin": fence["admin"], "completed_at": self._stamp(),
                                     "warehouse": copy.deepcopy(warehouse)}
            control["reset"] = None
            try:
                self.store.write("CONTROL", control, version)
                return warehouse
            except Conflict:
                continue
        raise WorkflowError("RESET_UNCONFIRMED", "Reset completion could not be persisted.", status=503)

    def _uncertain(self, reset_id):
        # Failure to save this annotation does not remove the original fence.
        for _ in range(8):
            try:
                version, control = self.store.read("CONTROL")
                fence = control.get("reset") or {}
                if fence.get("reset_id") != reset_id:
                    return
                fence["status"] = "UNCONFIRMED"
                self.store.write("CONTROL", control, version)
                return
            except Conflict:
                continue
            except Exception:
                return

    def _known_result(self, reset_id):
        try:
            _, control = self.store.read("CONTROL")
            prior = control.get("last_reset") or {}
            if prior.get("reset_id") == reset_id:
                return copy.deepcopy(prior["warehouse"])
        except Exception:
            pass
        return None

    def _release_refusal(self, reset_id, refusal):
        """Clear only this fence after the reset callee guarantees no mutation."""
        for _ in range(8):
            version, control = self.store.read("CONTROL")
            fence = control.get("reset") or {}
            if fence.get("reset_id") != reset_id:
                previous = control.get("last_reset_refusal") or {}
                return previous.get("reset_id") == reset_id
            control["last_reset_refusal"] = {
                "reset_id": reset_id, "run_id": fence["previous_run_id"],
                "admin": fence["admin"], "code": refusal.code,
                "retryable": refusal.retryable, "refused_at": self._stamp()}
            control["reset"] = None
            try:
                self.store.write("CONTROL", control, version)
                return True
            except Conflict:
                continue
            except Exception:
                # The cursor/fence write itself may have committed before its
                # acknowledgement was lost. Confirm that exact refusal marker.
                _, latest = self.store.read("CONTROL")
                return (latest.get("last_reset_refusal") or {}).get("reset_id") == reset_id
        return False

    def _raise_uncertain(self, reset_id):
        self._uncertain(reset_id)
        known = self._known_result(reset_id)
        if known is not None:
            return known
        raise WorkflowError("RESET_UNCONFIRMED",
                            "Reset outcome is unconfirmed; reconcile " + reset_id + " before new submissions.",
                            status=503) from None

    def reset(self, admin):
        self._admin(admin)
        version, control = self._acquire(admin)
        reset_id = control["reset"]["reset_id"]
        try:
            response = self.gateway.reset_demo(version, copy.deepcopy(control), admin)
        except Exception as error:
            # no_commit belongs to THIS mutation call, not a later read. A
            # get_run_id failure after a successful reset cannot clear the fence.
            refusal = gateway_failure(error, confirmed_only=True)
            released = False
            if refusal:
                try:
                    released = self._release_refusal(reset_id, refusal)
                except Exception:
                    pass
            if released:
                raise refusal from None
            return self._raise_uncertain(reset_id)
        try:
            warehouse = self._warehouse(response)
            run_id = normalize_run_id(self.gateway.get_run_id())
            return self._complete(reset_id, run_id, warehouse)
        except Exception:
            return self._raise_uncertain(reset_id)

    def reconcile(self, reset_id, admin):
        """Trusted recovery only: inspect current state; never replay a reset call."""
        self._admin(admin)
        _, control = self.store.read("CONTROL")
        fence = control.get("reset") or {}
        if fence.get("reset_id") != reset_id:
            prior = control.get("last_reset") or {}
            if prior.get("reset_id") == reset_id:
                return copy.deepcopy(prior["warehouse"])
            refusal = control.get("last_reset_refusal") or {}
            if refusal.get("reset_id") == reset_id and refusal.get("code") in ADMIN_REFUSALS:
                message, status = ADMIN_REFUSALS[refusal["code"]]
                raise WorkflowError(refusal["code"], message, refusal.get("retryable") is True, status)
            raise WorkflowError("RESET_CONFLICT", "Unknown reset identity.", status=409)
        try:
            run_id = normalize_run_id(self.gateway.get_run_id())
            warehouse = self._warehouse(self.gateway.get_warehouse())
            return self._complete(reset_id, run_id, warehouse)
        except Exception:
            self._uncertain(reset_id)
            known = self._known_result(reset_id)
            if known is not None:
                return known
            raise WorkflowError("RESET_UNCONFIRMED", "Reset is not yet confirmed; submissions remain blocked.", status=503) from None
