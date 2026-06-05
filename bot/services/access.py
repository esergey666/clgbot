from __future__ import annotations

import json
import secrets
import string
from pathlib import Path


class AccessService:
    def __init__(self, users_path: str | Path) -> None:
        self.users_path = Path(users_path)

    def _read_data(self) -> dict:
        if not self.users_path.exists():
            return {"user_ids": [], "quotas": {}, "keys": {}, "prices": {}}

        try:
            data = json.loads(self.users_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"user_ids": [], "quotas": {}, "keys": {}, "prices": {}}

        return {
            "user_ids": data.get("user_ids", []),
            "quotas": data.get("quotas", {}),
            "keys": data.get("keys", {}),
            "prices": data.get("prices", {}),
        }

    def _write_data(self, data: dict) -> None:
        self.users_path.parent.mkdir(parents=True, exist_ok=True)
        self.users_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_user_ids(self) -> set[int]:
        data = self._read_data()
        return {int(user_id) for user_id in data.get("user_ids", [])}

    def _write_user_ids(self, user_ids: set[int]) -> None:
        data = self._read_data()
        data["user_ids"] = sorted(user_ids)
        self._write_data(data)

    def _read_quotas(self) -> dict[int, int]:
        data = self._read_data()
        quotas: dict[int, int] = {}
        for user_id, value in data.get("quotas", {}).items():
            try:
                quotas[int(user_id)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        return quotas

    def _write_quotas(self, quotas: dict[int, int]) -> None:
        data = self._read_data()
        data["quotas"] = {str(user_id): value for user_id, value in sorted(quotas.items())}
        self._write_data(data)

    def list_user_ids(self) -> list[int]:
        return sorted(self._read_user_ids())

    def list_quotas(self) -> dict[int, int]:
        return self._read_quotas()

    def list_balances(self) -> dict[int, int]:
        return self._read_quotas()

    def list_keys(self) -> dict[str, int]:
        data = self._read_data()
        result: dict[str, int] = {}
        for key, value in data.get("keys", {}).items():
            try:
                result[str(key)] = int(value.get("balance", value.get("generations")))
            except (KeyError, TypeError, ValueError):
                continue
        return dict(sorted(result.items()))

    def get_generation_prices(self, defaults: dict[str, int]) -> dict[str, int]:
        data = self._read_data()
        prices = defaults.copy()
        for label_type, value in data.get("prices", {}).items():
            if label_type not in defaults:
                continue
            try:
                price = int(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                prices[label_type] = price
        return prices

    def set_generation_prices(self, prices: dict[str, int]) -> None:
        data = self._read_data()
        data["prices"] = {label_type: int(price) for label_type, price in sorted(prices.items())}
        self._write_data(data)

    def has_access(self, user_id: int, owner_ids: list[int]) -> bool:
        return user_id in owner_ids or user_id in self._read_user_ids() or self.get_balance(user_id) > 0

    def has_permanent_access(self, user_id: int, owner_ids: list[int]) -> bool:
        return user_id in owner_ids or user_id in self._read_user_ids()

    def get_balance(self, user_id: int) -> int:
        return self._read_quotas().get(user_id, 0)

    def get_remaining_generations(self, user_id: int) -> int:
        return self.get_balance(user_id)

    def add_user(self, user_id: int) -> bool:
        user_ids = self._read_user_ids()
        was_added = user_id not in user_ids
        user_ids.add(user_id)
        self._write_user_ids(user_ids)
        return was_added

    def remove_user(self, user_id: int) -> bool:
        user_ids = self._read_user_ids()
        if user_id not in user_ids:
            return False
        user_ids.remove(user_id)
        self._write_user_ids(user_ids)
        return True

    def clear_quota(self, user_id: int) -> bool:
        quotas = self._read_quotas()
        if user_id not in quotas:
            return False
        quotas.pop(user_id, None)
        self._write_quotas(quotas)
        return True

    def create_key(self, balance: int) -> str:
        if balance <= 0:
            raise ValueError("Balance amount must be positive.")

        alphabet = string.ascii_uppercase + string.digits
        data = self._read_data()
        keys = data.get("keys", {})

        while True:
            key = "KEY-" + "-".join(
                "".join(secrets.choice(alphabet) for _ in range(4))
                for _ in range(3)
            )
            if key not in keys:
                break

        keys[key] = {"balance": balance, "generations": balance}
        data["keys"] = keys
        self._write_data(data)
        return key

    def delete_key(self, key: str) -> bool:
        normalized_key = key.strip().upper()
        data = self._read_data()
        keys = data.get("keys", {})
        if normalized_key not in keys:
            return False
        keys.pop(normalized_key, None)
        data["keys"] = keys
        self._write_data(data)
        return True

    def activate_key(self, user_id: int, key: str) -> int | None:
        normalized_key = key.strip().upper()
        data = self._read_data()
        keys = data.get("keys", {})
        key_data = keys.get(normalized_key)
        if key_data is None:
            return None

        try:
            balance = int(key_data.get("balance", key_data.get("generations")))
        except (KeyError, TypeError, ValueError):
            return None

        quotas = self._read_quotas()
        quotas[user_id] = quotas.get(user_id, 0) + balance
        keys.pop(normalized_key, None)
        data["keys"] = keys
        data["quotas"] = {str(item_user_id): value for item_user_id, value in sorted(quotas.items())}
        self._write_data(data)
        return quotas[user_id]

    def consume_balance(self, user_id: int, owner_ids: list[int], amount: int) -> bool:
        if user_id in owner_ids or user_id in self._read_user_ids():
            return True
        if amount <= 0:
            return True

        quotas = self._read_quotas()
        remaining = quotas.get(user_id, 0)
        if remaining < amount:
            return False

        quotas[user_id] = remaining - amount
        self._write_quotas(quotas)
        return True

    def consume_generations(self, user_id: int, owner_ids: list[int], count: int) -> bool:
        return self.consume_balance(user_id, owner_ids, count)
