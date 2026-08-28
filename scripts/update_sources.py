#!/usr/bin/env python3
"""Update LBox and AltStore source files from stable GitHub Release IPAs."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "apps.json"
LBOX_PATH = ROOT / "apps.json"
ALTSTORE_PATH = ROOT / "source.json"
RAW_BASE = "https://raw.githubusercontent.com/ackles1215-xiong/lbox-ipa-source/main"
API_BASE = "https://api.github.com"
MAX_VERSIONS = 10
MAX_PLIST_SIZE = 2 * 1024 * 1024


class UpdateSkipped(RuntimeError):
    """A recoverable upstream issue; existing source data must be retained."""


@dataclass(frozen=True)
class IpaMetadata:
    bundle_identifier: str
    version: str
    build_version: str
    min_os_version: str | None


def request(url: str, *, accept: str = "application/vnd.github+json") -> urllib.response.addinfourl:
    headers = {
        "Accept": accept,
        "User-Agent": "lbox-ipa-source-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def get_json(url: str) -> Any:
    with request(url) as response:
        return json.load(response)


def stable_latest_release(repo: str) -> dict[str, Any]:
    releases = get_json(f"{API_BASE}/repos/{repo}/releases?per_page=20")
    stable = [r for r in releases if not r.get("draft") and not r.get("prerelease")]
    if not stable:
        raise UpdateSkipped("没有可用的稳定版 Release")
    return stable[0]


def matching_ipa(release: dict[str, Any], pattern: str) -> dict[str, Any]:
    regex = re.compile(pattern)
    assets = [a for a in release.get("assets", []) if regex.search(a.get("name", ""))]
    if not assets:
        raise UpdateSkipped(f"最新稳定版 {release.get('tag_name')} 没有匹配的 IPA")
    if len(assets) > 1:
        raise UpdateSkipped(f"最新稳定版 {release.get('tag_name')} 有多个匹配的 IPA")
    return assets[0]


def read_ipa_metadata(path: Path) -> IpaMetadata:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [
                info
                for info in archive.infolist()
                if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", info.filename)
            ]
            if len(candidates) != 1:
                raise UpdateSkipped("IPA 中没有唯一的主应用 Info.plist")
            info = candidates[0]
            if info.file_size > MAX_PLIST_SIZE:
                raise UpdateSkipped("IPA 的 Info.plist 大小异常")
            plist = plistlib.loads(archive.read(info))
    except (zipfile.BadZipFile, plistlib.InvalidFileException, KeyError) as error:
        raise UpdateSkipped(f"IPA 无法解析: {error}") from error

    required = ["CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion"]
    if any(not plist.get(key) for key in required):
        raise UpdateSkipped("IPA 缺少 bundle id、版本或 build 信息")
    return IpaMetadata(
        bundle_identifier=str(plist["CFBundleIdentifier"]),
        version=str(plist["CFBundleShortVersionString"]),
        build_version=str(plist["CFBundleVersion"]),
        min_os_version=str(plist["MinimumOSVersion"]) if plist.get("MinimumOSVersion") else None,
    )


def download_ipa(url: str) -> Path:
    last_error: Exception | None = None
    for attempt in range(3):
        temporary = tempfile.NamedTemporaryFile(suffix=".ipa", delete=False)
        path = Path(temporary.name)
        try:
            download_request = urllib.request.Request(
                url,
                headers={"Accept": "application/octet-stream", "User-Agent": "lbox-ipa-source-updater"},
            )
            with temporary, urllib.request.urlopen(download_request, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
            with path.open("rb") as handle:
                if handle.read(4) != b"PK\x03\x04":
                    raise UpdateSkipped("下载内容不是有效的 IPA/ZIP")
            return path
        except (urllib.error.URLError, TimeoutError, OSError, UpdateSkipped) as error:
            last_error = error
            temporary.close()
            path.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2**attempt)
    raise UpdateSkipped(f"IPA 下载重试失败: {last_error}")


def clean_release_notes(body: str | None) -> str:
    if not body:
        return "查看上游 GitHub Release 获取更新说明。"
    text = re.sub(r"<[^>]+>", "", body)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:8000]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def date_string(release: dict[str, Any]) -> str:
    value = release.get("published_at") or release.get("created_at")
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def lbox_app(config: dict[str, Any], release: dict[str, Any], asset: dict[str, Any], meta: IpaMetadata) -> dict[str, Any]:
    return {
        "name": config["name"],
        "bundleIdentifier": meta.bundle_identifier,
        "developerName": config["developerName"],
        "subtitle": config["subtitle"],
        "localizedDescription": config["localizedDescription"],
        "iconURL": f"{RAW_BASE}/{config['iconPath']}",
        "tintColor": config["tintColor"],
        "category": config["category"],
        "version": meta.version,
        "buildVersion": meta.build_version,
        "versionDate": date_string(release),
        "versionDescription": clean_release_notes(release.get("body")),
        "downloadURL": asset["browser_download_url"],
        "size": int(asset["size"]),
        "minOSVersion": meta.min_os_version,
        "screenshotURLs": [],
    }


def version_entry(app: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "version": app["version"],
        "buildVersion": app["buildVersion"],
        "date": app["versionDate"],
        "localizedDescription": app["versionDescription"],
        "downloadURL": app["downloadURL"],
        "size": app["size"],
    }
    if app.get("minOSVersion"):
        entry["minOSVersion"] = app["minOSVersion"]
    return entry


def altstore_app(app: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    versions = list(previous.get("versions", [])) if previous else []
    current = version_entry(app)
    identity = (current["version"], current["buildVersion"])
    versions = [v for v in versions if (v.get("version"), v.get("buildVersion")) != identity]
    versions.insert(0, current)
    return {
        "name": app["name"],
        "bundleIdentifier": app["bundleIdentifier"],
        "developerName": app["developerName"],
        "subtitle": app["subtitle"],
        "localizedDescription": app["localizedDescription"],
        "iconURL": app["iconURL"],
        "tintColor": app["tintColor"],
        "category": app["category"],
        "screenshots": [],
        "versions": versions[:MAX_VERSIONS],
    }


def validate_sources(lbox: dict[str, Any], altstore: dict[str, Any]) -> None:
    if len(lbox.get("apps", [])) != len(altstore.get("apps", [])):
        raise ValueError("两个 source 的 App 数量不一致")
    for app in lbox["apps"]:
        required = ("name", "bundleIdentifier", "version", "downloadURL", "size", "iconURL")
        if any(not app.get(key) for key in required):
            raise ValueError(f"{app.get('name', '未知 App')} 缺少 LBox 必需字段")
        if not app["downloadURL"].lower().endswith(".ipa"):
            raise ValueError(f"{app['name']} 的下载地址不是 IPA")
    for app in altstore["apps"]:
        if not app.get("versions"):
            raise ValueError(f"{app.get('name', '未知 App')} 缺少 AltStore versions")


def write_json(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(rendered, encoding="utf-8")


def update() -> int:
    configs = load_json(CONFIG_PATH, [])
    previous_lbox = load_json(LBOX_PATH, {"apps": []})
    previous_altstore = load_json(ALTSTORE_PATH, {"apps": []})
    old_lbox = {app["name"]: app for app in previous_lbox.get("apps", [])}
    old_altstore = {app["name"]: app for app in previous_altstore.get("apps", [])}
    next_lbox_apps: list[dict[str, Any]] = []
    next_altstore_apps: list[dict[str, Any]] = []

    for config in configs:
        name = config["name"]
        try:
            release = stable_latest_release(config["githubRepo"])
            asset = matching_ipa(release, config["assetPattern"])
            ipa_path = download_ipa(asset["browser_download_url"])
            try:
                metadata = read_ipa_metadata(ipa_path)
            finally:
                ipa_path.unlink(missing_ok=True)
            app = lbox_app(config, release, asset, metadata)
            next_lbox_apps.append(app)
            next_altstore_apps.append(altstore_app(app, old_altstore.get(name)))
            print(f"UPDATED {name}: {metadata.version} ({metadata.build_version})")
        except (UpdateSkipped, urllib.error.URLError, TimeoutError, OSError) as error:
            if name not in old_lbox or name not in old_altstore:
                raise RuntimeError(f"{name} 首次生成失败，且没有可保留的有效版本: {error}") from error
            next_lbox_apps.append(old_lbox[name])
            next_altstore_apps.append(old_altstore[name])
            print(f"RETAINED {name}: {error}", file=sys.stderr)

    lbox = {
        "name": "Ackles IPA Source",
        "identifier": "com.ackles.lboxipasource",
        "subtitle": "为 LBox / LiveContainer 自动跟踪开源 IPA",
        "description": "自动跟踪 iTorrent 与 Palladium 的最新稳定版 GitHub Release。",
        "sourceURL": f"{RAW_BASE}/apps.json",
        "website": "https://github.com/ackles1215-xiong/lbox-ipa-source",
        "iconURL": f"{RAW_BASE}/assets/source-icon.png",
        "apps": next_lbox_apps,
    }
    altstore = {
        "name": "Ackles IPA Source",
        "identifier": "com.ackles.lboxipasource",
        "subtitle": "自动跟踪开源 IPA",
        "description": "自动跟踪 iTorrent 与 Palladium 的最新稳定版 GitHub Release。",
        "sourceURL": f"{RAW_BASE}/source.json",
        "website": "https://github.com/ackles1215-xiong/lbox-ipa-source",
        "iconURL": f"{RAW_BASE}/assets/source-icon.png",
        "apps": next_altstore_apps,
    }
    validate_sources(lbox, altstore)
    write_json(LBOX_PATH, lbox)
    write_json(ALTSTORE_PATH, altstore)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    raise SystemExit(update())
