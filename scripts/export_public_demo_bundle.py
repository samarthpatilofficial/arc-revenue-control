"""Explicit read-only export of accepted public evaluator evidence."""

import argparse
from pathlib import Path

from arc.deployment import (
    DEFAULT_BUNDLE_PATH,
    PublicDemoBundleError,
    export_public_demo_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export sanitized ARC public-demo evidence"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_BUNDLE_PATH,
        help="Local gitignored output path",
    )
    args = parser.parse_args()
    try:
        result = export_public_demo_bundle(args.output)
    except PublicDemoBundleError:
        print("PUBLIC DEMO EXPORT: FAILED")
        print("Failure reason: accepted evidence validation failed")
        return 1
    print("PUBLIC DEMO EXPORT: COMPLETE")
    print(f"Path: {result.path}")
    print(f"Bundle version: {result.bundle_version}")
    print(f"Cases: {result.case_count}")
    print(f"Checksum prefix: {result.checksum_sha256[:12]}")
    print("Sanitization: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
