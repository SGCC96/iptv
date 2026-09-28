#!/usr/bin/env python3
"""
Build a combined Netherlands + Türkiye M3U from the current public IPTV Nexus API.

Sources:
  https://dearbulut.github.io/iptv/api/v1/by-country/nl.json
  https://dearbulut.github.io/iptv/api/v1/by-country/tr.json

The source database publishes health information for streams. By default this
builder includes channels whose best available stream is currently reported
online. Use --probe to additionally test every selected stream with ffprobe.

Output:
  turks_nederland_verified.m3u
  turks_nederland_validation.txt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


BASE = "https://dearbulut.github.io/iptv/api/v1/by-country"
COUNTRIES = [("nl", "Nederlands"), ("tr", "Turks")]
OUT = Path("turks_nederland_verified.m3u")
REPORT = Path("turks_nederland_validation.txt")


def fetch_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 turk-nl-m3u-builder"})
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def truthy_online(stream: dict[str, Any]) -> bool:
    health = stream.get("health") or {}
    status = str(health.get("status", "")).lower()
    if status == "online":
        return True
    return bool(stream.get("online"))


def quality_value(stream: dict[str, Any]) -> int:
    q = str(stream.get("quality") or "")
    for token in ("2160", "1440", "1080", "720", "576", "480", "360", "240"):
        if token in q:
            return int(token)
    return 0


def score_value(stream: dict[str, Any]) -> float:
    health = stream.get("health") or {}
    for v in (health.get("score"), stream.get("score")):
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return 0.0


def pick_stream(channel: dict[str, Any]) -> dict[str, Any] | None:
    streams = [s for s in (channel.get("streams") or []) if isinstance(s, dict) and s.get("url")]
    online = [s for s in streams if truthy_online(s)]
    candidates = online or streams
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (truthy_online(s), score_value(s), quality_value(s))
    )


def esc(value: Any) -> str:
    return str(value or "").replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def make_extinf(country_code: str, country_name: str, channel: dict[str, Any], stream: dict[str, Any]) -> list[str]:
    cid = esc(channel.get("id"))
    name = esc(channel.get("name") or stream.get("title") or cid)
    logo = esc(channel.get("logo"))
    langs = channel.get("languages") or []
    lang = esc(langs[0] if isinstance(langs, list) and langs else ("nld" if country_code == "nl" else "tur"))
    quality = esc(stream.get("quality"))
    suffix = f" ({quality})" if quality else ""

    attrs = [
        f'tvg-id="{cid}"',
        f'tvg-name="{name}"',
    ]
    if logo:
        attrs.append(f'tvg-logo="{logo}"')
    attrs.extend([
        f'tvg-country="{country_code.upper()}"',
        f'tvg-language="{lang}"',
        f'group-title="{country_name}"',
    ])

    lines = [f"#EXTINF:-1 {' '.join(attrs)},{name}{suffix}"]

    ua = stream.get("user_agent")
    ref = stream.get("referrer")
    if ua:
        lines.append(f"#EXTVLCOPT:http-user-agent={ua}")
    if ref:
        lines.append(f"#EXTVLCOPT:http-referrer={ref}")

    lines.append(str(stream["url"]).strip())
    return lines


def validate_m3u(lines: list[str]) -> list[str]:
    errors: list[str] = []
    if not lines or lines[0].strip() != "#EXTM3U":
        errors.append("Missing #EXTM3U as first line")

    for i, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("#EXTVLCOPT:"):
                j += 1
            if j >= len(lines) or not lines[j].startswith(("http://", "https://")):
                errors.append(f"Line {i+1}: EXTINF does not have an HTTP(S) stream URL")

    return errors


def ffprobe_one(item: tuple[int, str, dict[str, Any]]) -> tuple[int, bool, str]:
    idx, url, stream = item
    cmd = [
        "ffprobe", "-v", "error",
        "-rw_timeout", "10000000",
        "-user_agent", str(stream.get("user_agent") or "Mozilla/5.0"),
        "-show_entries", "format=format_name",
        "-of", "default=nw=1:nk=1",
        url,
    ]
    ref = stream.get("referrer")
    if ref:
        cmd[1:1] = ["-headers", f"Referer: {ref}\r\n"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if p.returncode == 0:
            return idx, True, (p.stdout.strip() or "OK")
        return idx, False, (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "ffprobe failed")
    except Exception as e:
        return idx, False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="Probe every selected stream with ffprobe")
    parser.add_argument("--workers", type=int, default=12, help="Concurrent ffprobe workers")
    args = parser.parse_args()

    all_entries: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    source_counts = {}

    for code, country_name in COUNTRIES:
        data = fetch_json(f"{BASE}/{code}.json")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected API response for {code}: expected a JSON list")

        source_counts[code] = len(data)

        # One stream per channel, selecting the best stream currently reported online.
        seen_ids: set[str] = set()
        for ch in data:
            cid = str(ch.get("id") or "").strip()
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            stream = pick_stream(ch)
            if stream:
                all_entries.append((code, country_name, ch, stream))

    all_entries.sort(key=lambda x: (x[0], str(x[2].get("name") or "").lower()))

    lines = ["#EXTM3U"]
    for code, country_name, ch, stream in all_entries:
        lines.extend(make_extinf(code, country_name, ch, stream))

    errors = validate_m3u(lines)
    if errors:
        raise RuntimeError("M3U validation failed:\n" + "\n".join(errors[:20]))

    OUT.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))

    report_lines = [
        "Turkish + Dutch IPTV validation report",
        "=======================================",
        f"Source API: {BASE}/nl.json and {BASE}/tr.json",
        f"Channels in source (NL): {source_counts['nl']}",
        f"Channels in source (TR): {source_counts['tr']}",
        f"Selected streams in output: {len(all_entries)}",
        f"M3U syntax errors: {len(errors)}",
        "",
    ]

    if args.probe:
        try:
            subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        except Exception:
            raise RuntimeError("ffprobe is required for --probe. Install FFmpeg first.")

        tasks = [(i, stream["url"], stream) for i, (_, _, _, stream) in enumerate(all_entries, 1)]
        results: list[tuple[int, bool, str]] = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futures = [ex.submit(ffprobe_one, item) for item in tasks]
            for fut in as_completed(futures):
                results.append(fut.result())
        results.sort()

        passed = sum(ok for _, ok, _ in results)
        failed = len(results) - passed
        report_lines += [f"ffprobe passed: {passed}", f"ffprobe failed: {failed}", ""]
        for (idx, ok, msg), entry in zip(results, all_entries):
            code, _, ch, stream = entry
            name = ch.get("name") or ch.get("id")
            report_lines.append(f"{idx:03d} [{code.upper()}] {'OK' if ok else 'FAIL'} | {name} | {stream.get('url')} | {msg}")
    else:
        report_lines += [
            "ffprobe probe: NOT RUN",
            "The source dataset already provides its own stream-health status.",
            "Run with --probe for an additional live media-layer test.",
        ]

    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} with {len(all_entries)} channel entries.")
    print(f"Wrote {REPORT}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
