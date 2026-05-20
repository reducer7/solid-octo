from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from redis import Redis as RedisClient
else:  # pragma: no cover - runtime keeps redis optional
    RedisClient = Any


class ScoreStore(Protocol):
    def get_entry(self, simhash_hex: str) -> dict[str, Any] | None:
        ...

    def save_entry(self, simhash_hex: str, fields: dict[str, Any]) -> None:
        ...

    def query_candidates(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> list[str]:
        ...

    def add_candidate(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> None:
        ...


class InMemoryStore:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.candidates: set[str] = set()

    def get_entry(self, simhash_hex: str) -> dict[str, Any] | None:
        return self.entries.get(simhash_hex)

    def save_entry(self, simhash_hex: str, fields: dict[str, Any]) -> None:
        payload = dict(fields)
        payload.setdefault("created_at", int(time.time()))
        self.entries[simhash_hex] = payload

    def query_candidates(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> list[str]:
        del simhash_hex, index_key, fallback_key, use_redisbloom, use_fallback, lsh_bands, lsh_bits
        return list(self.candidates)

    def add_candidate(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> None:
        del index_key, fallback_key, use_redisbloom, use_fallback, lsh_bands, lsh_bits
        self.candidates.add(simhash_hex)


class RedisStore:
    def __init__(self, client: RedisClient, entry_key_prefix: str) -> None:
        self.client = client
        self.entry_key_prefix = entry_key_prefix

    def _entry_key(self, simhash_hex: str) -> str:
        return f"{self.entry_key_prefix}:{simhash_hex}"

    def get_entry(self, simhash_hex: str) -> dict[str, Any] | None:
        raw = self.client.hgetall(self._entry_key(simhash_hex))
        if not raw:
            return None

        decoded: dict[str, Any] = {}
        for key, value in raw.items():
            decoded_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            decoded_value = value.decode("utf-8") if isinstance(value, bytes) else value
            decoded[decoded_key] = decoded_value
        return decoded

    def save_entry(self, simhash_hex: str, fields: dict[str, Any]) -> None:
        encoded = {k: str(v) for k, v in fields.items()}
        self.client.hset(self._entry_key(simhash_hex), mapping=encoded)

    def query_candidates(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> list[str]:
        out: set[str] = set()

        if use_redisbloom:
            try:
                self.client.execute_command("BF.LSH.CREATE", index_key, lsh_bands, lsh_bits)
            except Exception:
                pass
            try:
                response = self.client.execute_command("BF.LSH.QUERY", index_key, simhash_hex) or []
                out.update(self._decode_list(response))
            except Exception:
                pass

        if use_fallback:
            out.update(self._decode_list(self.client.smembers(fallback_key)))

        return list(out)

    def add_candidate(
        self,
        simhash_hex: str,
        index_key: str,
        fallback_key: str,
        use_redisbloom: bool,
        use_fallback: bool,
        lsh_bands: int,
        lsh_bits: int,
    ) -> None:
        if use_redisbloom:
            try:
                self.client.execute_command("BF.LSH.CREATE", index_key, lsh_bands, lsh_bits)
            except Exception:
                pass
            try:
                self.client.execute_command("BF.LSH.ADD", index_key, simhash_hex)
            except Exception:
                pass

        if use_fallback:
            self.client.sadd(fallback_key, simhash_hex)

    @staticmethod
    def _decode_list(values: Any) -> list[str]:
        decoded: list[str] = []
        for value in values:
            if isinstance(value, bytes):
                decoded.append(value.decode("utf-8"))
            else:
                decoded.append(str(value))
        return decoded
