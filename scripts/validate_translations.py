from __future__ import annotations

import json
import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")


def placeholder_names(value: str) -> set[str]:
    names: set[str] = set()
    for token in PLACEHOLDER_RE.findall(value):
        inner = token[2:-2].strip()
        name = inner.split("|", 1)[0].strip()
        if name:
            names.add(name)
    return names


def validate() -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    payloads: dict[Path, object] = {}

    for path in sorted(Path(".").rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            failures.append(f"{path}: empty file")
            continue

        try:
            payloads[path] = json.loads(text)
        except json.JSONDecodeError as exc:
            failures.append(f"{path}: {exc}")

    source_locales = [Path("API/en_US.json"), Path("WebApp/en_US.json")]
    for source in source_locales:
        if source not in payloads:
            failures.append(f"{source}: missing required source locale")
            continue

        source_payload = payloads[source]
        if not isinstance(source_payload, dict):
            failures.append(f"{source}: expected top-level JSON object")
            continue

        for path, payload in payloads.items():
            if path == source or path.parent != source.parent:
                continue
            if not isinstance(payload, dict):
                failures.append(f"{path}: expected top-level JSON object")
                continue

            for key, source_value in source_payload.items():
                if key not in payload or not isinstance(source_value, str):
                    continue

                expected_placeholders = placeholder_names(source_value)
                if not expected_placeholders:
                    continue

                translated_value = payload.get(key)
                if not isinstance(translated_value, str):
                    failures.append(f"{path}:{key}: expected string value")
                    continue

                found_placeholders = placeholder_names(translated_value)
                if found_placeholders != expected_placeholders:
                    failures.append(
                        f"{path}:{key}: placeholder mismatch; "
                        f"expected {sorted(expected_placeholders)}, "
                        f"found {sorted(found_placeholders)}"
                    )

    # Key-set drift guard: treat WebApp/en_US.json as source of truth.
    # Missing keys in non-source locales are allowed so translation updates can
    # follow after source-string changes. Orphan keys are allowed so staff can
    # add translations after publishing without blocking the validation workflow.
    webapp_source = Path("WebApp/en_US.json")
    if webapp_source in payloads and isinstance(payloads[webapp_source], dict):
        source_keys = set(payloads[webapp_source].keys())
        max_orphan_keys = None
        max_missing_keys = None

        for path, payload in payloads.items():
            if path == webapp_source or path.parent != webapp_source.parent:
                continue
            if not isinstance(payload, dict):
                continue

            locale_keys = set(payload.keys())
            orphan_keys = locale_keys - source_keys
            missing_keys = source_keys - locale_keys

            if max_orphan_keys is not None and len(orphan_keys) > max_orphan_keys:
                failures.append(f"{path}: {len(orphan_keys)} orphan keys (limit {max_orphan_keys})")
            elif orphan_keys:
                warnings.append(f"{path}: {len(orphan_keys)} orphan keys")

            if max_missing_keys is not None and len(missing_keys) > max_missing_keys:
                failures.append(f"{path}: {len(missing_keys)} missing keys (limit {max_missing_keys})")
    else:
        failures.append("WebApp/en_US.json: missing or invalid source locale for key-set drift check")

    return failures, warnings


def main() -> int:
    failures, warnings = validate()
    if warnings:
        print("JSON validation warnings:")
        for warning in warnings:
            print(f" - {warning}")

    if failures:
        print("JSON validation failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("All JSON files are non-empty and valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
