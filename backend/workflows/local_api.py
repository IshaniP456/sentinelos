"""Run Ishani's handlers on the Docker network. Author: Tishneet."""
import os
import time
from http.server import ThreadingHTTPServer

from backend.api.local_server import Proxy
from backend.api import backend_ops


def main():
    # Startup waits for DynamoDB Local; it never silently switches to memory.
    for attempt in range(30):
        try:
            backend_ops.get_backend()
            break
        except Exception:
            if attempt == 29:
                raise RuntimeError("Workflow storage unavailable at startup") from None
            time.sleep(1)
    host = os.environ.get("SENTINEL_API_HOST", "127.0.0.1")
    port = int(os.environ.get("SENTINEL_API_PORT", "8000"))
    print("Local fixture API on %s:%s; never deploy open authentication" % (host, port), flush=True)
    ThreadingHTTPServer((host, port), Proxy).serve_forever()


if __name__ == "__main__":
    main()
