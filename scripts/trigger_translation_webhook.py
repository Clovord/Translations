#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

API_BASE_URL = "https://clovord.com/api".rstrip("/")
TOKEN = os.getenv("BUILD_WEBHOOK_TOKEN", "").strip()
BEFORE_SHA = os.getenv("BEFORE_SHA", "").strip()
HEAD_SHA = os.getenv("HEAD_SHA", "").strip()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def list_changed_files(before: str, head: str) -> List[str]:
    if not head:
        raise RuntimeError("HEAD_SHA is not set")

    if not before or before.startswith("000000"):
        output = git("ls-tree", "-r", "--name-only", head)
    else:
        try:
            output = git("diff", "--name-only", f"{before}..{head}")
        except subprocess.CalledProcessError:
            output = git("ls-tree", "-r", "--name-only", head)

    return [line.strip() for line in output.splitlines() if line.strip()]


def load_json(commit: str, path: str) -> Dict[str, Any]:
    if not commit or commit.startswith("000000"):
        if not Path(path).exists():
            return {}
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    try:
        content = git("show", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        return {}

    if not content:
        return {}

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    if isinstance(obj, dict):
        result: Dict[str, Any] = {}
        for key, value in obj.items():
            name = f"{prefix}.{key}" if prefix else key
            result.update(flatten(value, name))
        return result
    return {prefix: normalize_value(obj)}


def build_changes(old_data: Dict[str, Any], new_data: Dict[str, Any], file_path: str) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    old_map = flatten(old_data)
    new_map = flatten(new_data)

    for key in sorted(set(old_map) | set(new_map)):
        old_value = old_map.get(key)
        new_value = new_map.get(key)
        if old_value == new_value:
            continue

        if key not in old_map:
            change_type = "added"
        elif key not in new_map:
            change_type = "removed"
        else:
            change_type = "modified"

        changes.append(
            {
                "change_type": change_type,
                "key": key,
                "old_value": None if key not in old_map else old_value,
                "new_value": None if key not in new_map else new_value,
                "context": file_path,
            }
        )

    return changes


def send_webhook(file_type: str, changes: List[Dict[str, Any]]) -> None:
    if not changes:
        return

    payload = {
        "commit": HEAD_SHA,
        "message": f"Translation changes ({file_type})",
        "file_type": file_type,
        "changes": changes,
        "send_webhook": True,
        "notify_translators": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE_URL}/v1/webhooks/translations",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Clovord-Build-Token", TOKEN)

    with urllib.request.urlopen(req, timeout=30) as response:
        print(f"Translation webhook sent for {file_type}: {response.status}")
        print(response.read().decode("utf-8"))


def main() -> int:
    if not TOKEN:
        print("Missing BUILD_WEBHOOK_TOKEN environment variable.")
        return 1

    changed_files = list_changed_files(BEFORE_SHA, HEAD_SHA)
    if not changed_files:
        print("No changed files detected.")
        return 0

    file_changes = {"api": [], "frontend": []}
    for path in changed_files:
        if not path.endswith(".json"):
            continue
        if path.startswith("API/"):
            file_changes["api"].append(path)
        elif path.startswith("WebApp/") or path.startswith("DesktopApp/") or path.startswith("MobileApp/") or path.startswith("DownloadPage/"):
            file_changes["frontend"].append(path)

    if not file_changes["api"] and not file_changes["frontend"]:
        print("No translation JSON changes to send.")
        return 0

    overall_exit = 0
    for file_type, paths in file_changes.items():
        if not paths:
            continue

        changes: List[Dict[str, Any]] = []
        for path in paths:
            old_json = load_json(BEFORE_SHA, path)
            new_json = load_json(HEAD_SHA, path)
            changes.extend(build_changes(old_json, new_json, path))

        if changes:
            try:
                send_webhook(file_type, changes)
            except Exception as exc:
                print(f"Failed to send webhook for {file_type}: {exc}")
                overall_exit = 1
        else:
            print(f"No actual {file_type} translation changes found in {len(paths)} files.")

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
