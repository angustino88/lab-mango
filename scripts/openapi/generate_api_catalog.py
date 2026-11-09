"""Generate a readable API catalog JSON from the current OpenAPI schema."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "openapi",
        help="Directory for the generated API catalog (default: openapi).",
    )
    options = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django

    django.setup()

    from drf_spectacular.generators import SchemaGenerator

    from core.common.openapi.api_catalog import build_api_catalog

    schema = SchemaGenerator().get_schema(request=None, public=True)
    catalog = build_api_catalog(schema)
    output_dir = options.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "api-catalog.json"
    content = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"

    with NamedTemporaryFile("w", encoding="utf-8", dir=output_dir, delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
        temporary_file.write(content)
    temporary_path.replace(output_path)
    print(f"Generated API catalog with {catalog['total_endpoints']} endpoints: {output_path}")


if __name__ == "__main__":
    main()
