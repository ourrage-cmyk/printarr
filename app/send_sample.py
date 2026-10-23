"""Send sample jobs to any ESC/POS TCP target: the real printer or the simulator.

    python -m app.send_sample 127.0.0.1 9100
"""

from __future__ import annotations

import socket
import sys

from tests.test_golden import CASES


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9100
    for name, make in CASES.items():
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(make())
        print(f"sent {name} to {host}:{port}")


if __name__ == "__main__":
    main()
