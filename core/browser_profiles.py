"""지역별 Chrome 계정(Profile) 관리 + (Area + OTA) → Profile 연결.

v2.0
- Profile 마다 별도 Chrome 사용자 폴더 + debug port. 지역(KR/JP/AU/UK)별로 따로 실행·연결한다.
- 기본 Profile 폴더는 이 프로그램 안의 chrome_profiles/<ID>.
- 기존 v1.3 로그인 폴더(Chrome_debug, Chrome_debug_JP ...)가 옆에 있으면 그대로 연결해서
  로그인을 다시 하지 않아도 된다 (link_legacy_profiles).
- 미설정 Area/OTA 는 절대 다른 계정으로 대신 수집하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Iterable

import pandas as pd

from collectors.config import CHANNEL_META, SUPPORTED_CHANNELS


APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "data" / "browser_routing.json"
SCHEMA_VERSION = 4

# 기본 지역 Profile. region = 이 Profile 이 주로 담당하는 국가 그룹 (화면 표시용).
DEFAULT_PROFILES = {
    "KR": {"name": "한국 OTA 계정", "region": "KOREA", "port": 9222, "profile_dir": "chrome_profiles/KR"},
    "JP": {"name": "일본 OTA 계정", "region": "JAPAN", "port": 9223, "profile_dir": "chrome_profiles/JP"},
    "AU": {"name": "호주 OTA 계정", "region": "AUSTRALIA", "port": 9224, "profile_dir": "chrome_profiles/AU"},
    "UK": {"name": "영국 OTA 계정", "region": "UK", "port": 9225, "profile_dir": "chrome_profiles/UK"},
}

# v1.3 의 로그인 폴더 이름 (같은 상위 폴더 안의 v1.x 폴더에서 찾는다)
LEGACY_PROFILE_DIRS = {
    "KR": "Chrome_debug",
    "JP": "Chrome_debug_JP",
    "AU": "Chrome_debug_AU",
    "UK": "Chrome_debug_UK",
}

DEFAULT_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "profiles": deepcopy(DEFAULT_PROFILES),
    "routes": {
        # 현재 운영 기준 계정 구성
        "KOREA": {"L": "KR", "KK": "KR", "GG": "KR", "TPC": "KR", "MRT": "KR"},
        "JAPAN": {"L": "JP", "KK": None, "GG": "JP", "TPC": "KR", "MRT": "KR"},
        "AUSTRALIA": {"L": "AU", "KK": None, "GG": "AU", "TPC": "AU", "MRT": None},
        "UK": {"L": "UK", "KK": None, "GG": "UK", "TPC": None, "MRT": None},
        "OTHER": {ch: None for ch in SUPPORTED_CHANNELS},
    },
    # 정확한 Area 단위 예외. 예: {"Sapporo": {"L": "JP_KLOOK_2"}}
    "area_routes": {},
}

KOREA_HINTS = {
    "seoul", "busan", "jeju", "korea", "gyeongju", "incheon", "suwon",
    "gangwon", "pocheon", "paju", "nami", "daegu", "ulsan", "danyang",
}
JAPAN_HINTS = {
    "tokyo", "osaka", "kyoto", "nagoya", "fukuoka", "sapporo", "hokkaido",
    "japan", "yokohama", "kamakura", "nara", "kobe", "biei", "furano",
    "otaru", "asahikawa", "hakone", "fuji", "enoshima",
}
AU_HINTS = {
    "sydney", "melbourne", "brisbane", "gold coast", "cairns", "australia",
    "wollongong", "kiama", "blue mountains", "perth", "adelaide", "canberra",
}
UK_HINTS = {
    "uk", "united kingdom", "england", "scotland", "wales", "london", "oxford",
    "cambridge", "bath", "cotswold", "edinburgh", "manchester", "liverpool",
    "birmingham", "glasgow", "york", "stonehenge",
}

REGION_LABELS = {
    "KOREA": "한국",
    "JAPAN": "일본",
    "AUSTRALIA": "호주",
    "UK": "영국",
    "OTHER": "기타",
}
REGION_EN = {"KOREA": "Korea", "JAPAN": "Japan", "AUSTRALIA": "Australia", "UK": "UK", "OTHER": "Etc"}

# 로그인 페이지로 튕겼는지 판단하는 URL 단서
LOGIN_URL_HINTS = ("login", "signin", "sign-in", "sign_in", "passport", "/auth", "sso")


def _norm_area_key(area: str) -> str:
    return re.sub(r"\s+", " ", str(area or "").strip()).casefold()


def area_group(area: str) -> str:
    text = _norm_area_key(area)
    words = set(re.split(r"[^a-z]+", text))
    if any(h in text for h in KOREA_HINTS):
        return "KOREA"
    if any(h in text for h in JAPAN_HINTS):
        return "JAPAN"
    if any(h in text for h in AU_HINTS):
        return "AUSTRALIA"
    # 'uk' 같은 짧은 단어는 부분 문자열로 보면 오탐(예: 'fukuoka')이 나므로 단어로 본다.
    if any((h in words) if len(h) <= 3 else (h in text) for h in UK_HINTS):
        return "UK"
    return "OTHER"


def _deep_merge(default: dict, override: dict) -> dict:
    out = deepcopy(default)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _route_value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NONE", "UNCONFIGURED", "미설정", "-"}:
        return None
    return text.upper()


def find_legacy_app_dirs(base: Path | None = None) -> list[Path]:
    """같은 상위 폴더에서 v1.x Review Analyzer 폴더(Chrome_debug 포함)를 찾는다."""
    base = Path(base or APP_DIR.parent)
    found = []
    try:
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.resolve() != APP_DIR.resolve() and (child / "Chrome_debug").is_dir():
                found.append(child)
    except OSError:
        pass
    return found


class BrowserProfileManager:
    def __init__(self, config_path: Path | None = None):
        self.config_path = Path(config_path or CONFIG_PATH)
        self.first_run = not self.config_path.exists()
        self.config = self._load_config()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def _load_config(self) -> dict:
        if not self.config_path.exists():
            cfg = deepcopy(DEFAULT_CONFIG)
            self.config = cfg
            self.save_config(cfg)
            return cfg
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            cfg = _deep_merge(DEFAULT_CONFIG, raw)
            # 사용자가 지운 기본 Profile 은 되살리지 않는다.
            if "profiles" in raw:
                cfg["profiles"] = {k.upper(): v for k, v in raw["profiles"].items()}
            for group in REGION_LABELS:
                cfg["routes"].setdefault(group, {})
                for ch in SUPPORTED_CHANNELS:
                    cfg["routes"][group].setdefault(ch, DEFAULT_CONFIG["routes"][group][ch])
                    cfg["routes"][group][ch] = _route_value(cfg["routes"][group][ch])
            for key, info in cfg["profiles"].items():
                info.setdefault("region", DEFAULT_PROFILES.get(key, {}).get("region", "OTHER"))
            cfg["schema_version"] = SCHEMA_VERSION
            self.config = cfg
            return cfg
        except Exception:
            cfg = deepcopy(DEFAULT_CONFIG)
            self.config = cfg
            return cfg

    def save_config(self, config: dict | None = None) -> None:
        if config is not None:
            self.config = deepcopy(config)
        self.config["schema_version"] = SCHEMA_VERSION
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    def reload(self) -> None:
        self.config = self._load_config()

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------
    @property
    def profile_keys(self) -> list[str]:
        return list(self.config.get("profiles", {}).keys())

    def profile_info(self, key: str) -> dict:
        k = str(key).upper()
        if k not in self.config.get("profiles", {}):
            raise KeyError(f"Unknown Chrome profile: {key}")
        return self.config["profiles"][k]

    def profile_name(self, key: str) -> str:
        return str(self.profile_info(key).get("name", key))

    def profile_region(self, key: str) -> str:
        return str(self.profile_info(key).get("region", "OTHER"))

    def profile_port(self, key: str) -> int:
        return int(self.profile_info(key).get("port", 9222))

    def profile_dir(self, key: str) -> Path:
        raw = Path(str(self.profile_info(key).get("profile_dir", f"chrome_profiles/{key}")))
        return raw if raw.is_absolute() else APP_DIR / raw

    def debug_address(self, key: str) -> str:
        return f"127.0.0.1:{self.profile_port(key)}"

    def upsert_profile(self, key: str, name: str, port: int, profile_dir: str, region: str = "OTHER") -> str:
        k = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key).strip()).strip("_").upper()
        if not k:
            raise ValueError("Profile ID를 입력하세요.")
        port = int(port)
        if not 1024 <= port <= 65535:
            raise ValueError("Debug port는 1024~65535 사이여야 합니다.")
        for other, info in self.config.get("profiles", {}).items():
            if other != k and int(info.get("port", 0)) == port:
                raise ValueError(f"Port {port}는 이미 {other} Profile에서 사용 중입니다.")
        self.config.setdefault("profiles", {})[k] = {
            "name": str(name or k).strip(),
            "region": str(region or "OTHER").upper(),
            "port": port,
            "profile_dir": str(profile_dir or f"chrome_profiles/{k}").strip(),
        }
        self.save_config()
        return k

    def next_free_port(self) -> int:
        used = {int(i.get("port", 0)) for i in self.config.get("profiles", {}).values()}
        port = 9226
        while port in used:
            port += 1
        return port

    def profile_uses(self, key: str) -> list[str]:
        k = str(key).upper()
        uses = []
        for group, routes in self.config.get("routes", {}).items():
            for ch, profile in routes.items():
                if _route_value(profile) == k:
                    uses.append(f"{REGION_LABELS.get(group, group)}/{ch}")
        for area, routes in self.config.get("area_routes", {}).items():
            for ch, profile in routes.items():
                if _route_value(profile) == k:
                    uses.append(f"{area}/{ch}")
        return uses

    def delete_profile(self, key: str) -> None:
        k = str(key).upper()
        if k not in self.config.get("profiles", {}):
            return
        uses = self.profile_uses(k)
        if uses:
            raise ValueError("이 Profile은 아직 OTA 연결에서 사용 중입니다: " + ", ".join(uses[:12]))
        del self.config["profiles"][k]
        self.save_config()

    def channels_for_profile(self, key: str) -> dict[str, list[str]]:
        """{지역 라벨: [채널...]} – 이 Profile 로 수집하는 지역/OTA (카드 표시용)."""
        k = str(key).upper()
        out: dict[str, list[str]] = {}
        for group, routes in self.config.get("routes", {}).items():
            for ch in SUPPORTED_CHANNELS:
                if _route_value(routes.get(ch)) == k:
                    out.setdefault(REGION_LABELS.get(group, group), []).append(ch)
        for area, routes in self.config.get("area_routes", {}).items():
            for ch, profile in routes.items():
                if _route_value(profile) == k:
                    out.setdefault(area, []).append(ch)
        return out

    # ------------------------------------------------------------------
    # v1.3 로그인 폴더 연결
    # ------------------------------------------------------------------
    def legacy_candidates(self, legacy_app_dir: Path) -> dict[str, Path]:
        out = {}
        for key, folder in LEGACY_PROFILE_DIRS.items():
            p = Path(legacy_app_dir) / folder
            if p.is_dir() and key in self.config.get("profiles", {}):
                out[key] = p
        return out

    def link_legacy_profiles(self, legacy_app_dir: Path) -> list[str]:
        """기존 v1.3 로그인 폴더를 그대로 사용하도록 Profile 폴더 경로를 바꾼다 (복사하지 않음)."""
        linked = []
        for key, path in self.legacy_candidates(legacy_app_dir).items():
            self.config["profiles"][key]["profile_dir"] = str(path.resolve())
            linked.append(key)
        if linked:
            self.save_config()
        return linked

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def _exact_area_routes(self, area: str) -> dict:
        target = _norm_area_key(area)
        for saved_area, routes in self.config.get("area_routes", {}).items():
            if _norm_area_key(saved_area) == target:
                return routes or {}
        return {}

    def route_profile(self, area: str, channel: str) -> str | None:
        ch = str(channel or "").strip().upper()
        exact = self._exact_area_routes(area)
        if ch in exact:
            profile = _route_value(exact.get(ch))
        else:
            profile = _route_value(self.config.get("routes", {}).get(area_group(area), {}).get(ch))
        if profile is None or profile not in self.config.get("profiles", {}):
            return None
        return profile

    def set_region_route(self, group: str, channel: str, profile: str | None) -> None:
        group, ch = str(group).upper(), str(channel).upper()
        if group not in REGION_LABELS:
            raise ValueError(f"Unknown region: {group}")
        p = _route_value(profile)
        if p is not None and p not in self.config.get("profiles", {}):
            raise ValueError(f"Unknown Chrome profile: {p}")
        self.config.setdefault("routes", {}).setdefault(group, {})[ch] = p
        self.save_config()

    def set_area_route(self, area: str, channel: str, profile: str | None) -> None:
        area = str(area or "").strip()
        if not area:
            raise ValueError("Area 이름을 입력하세요.")
        p = _route_value(profile)
        if p is not None and p not in self.config.get("profiles", {}):
            raise ValueError(f"Unknown Chrome profile: {p}")
        self.config.setdefault("area_routes", {}).setdefault(area, {})[str(channel).upper()] = p
        self.save_config()

    def remove_area_route(self, area: str, channel: str | None = None) -> None:
        routes = self.config.setdefault("area_routes", {})
        matched = next((a for a in routes if _norm_area_key(a) == _norm_area_key(area)), None)
        if matched is None:
            return
        if channel is None:
            routes.pop(matched, None)
        else:
            routes[matched].pop(str(channel).upper(), None)
            if not routes[matched]:
                routes.pop(matched, None)
        self.save_config()

    def unconfigured_routes(self, crawl_df, selected_channels: Iterable[str] | None = None) -> list[dict]:
        selected = set(selected_channels or SUPPORTED_CHANNELS)
        out, seen = [], set()
        if crawl_df is None or len(crawl_df) == 0:
            return out
        for area, ch in crawl_df[["Area", "Agency"]].drop_duplicates().itertuples(index=False):
            ch = str(ch).strip().upper()
            if ch not in selected or ch not in SUPPORTED_CHANNELS:
                continue
            if self.route_profile(str(area), ch) is None and (area, ch) not in seen:
                seen.add((area, ch))
                out.append({"area": str(area), "channel": ch, "group": area_group(str(area))})
        return out

    def build_collection_plan(self, crawl_df, selected_channels: Iterable[str] | None = None) -> dict[str, list[dict]]:
        selected = set(selected_channels or SUPPORTED_CHANNELS)
        plan: dict[str, dict] = {}
        if crawl_df is None or len(crawl_df) == 0:
            return {}
        for idx, row in crawl_df.iterrows():
            ch = str(row.get("Agency", "")).strip().upper()
            if ch not in selected or ch not in SUPPORTED_CHANNELS:
                continue
            area = str(row.get("Area", ""))
            profile = self.route_profile(area, ch)
            item = plan.setdefault(ch, {}).setdefault(
                profile, {"channel": ch, "profile": profile, "areas": set(), "row_indices": [], "dates": []}
            )
            item["areas"].add(area)
            item["row_indices"].append(idx)
            item["dates"].append(row.get("Date"))
        out: dict[str, list[dict]] = {}
        for ch, profiles in plan.items():
            out[ch] = []
            for profile, item in profiles.items():
                # NaT 는 None 이 아니므로 직접 거른다 (min/max 가 NaT 를 돌려주면 strftime 이 터짐).
                dates = [d for d in item["dates"] if d is not None and not pd.isna(d)]
                out[ch].append({
                    "channel": ch,
                    "profile": profile,
                    "areas": sorted(item["areas"]),
                    "row_indices": list(item["row_indices"]),
                    "start_date": min(dates) if dates else None,
                    "end_date": max(dates) if dates else None,
                })
        return out

    def required_profiles(self, crawl_df, selected_channels: Iterable[str] | None = None) -> dict[str, dict]:
        req: dict[str, dict] = {}
        for ch, entries in self.build_collection_plan(crawl_df, selected_channels).items():
            for e in entries:
                if e["profile"] is None:
                    continue
                item = req.setdefault(e["profile"], {"channels": set(), "areas": set()})
                item["channels"].add(ch)
                item["areas"].update(e.get("areas", []))
        return req

    # ------------------------------------------------------------------
    # Chrome process
    # ------------------------------------------------------------------
    @staticmethod
    def _port_open(port: int, timeout: float = 0.35) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def is_running(self, key: str) -> bool:
        return self._port_open(self.profile_port(key))

    @staticmethod
    def find_chrome() -> str | None:
        candidates: list[str] = []
        if sys.platform.startswith("win"):
            for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env_name)
                if base:
                    candidates.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
            try:
                import winreg  # type: ignore
                for root, path in [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
                ]:
                    try:
                        with winreg.OpenKey(root, path) as reg_key:
                            value, _ = winreg.QueryValueEx(reg_key, None)
                            if value:
                                candidates.append(str(value))
                    except OSError:
                        pass
            except Exception:
                pass
        else:
            candidates.extend(["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"])
        for candidate in candidates:
            p = Path(candidate)
            if p.exists():
                return str(p)
            found = shutil.which(candidate)
            if found:
                return found
        return shutil.which("chrome") or shutil.which("chrome.exe")

    def ota_pages_for_profile(self, key: str) -> list[str]:
        chans = sorted({c for lst in self.channels_for_profile(key).values() for c in lst},
                       key=lambda c: SUPPORTED_CHANNELS.index(c) if c in SUPPORTED_CHANNELS else 99)
        return [CHANNEL_META[c]["page"] for c in chans if c in CHANNEL_META]

    def launch_profile(self, key: str, urls: list[str] | None = None) -> bool:
        if self.is_running(key):
            return False
        chrome = self.find_chrome()
        if not chrome:
            raise RuntimeError("Google Chrome을 찾을 수 없습니다. Chrome을 설치한 뒤 다시 실행하세요.")
        profile_dir = self.profile_dir(key)
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            chrome,
            f"--remote-debugging-port={self.profile_port(key)}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        args.extend(urls or ["about:blank"])
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0
        subprocess.Popen(args, creationflags=flags)
        return True

    def ensure_profile(self, key: str, wait_seconds: float = 8.0, urls: list[str] | None = None) -> tuple[bool, bool]:
        started = self.launch_profile(key, urls=urls)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.is_running(key):
                return started, True
            time.sleep(0.35)
        return started, self.is_running(key)

    def ensure_required(self, crawl_df, selected_channels: Iterable[str] | None = None) -> tuple[list[str], list[str]]:
        started, failed = [], []
        for key, info in self.required_profiles(crawl_df, selected_channels).items():
            urls = [CHANNEL_META[ch]["page"] for ch in sorted(info["channels"]) if ch in CHANNEL_META]
            was_started, ready = self.ensure_profile(key, urls=urls)
            if was_started:
                started.append(key)
            if not ready:
                failed.append(key)
        return started, failed

    def close_profile(self, key: str, wait_seconds: float = 6.0) -> bool:
        """이 Profile 의 전용 Chrome 만 종료한다 (DevTools Browser.close)."""
        if not self.is_running(key):
            return True
        try:
            import json as _json
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{self.profile_port(key)}/json/version", timeout=3) as r:
                ws_url = _json.loads(r.read().decode("utf-8")).get("webSocketDebuggerUrl")
            if ws_url:
                from websocket import create_connection  # selenium 의존 패키지
                conn = create_connection(ws_url, timeout=3)
                conn.send(_json.dumps({"id": 1, "method": "Browser.close"}))
                try:
                    conn.recv()
                except Exception:
                    pass
                conn.close()
        except Exception:
            pass
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if not self.is_running(key):
                return True
            time.sleep(0.3)
        return not self.is_running(key)
