"""Generate standalone full OpenAPI specification files (YAML and JSON)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "openapi",
        help="Directory for the generated OpenAPI documents (default: openapi).",
    )
    parser.add_argument(
        "--yaml-name",
        default="openapi-full.yml",
        help="Filename for the full YAML specification (default: openapi-full.yml).",
    )
    parser.add_argument(
        "--json-name",
        default="openapi-full.json",
        help="Filename for the full JSON specification (default: openapi-full.json).",
    )
    options = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django

    django.setup()

    from drf_spectacular.generators import SchemaGenerator

    from core.common.openapi.api_catalog import normalize_schema_metadata

    schema = SchemaGenerator().get_schema(request=None, public=True)
    schema = normalize_schema_metadata(schema)

    output_dir = options.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if options.yaml_name:
        yaml_path = output_dir / options.yaml_name
        yaml_content = yaml.safe_dump(schema, sort_keys=False, allow_unicode=False)
        with NamedTemporaryFile("w", encoding="utf-8", dir=output_dir, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(yaml_content)
        temporary_path.replace(yaml_path)
        print(f"Generated full OpenAPI YAML specification: {yaml_path}")

    if options.json_name:
        json_path = output_dir / options.json_name
        json_content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        with NamedTemporaryFile("w", encoding="utf-8", dir=output_dir, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(json_content)
        temporary_path.replace(json_path)
        print(f"Generated full OpenAPI JSON specification: {json_path}")


if __name__ == "__main__":
    main()
