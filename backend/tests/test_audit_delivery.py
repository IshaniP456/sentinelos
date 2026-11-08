"""Durable audit outbox acceptance tests. Author: Tishneet."""
import unittest

from backend.ai.planner import Planner
from backend.ai.providers import FixtureProvider
from backend.workflows.fixtures import FixtureGateway
from backend.workflows.service import WorkflowService
from backend.workflows.store import MemoryStore


class AuditDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.gateway = FixtureGateway(self.store)

    def service(self, sink):
        return WorkflowService(self.store, Planner(FixtureProvider()), self.gateway, audit_sink=sink)

    def test_sink_outage_does_not_repeat_execution_and_recovers_after_restart(self):
        def outage(event):
            raise TimeoutError("Audit service unavailable")
        service = self.service(outage)
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        for _ in range(10):
            service.tick(plan_id)
        self.assertEqual(service.get_plan_status(plan_id)["status"], "COMPLETED")
        self.assertEqual(self.gateway.get_warehouse()["version"], 2)
        received = {}
        service = self.service(lambda event: received.setdefault(event["event_id"], event))
        delivered = service.flush_audit()
        self.assertEqual(delivered, len(service.get_audit(plan_id)["events"]))
        self.assertEqual(service.flush_audit(), 0)
        self.assertEqual(len(received), delivered)
        self.assertEqual(self.gateway.get_warehouse()["version"], 2)

    def test_lost_sink_ack_redelivers_same_event_identity(self):
        received = {}
        def sink(event):
            first = event["event_id"] not in received
            received[event["event_id"]] = event
            if first:
                raise TimeoutError("Acknowledgment lost")
        service = self.service(sink)
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        for _ in range(40):
            service.tick(plan_id)
            service.flush_audit(plan_id)
        events = service.get_audit(plan_id)["events"]
        self.assertEqual(set(received), {event["event_id"] for event in events})
        self.assertEqual(self.gateway.get_warehouse()["version"], 2)

    def test_public_status_excludes_outbox_cursor(self):
        service = self.service(lambda event: None)
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        service.flush_audit(plan_id)
        self.assertNotIn("_audit_delivered", service.get_plan_status(plan_id))

    def test_flush_updates_separate_cursor_without_changing_plan_version(self):
        received = {}
        service = self.service(lambda event: received.setdefault(event["event_id"], event))
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        before = self.store.read("PLAN#" + plan_id)
        self.assertEqual(service.flush_audit(plan_id), 1)
        self.assertEqual(self.store.read("PLAN#" + plan_id), before)
        cursor_version, cursor = self.store.read("AUDIT_CURSOR#" + plan_id)
        self.assertEqual(cursor_version, 1)
        self.assertEqual(cursor, {"offset": 1})
        self.assertEqual(service.flush_audit(plan_id), 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(self.store.read("PLAN#" + plan_id), before)

    def test_flush_during_model_call_does_not_lose_candidate_cas(self):
        received = {}
        observations = []

        class FlushingProvider(FixtureProvider):
            calls = 0
            service = None
            plan_id = None

            def generate(provider, *args, **kwargs):
                provider.calls += 1
                before = self.store.read("PLAN#" + provider.plan_id)
                delivered = provider.service.flush_audit(provider.plan_id)
                observations.append((before, self.store.read("PLAN#" + provider.plan_id), delivered))
                return super().generate(*args, **kwargs)

        provider = FlushingProvider()
        service = WorkflowService(self.store, Planner(provider), self.gateway,
                                  audit_sink=lambda event: received.setdefault(event["event_id"], event))
        provider.service = service
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        provider.plan_id = plan_id
        self.assertTrue(service.tick(plan_id))
        self.assertEqual(len(observations), 1)
        before, after, delivered = observations[0]
        self.assertGreater(delivered, 0)
        self.assertEqual(before, after, "delivery must not invalidate the model invocation's plan CAS")
        self.assertTrue(before[1]["_model_inflight"])
        status = service.get_plan_status(plan_id)
        self.assertEqual(status["status"], "VALIDATING")
        self.assertEqual(status["attempt"], 1)
        self.assertEqual(len(status["candidates"]), 1)
        for _ in range(15):
            service.tick(plan_id)
        completed = service.get_plan_status(plan_id)
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.gateway.get_warehouse()["version"], 2)
        self.assertEqual(set(received), {event["event_id"] for event in service.get_audit(plan_id)["events"]})
        self.assertEqual(service.flush_audit(plan_id), 0)

    def test_flush_during_executor_does_not_lose_completed_outcome_cas(self):
        received = {}
        observations = []
        sink_online = [False]

        def sink(event):
            if not sink_online[0]:
                raise TimeoutError("Sink unavailable until the executor is in flight")
            received.setdefault(event["event_id"], event)

        class FlushingExecutor(FixtureGateway):
            calls = 0
            service = None

            def execute_plan(gateway, **kwargs):
                gateway.calls += 1
                key = "PLAN#" + kwargs["plan_id"]
                before = self.store.read(key)
                sink_online[0] = True
                delivered = gateway.service.flush_audit(kwargs["plan_id"])
                observations.append((before, self.store.read(key), delivered))
                return super().execute_plan(**kwargs)

        gateway = FlushingExecutor(self.store)
        service = WorkflowService(self.store, Planner(FixtureProvider()), gateway,
                                  audit_sink=sink)
        gateway.service = service
        plan_id = service.start_plan("Move three packages from A to C.")["plan_id"]
        for _ in range(15):
            service.tick(plan_id)
        self.assertEqual(len(observations), 1)
        before, after, delivered = observations[0]
        self.assertGreater(delivered, 0, "the race requires a pending delivery cursor update")
        self.assertEqual(before, after, "delivery must not invalidate the executor's plan CAS")
        self.assertEqual(before[1]["status"], "EXECUTING")
        self.assertIsNotNone(before[1]["_lease"])
        completed = service.get_plan_status(plan_id)
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(completed["execution"]["warehouse_version_after"], 2)
        self.assertIsNone(completed["error"])
        self.assertEqual(gateway.calls, 1)
        self.assertEqual(self.gateway.get_warehouse()["version"], 2)
        self.assertEqual(self.gateway.get_warehouse()["zones"]["A"]["inventory"], 17)
        self.assertEqual(set(received), {event["event_id"] for event in service.get_audit(plan_id)["events"]})
        self.assertEqual(service.flush_audit(plan_id), 0)


if __name__ == "__main__":
    unittest.main()
