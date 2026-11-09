"""Stub router client for testing backend routing sync endpoints."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class StubRouter:
    """Client implementing the router consumption contract (Section 9)."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.cursors: dict[str, dict[str, Any]] = {}

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                err_data = json.loads(body)
            except Exception:
                err_data = {"error": {"message": body}}
            raise RuntimeError(f"HTTP {exc.code}: {err_data}") from exc

    def info(self) -> dict[str, Any]:
        resp = self._request("/internal/info")
        return resp.get("data", {})

    def snapshot(self, entity: str, limit: int = 1000) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after: str | None = None
        epoch: str | None = None
        head_version: int = 0

        while True:
            params: dict[str, Any] = {"limit": limit}
            if after:
                params["after"] = after
            resp = self._request(f"/internal/snapshot/{entity}", params).get("data", {})
            if epoch is None:
                epoch = resp["epoch"]
                head_version = resp["head_version"]
            elif epoch != resp["epoch"]:
                raise RuntimeError("Epoch changed during snapshot scan! Resync required.")

            items.extend(resp.get("items", []))
            after = resp.get("next_after")
            if not after:
                break

        self.cursors[entity] = {"epoch": epoch, "version": head_version}
        return items

    def changes(self, entity: str, wait: int = 0, limit: int = 500) -> dict[str, Any]:
        cursor = self.cursors.get(entity)
        if not cursor:
            raise RuntimeError(f"No cursor for {entity}. Run snapshot first.")

        params = {
            "since": cursor["version"],
            "epoch": cursor["epoch"],
            "limit": limit,
            "wait": wait,
        }
        resp = self._request(f"/internal/changes/{entity}", params).get("data", {})
        if resp.get("mode") == "reset":
            # Reset triggers a new snapshot scan
            return resp

        # Advance cursor
        self.cursors[entity]["version"] = resp.get("version", cursor["version"])
        return resp

    def digest(self, entity: str) -> dict[str, Any]:
        resp = self._request(f"/internal/digest/{entity}")
        return resp.get("data", {})


def main() -> None:
    parser = argparse.ArgumentParser(description="Stub Router CLI")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL of backend")
    parser.add_argument("--token", required=True, help="Bearer token for sync API")
    parser.add_argument("--entity", choices=["users", "agents"], default="users", help="Entity to sync")
    parser.add_argument("--action", choices=["info", "snapshot", "changes", "digest", "poll"], default="info")
    args = parser.parse_args()

    router = StubRouter(args.base_url, args.token)
    if args.action == "info":
        print(json.dumps(router.info(), indent=2))
    elif args.action == "snapshot":
        claims = router.snapshot(args.entity)
        print(f"Snapshot received {len(claims)} claims. Cursor: {router.cursors[args.entity]}")
    elif args.action == "digest":
        print(json.dumps(router.digest(args.entity), indent=2))
    elif args.action == "changes":
        router.snapshot(args.entity)
        chg = router.changes(args.entity)
        print(json.dumps(chg, indent=2))
    elif args.action == "poll":
        router.snapshot(args.entity)
        print(f"Starting long-poll loop for {args.entity} at cursor {router.cursors[args.entity]}...")
        while True:
            chg = router.changes(args.entity, wait=10)
            print(f"[{time.strftime('%X')}] Poll result: mode={chg.get('mode')}, changes={len(chg.get('changes', []))}")
            if chg.get("mode") == "reset":
                print("Reset signal received! Re-scanning snapshot...")
                router.snapshot(args.entity)


if __name__ == "__main__":
    main()
