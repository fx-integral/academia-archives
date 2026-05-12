"""Lightweight Minecraft server scanner for mechanism 0."""

from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

SCANNER_TIMEOUT = 3.0
SCANNERS = ("mcsrvstat", "mcstatus", "mcapi", "xdefcon", "minetools", "tickhosting")


def _split_host_port(address: str) -> Tuple[str, Optional[int]]:
    if address.count(":") == 1:
        host, port = address.split(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return host, None
    return address, None


def _fetch_json(url: str, *, params: Optional[Dict[str, Any]] = None, timeout: float, logger: logging.Logger) -> Dict[str, Any]:
    logger.debug(f"scanner GET {url} params={params}")
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected payload type from {url}: {type(data)!r}")
    return data


def _fetch(name: str, address: str, host: str, port: Optional[int], timeout: float, logger: logging.Logger) -> Dict[str, Any]:
    if name == "mcsrvstat":
        return _fetch_json(f"https://api.mcsrvstat.us/3/{address}", timeout=timeout, logger=logger)
    if name == "mcstatus":
        return _fetch_json(f"https://api.mcstatus.io/v2/status/java/{address}", timeout=timeout, logger=logger)
    if name == "mcapi":
        params: Dict[str, Any] = {"ip": host}
        if port is not None:
            params["port"] = port
        return _fetch_json("https://mcapi.us/server/status", params=params, timeout=timeout, logger=logger)
    if name == "xdefcon":
        return _fetch_json(f"https://mcapi.xdefcon.com/server/{address}/full/json", timeout=timeout, logger=logger)
    if name == "minetools":
        path = f"{host}/{port}" if port is not None else host
        return _fetch_json(f"https://api.minetools.eu/ping/{path}", timeout=timeout, logger=logger)
    if name == "tickhosting":
        params = {"ip": host, "type": "java"}
        if port is not None:
            params["port"] = port
        return _fetch_json("https://mcstats.tickhosting.com/api/status", params=params, timeout=timeout, logger=logger)
    raise ValueError(f"Unknown scanner {name}")


def _extract(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    players = None
    max_players = None
    online = None
    ping = None

    if name in {"mcsrvstat", "mcstatus", "mcapi"}:
        section = payload.get("players") if isinstance(payload.get("players"), dict) else {}
        if name == "mcsrvstat":
            players = section.get("online") if isinstance(section.get("online"), int) else None
            max_players = section.get("max") if isinstance(section.get("max"), int) else None
            online = payload.get("online") if isinstance(payload.get("online"), bool) else None
        elif name == "mcstatus":
            online = payload.get("online") if isinstance(payload.get("online"), bool) else None
            players = section.get("online") if isinstance(section.get("online"), int) else None
            max_players = section.get("max") if isinstance(section.get("max"), int) else None
        else:  # mcapi
            online = payload.get("online") if isinstance(payload.get("online"), bool) else None
            players = section.get("now") if isinstance(section.get("now"), int) else None
            max_players = section.get("max") if isinstance(section.get("max"), int) else None

    elif name == "xdefcon":
        status = payload.get("serverStatus")
        online = True if status == "online" else False if status == "offline" else None
        raw_players = payload.get("players")
        raw_max = payload.get("maxplayers")
        raw_ping = payload.get("ping")
        if isinstance(raw_players, (int, float)):
            players = int(raw_players)
        if isinstance(raw_max, (int, float)):
            max_players = int(raw_max)
        if isinstance(raw_ping, (int, float)):
            ping = float(raw_ping)

    elif name in {"minetools", "tickhosting"}:
        section = payload.get("players") if isinstance(payload.get("players"), dict) else {}
        raw_latency = payload.get("latency")
        raw_online = section.get("online")
        raw_max = section.get("max")
        if isinstance(raw_online, int):
            players = raw_online
        if isinstance(raw_max, int):
            max_players = raw_max
        if name == "minetools":
            online = True if isinstance(raw_online, int) else None
        else:
            online = payload.get("online") if isinstance(payload.get("online"), bool) else None
        if isinstance(raw_latency, (int, float)):
            ping = float(raw_latency)

    return {
        "players": players,
        "max_players": max_players,
        "online": online,
        "ping": ping,
    }


def _attempt(
    name: str,
    address: str,
    host: str,
    port: Optional[int],
    timeout: float,
    logger: logging.Logger,
    stage: str,
    stat: List[float],
    index: Optional[int] = None,
    total: Optional[int] = None,
) -> Tuple[bool, Any, bool]:
    start = perf_counter()
    label = f"[{index}/{total}][{name}]" if index is not None and total is not None else f"[{stage}][{name}]"
    disable_scanner = False
    try:
        payload = _fetch(name, address, host, port, timeout, logger)
        data = _extract(name, payload)
        elapsed = perf_counter() - start
        stat[0] += 1
        stat[1] += elapsed
        players = data.get("players")
        observed = players if isinstance(players, int) else "UNK"
        logger.info(f"{label} {address} -> players={observed} in {elapsed:.3f}s")
        return True, data, False
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 429:
            disable_scanner = True
            logger.warning(
                f"{label} {address} -> rate limited (HTTP 429); disabling scanner {name} for the remainder of this cycle"
            )
        elapsed = perf_counter() - start
        stat[0] += 1
        stat[1] += elapsed
        logger.error(f"{label} {address} -> ERROR after {elapsed:.3f}s: {exc}")
        return False, str(exc), disable_scanner
    except requests.RequestException as exc:
        elapsed = perf_counter() - start
        stat[0] += 1
        stat[1] += elapsed
        logger.error(f"{label} {address} -> ERROR after {elapsed:.3f}s: {exc}")
        return False, str(exc), False
    except Exception as exc:  # noqa: BLE001
        elapsed = perf_counter() - start
        stat[0] += 1
        stat[1] += elapsed
        logger.error(f"{label} {address} -> ERROR after {elapsed:.3f}s: {exc}")
        return False, str(exc), False


def _pick_scanner(start_index: int, disabled: Set[str]) -> Optional[str]:
    for offset in range(len(SCANNERS)):
        candidate = SCANNERS[(start_index + offset) % len(SCANNERS)]
        if candidate not in disabled:
            return candidate
    return None


def scan_catalog(
    catalog: Dict[str, Optional[int]],
    logger: logging.Logger,
    *,
    timeout: float = SCANNER_TIMEOUT,
    disabled_scanners: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Set[str]]:
    items = list(catalog.items())
    total = len(items)
    successes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    attempts: Dict[str, set[str]] = defaultdict(set)
    pool: set[str] = set()
    stats = {name: [0, 0.0] for name in SCANNERS}
    retries = {name: 0 for name in SCANNERS}
    disabled: Set[str] = set(disabled_scanners or set())
    newly_disabled: Set[str] = set()

    if not items:
        logger.info("No servers to process.")
        metrics = {"total_elapsed": 0.0, "avg_per_server": 0.0, "per_scanner": stats, "retries": retries}
        return [], metrics, newly_disabled

    start_all = perf_counter()

    for index, (address, _hint) in enumerate(items, 1):
        name = _pick_scanner((index - 1) % len(SCANNERS), disabled)
        if name is None:
            logger.warning(f"No scanners available for {address}; all providers disabled this cycle")
            pool.add(address)
            continue
        host, port = _split_host_port(address)
        attempts[address].add(name)
        ok, payload, disable = _attempt(name, address, host, port, timeout, logger, "main", stats[name], index, total)
        if disable:
            disabled.add(name)
            newly_disabled.add(name)
        if ok:
            payload["scanner"] = name
            successes[address].append(payload)
        else:
            pool.add(address)

    for address in list(pool):
        host, port = _split_host_port(address)
        for name in SCANNERS:
            if name in attempts[address]:
                continue
            if name in disabled:
                continue
            attempts[address].add(name)
            ok, payload, disable = _attempt(name, address, host, port, timeout, logger, "retry", stats[name])
            if disable:
                disabled.add(name)
                newly_disabled.add(name)
            if ok:
                payload["scanner"] = name
                successes[address].append(payload)
                retries[name] += 1
                break

    total_elapsed = perf_counter() - start_all
    results: List[Dict[str, Any]] = []
    for address, _ in items:
        base = {"address": address, "online": False, "players": 0, "max_players": 0, "ping": 0.0, "scanner": None}
        success_list = successes.get(address, [])
        if success_list:
            entry = success_list[0]
            base["online"] = bool(next((s.get("online") for s in success_list if s.get("online") is not None), True))
            base["players"] = next((s.get("players") for s in success_list if isinstance(s.get("players"), int)), 0)
            base["max_players"] = next((s.get("max_players") for s in success_list if isinstance(s.get("max_players"), int)), 0)
            base["ping"] = next((s.get("ping") for s in success_list if isinstance(s.get("ping"), (int, float))), 0.0)
            base["scanner"] = entry.get("scanner")
        results.append(base)

    metrics = {
        "total_elapsed": total_elapsed,
        "avg_per_server": total_elapsed / total if total else 0.0,
        "per_scanner": stats,
        "retries": retries,
        "disabled_scanners": sorted(newly_disabled),
    }
    return results, metrics, newly_disabled


__all__ = ["SCANNER_TIMEOUT", "scan_catalog"]
