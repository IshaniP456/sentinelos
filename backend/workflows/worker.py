"""Docker-only scheduler for the durable local workflow. Author: Tishneet."""
import logging
import os
import signal
import threading
import uuid

from .factory import create_service


def main():
    if os.environ.get("SENTINEL_RUNTIME", "local") != "local":
        raise RuntimeError("Local worker must not schedule AWS-managed executions")
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    owner = "docker-" + uuid.uuid4().hex
    service = None
    while not stop.is_set():
        try:
            if service is None:
                service = create_service(runtime="local")
                logging.info("Local workflow ready; model and security/data adapters are labeled fixtures")
            changed = service.tick(owner=owner)
            service.flush_audit()
            stop.wait(0.15 if changed else 0.5)
        except Exception:
            # Retry storage availability without logging exception payloads.
            logging.error("Required workflow dependency unavailable; retrying safely")
            stop.wait(2)


if __name__ == "__main__":
    main()
