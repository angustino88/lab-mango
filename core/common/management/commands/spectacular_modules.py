import copy
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.urls import URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema
from jsonschema.exceptions import ValidationError

from core.common.openapi.api_catalog import build_api_catalog, normalize_schema_metadata

API_CATALOG_FILENAME = "api-catalog.json"
COMPONENTS_FILENAME = "components.yml"
DEFAULT_MASTER_FILENAME = "openapi.yml"
FULL_JSON_FILENAME = "openapi-full.json"


class Command(BaseCommand):
    help = "Generate deterministic OpenAPI master, component, and feature module documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default="openapi",
            help="Directory for generated OpenAPI documents (default: openapi).",
        )
        parser.add_argument(
            "--include-untagged",
            action="store_true",
            help="Write paths outside feature URL modules to untagged.yml instead of failing.",
        )
        parser.add_argument(
            "--master-file",
            default=DEFAULT_MASTER_FILENAME,
            help=f"Master document filename inside the output directory (default: {DEFAULT_MASTER_FILENAME}).",
        )
        parser.add_argument(
            "--full-file",
            default=None,
            help="Optional filename for a full merged YAML document inside the output directory (default: none; full schema is emitted as JSON).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report generated files without modifying the output directory.",
        )
        parser.add_argument(
            "--no-clean",
            action="store_true",
            help="Keep previously generated YAML files that are not part of this run.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Validate schemas and fail on missing, extra, or changed YAML/JSON files; never write files.",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Validate all generated schemas and offline references before writing (also implied by --check).",
        )

    def handle(self, *args, **options):
        if options.get("check") and (options.get("dry_run") or options.get("no_clean")):
            raise CommandError("--check cannot be combined with --dry-run or --no-clean.")
        schema = SchemaGenerator().get_schema(request=None, public=True)
        try:
            schema = normalize_schema_metadata(schema)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        modules = self._split_schema(schema, options["include_untagged"])
        output_dir = Path(options["output_dir"])
        master_filename = options["master_file"]
        if master_filename == API_CATALOG_FILENAME:
            raise CommandError(
                f"API catalog filename conflicts with the master document: {API_CATALOG_FILENAME}"
            )
        if master_filename == COMPONENTS_FILENAME:
            raise CommandError(
                f"Components document filename conflicts with the master document: {COMPONENTS_FILENAME}"
            )
        if master_filename == FULL_JSON_FILENAME:
            raise CommandError(
                f"Full JSON schema filename conflicts with the master document: {FULL_JSON_FILENAME}"
            )
        master_file = self._validate_filename(master_filename, "master file")

        full_filename = options.get("full_file")
        if full_filename:
            if full_filename == API_CATALOG_FILENAME:
                raise CommandError(
                    f"API catalog filename conflicts with the full schema document: {API_CATALOG_FILENAME}"
                )
            if full_filename == COMPONENTS_FILENAME:
                raise CommandError(
                    f"Components document filename conflicts with the full schema document: {COMPONENTS_FILENAME}"
                )
            if full_filename == FULL_JSON_FILENAME:
                raise CommandError(
                    f"Full JSON schema filename conflicts with the full schema document: {FULL_JSON_FILENAME}"
                )
            if full_filename == master_filename:
                raise CommandError(
                    f"Full schema filename conflicts with the master document: {master_filename}"
                )
            full_file = self._validate_filename(full_filename, "full schema file")
        else:
            full_file = None

        documents = self._build_documents(schema, modules, master_file, full_file=full_file)
        generated_filenames = {*documents, API_CATALOG_FILENAME, FULL_JSON_FILENAME}
        if len(generated_filenames) < len(documents) + 2:
            raise CommandError(
                "API catalog or JSON schema filename conflicts with a generated OpenAPI document."
            )
        catalog = build_api_catalog(schema)

        if options.get("validate") or options.get("check"):
            self._validate_documents(documents, schema, master_file)

        if options.get("check"):
            expected = {
                **documents,
                API_CATALOG_FILENAME: json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
                FULL_JSON_FILENAME: json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
            }
            self._check_documents(output_dir, expected)
            self.stdout.write(
                self.style.SUCCESS(f"Verified {len(expected)} generated OpenAPI files; no files were written.")
            )
            return

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validated {len(documents)} OpenAPI documents, full JSON schema, and API catalog; no files were written."
                )
            )
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        if not options["no_clean"]:
            self._clean_generated_files(output_dir)

        for filename, content in documents.items():
            output_path = output_dir / filename
            self._write_atomically(output_path, content)
            self.stdout.write(f"Generated {output_path}")

        catalog_path = output_dir / API_CATALOG_FILENAME
        self._write_atomically(
            catalog_path,
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        )
        self.stdout.write(f"Generated {catalog_path}")

        full_json_path = output_dir / FULL_JSON_FILENAME
        self._write_atomically(
            full_json_path,
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        )
        self.stdout.write(f"Generated {full_json_path}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated master schema, full merged schema (YAML & JSON), {len(modules)} OpenAPI modules, and API catalog."
            )
        )

    def _build_documents(self, schema, modules, master_file, full_file=None):
        documents = {
            master_file: self._dump_yaml(self._build_master_schema(schema, modules, master_file)),
            COMPONENTS_FILENAME: self._dump_yaml({"components": schema.get("components", {})}),
        }
        if full_file:
            documents[full_file] = self._dump_yaml(schema)
        for module_name, module_schema in modules.items():
            filename = self._validate_filename(module_name, "module file")
            if filename in documents:
                raise CommandError(f"Generated OpenAPI filename conflicts with another document: {filename}")
            documents[filename] = self._dump_yaml(module_schema)
        return documents

    @staticmethod
    def _dump_yaml(document):
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=False)

    @staticmethod
    def _check_documents(output_dir, expected):
        actual = (
            {path.name for path in output_dir.iterdir() if path.suffix.lower() in {".yml", ".yaml", ".json"}}
            if output_dir.is_dir()
            else set()
        )
        missing = sorted(expected.keys() - actual)
        extra = sorted(actual - expected.keys())
        changed = []
        for filename in sorted(expected.keys() & actual):
            try:
                content = (output_dir / filename).read_text(encoding="utf-8")
                generated = expected[filename]
                if filename == API_CATALOG_FILENAME:
                    content = json.loads(content)
                    generated = json.loads(generated)
                    if isinstance(content, dict):
                        content.pop("generated_at", None)
                    generated.pop("generated_at", None)
                if content != generated:
                    changed.append(filename)
            except (OSError, UnicodeError, json.JSONDecodeError):
                changed.append(filename)
        if missing or extra or changed:
            details = [
                f"{label}: {', '.join(filenames)}"
                for label, filenames in (("Missing", missing), ("Extra", extra), ("Changed", changed))
                if filenames
            ]
            raise CommandError("Generated OpenAPI files are out of date:\n" + "\n".join(details))

    def _validate_documents(self, documents, schema, master_file):
        parsed = {filename: yaml.safe_load(content) for filename, content in documents.items()}

        def resolve(ref, filename):
            target_file, separator, pointer = ref.partition("#")
            if not separator or (pointer and not pointer.startswith("/")):
                raise CommandError(f"Invalid offline OpenAPI reference in {filename}: {ref}")
            if target_file:
                if not target_file.startswith("./") or target_file[2:] not in parsed:
                    raise CommandError(f"Unknown offline OpenAPI reference in {filename}: {ref}")
                target_file = target_file[2:]
            else:
                target_file = filename
            target = parsed[target_file]
            try:
                for segment in pointer.split("/")[1:]:
                    segment = segment.replace("~1", "/").replace("~0", "~")
                    target = target[int(segment)] if isinstance(target, list) else target[segment]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise CommandError(f"Unresolved OpenAPI reference in {filename}: {ref}") from exc
            return target

        for filename, document in parsed.items():
            for ref in sorted(self._extract_refs(document)):
                resolve(ref, filename)
            for scheme in sorted(self._extract_security_schemes(document)):
                components = document.get("components", {})
                if "$ref" in components:
                    components = resolve(components["$ref"], filename)
                if scheme not in components.get("securitySchemes", {}):
                    raise CommandError(f"Unknown OpenAPI security scheme in {filename}: {scheme}")

        # The split master's root components $ref is not an OpenAPI Components Object.
        # Resolve only the split links; retain internal refs (including recursive schemas).
        master = copy.deepcopy(parsed[master_file])
        master["paths"] = {
            path: resolve(path_item["$ref"], master_file) for path, path_item in master["paths"].items()
        }
        master["components"] = resolve(master["components"]["$ref"], master_file)
        standalone = {
            **{name: doc for name, doc in parsed.items() if name not in {master_file, COMPONENTS_FILENAME}},
            master_file: master,
            FULL_JSON_FILENAME: schema,
        }
        for filename, document in standalone.items():
            try:
                validate_schema(document)
            except (ValidationError, RuntimeError) as exc:
                raise CommandError(f"OpenAPI schema validation failed for {filename}: {exc}") from exc
        self.stdout.write(f"Validated {len(standalone)} OpenAPI schemas and all generated document references.")

    @staticmethod
    def _validate_filename(filename, description):
        path = Path(filename)
        if path.is_absolute() or path.name != filename or path.suffix not in {".yml", ".yaml"}:
            raise CommandError(
                f"{description.capitalize()} must be a YAML filename without directory components: {filename!r}"
            )
        return filename

    @staticmethod
    def _write_atomically(path, content):
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        temporary_path.replace(path)

    @staticmethod
    def _clean_generated_files(output_dir):
        for path in output_dir.glob("*.yml"):
            path.unlink()
        for path in output_dir.glob("*.yaml"):
            path.unlink()

    def _split_schema(self, schema, include_untagged):
        module_prefixes = self._registered_module_prefixes()
        grouped_paths = {}
        unmatched_paths = []

        for path, path_item in schema.get("paths", {}).items():
            module_name = self._module_for_path(path, module_prefixes)
            if module_name is None:
                unmatched_paths.append(path)
                if not include_untagged:
                    continue
                module_name = "untagged.yml"
            grouped_paths.setdefault(module_name, {})[path] = copy.deepcopy(path_item)

        if unmatched_paths and not include_untagged:
            details = ", ".join(unmatched_paths[:5])
            suffix = " ..." if len(unmatched_paths) > 5 else ""
            raise CommandError(
                "Found OpenAPI paths not registered through a feature URL module. "
                "Register the route through a feature urls.py or rerun with "
                f"--include-untagged: {details}{suffix}"
            )

        return {module_name: self._build_module_schema(schema, paths) for module_name, paths in grouped_paths.items()}

    def _registered_module_prefixes(self):
        prefix_owners = {}
        for prefix, module_name in self._walk_urlpatterns(get_resolver().url_patterns):
            filename = self._module_filename(module_name)
            owner = prefix_owners.setdefault(prefix, filename)
            if owner != filename:
                raise CommandError(f"OpenAPI path prefix {prefix!r} is assigned to both {owner!r} and {filename!r}.")

        if not prefix_owners:
            raise CommandError("No URL-registered OpenAPI feature modules were found.")

        return sorted(prefix_owners.items(), key=lambda item: len(item[0]), reverse=True)

    def _walk_urlpatterns(self, patterns, prefix="", module_name=None):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                included_module = self._included_module(pattern.urlconf_module)
                child_module = included_module or module_name
                child_prefix = f"{prefix}{pattern.pattern}"
                if child_module and not pattern.url_patterns:
                    yield f"/{child_prefix}".rstrip("/") or "", child_module
                yield from self._walk_urlpatterns(
                    pattern.url_patterns,
                    child_prefix,
                    child_module,
                )
            elif module_name:
                route = self._openapi_path(prefix, pattern.pattern)
                yield route, module_name

    @staticmethod
    def _openapi_path(prefix, pattern):
        import re

        route = getattr(pattern, "_route", None)
        if route is None:
            route = pattern.regex.pattern
            route = route.removeprefix("^").removesuffix("$")
            route = route.replace("(?P<", "{").replace(">[^/]+)", "}")
            route = route.replace(">[^/.]+)", "}")
        else:
            route = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", route)
            route = route.replace("{pk}", "{id}")
        return f"/{prefix}{route}".rstrip("/") or "/"

    @staticmethod
    def _included_module(urlconf_module):
        module_name = getattr(urlconf_module, "__name__", "")
        if module_name in ("core.routing.urls", "core.routing.api.urls"):
            return module_name
        if module_name in ("core.agents.urls", "core.agents.api.urls"):
            return module_name
        if ".features." in module_name and module_name.endswith(".urls"):
            return module_name
        return None

    @staticmethod
    def _module_filename(module_name):
        if module_name in ("core.routing.urls", "core.routing.api.urls"):
            return "routing-sync.yml"
        if module_name in ("core.agents.urls", "core.agents.api.urls"):
            return "agents.yml"
        parts = module_name.split(".")
        try:
            feature_index = parts.index("features")
            app_name = parts[1].replace("_integration", "").replace("_", "-")
            feature_name = "-".join(parts[feature_index + 1 : -1])
        except (ValueError, IndexError):
            return "unclassified.yml"
        return f"{app_name}-{feature_name.replace('_', '-')}.yml"

    @staticmethod
    def _module_for_path(path, module_prefixes):
        for prefix, filename in module_prefixes:
            if path == prefix or path.startswith(f"{prefix}/"):
                return filename
        return None

    def _build_module_schema(self, schema, paths):
        module_schema = copy.deepcopy(schema)
        module_schema["paths"] = paths
        module_schema["components"] = self._prune_components(
            schema.get("components", {}),
            paths,
            schema.get("security", []),
        )
        methods = ("get", "post", "put", "patch", "delete", "options", "head")
        used_tags = {
            tag
            for path_item in paths.values()
            if isinstance(path_item, dict)
            for method in methods
            if isinstance(path_item.get(method), dict)
            for tag in path_item[method].get("tags", [])
        }
        if "tags" in schema and isinstance(schema["tags"], list):
            module_schema["tags"] = [
                tag_obj
                for tag_obj in schema["tags"]
                if isinstance(tag_obj, dict) and tag_obj.get("name") in used_tags
            ]
        return module_schema

    @classmethod
    def _prune_components(cls, all_components, paths, root_security=None):
        visited = set()
        queue = []

        def enqueue(target):
            if target not in visited:
                visited.add(target)
                queue.append(target)

        for ref in cls._extract_refs(paths):
            parsed = cls._parse_component_ref(ref)
            if parsed:
                enqueue(parsed)

        for scheme in cls._extract_security_schemes(paths):
            enqueue(("securitySchemes", scheme))

        if root_security:
            for scheme in cls._extract_security_schemes({"security": root_security}):
                enqueue(("securitySchemes", scheme))

        while queue:
            sec, name = queue.pop(0)
            component_obj = all_components.get(sec, {}).get(name)
            if component_obj is None:
                continue

            for ref in cls._extract_refs(component_obj):
                parsed = cls._parse_component_ref(ref)
                if parsed:
                    enqueue(parsed)

            for scheme in cls._extract_security_schemes(component_obj):
                enqueue(("securitySchemes", scheme))

        pruned = {}
        for sec, name in visited:
            if sec in all_components and name in all_components[sec]:
                pruned.setdefault(sec, {})[name] = copy.deepcopy(all_components[sec][name])

        sorted_pruned = {}
        for sec in sorted(pruned.keys()):
            sorted_pruned[sec] = {k: pruned[sec][k] for k in sorted(pruned[sec].keys())}
        return sorted_pruned

    @classmethod
    def _extract_refs(cls, node):
        refs = set()
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str):
                    refs.add(v)
                else:
                    refs.update(cls._extract_refs(v))
        elif isinstance(node, list):
            for item in node:
                refs.update(cls._extract_refs(item))
        return refs

    @classmethod
    def _extract_security_schemes(cls, node):
        schemes = set()
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "security" and isinstance(v, list):
                    for req in v:
                        if isinstance(req, dict):
                            schemes.update(req.keys())
                else:
                    schemes.update(cls._extract_security_schemes(v))
        elif isinstance(node, list):
            for item in node:
                schemes.update(cls._extract_security_schemes(item))
        return schemes

    @staticmethod
    def _parse_component_ref(ref):
        prefix = "#/components/"
        if not isinstance(ref, str) or not ref.startswith(prefix):
            return None
        parts = ref[len(prefix):].split("/")
        if len(parts) < 2:
            return None
        section = parts[0].replace("~1", "/").replace("~0", "~")
        name = parts[1].replace("~1", "/").replace("~0", "~")
        return section, name

    @staticmethod
    def _build_master_schema(schema, modules, master_file):
        master_schema = copy.deepcopy(schema)
        master_schema["paths"] = {
            path: {"$ref": f"./{module_name}#/paths/{Command._json_pointer(path)}"}
            for module_name in modules
            for path in modules[module_name]["paths"]
        }
        master_schema["components"] = {"$ref": f"./{COMPONENTS_FILENAME}#/components"}
        return master_schema

    @staticmethod
    def _json_pointer(value):
        return value.replace("~", "~0").replace("/", "~1")
