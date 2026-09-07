#!/usr/bin/env python3
"""P5 — CLI wrapper for the PHYTbed orchestrator demo."""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware"))

from phytbed_orchestrator import demo as o_demo  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        prog="phytbed",
        description="P5 — PHYTbed: multi-protocol PHY testbed orchestrator.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output (accepted for CLI compatibility)")
    parser.add_argument("--seed", type=int, default=0x5EED, help="RNG seed for the demo (default: 0x5EED)")
    args = parser.parse_args()
    sys.exit(o_demo([str(args.seed)]))


if __name__ == "__main__":
    main()
