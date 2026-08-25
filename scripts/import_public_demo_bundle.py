"""Operator-only import into an empty migrated public-demo database."""

import argparse
from pathlib import Path

from arc.deployment import (
    PublicDemoAlreadyImportedError,
    PublicDemoImportError,
    import_public_demo_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a sanitized ARC public-demo bundle"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = import_public_demo_bundle(args.bundle)
    except PublicDemoAlreadyImportedError:
        print("PUBLIC DEMO IMPORT: ALREADY IMPORTED")
        return 2
    except PublicDemoImportError:
        print("PUBLIC DEMO IMPORT: FAILED")
        print("Failure reason: bundle or target database validation failed")
        return 1
    print("PUBLIC DEMO IMPORT: COMPLETE")
    print(f"Bundle version: {result.bundle_version}")
    print(f"Cases: {result.case_count}")
    print(f"Checksum prefix: {result.checksum_sha256[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
