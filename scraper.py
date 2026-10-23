#!/usr/bin/env python3
"""Polite, scope-limited FlatNama research collector with PostgreSQL storage.

It does not bypass CAPTCHAs, authentication, robots.txt, or site protections. By default,
only a small number of explicitly seeded area/project pages are collected. Whole-site
copying is not enabled; seek written permission from FlatNama before bulk collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

PARSER_VERSION = "0.7.0"
BASE_HOSTS = {"flatnama.com", "www.flatnama.com"}
PROJECT_SLUG_RE = re.compile(r"^/(?:pune/)(?P<rera>(?:p\d{8,}|p[rmcp]\d{7,}|pr\d{7,}|pm\d{7,}|pc\d{7,}|pp\d{7,}))-[^/]+/?$", re.I)
RERA_RE = re.compile(r"\b(?:P\d{9,}|PR\d{8,}|PM\d{8,}|PC\d{8,}|PP\d{8,})\b", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
MONEY_RE = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)")
KNOWN_STAGES = ("Ready to move", "Nearing possession", "Mid-construction", "Early stage")
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("flatnama-collector")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def clean_truncate(value: Any, limit: int) -> str | None:
    """Normalize a value and truncate it without slicing None/blank text."""
    if value is None:
        return None
    cleaned = clean_text(str(value))
    return cleaned[:limit] if cleaned else None


def parse_month_year(text: str | None) -> tuple[str | None, int | None]:
    if not text:
        return None, None
    m = re.search(r"\b([A-Za-z]+)\s+(20\d{2})\b", text)
    if not m:
        return None, None
    month_name = m.group(1).capitalize()
    if month_name.lower()[:3] not in MONTH_MAP:
        return None, None
    return month_name, int(m.group(2))


def parse_timeline_months(text: str | None) -> int | None:
    if not text:
        return None
    years = re.search(r"(\d+)\s*(?:years?|yrs?)", text, re.I)
    months = re.search(r"(\d+)\s*(?:months?|mths?)", text, re.I)
    total = 0
    if years:
        total += int(years.group(1)) * 12
    if months:
        total += int(months.group(1))
    if total == 0:
        single_m = re.search(r"(\d+)\s*months?\b", text, re.I)
        if single_m:
            total = int(single_m.group(1))
    return total if total > 0 else None


def diff_in_months(year1: int | None, month1_num: int | None, year2: int | None, month2_num: int | None) -> int | None:
    if None in (year1, month1_num, year2, month2_num):
        return None
    return (year2 - year1) * 12 + (month2_num - month1_num)


def extract_phase_name(name: str | None) -> str | None:
    if not name:
        return None
    patterns = [
        r"(?:[-–—|]\s*)?((?:BUILDING[- ]+[A-Z0-9]+(?:\s*[-–—]\s*)?)?(?:Phase\s+[A-Z0-9]+|Wing\s+[A-Z0-9]+|[A-Z0-9]+\s+Wing|Tower\s+[A-Z0-9]+|Building\s+[A-Z0-9]+(?:\s+Phase\s+[A-Z0-9]+)?))\b",
        r"\b(Phase\s+[A-Z0-9]+)\b",
        r"\b([A-Z0-9]+\s+Wing)\b",
        r"\b(Building\s+[A-Z0-9]+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, name, re.I)
        if m:
            cand = m.group(1).strip()
            if cand and len(cand) <= 60:
                return cand
    return None


def extract_project_type(name: str | None, flat_text: str) -> str | None:
    combined = f"{name or ''} {flat_text}".lower()
    if "residential and commercial" in combined or "mixed use" in combined:
        return "Mixed Use"
    if "business zone" in combined or "commercial" in combined or "tech park" in combined or "office space" in combined:
        return "Commercial"
    if "residential" in combined or "apartment" in combined or "flat" in combined or "bhk" in combined:
        return "Residential"
    return None


def aggregate_unit_mix(unit_mix: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "units_1rk": 0,
        "units_1bhk": 0,
        "units_2bhk": 0,
        "units_3bhk": 0,
        "units_4bhk": 0,
        "units_5bhk_plus": 0,
        "units_other": 0,
        "total_residential_units": 0,
    }
    for item in unit_mix:
        t = (item.get("flat_type") or "").upper()
        cnt = item.get("unit_count") or 0
        if "1 RK" in t:
            counts["units_1rk"] += cnt
        elif "1 BHK" in t:
            counts["units_1bhk"] += cnt
        elif "2 BHK" in t:
            counts["units_2bhk"] += cnt
        elif "3 BHK" in t:
            counts["units_3bhk"] += cnt
        elif "4 BHK" in t:
            counts["units_4bhk"] += cnt
        elif any(x in t for x in ("5+", "5 BHK", "6 BHK")):
            counts["units_5bhk_plus"] += cnt
        else:
            counts["units_other"] += cnt
    counts["total_residential_units"] = sum(counts.values()) - counts["units_other"]
    return counts


def compute_progress_deltas(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(u: dict[str, Any]) -> tuple[int, int]:
        m, y = parse_month_year(u.get("update_label"))
        m_num = MONTH_MAP.get((m or "").lower()[:3], 0)
        return (y or 0, m_num)

    sorted_u = sorted(updates, key=sort_key)
    for i, curr in enumerate(sorted_u):
        if i == 0:
            curr["rcc_change"] = None
            curr["finishing_change"] = None
            curr["booking_change"] = None
        else:
            prev = sorted_u[i - 1]
            curr["rcc_change"] = round(curr["rcc_pct"] - prev["rcc_pct"], 2) if curr.get("rcc_pct") is not None and prev.get("rcc_pct") is not None else None
            curr["finishing_change"] = round(curr["finishing_pct"] - prev["finishing_pct"], 2) if curr.get("finishing_pct") is not None and prev.get("finishing_pct") is not None else None
            curr["booking_change"] = curr["units_booked"] - prev["units_booked"] if curr.get("units_booked") is not None and prev.get("units_booked") is not None else None
    return sorted(sorted_u, key=sort_key, reverse=True)


def extract_breadcrumbs(soup: BeautifulSoup, page_url: str, project_name: str | None) -> list[dict[str, str]]:
    crumbs: list[dict[str, str]] = []
    b_tag = soup.find(class_=re.compile(r"breadcrumb", re.I))
    if b_tag:
        for a in b_tag.find_all("a", href=True):
            lbl = clean_text(a.get_text(" ", strip=True))
            if lbl:
                crumbs.append({"label": lbl, "url": urljoin(page_url, a["href"])})
    if not crumbs:
        crumbs = [{"label": "Pune", "url": "https://flatnama.com/pune/"}]
    if project_name and (not crumbs or crumbs[-1].get("label") != project_name):
        crumbs.append({"label": project_name, "url": canonical_url(page_url)})
    return crumbs


def extract_source_faqs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extracts only genuine source-published FAQs from HTML or JSON-LD schema.org/FAQPage."""
    faqs = []
    # 1. Parse JSON-LD FAQPage if present
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
            if isinstance(payload, dict) and payload.get("@type") == "FAQPage":
                for item in payload.get("mainEntity", []):
                    q = clean_text(item.get("name"))
                    ans = clean_text(item.get("acceptedAnswer", {}).get("text"))
                    if q and ans:
                        faqs.append({"topic": "Source FAQ", "question": q, "answer": ans, "is_synthesized": False})
        except Exception:
            continue

    # 2. Parse HTML FAQ sections (<details> or accordion with FAQ classes)
    for block in soup.find_all(["details", "div"], class_=re.compile(r"\b(?:faq|accordion)\b", re.I)):
        summary = block.find(["summary", "h3", "h4", "button"])
        if summary:
            q = clean_text(summary.get_text(" ", strip=True))
            content_nodes = [c for c in block.find_all(["p", "div", "span"], recursive=False) if c != summary]
            ans = clean_text(" ".join(c.get_text(" ", strip=True) for c in content_nodes))
            if q and ans and len(q) > 5 and len(ans) > 10:
                faqs.append({"topic": "Source FAQ", "question": q, "answer": ans, "is_synthesized": False})

    return faqs


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are accepted: {url}")
    if (parsed.hostname or "").lower() not in BASE_HOSTS:
        raise ValueError(f"Only flatnama.com URLs are accepted: {url}")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and not path.endswith("/"):
        path += "/"
    # Drop tracking/query parameters and fragments; data pages do not need them.
    return urlunparse(("https", "flatnama.com", path, "", "", ""))


def is_project_url(url: str) -> bool:
    return bool(PROJECT_SLUG_RE.match(urlparse(canonical_url(url)).path))


def read_url_file(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(canonical_url(line))
    # De-dupe without changing order.
    return list(dict.fromkeys(urls))


@dataclass
class FetchResult:
    requested_url: str
    canonical_url: str
    status_code: int
    html: str
    content_sha256: str
    fetched_at: datetime


class PoliteClient:
    def __init__(self, user_agent: str, delay_seconds: float, timeout_seconds: float, max_retries: int):
        if not user_agent or "your-email@example.com" in user_agent:
            raise ValueError("Set FLATNAMA_USER_AGENT to a descriptive User-Agent with a real contact channel in .env")
        self.delay = max(1.0, delay_seconds)
        self.timeout = timeout_seconds
        self.max_retries = max(0, min(max_retries, 4))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.8",
        })
        self._last_request = 0.0
        self._robots: RobotFileParser | None = None

    def _throttle(self) -> None:
        remaining = self.delay - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)

    def _get_robots(self) -> RobotFileParser:
        if self._robots is not None:
            return self._robots
        robots_url = "https://flatnama.com/robots.txt"
        self._throttle()
        try:
            response = self.session.get(robots_url, timeout=self.timeout, allow_redirects=False)
            self._last_request = time.monotonic()
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not check robots.txt; stopping rather than guessing: {exc}") from exc
        if response.status_code in (403, 429) or response.status_code >= 500:
            raise RuntimeError(f"robots.txt returned HTTP {response.status_code}; stopping rather than guessing")
        parser = RobotFileParser(robots_url)
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
        elif response.status_code == 404:
            # No robots file is different from a robots file that disallows crawling.
            parser.parse([])
        else:
            raise RuntimeError(f"Unexpected robots.txt response HTTP {response.status_code}; refusing to crawl")
        self._robots = parser
        return parser

    def fetch(self, url: str) -> FetchResult:
        url = canonical_url(url)
        robots = self._get_robots()
        if not robots.can_fetch(self.session.headers["User-Agent"], url):
            raise PermissionError(f"robots.txt disallows fetching {url}")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
                self._last_request = time.monotonic()
            except requests.RequestException as exc:
                self._last_request = time.monotonic()
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(15, 2 ** (attempt + 1)))
                    continue
                raise RuntimeError(f"Request failed for {url}: {exc}") from exc

            if response.status_code in (403, 429):
                raise RuntimeError(f"HTTP {response.status_code} for {url}; stopping. Do not bypass access controls or rate limits.")
            if response.status_code in (500, 502, 503, 504) and attempt < self.max_retries:
                time.sleep(min(20, 2 ** (attempt + 1)))
                continue
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code} for {url}")

            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                raise RuntimeError(f"Unexpected content type for {url}: {content_type}")
            body_lower = response.text[:150_000].lower()
            if any(marker in body_lower for marker in ("verify you are human", "captcha challenge", "access denied by security")):
                raise RuntimeError(f"Possible challenge/access restriction returned for {url}; stopping without attempting to bypass it")

            html = response.text
            return FetchResult(
                requested_url=url,
                canonical_url=url,
                status_code=response.status_code,
                html=html,
                content_sha256=hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest(),
                fetched_at=utcnow(),
            )
        raise RuntimeError(f"Could not fetch {url}: {last_error}")


def normalize_rupees(text: str | None) -> float | None:
    if not text:
        return None
    m = MONEY_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_indian_price(text: str | None) -> float | None:
    """Parse example labels '₹1.32 – 1.71 crore' into INR only for price-band strings."""
    if not text:
        return None
    m = re.search(r"₹\s*([\d.]+)\s*(?:[–—-]\s*([\d.]+))?\s*(crore|lakh|lac)?", text, re.I)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(3) or "").lower()
    factor = 10_000_000 if unit == "crore" else (100_000 if unit in ("lakh", "lac") else 1)
    return round(val * factor, 2)


def parse_size_range(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:–|—|-|to)\s*([\d,]+(?:\.\d+)?)\s*sq\s*ft", text, re.I)
    if m:
        return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*sq\s*ft", text, re.I)
    if m:
        val = float(m.group(1).replace(",", ""))
        return val, val
    return None, None


def parse_price_range(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    # Same unit suffix is typically applied to both ends, e.g. ₹1.32 – 1.71 crore.
    m = re.search(r"₹\s*([\d.]+)\s*(?:–|—|-|to)\s*([\d.]+)\s*(crore|lakh|lac)?", text, re.I)
    if m:
        factor = 10_000_000 if (m.group(3) or "").lower() == "crore" else (100_000 if (m.group(3) or "").lower() in ("lakh", "lac") else 1)
        return round(float(m.group(1)) * factor, 2), round(float(m.group(2)) * factor, 2)
    single = parse_indian_price(text)
    return single, single


ANNUAL_PRICE_RE = re.compile(
    r"(?<!\d)(?P<label>20\d{2}(?:\s+so\s+far)?)"
    r"\s*(?:[·•|:–—-]\s*)?₹\s*(?P<price>[\d,]+(?:\.\d+)?)"
    r"\s*(?:per\s*sq\s*ft|/\s*sq\.?\s*ft)\b"
    r"(?P<middle>.{0,220}?)\b(?P<count>[\d,]+)\s+registered\s+sales?\s+found\b",
    re.I,
)
UNIT_MIX_RE = re.compile(
    r"^(?P<count>[\d,]+)\s+(?P<type>(?:1|2|3|4|5\+)\s*(?:BHK|RK)|Other)$",
    re.I,
)


def _candidate_texts(soup: BeautifulSoup, flat_text: str) -> list[str]:
    """Return de-duplicated, normalized short text blocks plus the whole-page text.

    The same facts commonly appear in a list item, its parent card, and the page's
    accessible/SEO text. Scanning multiple block sizes is intentional; downstream
    extraction de-duplicates by the fact's natural key.
    """
    found: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all(["li", "tr", "td", "th", "p", "span", "div", "section", "article", "dd"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt or len(txt) > 1200 or txt in seen:
            continue
        seen.add(txt)
        found.append(txt)
    if flat_text and flat_text not in seen:
        found.append(flat_text)
    return sorted(found, key=len)


def _extract_annual_price_stats(soup: BeautifulSoup, flat_text: str) -> list[dict[str, Any]]:
    """Extract every visible annual project-level price statistic from the named section.

    FlatNama sometimes inserts a year-over-year phrase between the year and price, e.g.
    ``2025 down 2% on 2024 ₹22,700 per sq ft 42 registered sales found``. The parser
    deliberately starts inside the year-by-year section and consumes each whole row, so the
    comparison year cannot be mistaken for a separate sale year. Both "registered sales found"
    and short "sales" labels are supported because page renderings have differed.

    These are project-level 80th-percentile summaries, not individual sale transactions.
    """
    heading_pattern = re.compile(r"price\s+per\s+sq\.?\s*ft\s*,?\s*year\s+by\s+year", re.I)
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    section_texts: list[str] = []
    page_tags = list(soup.find_all(True))

    # Collect section candidates from DOM elements, stopping at the next semantic heading.
    for idx, tag in enumerate(page_tags):
        if tag.name not in heading_tags or not heading_pattern.search(clean_text(tag.get_text(" ", strip=True)) or ""):
            continue
        for candidate in page_tags[idx + 1:]:
            if candidate.name in heading_tags:
                break
            if candidate.name not in {"li", "tr", "td", "th", "p", "span", "div", "ul", "ol", "table", "section", "article"}:
                continue
            if candidate.find(list(heading_tags)) is not None:
                continue
            txt = clean_text(candidate.get_text(" ", strip=True))
            if txt and len(txt) <= 6000 and re.search(r"\b20\d{2}\b", txt) and "₹" in txt:
                section_texts.append(txt)

    # Flat text fallback: scope strictly from the annual section heading to the next heading.
    heading_match = heading_pattern.search(flat_text)
    if heading_match:
        tail = flat_text[heading_match.end():]
        stop_match = re.search(
            r"\b(?:Construction\s+progress|Updates\s+reported\s+to\s+MahaRERA|Other\s+phases\s+of\s+this\s+project|About\s+this\s+project|Disclaimers)\b",
            tail, re.I,
        )
        section_texts.append(tail[:stop_match.start()] if stop_match else tail)

    if not section_texts:
        return []

    annual_row_re = re.compile(
        r"(?<!\d)(?P<label>20\d{2}(?:\s+so\s+far)?)"
        # Comparison delta sometimes has no whitespace where adjacent inline spans meet.
        r"(?P<delta>\s*(?:up|down)\s*\d+(?:\.\d+)?%\s*on\s*20\d{2})?"
        r"\s*(?:[·•|:–—-]\s*)?₹\s*(?P<price>[\d,]+(?:\.\d+)?)"
        r"\s*(?:per\s*sq\.?\s*ft|/\s*sq\.?\s*ft)?"
        r".{0,260}?(?P<count>[\d,]+)\s+(?:registered\s+sales?\s+found|registered\s+sales?|sales?)\b",
        re.I,
    )

    rows: dict[tuple[int, bool, float, int], dict[str, Any]] = {}
    for candidate in sorted(set(section_texts), key=len):
        for match in annual_row_re.finditer(candidate):
            label = clean_text(match.group("label")) or match.group("label")
            year_match = YEAR_RE.search(label)
            try:
                if not year_match:
                    continue
                year = int(year_match.group(1))
                price = float(match.group("price").replace(",", ""))
                count = int(match.group("count").replace(",", ""))
            except (AttributeError, TypeError, ValueError):
                continue
            # Ignore impossible numbers rather than interpreting nearby prose as prices.
            if price <= 0 or count < 0:
                continue
            key = (year, "so far" in label.lower(), price, count)
            rows.setdefault(key, {
                "sales_year": year,
                "year_label": label,
                "price_per_sqft_80pct": price,
                "sale_count": count,
                "year_over_year_delta_text": clean_text(match.group("delta")),
                "raw_row": [match.group(0)[:500]],
            })
    return sorted(rows.values(), key=lambda x: (x["sales_year"], "so far" in x["year_label"].lower()))


def _extract_headline_price(soup: BeautifulSoup, flat_text: str) -> dict[str, Any]:
    """Extract the page's headline price statistic for cross-checking annual history."""
    candidates = _candidate_texts(soup, flat_text)
    for candidate in candidates:
        low = candidate.lower()
        if "price per sq ft" not in low or "registered sales found" not in low:
            continue
        price_match = re.search(r"price per sq ft(?:\s*\([^)]*\))?.{0,100}?₹\s*([\d,]+(?:\.\d+)?)", candidate, re.I)
        count_matches = list(re.finditer(r"([\d,]+)\s+registered\s+sales\s+found", candidate, re.I))
        if not price_match or not count_matches:
            continue
        # The headline can mention the same calendar year twice (e.g. "in 2026 ... 2026 so far").
        # Restrict year detection to text before the sales-count phrase so the comparison
        # suffix (e.g. "up 5% on 2025") cannot override the headline period ("2026 so far").
        prefix = candidate[:count_matches[-1].start()]
        labels = list(re.finditer(r"20\d{2}(?:\s+so\s+far)?", prefix, re.I))
        year_label = clean_text(labels[-1].group(0)) if labels else None
        return {
            "price_per_sqft_80pct": float(price_match.group(1).replace(",", "")),
            "year_label": year_label,
            "sales_year": int(YEAR_RE.search(year_label).group(1)) if year_label and YEAR_RE.search(year_label) else None,
            "sale_count": int(count_matches[-1].group(1).replace(",", "")),
            "raw_text": candidate[:500],
        }
    return {"price_per_sqft_80pct": None, "year_label": None, "sales_year": None, "sale_count": None, "raw_text": None}


def _extract_unit_mix(soup: BeautifulSoup, lines: list[str]) -> list[dict[str, Any]]:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    candidates = list(lines)
    candidates.extend(_candidate_texts(soup, ""))
    for text in candidates:
        txt = clean_text(text) or ""
        if len(txt) > 100:
            continue
        # The common list layout reads e.g. "60 2 BHK" or "2 1 RK".
        m = UNIT_MIX_RE.fullmatch(txt)
        if not m:
            # Handle table-style cells serialized as "2 BHK | 60".
            m2 = re.fullmatch(r"(?P<type>(?:1|2|3|4|5\+)\s*(?:BHK|RK)|Other)\s*[|:]\s*(?P<count>[\d,]+)", txt, re.I)
            if m2:
                flat_type = re.sub(r"\s+", " ", m2.group("type")).upper()
                count = int(m2.group("count").replace(",", ""))
            else:
                continue
        else:
            flat_type = re.sub(r"\s+", " ", m.group("type")).upper()
            count = int(m.group("count").replace(",", ""))
        rows[(flat_type, count)] = {"flat_type": flat_type, "unit_count": count}
    return sorted(rows.values(), key=lambda x: x["flat_type"])


def _extract_size_price_bands(soup: BeautifulSoup, lines: list[str], default_year_label: str | None) -> list[dict[str, Any]]:
    rows: dict[tuple[float | None, float | None, float | None, float | None, str, str], dict[str, Any]] = {}
    candidates: list[str] = list(lines)
    for tag in soup.find_all(["tr", "li", "p", "td", "dd", "div", "span"]):
        txt = clean_text(tag.get_text(" | ", strip=True))
        if txt and len(txt) <= 300:
            candidates.append(txt)
    for txt in candidates:
        if "sq ft" not in txt.lower() or "₹" not in txt:
            continue
        size_label = next((part.strip() for part in re.split(r"\s*[|]\s*", txt) if "sq ft" in part.lower() and parse_size_range(part) != (None, None)), None)
        price_label = next((part.strip() for part in re.split(r"\s*[|]\s*", txt) if "₹" in part and ("crore" in part.lower() or "lakh" in part.lower() or "lac" in part.lower())), None)
        if not size_label:
            size_match = re.search(r"[\d,]+(?:\.\d+)?\s*(?:–|—|-|to)?\s*[\d,]*(?:\.\d+)?\s*sq\s*ft", txt, re.I)
            size_label = size_match.group(0) if size_match else None
        if not price_label:
            price_match = re.search(r"₹\s*[\d.]+\s*(?:(?:–|—|-|to)\s*[\d.]+)?\s*(?:crore|lakh|lac)", txt, re.I)
            price_label = price_match.group(0) if price_match else None
        if not size_label or not price_label:
            continue
        min_size, max_size = parse_size_range(size_label)
        min_price, max_price = parse_price_range(price_label)
        if min_size is None or min_price is None:
            continue
        key = (min_size, max_size, min_price, max_price, size_label, price_label)
        rows.setdefault(key, {
            "year_label": default_year_label,
            "min_size_sqft": min_size,
            "max_size_sqft": max_size,
            "min_price_inr": min_price,
            "max_price_inr": max_price,
            "raw_size_label": size_label,
            "raw_price_label": price_label,
        })
    return list(rows.values())


def project_link_discovery_details(html: str, base_url: str) -> tuple[list[str], str]:
    """Find project links from project-card containers, avoiding related-phase links where possible.

    If the page HTML has no recognisable card containers, fall back to all matching project
    links and return an explicit fallback label. This avoids silently pretending that a
    heuristic matched the area's entire catalogue.
    """
    soup = BeautifulSoup(html, "html.parser")
    all_links: list[str] = []
    card_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        try:
            href = canonical_url(href)
        except ValueError:
            continue
        if not is_project_url(href):
            continue
        all_links.append(href)
        parent = a.parent
        for _ in range(6):
            if parent is None or getattr(parent, "name", None) in {"body", "html", "main", "[document]"}:
                break
            text = clean_text(parent.get_text(" ", strip=True)) or ""
            low = text.lower()
            has_project_facts = (
                ("possession date" in low or "possession" in low)
                and ("units booked" in low or "concrete structure" in low or "rcc" in low or "bhk" in low or "rk" in low)
            )
            if has_project_facts and 30 <= len(text) <= 1800:
                card_links.append(href)
                break
            # Stop as soon as a card-like container would become a large page wrapper.
            if len(text) > 1800:
                break
            parent = parent.parent
    unique_cards = list(dict.fromkeys(card_links))
    if unique_cards:
        return unique_cards, "project_card_heuristic"
    return list(dict.fromkeys(all_links)), "fallback_all_project_links_no_card_match"


def project_links_from_html(html: str, base_url: str) -> list[str]:
    """Backward-compatible wrapper for tests and external use."""
    return project_link_discovery_details(html, base_url)[0]


def parse_area_page(url: str, html: str) -> dict[str, Any]:
    """Extract locality-level summary/filters where explicitly displayed by FlatNama."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True) if h1 else None)
    visible_text = soup.get_text("\n", strip=True)
    flat_text = clean_text(visible_text) or ""
    lines = [clean_text(x) for x in visible_text.splitlines()]
    lines = [x for x in lines if x]
    area_name = title
    if area_name:
        area_name = re.sub(r"^(?:new projects in|projects in)\s+", "", area_name, flags=re.I).strip()
        area_name = re.sub(r"^new projects across\s+", "", area_name, flags=re.I).strip()
    pin_match = re.search(r"\bPIN\s+(\d{6})\b", flat_text, re.I)
    summary_match = re.search(r"([\d,]+)\s+new residential projects? in\s+([^(.]+)", flat_text, re.I)
    listed_project_count = int(summary_match.group(1).replace(",", "")) if summary_match else None
    if not area_name and summary_match:
        area_name = clean_text(summary_match.group(2))
    launched_match = re.search(r"([\d,]+)\s+(?:were|was) launched in the last 6 months", flat_text, re.I)
    structure_match = re.search(r"([\d,]+)\s+(?:have|has) (?:their )?structure\s*\(RCC\)\s+complete", flat_text, re.I)
    extended_match = re.search(r"([\d,]+)\s+(?:have|has) had (?:their )?possession date extended", flat_text, re.I)
    hidden_match = re.search(r"([\d,]+)\s+projects?\s*[·|]\s*([\d,]+)\s+small projects? hidden", flat_text, re.I)
    small_projects_hidden = int(hidden_match.group(2).replace(",", "")) if hidden_match else None
    visible_listed_count = int(hidden_match.group(1).replace(",", "")) if hidden_match else None
    nearby_areas: list[dict[str, str]] = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if "nearby areas" not in (clean_text(heading.get_text(" ", strip=True)) or "").lower():
            continue
        for node in heading.find_all_next(["h2", "h3", "h4", "a"]):
            if node.name in {"h2", "h3", "h4"}:
                break
            label = clean_text(node.get_text(" ", strip=True)) or ""
            href = node.get("href") if node.name == "a" else None
            if label:
                nearby_areas.append({"name": label, "url": urljoin(url, href) if href else ""})
    nearby_areas = list({(x["name"], x["url"]): x for x in nearby_areas}.values())
    filter_terms = ("budget", "village", "possession year", "construction stage", "flat type", "sort", "show small projects")
    filters_detected = sorted({term for term in filter_terms if term in flat_text.lower()})
    title_tag = soup.find("title")
    return {
        "area_url": canonical_url(url),
        "page_title": clean_text(title_tag.get_text(" ", strip=True) if title_tag else None),
        "heading": title,
        "area_name": area_name,
        "pin_code": pin_match.group(1) if pin_match else None,
        "listed_project_count": listed_project_count,
        "visible_projects_count_from_hidden_toggle": visible_listed_count,
        "small_projects_hidden_count": small_projects_hidden,
        "launched_last_6_months_count": int(launched_match.group(1).replace(",", "")) if launched_match else None,
        "rcc_complete_count": int(structure_match.group(1).replace(",", "")) if structure_match else None,
        "possession_date_extended_count": int(extended_match.group(1).replace(",", "")) if extended_match else None,
        "nearby_areas": nearby_areas,
        "filters_detected": filters_detected,
        "source_notes": {
            "source": "FlatNama area page",
            "scope": "Area-level catalogue summary; displayed totals and filter controls may represent only the default view.",
            "limitations": ["Area totals do not establish full catalogue extraction coverage.", "Hidden small projects and client-side filter results may not all be available in the returned HTML."],
        },
    }



_HEADING_NAMES = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_NAMES = {"address", "article", "aside", "blockquote", "dd", "div", "dt", "figcaption", "footer", "li", "main", "p", "section", "td", "th", "tr"}


def _json_safe(value: Any, max_string: int = 12000) -> Any:
    """Convert structured page values to JSON-safe, bounded primitives."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:max_string]
    if isinstance(value, list):
        return [_json_safe(v, max_string) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k)[:200]: _json_safe(v, max_string) for k, v in list(value.items())[:300]}
    return clean_text(str(value))


def _extract_comprehensive_page_data(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    """Preserve broad page-level evidence that does not fit the curated columns.

    The canonical columns remain convenient for analysis; these structured captures make the
    PostgreSQL JSONB snapshot retain the rest of the rendered page's available facts and links.
    Only metadata is captured for images; image files are not downloaded.
    """
    body = soup.body or soup
    raw_lines = [clean_text(x) for x in body.get_text("\n", strip=True).splitlines()]
    text_lines = [x for x in raw_lines if x]
    # Repeated page chrome can appear, but preserve order for auditability. Bound pathological pages.
    text_lines = text_lines[:1200]

    # Meta and canonical metadata.
    meta_tags: list[dict[str, Any]] = []
    for tag in soup.find_all("meta")[:300]:
        attrs = tag.attrs or {}
        content = attrs.get("content")
        if isinstance(content, list):
            content = " ".join(map(str, content))
        key_parts = []
        for attr_name in ("name", "property", "itemprop", "http-equiv", "charset"):
            val = attrs.get(attr_name)
            if val:
                key_parts.append(f"{attr_name}={val}")
        if content or key_parts:
            meta_tags.append({"keys": key_parts, "content": clean_truncate(content, 3000)})
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in ([str(v).lower() for v in value] if isinstance(value, list) else str(value).lower().split()))
    canonical_href = urljoin(page_url, canonical_tag.get("href")) if canonical_tag and canonical_tag.get("href") else None

    # JSON-LD / schema.org blocks may carry a second copy of structured project metadata.
    jsonld: list[Any] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)})[:30]:
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            jsonld.append(_json_safe(json.loads(raw)))
        except (json.JSONDecodeError, TypeError):
            jsonld.append({"parse_error": True, "raw_excerpt": clean_truncate(raw, 1500)})

    # Generic section contents, based on visible text order, not only sections known to our parser.
    sections: list[dict[str, Any]] = []
    heading_entries: list[tuple[int, int, str]] = []
    for heading in soup.find_all(list(_HEADING_NAMES)):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if heading_text:
            heading_entries.append((len(heading_entries), int(heading.name[1]), heading_text[:300]))
    # Match heading text against displayed text lines sequentially, then take every line to next heading.
    positions: list[tuple[int, int, str]] = []
    cursor = 0
    for _, level, heading_text in heading_entries:
        found_idx = None
        for idx in range(cursor, len(text_lines)):
            if text_lines[idx] == heading_text:
                found_idx = idx
                break
        if found_idx is None:
            # Some headings include nested/icon text that differs from the visible text line.
            target = heading_text.lower()
            for idx in range(cursor, len(text_lines)):
                if text_lines[idx].lower() == target or (len(target) > 12 and target in text_lines[idx].lower()):
                    found_idx = idx
                    break
        if found_idx is not None:
            positions.append((found_idx, level, heading_text))
            cursor = found_idx + 1
    for i, (line_idx, level, heading_text) in enumerate(positions):
        end_idx = positions[i + 1][0] if i + 1 < len(positions) else len(text_lines)
        content_lines = text_lines[line_idx + 1:end_idx]
        sections.append({
            "heading": heading_text,
            "heading_level": level,
            "text_lines": content_lines[:250],
            "text": "\n".join(content_lines)[:15000],
        })

    # Every HTML table, not just tables recognized as unit mix / progress / comparables.
    tables: list[dict[str, Any]] = []
    for table_idx, table in enumerate(soup.find_all("table")[:100]):
        rows: list[list[str]] = []
        for tr in table.find_all("tr")[:300]:
            cells = [clean_text(cell.get_text(" ", strip=True)) or "" for cell in tr.find_all(["th", "td"], recursive=False)]
            if not cells:
                cells = [clean_text(cell.get_text(" ", strip=True)) or "" for cell in tr.find_all(["th", "td"])[:20]]
            if any(cells):
                rows.append(cells[:30])
        if rows:
            headers = rows[0] if any(cell for cell in rows[0]) else []
            tables.append({"table_index": table_idx, "headers": headers, "rows": rows[:300], "row_count": len(rows)})

    # Every unordered/ordered list, preserving list hierarchy as visible item text.
    lists_data: list[dict[str, Any]] = []
    for list_idx, list_tag in enumerate(soup.find_all(["ul", "ol"])[:150]):
        items = []
        for li in list_tag.find_all("li", recursive=False)[:250]:
            value = clean_text(li.get_text(" ", strip=True))
            if value:
                items.append(value[:2000])
        if items:
            lists_data.append({"list_index": list_idx, "kind": list_tag.name, "items": items, "item_count": len(items)})

    # Normalize table key/value rows and definition-list pairs as a flexible property-facts layer.
    key_value_facts: list[dict[str, Any]] = []
    for table in tables:
        rows = table.get("rows") or []
        for row_idx, row in enumerate(rows):
            if len(row) == 2 and row[0] and row[1]:
                key_value_facts.append({"label": row[0], "value": row[1], "source_type": "table_row", "source_table_index": table["table_index"], "source_row_index": row_idx})
    for dl_idx, dl in enumerate(soup.find_all("dl")[:100]):
        terms = dl.find_all("dt", recursive=False)
        for term in terms:
            definitions = []
            sibling = term.find_next_sibling()
            while sibling and sibling.name == "dd":
                val = clean_text(sibling.get_text(" ", strip=True))
                if val:
                    definitions.append(val[:1500])
                sibling = sibling.find_next_sibling()
            if definitions:
                key_value_facts.append({"label": clean_text(term.get_text(" ", strip=True)), "value": definitions, "source_type": "definition_list", "source_table_index": dl_idx})
    # FlatNama's project facts sometimes appear as separate text lines separated by a pipe, not table markup.
    for line_idx, line in enumerate(text_lines):
        if "|" not in line:
            continue
        parts = [clean_text(part) for part in line.split("|")]
        if len(parts) == 2 and parts[0] and parts[1] and len(parts[0]) <= 120 and len(parts[1]) <= 300:
            key_value_facts.append({"label": parts[0], "value": parts[1], "source_type": "pipe_text_line", "source_line_index": line_idx})

    # Many fact cards are built with DIV/SPAN grids rather than semantic TABLE or DL elements.
    # Capture compact direct-child pairs (label/value) so their values remain structured too.
    for node_idx, node in enumerate(soup.find_all(["div", "li", "p", "section", "article"])[:2500]):
        direct_children = [child for child in node.find_all(recursive=False) if getattr(child, "name", None)]
        if not (2 <= len(direct_children) <= 4):
            continue
        child_texts = [clean_text(child.get_text(" ", strip=True)) for child in direct_children]
        child_texts = [value for value in child_texts if value]
        if len(child_texts) < 2 or len(child_texts) > 4:
            continue
        # A compact pair is a useful fact only when the parent is reasonably short.
        parent_text = clean_text(node.get_text(" ", strip=True)) or ""
        if len(parent_text) > 450 or len(parent_text) < 3:
            continue
        if len(child_texts) == 2 and child_texts[0] != child_texts[1]:
            key_value_facts.append({"label": child_texts[0][:200], "value": child_texts[1][:400], "source_type": "dom_child_pair", "source_node_index": node_idx})

    facts_by_value: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in key_value_facts:
        label = clean_text(str(fact.get("label") or "")) or ""
        value_key = json.dumps(fact.get("value"), ensure_ascii=False, sort_keys=True, default=str)
        key = (label.casefold(), value_key.casefold())
        source_evidence = {
            k: fact[k] for k in ("source_type", "source_table_index", "source_row_index", "source_line_index", "source_node_index") if k in fact
        }
        if key not in facts_by_value:
            facts_by_value[key] = {
                "label": label,
                "value": fact.get("value"),
                "evidence_sources": [source_evidence],
            }
        else:
            existing = facts_by_value[key]
            if source_evidence not in existing["evidence_sources"]:
                existing["evidence_sources"].append(source_evidence)
    deduped_facts = list(facts_by_value.values())

    # Links from the detail page—including maps, section anchors, related phases, and source links.
    links: list[dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True)[:1000]:
        raw_href = str(anchor.get("href", "")).strip()
        absolute_href = urljoin(page_url, raw_href)
        label = clean_text(anchor.get_text(" ", strip=True)) or clean_text(anchor.get("aria-label")) or clean_text(anchor.get("title"))
        if not raw_href and not label:
            continue
        host = (urlparse(absolute_href).hostname or "").lower()
        classes = anchor.get("class", [])
        rel = anchor.get("rel", [])
        links.append({
            "text": (label or "")[:500],
            "href": absolute_href[:2000],
            "raw_href": raw_href[:1000],
            "same_site": host in BASE_HOSTS,
            "is_anchor": raw_href.startswith("#"),
            "rel": [str(x) for x in rel] if isinstance(rel, list) else str(rel),
            "class": [str(x) for x in classes] if isinstance(classes, list) else str(classes),
            "title": clean_truncate(anchor.get("title"), 500),
        })

    # Full image metadata rather than URL-only records; no images are downloaded.
    image_assets: list[dict[str, Any]] = []
    for img in soup.find_all(["img", "source"])[:300]:
        attrs = img.attrs or {}
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("srcset") or attrs.get("data-srcset")
        if isinstance(src, list):
            src = " ".join(str(v) for v in src)
        if not src and not attrs.get("alt"):
            continue
        image_assets.append({
            "tag": img.name,
            "src": urljoin(page_url, str(src).split(",")[0].strip().split(" ")[0]) if src else None,
            "srcset": clean_truncate(attrs.get("srcset") or attrs.get("data-srcset"), 3000),
            "alt": clean_truncate(attrs.get("alt"), 1000),
            "title": clean_truncate(attrs.get("title"), 500),
            "width": attrs.get("width"),
            "height": attrs.get("height"),
            "loading": attrs.get("loading"),
            "class": [str(v) for v in attrs.get("class", [])] if isinstance(attrs.get("class", []), list) else str(attrs.get("class")),
        })
    og_images = [m.get("content") for m in soup.find_all("meta", attrs={"property": re.compile(r"^og:image$", re.I)}) if m.get("content")]

    # Capture concise data-* attributes and controls when present (charts, responsive cards, filters).
    data_attributes: list[dict[str, Any]] = []
    for tag in soup.find_all(True):
        if len(data_attributes) >= 600:
            break
        data_attrs = {str(k): _json_safe(v) for k, v in (tag.attrs or {}).items() if str(k).startswith("data-") and v not in (None, "")}
        if data_attrs:
            text_excerpt = clean_text(tag.get_text(" ", strip=True))
            data_attributes.append({"tag": tag.name, "text": text_excerpt[:500] if text_excerpt else None, "attributes": data_attrs})

    controls: list[dict[str, Any]] = []
    for tag in soup.find_all(["button", "input", "select", "option", "iframe", "video", "audio"])[:500]:
        attrs = tag.attrs or {}
        label = clean_text(tag.get_text(" ", strip=True)) or clean_text(attrs.get("aria-label")) or clean_text(attrs.get("name"))
        control = {"tag": tag.name, "label": (label or "")[:500]}
        for attr in ("type", "name", "value", "placeholder", "href", "src", "title", "aria-label", "selected", "checked", "disabled", "id"):
            if attrs.get(attr) is not None:
                control[attr] = _json_safe(attrs.get(attr))
        if tag.name == "select":
            control["options"] = [{"text": clean_text(opt.get_text(" ", strip=True)), "value": opt.get("value"), "selected": opt.has_attr("selected")} for opt in tag.find_all("option")[:100]]
        controls.append(control)

    return {
        "capture_version": 1,
        "page_url": canonical_url(page_url),
        "canonical_url_from_page": canonical_href,
        "page_title": clean_text(soup.title.get_text(" ", strip=True)) if soup.title else None,
        "meta_tags": meta_tags,
        "open_graph_image_urls": og_images,
        "json_ld": jsonld,
        "sections": sections,
        "tables": tables,
        "lists": lists_data,
        "key_value_facts": deduped_facts,
        "links": links,
        "images": image_assets,
        "data_attributes": data_attributes,
        "controls_and_embeds": controls,
        "visible_text_lines": text_lines,
        "visible_text_char_count": sum(len(x) for x in text_lines),
        "capture_limits": {
            "text_lines_max": 1200,
            "tables_max": 100,
            "links_max": 1000,
            "images_max": 300,
            "data_attribute_elements_max": 600,
            "images_downloaded": False,
            "raw_html_stored": False,
        },
    }

def parse_project_page(url: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ", strip=True) if h1 else None)
    visible_text = soup.get_text("\n", strip=True)
    flat_text = clean_text(visible_text) or ""
    lines = [clean_text(x) for x in visible_text.splitlines()]
    lines = [x for x in lines if x]

    rera_match = RERA_RE.search(flat_text) or RERA_RE.search(url)
    rera = rera_match.group(0).upper() if rera_match else None

    developer = locality = pin_code = None
    # Match the final "... Locality, Pune 411xxx" segment so a developer name such as
    # "Pvt. Ltd." does not get split at its internal periods.
    for place_match in re.finditer(r"\.\s+([^,.\n]{2,100}),\s*Pune\s+(\d{6})\b", flat_text, re.I):
        by_pos = flat_text.lower().rfind(" by ", 0, place_match.start())
        if by_pos >= 0:
            developer_candidate = clean_text(flat_text[by_pos + 4:place_match.start()].rstrip(" ."))
            if developer_candidate and len(developer_candidate) <= 200:
                developer = developer_candidate
                locality = clean_text(place_match.group(1))
                pin_code = place_match.group(2)
                break

    # Breadcrumb anchors provide a second, usually less precise locality signal.
    if not locality:
        anchors = [clean_text(a.get_text(" ", strip=True)) for a in soup.select('a[href^="/pune/"]')]
        anchors = [x for x in anchors if x and x.lower() not in {"pune", "all projects", "guides", "shortlist"}]
        if len(anchors) >= 2:
            locality = anchors[-2]

    status = None
    first_lines = " | ".join(lines[:25])
    for candidate in KNOWN_STAGES:
        if candidate.lower() in first_lines.lower():
            status = candidate
            break

    def first_group(pattern: str, flags: int = re.I) -> str | None:
        m = re.search(pattern, flat_text, flags)
        return clean_text(m.group(1)) if m else None

    launch_date = first_group(r"\bLaunched\s+([A-Z][a-z]+\s+20\d{2})")
    possession_date = first_group(r"Possession date\s*\(MahaRERA\)\s+([A-Z][a-z]+\s+20\d{2})")
    promised_timeline = first_group(r"(\d+\s*(?:years?|yrs?|months?|mths?)(?:\s+\d+\s*(?:months?|mths?))?\s+promised)")
    original_possession = first_group(r"first date registered\s*[:：]?\s*([A-Z][a-z]+\s+20\d{2})") or first_group(r"originally\s+([A-Z][a-z]+\s+20\d{2})")
    maharera_status = first_group(r"MahaRERA status\s+(?:is\s+)?([A-Za-z][A-Za-z -]+?)(?:\s+Its registered possession|\s+It was launched|\.)")

    def first_int(pattern: str) -> int | None:
        value = first_group(pattern)
        if not value:
            return None
        try:
            return int(value.replace(",", ""))
        except ValueError:
            return None

    total_units = first_int(r"Total units\s*([\d,]+)") or first_int(r"([\d,]+)\s+Total units\b")
    if total_units is None:
        # Project descriptions often say "It has 114 units" rather than "Total units 114".
        total_units = first_int(r"\bhas\s+([\d,]+)\s+units\b")
    building_count = first_int(r"([\d,]+)\s+buildings?\b")
    complaint_count = first_int(r"Complaints on MahaRERA[^\d]{0,90}(\d+)\b")
    land_match = re.search(r"([\d.]+)\s+acres?\b", flat_text, re.I)
    land_acres = float(land_match.group(1)) if land_match else None

    rcc_match = re.search(r"Concrete structure\s*\(RCC\)\s*(\d{1,3}(?:\.\d+)?)%", flat_text, re.I)
    rcc_pct = float(rcc_match.group(1)) if rcc_match else None
    excavation_pct = finishing_pct = None

    # Booking values use several page layouts. Keep the page's denominator separate from total units.
    units_booked = units_for_sale = reported_booking_denominator = None
    booking_pct = None
    booking_pct_displayed = None
    recent_bookings_count = first_int(r"\+\s*([\d,]+)\s+booked recently")
    not_for_sale_units = first_int(r"([\d,]+)\s+not for sale")
    booking_patterns = [
        r"units booked\s+([\d,]+)\s+of\s+([\d,]+)",
        r"([\d,]+)\s+units booked,\s*out of\s*([\d,]+)\s+units for sale",
        r"([\d,]+)\s+of\s+([\d,]+)\s+units?\s+(?:are\s+)?booked",
        r"all booked\s+([\d,]+)\s+units booked,\s*out of\s*([\d,]+)\s+units",
    ]
    for pattern in booking_patterns:
        booking_match = re.search(pattern, flat_text, re.I)
        if booking_match:
            units_booked = int(booking_match.group(1).replace(",", ""))
            reported_booking_denominator = int(booking_match.group(2).replace(",", ""))
            break
    booking_pct_match = re.search(r"(\d+(?:\.\d+)?)%\s+booked", flat_text, re.I)
    if booking_pct_match:
        booking_pct_displayed = float(booking_pct_match.group(1))
    if units_for_sale is None and total_units is not None and not_for_sale_units is not None:
        units_for_sale = max(0, total_units - not_for_sale_units)
    if re.search(r"all units for sale are booked|all booked", flat_text, re.I):
        booking_status = "all_booked"
        if units_booked is None:
            all_booked_match = re.search(r"all units for sale are booked\s*\(?([\d,]+)\s+booked", flat_text, re.I)
            if all_booked_match:
                units_booked = int(all_booked_match.group(1).replace(",", ""))
        # If all units offered are booked, the for-sale denominator equals booked units;
        # it is not necessarily the full registered inventory.
        if units_for_sale is None and units_booked is not None:
            units_for_sale = units_booked
        booking_pct = 100.0 if units_booked is not None else booking_pct_displayed
    elif re.search(r"bookings not reported", flat_text, re.I):
        booking_status = "not_reported"
        booking_pct = None
    else:
        booking_status = "reported_count" if units_booked is not None else "unknown"
        if units_for_sale is None and reported_booking_denominator is not None:
            units_for_sale = reported_booking_denominator
        if units_for_sale is None and total_units is not None:
            units_for_sale = total_units
        if units_booked is not None and units_for_sale:
            booking_pct = round(units_booked / units_for_sale * 100, 2)
        elif booking_pct_displayed is not None:
            booking_pct = booking_pct_displayed

    # Project flat-type mix: only parse rows whose first cell is a known type.
    unit_mix: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            type_match = re.fullmatch(r"(\d+\s*BHK|\d+\s*RK|Other|5\+\s*BHK)", cells[0], re.I)
            if type_match and re.fullmatch(r"[\d,]+", cells[1]):
                unit_mix.append({"flat_type": re.sub(r"\s+", " ", cells[0]).upper(), "unit_count": int(cells[1].replace(",", ""))})

    sale_year_stats: list[dict[str, Any]] = []
    size_price_bands: list[dict[str, Any]] = []
    flat_sizes_sold_sqft: list[float] = []
    # Parse the named section from visible text lines as well as heading siblings: current
    # pages may wrap the section's list in nested cards, so find_next_siblings can miss it.
    in_size_section = False
    for line in lines:
        low = (line or "").lower()
        if "flat sizes sold here" in low:
            in_size_section = True
            continue
        if in_size_section and any(stop in low for stop in ("what buyers paid", "price per sq ft, year by year", "construction progress", "compared with")):
            in_size_section = False
        if in_size_section:
            for size_match in re.finditer(r"([\d,]+(?:\.\d+)?)\s*sq\s*ft", line or "", re.I):
                flat_sizes_sold_sqft.append(float(size_match.group(1).replace(",", "")))
    # DOM fallback for pages where the heading/list are present on one text block.
    for tag in soup.find_all(["li", "p", "div", "span"]):
        txt = clean_text(tag.get_text(" ", strip=True)) or ""
        if len(txt) <= 120 and "sq ft" in txt.lower() and re.search(r"flat sizes sold here", flat_text, re.I):
            m_size = re.fullmatch(r"([\d,]+(?:\.\d+)?)\s*sq\s*ft", txt, re.I)
            if m_size:
                flat_sizes_sold_sqft.append(float(m_size.group(1).replace(",", "")))
    flat_sizes_sold_sqft = sorted(set(flat_sizes_sold_sqft))
    band_year_match = re.search(r"Based on flats sold in\s+(20\d{2})", flat_text, re.I)
    band_year_label = band_year_match.group(1) if band_year_match else None
    progress_updates: list[dict[str, Any]] = []
    comparables: list[dict[str, Any]] = []
    comparison_summary: list[dict[str, Any]] = []

    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        if not rows:
            continue
        header_text = " ".join(rows[0]).lower()
        is_progress = "excavation" in header_text and ("structure" in header_text or "rcc" in header_text) and "update" in header_text
        is_comparison = ("possession date" in header_text and "project" in header_text) or ("launch" in header_text and "booked" in header_text and "project" in header_text)
        is_comparison_summary = "measure" in header_text and "this project" in header_text and "similar projects" in header_text

        for row in rows[1:] if len(rows) > 1 else []:
            row_text = " | ".join(row)
            year_m = YEAR_RE.search(row_text)
            price = normalize_rupees(row_text)
            sale_count_m = re.search(r"([\d,]+)\s+sales?\b", row_text, re.I)
            if year_m and price is not None and ("sq ft" in row_text.lower() or "sqft" in row_text.lower()) and sale_count_m:
                year_label = next((c for c in row if YEAR_RE.search(c)), str(year_m.group(1)))
                sale_year_stats.append({
                    "sales_year": int(year_m.group(1)),
                    "year_label": year_label,
                    "price_per_sqft_80pct": price,
                    "sale_count": int(sale_count_m.group(1).replace(",", "")),
                    "raw_row": row,
                })
            # Sold price bands (e.g., '830–880 sq ft' and '₹1.32–1.71 crore').
            size_label = next((c for c in row if "sq ft" in c.lower() and parse_size_range(c) != (None, None)), None)
            price_label = next((c for c in row if "₹" in c and ("crore" in c.lower() or "lakh" in c.lower())), None)
            if size_label and price_label:
                min_size, max_size = parse_size_range(size_label)
                min_price, max_price = parse_price_range(price_label)
                size_price_bands.append({
                    "year_label": band_year_label,
                    "min_size_sqft": min_size,
                    "max_size_sqft": max_size,
                    "min_price_inr": min_price,
                    "max_price_inr": max_price,
                    "raw_size_label": size_label,
                    "raw_price_label": price_label,
                })
            if is_progress:
                # Header order is Update, Excavation, Structure (RCC), Final finishes, Units booked.
                if len(row) >= 4:
                    def pct_at(index: int) -> float | None:
                        if index >= len(row):
                            return None
                        m = re.search(r"(\d+(?:\.\d+)?)\s*%", row[index])
                        return float(m.group(1)) if m else None
                    booked_match = re.search(r"\d+", row[4]) if len(row) > 4 else None
                    update = {
                        "update_label": row[0],
                        "excavation_pct": pct_at(1),
                        "rcc_pct": pct_at(2),
                        "finishing_pct": pct_at(3),
                        "units_booked": int(booked_match.group(0)) if booked_match else None,
                        "raw_row": row,
                    }
                    if YEAR_RE.search(row[0]):
                        progress_updates.append(update)
            if is_comparison and row:
                headers = [h.lower() for h in rows[0]]
                def col_value(term: str) -> str | None:
                    idx = next((i for i, h in enumerate(headers) if term in h), None)
                    return row[idx] if idx is not None and idx < len(row) else None
                rcc_text = col_value("structure") or col_value("rcc")
                rcc_value = re.search(r"(\d+(?:\.\d+)?)\s*%", rcc_text or "")
                comparables.append({
                    "comparable_name": row[0],
                    "launch_date_text": col_value("launch"),
                    "possession_date_text": col_value("possession date"),
                    "rcc_pct": float(rcc_value.group(1)) if rcc_value else None,
                    "booking_text": col_value("booked"),
                    "raw_row": row,
                })
            if is_comparison_summary and row:
                comparison_summary.append({
                    "measure": row[0],
                    "this_project": row[1] if len(row) > 1 else None,
                    "similar_projects": row[2] if len(row) > 2 else None,
                    "raw_row": row,
                })

    # Current FlatNama pages use list/card rows as well as tables. Scan normalized block
    # text, not only a broad section slice: hidden/SEO text and nested wrappers can move
    # section boundaries in the HTML source order. Natural-key dedupe below removes repeats.
    sale_year_stats.extend(_extract_annual_price_stats(soup, flat_text))
    unit_mix.extend(_extract_unit_mix(soup, lines))
    size_price_bands.extend(_extract_size_price_bands(soup, lines, band_year_label))

    # Deduplicate parsed arrays that can appear in more than one on-page table/card.
    unit_mix = list({(x["flat_type"], x["unit_count"]): x for x in unit_mix}.values())
    sale_year_stats = list({(x["sales_year"], bool(re.search(r"so far", x["year_label"], re.I)), x["price_per_sqft_80pct"], x["sale_count"]): x for x in sale_year_stats}.values())
    size_price_bands = list({(x["min_size_sqft"], x["max_size_sqft"], x["min_price_inr"], x["max_price_inr"]): x for x in size_price_bands}.values())
    progress_updates = list({(x["update_label"], tuple(x["raw_row"])): x for x in progress_updates}.values())
    comparison_summary = list({(x["measure"], x.get("this_project"), x.get("similar_projects")): x for x in comparison_summary}.values())

    # Keep the displayed headline statistic separate from annual history. If year-by-year
    # history is absent, use the headline as a clearly labeled fallback rather than losing it.
    headline_price = _extract_headline_price(soup, flat_text)
    latest_stat = max(sale_year_stats, key=lambda x: (x["sales_year"], "so far" in x["year_label"].lower()), default=None)
    latest_sale_year = latest_stat["sales_year"] if latest_stat else headline_price.get("sales_year")
    price_per_sqft_80pct = latest_stat["price_per_sqft_80pct"] if latest_stat else headline_price.get("price_per_sqft_80pct")
    latest_sale_count = latest_stat["sale_count"] if latest_stat else headline_price.get("sale_count")
    price_per_sqft_80pct_source = "annual_year_by_year" if latest_stat else ("headline_only" if headline_price.get("price_per_sqft_80pct") is not None else None)
    if progress_updates:
        month_number = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
        def progress_key(item: dict[str, Any]) -> tuple[int, int]:
            m = re.search(r"([A-Za-z]{3,})\s+(20\d{2})", item["update_label"])
            if not m:
                return (0, 0)
            return (int(m.group(2)), month_number.get(m.group(1)[:3].lower(), 0))
        latest_progress = max(progress_updates, key=progress_key)
        excavation_pct = latest_progress.get("excavation_pct")
        rcc_pct = latest_progress.get("rcc_pct") if latest_progress.get("rcc_pct") is not None else rcc_pct
        finishing_pct = latest_progress.get("finishing_pct")
        if latest_progress.get("units_booked") is not None and units_booked is None:
            units_booked = latest_progress["units_booked"]

    map_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = clean_text(a.get_text(" ", strip=True)) or ""
        if "google.com/maps" in href and "map" in label.lower():
            map_url = href
            break

    images = []
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        images.append(og_image["content"])
    for img in soup.find_all("img"):
        candidate_srcs = [img.get("src"), img.get("data-src"), img.get("data-lazy-src")]
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            candidate_srcs.extend(item.strip().split(" ")[0] for item in srcset.split(","))
        for candidate_src in candidate_srcs:
            if not candidate_src:
                continue
            src = urljoin(url, candidate_src)
            if src.startswith("https://") and (urlparse(src).hostname or "").lower() in BASE_HOSTS:
                images.append(src)
    images = list(dict.fromkeys(images))[:50]  # same-site image URL metadata only; files are not downloaded.

    related_project_links: list[dict[str, str]] = []
    heading_rules = (
        ("other phases of this project", "other_phase"),
        ("compared with", "comparable_project"),
        ("all projects in", "area_project_list"),
    )
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = clean_text(heading.get_text(" ", strip=True)) or ""
        category = next((kind for phrase, kind in heading_rules if phrase in heading_text.lower()), None)
        if not category:
            continue
        for sibling in heading.find_all_next(["h2", "h3", "h4", "a"]):
            if sibling.name in {"h2", "h3", "h4"}:
                break
            if sibling.name == "a" and sibling.get("href"):
                href = urljoin(url, sibling["href"])
                label = clean_text(sibling.get_text(" ", strip=True)) or ""
                if not label:
                    continue
                if href.startswith("https://flatnama.com/pune/"):
                    related_project_links.append({"category": category, "label": label, "url": canonical_url(href)})
    related_project_links = list({(x["category"], x["url"]): x for x in related_project_links}.values())

    # Market comparative deltas are descriptive context, not sold-price transactions.
    nearby_rate_match = re.search(r"rate about\s+(\d+(?:\.\d+)?)%\s+(higher|lower) than (?:other )?nearby projects", flat_text, re.I)
    yoy_match = re.search(r"\b(up|down)\s+(\d+(?:\.\d+)?)%\s+on\s+(20\d{2})", flat_text, re.I)
    rate_vs_nearby_pct = (float(nearby_rate_match.group(1)) * (1 if nearby_rate_match.group(2).lower() == "higher" else -1)) if nearby_rate_match else None
    year_over_year_change_pct = (float(yoy_match.group(2)) * (1 if yoy_match.group(1).lower() == "up" else -1)) if yoy_match else None
    year_over_year_comparison_year = int(yoy_match.group(3)) if yoy_match else None

    context_keywords = ("rate about", "up ", "lower than", "higher than", "since ", "was due", "months away",
                        "promised", "not for sale", "booked recently", "bookings not reported", "last reported",
                        "possession date unchanged", "extended", "revised")
    market_context = [line for line in lines if any(k in line.lower() for k in context_keywords)]
    meta_description_tag = soup.find("meta", attrs={"name": "description"})
    page_title_tag = soup.find("title")
    comprehensive_page_data = _extract_comprehensive_page_data(soup, url)
    not_for_sale_flag_derived = bool(units_for_sale is not None and not_for_sale_units is not None and
                                     not re.search(r"units for sale", flat_text, re.I))

    phase_name = extract_phase_name(name)
    project_type = extract_project_type(name, flat_text)
    project_desc = clean_text(meta_description_tag.get("content") if meta_description_tag else None)
    launch_month, launch_year = parse_month_year(launch_date)
    possession_month, possession_year = parse_month_year(possession_date)
    promised_timeline_months = parse_timeline_months(promised_timeline)

    now = utcnow()
    months_elapsed = diff_in_months(launch_year, MONTH_MAP.get((launch_month or "").lower()[:3]), now.year, now.month)
    months_remaining = diff_in_months(now.year, now.month, possession_year, MONTH_MAP.get((possession_month or "").lower()[:3]))

    possession_ext_months = first_int(r"extended by\s+(\d+)\s+months?") or first_int(r"added\s+(\d+)\s+months? to (?:the )?completion dates?")
    possession_ext_note = next((line for line in lines if re.search(r"extended by \d+ months|possession date was extended|possession date extended", line, re.I)), None)
    if possession_ext_months is None and original_possession and possession_date:
        orig_m, orig_y = parse_month_year(original_possession)
        calc_delay = diff_in_months(orig_y, MONTH_MAP.get((orig_m or "").lower()[:3]), possession_year, MONTH_MAP.get((possession_month or "").lower()[:3]))
        if calc_delay and calc_delay > 0:
            possession_ext_months = calc_delay

    if possession_ext_months or possession_ext_note or re.search(r"extended by \d+ months|possession date was extended|possession date extended", flat_text, re.I):
        possession_extension_status = "Extended"
    elif re.search(r"possession date unchanged|on schedule", flat_text, re.I):
        possession_extension_status = "On Schedule"
    elif possession_date:
        possession_extension_status = "Reported"
    else:
        possession_extension_status = None

    if status == "Ready to move":
        ready_to_move = True
    elif status in ("Mid-construction", "Early stage", "Nearing possession"):
        ready_to_move = False
    else:
        ready_to_move = None

    structural_complete = (rcc_pct == 100.0) if rcc_pct is not None else None
    finishing_complete = (finishing_pct == 100.0) if finishing_pct is not None else None

    unit_counts = aggregate_unit_mix(unit_mix)

    comp_heading = re.search(r"Compared with\s+(\d+)\s+similar projects\s+(?:in\s+PIN\s+(\d{6}))?", flat_text, re.I)
    similar_projects_count = int(comp_heading.group(1)) if comp_heading else None
    similar_projects_pin = comp_heading.group(2) if comp_heading else None

    current_ytd_price = next((x["price_per_sqft_80pct"] for x in sale_year_stats if "so far" in x.get("year_label", "").lower()), None)
    previous_year_price = next((x["price_per_sqft_80pct"] for x in sale_year_stats if latest_sale_year and x.get("sales_year") == latest_sale_year - 1), None)
    year_over_year_direction = "up" if year_over_year_change_pct and year_over_year_change_pct > 0 else ("down" if year_over_year_change_pct and year_over_year_change_pct < 0 else ("stable" if year_over_year_change_pct == 0 else None))

    breadcrumbs = extract_breadcrumbs(soup, url, name)
    progress_updates = compute_progress_deltas(progress_updates)

    result = {
        "project_url": canonical_url(url),
        "page_title": clean_text(page_title_tag.get_text(" ", strip=True) if page_title_tag else None),
        "meta_description": project_desc,
        "project_name": name or url.rstrip("/").split("/")[-1],
        "rera_number": rera,
        "phase_name": phase_name,
        "developer": developer,
        "project_type": project_type,
        "project_description": project_desc,
        "locality": locality,
        "sub_locality": None,
        "city": "Pune",
        "district": "Pune",
        "pin_code": pin_code,
        "maharera_status": maharera_status,
        "construction_stage": status,
        "launch_date_text": launch_date,
        "launch_month": launch_month,
        "launch_year": launch_year,
        "possession_date_text": possession_date,
        "possession_month": possession_month,
        "possession_year": possession_year,
        "original_possession_date_text": original_possession,
        "possession_extension_status": possession_extension_status,
        "possession_extension_months": possession_ext_months,
        "possession_extension_note": possession_ext_note,
        "promised_timeline_text": promised_timeline,
        "promised_timeline_months": promised_timeline_months,
        "months_elapsed_since_launch": months_elapsed,
        "months_remaining_to_possession": months_remaining,
        "ready_to_move_status": ready_to_move,
        "structural_completion_status": structural_complete,
        "finishing_completion_status": finishing_complete,
        "total_units": total_units,
        "units_for_sale": units_for_sale,
        "units_booked": units_booked,
        "not_for_sale_units": not_for_sale_units,
        "units_for_sale_derived_from_total_minus_not_for_sale": not_for_sale_flag_derived,
        "booking_status": booking_status,
        "booking_pct": booking_pct,
        "building_count": building_count,
        "land_acres": land_acres,
        "excavation_pct": excavation_pct,
        "rcc_pct": rcc_pct,
        "finishing_pct": finishing_pct,
        "complaint_count": complaint_count,
        "units_1rk": unit_counts["units_1rk"],
        "units_1bhk": unit_counts["units_1bhk"],
        "units_2bhk": unit_counts["units_2bhk"],
        "units_3bhk": unit_counts["units_3bhk"],
        "units_4bhk": unit_counts["units_4bhk"],
        "units_5bhk_plus": unit_counts["units_5bhk_plus"],
        "units_other": unit_counts["units_other"],
        "total_residential_units": unit_counts["total_residential_units"],
        "latest_sale_year": latest_sale_year,
        "price_per_sqft_80pct": price_per_sqft_80pct,
        "price_per_sqft_80pct_source": price_per_sqft_80pct_source,
        "latest_sale_count": latest_sale_count,
        "headline_price_per_sqft_80pct": headline_price.get("price_per_sqft_80pct"),
        "headline_price_year_label": headline_price.get("year_label"),
        "headline_price_sale_count": headline_price.get("sale_count"),
        "headline_price_raw_text": headline_price.get("raw_text"),
        "current_ytd_price": current_ytd_price,
        "previous_year_price": previous_year_price,
        "recent_bookings_count": recent_bookings_count,
        "reported_booking_denominator": reported_booking_denominator,
        "booking_pct_displayed": booking_pct_displayed,
        "price_area_basis": "includes balconies and terrace" if re.search(r"price per sq ft\s*\(incl\.?\s*balconies and terrace\)", flat_text, re.I) else None,
        "rate_vs_nearby_projects_pct": rate_vs_nearby_pct,
        "year_over_year_change_pct": year_over_year_change_pct,
        "year_over_year_direction": year_over_year_direction,
        "year_over_year_comparison_year": year_over_year_comparison_year,
        "years_of_sales_data": len(sale_year_stats),
        "similar_projects_count": similar_projects_count,
        "similar_projects_pin": similar_projects_pin,
        "map_url": map_url,
        "breadcrumbs": breadcrumbs,
        "flat_type_mix": unit_mix,
        "sale_year_stats": sale_year_stats,
        "size_price_bands": size_price_bands,
        "flat_sizes_sold_sqft": flat_sizes_sold_sqft,
        "market_context_snippets": market_context,
        "progress_updates": progress_updates,
        "comparables": comparables,
        "comparison_summary": comparison_summary,
        "related_project_links": related_project_links,
        "image_urls_metadata_only": images,
        "page_data_inventory": comprehensive_page_data,
        "source_notes": {
            "source": "FlatNama",
            "data_basis": "Structured fields shown on the page; figures may reflect developer-reported MahaRERA submissions and available registered-sale records.",
            "price_statistic_definition": "FlatNama describes its project price as the rate at or below which 80% of flats sold in the stated period went; it is not an individual transaction price.",
            "collection_scope": "Limited, rate-limited collection of supplied pages; not a copy of the whole website.",
            "limitations": [
                "A page may not show every transaction.",
                "Construction/bookings data may be developer-reported and may be revised.",
                "No individual transaction-level sale deeds are extracted by this parser.",
                "Fields not confidently parsed remain null instead of being guessed."
            ]
        },
    }

    result["faqs"] = extract_source_faqs(soup)

    quality_warnings: list[str] = []
    if "price per sq ft, year by year" in flat_text.lower() and not result.get("sale_year_stats"):
        quality_warnings.append("annual_price_section_visible_but_no_rows_extracted")
    elif "price per sq ft, year by year" in flat_text.lower() and len(result.get("sale_year_stats", [])) == 1:
        quality_warnings.append("only_one_annual_price_row_extracted_check_source_layout")
    if headline_price.get("price_per_sqft_80pct") is not None and result.get("sale_year_stats"):
        latest_year_row = max(result["sale_year_stats"], key=lambda x: (x["sales_year"], "so far" in x["year_label"].lower()))
        if (headline_price.get("sales_year") == latest_year_row.get("sales_year") and
                headline_price.get("price_per_sqft_80pct") != latest_year_row.get("price_per_sqft_80pct")):
            quality_warnings.append("headline_price_differs_from_latest_annual_row_review_page_layout")
    if headline_price.get("price_per_sqft_80pct") is not None and not result.get("sale_year_stats"):
        quality_warnings.append("headline_price_found_but_year_by_year_rows_not_extracted_or_not_published")
    if re.search(r"\bflat types\b", flat_text, re.I) and not result.get("flat_type_mix"):
        quality_warnings.append("flat_types_section_visible_but_no_unit_mix_extracted")
    if re.search(r"flat sizes sold here", flat_text, re.I) and not result.get("flat_sizes_sold_sqft"):
        quality_warnings.append("flat_sizes_section_visible_but_no_sizes_extracted")
    if re.search(r"updates reported to maharera", flat_text, re.I) and not result.get("progress_updates"):
        quality_warnings.append("construction_updates_section_visible_but_no_rows_extracted")
    if re.search(r"\btotal units\b", flat_text, re.I) and result.get("total_units") is None:
        quality_warnings.append("total_units_text_visible_but_not_parsed")
    if comprehensive_page_data.get("visible_text_char_count", 0) < 500:
        quality_warnings.append("very_little_visible_page_text_captured_check_block_or_javascript_rendering")
    if comprehensive_page_data.get("sections") and not any("disclaimer" in (section.get("heading", "").lower()) for section in comprehensive_page_data["sections"]):
        if re.search(r"\bdisclaimers?\b", flat_text, re.I):
            quality_warnings.append("disclaimer_text_exists_but_no_disclaimer_section_was_built")

    fields_to_audit = (
        "rera_number", "developer", "locality", "pin_code", "launch_date_text",
        "possession_date_text", "maharera_status", "total_units", "units_booked",
        "booking_pct", "building_count", "land_acres", "price_per_sqft_80pct",
        "latest_sale_count", "flat_type_mix", "flat_sizes_sold_sqft", "size_price_bands",
        "sale_year_stats", "progress_updates", "comparables", "comparison_summary", "map_url",
        "phase_name", "possession_extension_status", "promised_timeline_months", "faqs",
    )
    field_presence = {
        field: (bool(result.get(field)) if isinstance(result.get(field), (list, dict, str)) else result.get(field) is not None)
        for field in fields_to_audit
    }
    present_count = sum(1 for value in field_presence.values() if value)
    completeness_pct = round(present_count / len(fields_to_audit) * 100, 2)
    result["quality_score"] = completeness_pct
    result["extraction_quality"] = {
        "parser_version": PARSER_VERSION,
        "fields_checked": len(fields_to_audit),
        "fields_present": present_count,
        "completeness_pct": completeness_pct,
        "field_presence": field_presence,
        "annual_price_rows": len(result.get("sale_year_stats", [])),
        "unit_mix_rows": len(result.get("flat_type_mix", [])),
        "flat_sizes_sold_count": len(result.get("flat_sizes_sold_sqft", [])),
        "size_price_band_rows": len(result.get("size_price_bands", [])),
        "construction_update_rows": len(result.get("progress_updates", [])),
        "comparable_rows": len(result.get("comparables", [])),
        "comparison_summary_rows": len(result.get("comparison_summary", [])),
        "faq_count": len(result.get("faqs", [])),
        "page_section_count": len(comprehensive_page_data.get("sections", [])),
        "generic_table_count": len(comprehensive_page_data.get("tables", [])),
        "generic_list_count": len(comprehensive_page_data.get("lists", [])),
        "generic_key_value_fact_count": len(comprehensive_page_data.get("key_value_facts", [])),
        "page_link_count": len(comprehensive_page_data.get("links", [])),
        "page_image_asset_count": len(comprehensive_page_data.get("images", [])),
        "page_jsonld_blocks": len(comprehensive_page_data.get("json_ld", [])),
        "visible_text_char_count": comprehensive_page_data.get("visible_text_char_count", 0),
        "warnings": quality_warnings,
    }
    return result


def project_key(data: dict[str, Any]) -> str:
    if data.get("rera_number"):
        return data["rera_number"].upper()
    return "URL:" + hashlib.sha256(data["project_url"].encode()).hexdigest()[:32]


class Store:
    def __init__(self, dsn: str):
        import psycopg
        self.conn = psycopg.connect(dsn)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.conn.cursor() as cur:
            cur.execute(schema)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def start_run(self, run_id: uuid.UUID, mode: str, seed_count: int, notes: str | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scrape_runs (run_id, mode, seed_count, notes) VALUES (%s, %s, %s, %s)",
                (run_id, mode, seed_count, notes),
            )
        self.conn.commit()

    def finish_run(self, run_id: uuid.UUID, area_pages: int, project_pages: int, succeeded: int, failed: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE scrape_runs SET finished_at=now(), area_pages_seen=%s, project_pages_seen=%s, pages_succeeded=%s, pages_failed=%s WHERE run_id=%s",
                (area_pages, project_pages, succeeded, failed, run_id),
            )
        self.conn.commit()

    def add_source_page(self, run_id: uuid.UUID, url: str, page_type: str, status: int | None,
                        content_hash: str | None, parse_status: str, error: str | None = None) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO source_pages (run_id, requested_url, canonical_url, page_type, http_status, content_sha256, parse_status, error_message)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING source_page_id""",
                (run_id, url, url, page_type, status, content_hash, parse_status, error),
            )
            result = cur.fetchone()
            assert result is not None
            return result[0]

    def save_area_snapshot(self, run_id: uuid.UUID, source_page_id: int, data: dict[str, Any], content_hash: str) -> None:
        from psycopg.types.json import Jsonb
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO area_page_snapshots (run_id, source_page_id, area_url, area_name, content_sha256, parser_version, data)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (area_url, content_sha256, parser_version)
                   DO UPDATE SET data = EXCLUDED.data, observed_at = now()""",
                (run_id, source_page_id, data["area_url"], data.get("area_name"), content_hash, PARSER_VERSION, Jsonb(data)),
            )
        self.conn.commit()

    def save_discovered_urls(self, run_id: uuid.UUID, area_url: str, links: list[str], method: str) -> None:
        with self.conn.cursor() as cur:
            for link in links:
                cur.execute(
                    """INSERT INTO discovered_project_urls (run_id, source_area_url, project_url, discovery_method)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (run_id, source_area_url, project_url) DO NOTHING""",
                    (run_id, area_url, link, method),
                )
        self.conn.commit()

    def mark_discovered_urls_selected(self, run_id: uuid.UUID, links: list[str]) -> None:
        if not links:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE discovered_project_urls SET selected_for_fetch=TRUE WHERE run_id=%s AND project_url = ANY(%s)",
                (run_id, links),
            )
        self.conn.commit()

    def update_discovered_fetch_status(self, run_id: uuid.UUID, project_url: str, status: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE discovered_project_urls SET fetch_status=%s WHERE run_id=%s AND project_url=%s",
                (status, run_id, project_url),
            )
        self.conn.commit()

    def save_project(self, source_page_id: int, data: dict[str, Any], content_hash: str) -> tuple[str, bool]:
        from psycopg.types.json import Jsonb
        key = project_key(data)
        now = utcnow()
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO projects (
                    project_key, rera_number, project_name, phase_name, developer, project_type,
                    project_description, locality, sub_locality, city, district, pin_code,
                    project_url, area_page_url, map_url, displayed_address,
                    maharera_status, construction_stage, launch_date_text, launch_month, launch_year,
                    possession_date_text, possession_month, possession_year, original_possession_date_text,
                    possession_extension_status, possession_extension_months, possession_extension_note,
                    promised_timeline_text, promised_timeline_months, months_elapsed_since_launch, months_remaining_to_possession,
                    ready_to_move_status, structural_completion_status, finishing_completion_status,
                    building_count, land_acres, excavation_pct, rcc_pct, finishing_pct, complaint_count,
                    total_units, units_for_sale, units_booked, not_for_sale_units, reported_booking_denominator,
                    recent_bookings_count, booking_pct, booking_status,
                    units_1rk, units_1bhk, units_2bhk, units_3bhk, units_4bhk, units_5bhk_plus, units_other, total_residential_units,
                    latest_sale_year, price_per_sqft_80pct, price_per_sqft_80pct_source, latest_sale_count,
                    current_ytd_price, previous_year_price, headline_price_per_sqft_80pct, headline_price_year_label, headline_price_sale_count,
                    year_over_year_change_pct, year_over_year_direction, year_over_year_comparison_year,
                    rate_vs_nearby_projects_pct, price_area_basis, years_of_sales_data,
                    similar_projects_count, similar_projects_pin,
                    breadcrumbs, source_notes, quality_score, quality_warnings,
                    last_content_sha256, raw_latest,
                    first_seen_at, last_seen_at, last_scraped_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s
                )
                ON CONFLICT (project_key) DO UPDATE SET
                    rera_number=COALESCE(EXCLUDED.rera_number, projects.rera_number),
                    project_name=COALESCE(EXCLUDED.project_name, projects.project_name),
                    phase_name=COALESCE(EXCLUDED.phase_name, projects.phase_name),
                    developer=COALESCE(EXCLUDED.developer, projects.developer),
                    project_type=COALESCE(EXCLUDED.project_type, projects.project_type),
                    project_description=COALESCE(EXCLUDED.project_description, projects.project_description),
                    locality=COALESCE(EXCLUDED.locality, projects.locality),
                    sub_locality=COALESCE(EXCLUDED.sub_locality, projects.sub_locality),
                    city=COALESCE(EXCLUDED.city, projects.city),
                    district=COALESCE(EXCLUDED.district, projects.district),
                    pin_code=COALESCE(EXCLUDED.pin_code, projects.pin_code),
                    project_url=EXCLUDED.project_url,
                    area_page_url=COALESCE(EXCLUDED.area_page_url, projects.area_page_url),
                    map_url=COALESCE(EXCLUDED.map_url, projects.map_url),
                    displayed_address=COALESCE(EXCLUDED.displayed_address, projects.displayed_address),
                    maharera_status=COALESCE(EXCLUDED.maharera_status, projects.maharera_status),
                    construction_stage=COALESCE(EXCLUDED.construction_stage, projects.construction_stage),
                    launch_date_text=COALESCE(EXCLUDED.launch_date_text, projects.launch_date_text),
                    launch_month=COALESCE(EXCLUDED.launch_month, projects.launch_month),
                    launch_year=COALESCE(EXCLUDED.launch_year, projects.launch_year),
                    possession_date_text=COALESCE(EXCLUDED.possession_date_text, projects.possession_date_text),
                    possession_month=COALESCE(EXCLUDED.possession_month, projects.possession_month),
                    possession_year=COALESCE(EXCLUDED.possession_year, projects.possession_year),
                    original_possession_date_text=COALESCE(EXCLUDED.original_possession_date_text, projects.original_possession_date_text),
                    possession_extension_status=COALESCE(EXCLUDED.possession_extension_status, projects.possession_extension_status),
                    possession_extension_months=COALESCE(EXCLUDED.possession_extension_months, projects.possession_extension_months),
                    possession_extension_note=COALESCE(EXCLUDED.possession_extension_note, projects.possession_extension_note),
                    promised_timeline_text=COALESCE(EXCLUDED.promised_timeline_text, projects.promised_timeline_text),
                    promised_timeline_months=COALESCE(EXCLUDED.promised_timeline_months, projects.promised_timeline_months),
                    months_elapsed_since_launch=COALESCE(EXCLUDED.months_elapsed_since_launch, projects.months_elapsed_since_launch),
                    months_remaining_to_possession=COALESCE(EXCLUDED.months_remaining_to_possession, projects.months_remaining_to_possession),
                    ready_to_move_status=COALESCE(EXCLUDED.ready_to_move_status, projects.ready_to_move_status),
                    structural_completion_status=COALESCE(EXCLUDED.structural_completion_status, projects.structural_completion_status),
                    finishing_completion_status=COALESCE(EXCLUDED.finishing_completion_status, projects.finishing_completion_status),
                    building_count=COALESCE(EXCLUDED.building_count, projects.building_count),
                    land_acres=COALESCE(EXCLUDED.land_acres, projects.land_acres),
                    excavation_pct=COALESCE(EXCLUDED.excavation_pct, projects.excavation_pct),
                    rcc_pct=COALESCE(EXCLUDED.rcc_pct, projects.rcc_pct),
                    finishing_pct=COALESCE(EXCLUDED.finishing_pct, projects.finishing_pct),
                    complaint_count=COALESCE(EXCLUDED.complaint_count, projects.complaint_count),
                    total_units=COALESCE(EXCLUDED.total_units, projects.total_units),
                    units_for_sale=COALESCE(EXCLUDED.units_for_sale, projects.units_for_sale),
                    units_booked=COALESCE(EXCLUDED.units_booked, projects.units_booked),
                    not_for_sale_units=COALESCE(EXCLUDED.not_for_sale_units, projects.not_for_sale_units),
                    reported_booking_denominator=COALESCE(EXCLUDED.reported_booking_denominator, projects.reported_booking_denominator),
                    recent_bookings_count=COALESCE(EXCLUDED.recent_bookings_count, projects.recent_bookings_count),
                    booking_pct=COALESCE(EXCLUDED.booking_pct, projects.booking_pct),
                    booking_status=COALESCE(EXCLUDED.booking_status, projects.booking_status),
                    units_1rk=COALESCE(EXCLUDED.units_1rk, projects.units_1rk),
                    units_1bhk=COALESCE(EXCLUDED.units_1bhk, projects.units_1bhk),
                    units_2bhk=COALESCE(EXCLUDED.units_2bhk, projects.units_2bhk),
                    units_3bhk=COALESCE(EXCLUDED.units_3bhk, projects.units_3bhk),
                    units_4bhk=COALESCE(EXCLUDED.units_4bhk, projects.units_4bhk),
                    units_5bhk_plus=COALESCE(EXCLUDED.units_5bhk_plus, projects.units_5bhk_plus),
                    units_other=COALESCE(EXCLUDED.units_other, projects.units_other),
                    total_residential_units=COALESCE(EXCLUDED.total_residential_units, projects.total_residential_units),
                    latest_sale_year=COALESCE(EXCLUDED.latest_sale_year, projects.latest_sale_year),
                    price_per_sqft_80pct=COALESCE(EXCLUDED.price_per_sqft_80pct, projects.price_per_sqft_80pct),
                    price_per_sqft_80pct_source=COALESCE(EXCLUDED.price_per_sqft_80pct_source, projects.price_per_sqft_80pct_source),
                    latest_sale_count=COALESCE(EXCLUDED.latest_sale_count, projects.latest_sale_count),
                    current_ytd_price=COALESCE(EXCLUDED.current_ytd_price, projects.current_ytd_price),
                    previous_year_price=COALESCE(EXCLUDED.previous_year_price, projects.previous_year_price),
                    headline_price_per_sqft_80pct=COALESCE(EXCLUDED.headline_price_per_sqft_80pct, projects.headline_price_per_sqft_80pct),
                    headline_price_year_label=COALESCE(EXCLUDED.headline_price_year_label, projects.headline_price_year_label),
                    headline_price_sale_count=COALESCE(EXCLUDED.headline_price_sale_count, projects.headline_price_sale_count),
                    year_over_year_change_pct=COALESCE(EXCLUDED.year_over_year_change_pct, projects.year_over_year_change_pct),
                    year_over_year_direction=COALESCE(EXCLUDED.year_over_year_direction, projects.year_over_year_direction),
                    year_over_year_comparison_year=COALESCE(EXCLUDED.year_over_year_comparison_year, projects.year_over_year_comparison_year),
                    rate_vs_nearby_projects_pct=COALESCE(EXCLUDED.rate_vs_nearby_projects_pct, projects.rate_vs_nearby_projects_pct),
                    price_area_basis=COALESCE(EXCLUDED.price_area_basis, projects.price_area_basis),
                    years_of_sales_data=COALESCE(EXCLUDED.years_of_sales_data, projects.years_of_sales_data),
                    similar_projects_count=COALESCE(EXCLUDED.similar_projects_count, projects.similar_projects_count),
                    similar_projects_pin=COALESCE(EXCLUDED.similar_projects_pin, projects.similar_projects_pin),
                    breadcrumbs=EXCLUDED.breadcrumbs,
                    source_notes=EXCLUDED.source_notes,
                    quality_score=EXCLUDED.quality_score,
                    quality_warnings=EXCLUDED.quality_warnings,
                    last_content_sha256=EXCLUDED.last_content_sha256,
                    raw_latest=EXCLUDED.raw_latest,
                    last_seen_at=EXCLUDED.last_seen_at,
                    last_scraped_at=EXCLUDED.last_scraped_at""",
                (
                    key, data.get("rera_number"), data["project_name"], data.get("phase_name"), data.get("developer"),
                    data.get("project_type"), data.get("project_description"), data.get("locality"),
                    data.get("sub_locality"), data.get("city", "Pune"), data.get("district", "Pune"), data.get("pin_code"),
                    data["project_url"], data.get("area_page_url"), data.get("map_url"), data.get("displayed_address"),
                    data.get("maharera_status"), data.get("construction_stage"), data.get("launch_date_text"),
                    data.get("launch_month"), data.get("launch_year"), data.get("possession_date_text"),
                    data.get("possession_month"), data.get("possession_year"), data.get("original_possession_date_text"),
                    data.get("possession_extension_status"), data.get("possession_extension_months"), data.get("possession_extension_note"),
                    data.get("promised_timeline_text"), data.get("promised_timeline_months"), data.get("months_elapsed_since_launch"),
                    data.get("months_remaining_to_possession"), data.get("ready_to_move_status"),
                    data.get("structural_completion_status"), data.get("finishing_completion_status"),
                    data.get("building_count"), data.get("land_acres"), data.get("excavation_pct"), data.get("rcc_pct"),
                    data.get("finishing_pct"), data.get("complaint_count"),
                    data.get("total_units"), data.get("units_for_sale"), data.get("units_booked"), data.get("not_for_sale_units"),
                    data.get("reported_booking_denominator"), data.get("recent_bookings_count"), data.get("booking_pct"), data.get("booking_status"),
                    data.get("units_1rk"), data.get("units_1bhk"), data.get("units_2bhk"), data.get("units_3bhk"),
                    data.get("units_4bhk"), data.get("units_5bhk_plus"), data.get("units_other"), data.get("total_residential_units"),
                    data.get("latest_sale_year"), data.get("price_per_sqft_80pct"), data.get("price_per_sqft_80pct_source"), data.get("latest_sale_count"),
                    data.get("current_ytd_price"), data.get("previous_year_price"), data.get("headline_price_per_sqft_80pct"),
                    data.get("headline_price_year_label"), data.get("headline_price_sale_count"),
                    data.get("year_over_year_change_pct"), data.get("year_over_year_direction"), data.get("year_over_year_comparison_year"),
                    data.get("rate_vs_nearby_projects_pct"), data.get("price_area_basis"), data.get("years_of_sales_data", 0),
                    data.get("similar_projects_count"), data.get("similar_projects_pin"),
                    Jsonb(data.get("breadcrumbs", [])), Jsonb(data.get("source_notes", {})),
                    data.get("quality_score"), Jsonb(data.get("extraction_quality", {}).get("warnings", [])),
                    content_hash, Jsonb(data),
                    now, now, now,
                ),
            )
            cur.execute(
                """INSERT INTO project_snapshots (project_key, source_page_id, content_sha256, parser_version, data)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (project_key, content_sha256, parser_version)
                   DO UPDATE SET data = EXCLUDED.data, observed_at = now()
                   RETURNING snapshot_id""",
                (key, source_page_id, content_hash, PARSER_VERSION, Jsonb(data)),
            )
            snapshot_row = cur.fetchone()
            is_new_snapshot = snapshot_row is not None
            if is_new_snapshot:
                snapshot_id = snapshot_row[0]
                cur.execute("DELETE FROM project_unit_mix WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_sale_year_stats WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_size_price_bands WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_progress_updates WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_comparables WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_comparison_benchmarks WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_related_links WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_faqs WHERE snapshot_id = %s", (snapshot_id,))
                cur.execute("DELETE FROM project_quality_audits WHERE snapshot_id = %s", (snapshot_id,))
                for item in data.get("flat_type_mix", []):
                    cur.execute(
                        "INSERT INTO project_unit_mix (snapshot_id, project_key, flat_type, unit_count) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (snapshot_id, key, item["flat_type"], item.get("unit_count")),
                    )
                for item in data.get("sale_year_stats", []):
                    cur.execute(
                        """INSERT INTO project_sale_year_stats (snapshot_id, project_key, sales_year, year_label, price_per_sqft_80pct, sale_count, year_over_year_delta_text, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item["sales_year"], item.get("year_label") or str(item["sales_year"]), item.get("price_per_sqft_80pct"), item.get("sale_count"), item.get("year_over_year_delta_text"), Jsonb(item.get("raw_row", []))),
                    )
                for item in data.get("size_price_bands", []):
                    cur.execute(
                        """INSERT INTO project_size_price_bands (snapshot_id, project_key, year_label, min_size_sqft, max_size_sqft, min_price_inr, max_price_inr, raw_size_label, raw_price_label)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item.get("year_label"), item.get("min_size_sqft"), item.get("max_size_sqft"), item.get("min_price_inr"), item.get("max_price_inr"), item.get("raw_size_label") or "unknown", item.get("raw_price_label") or "unknown"),
                    )
                for item in data.get("progress_updates", []):
                    cur.execute(
                        """INSERT INTO project_progress_updates (snapshot_id, project_key, update_label, excavation_pct, rcc_pct, finishing_pct, units_booked, rcc_change, finishing_change, booking_change, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item["update_label"], item.get("excavation_pct"), item.get("rcc_pct"), item.get("finishing_pct"), item.get("units_booked"), item.get("rcc_change"), item.get("finishing_change"), item.get("booking_change"), Jsonb(item.get("raw_row", []))),
                    )
                for item in data.get("comparables", []):
                    label = item.get("comparable_name") or "unknown"
                    cur.execute(
                        """INSERT INTO project_comparables (snapshot_id, project_key, comparable_name, launch_date_text, possession_date_text, rcc_pct, booking_text, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, label, item.get("launch_date_text"), item.get("possession_date_text"), item.get("rcc_pct"), item.get("booking_text"), Jsonb(item.get("raw_row", []))),
                    )
                for bm in data.get("comparison_summary", []):
                    cur.execute(
                        """INSERT INTO project_comparison_benchmarks (snapshot_id, project_key, measure, this_project, similar_projects, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (snapshot_id, measure) DO NOTHING""",
                        (snapshot_id, key, bm["measure"], bm.get("this_project"), bm.get("similar_projects"), Jsonb(bm.get("raw_row", []))),
                    )
                for link in data.get("related_project_links", []):
                    cur.execute(
                        """INSERT INTO project_related_links (snapshot_id, project_key, category, label, url)
                           VALUES (%s,%s,%s,%s,%s) ON CONFLICT (snapshot_id, category, url) DO NOTHING""",
                        (snapshot_id, key, link["category"], link.get("label") or "Link", link["url"]),
                    )
                for faq in data.get("faqs", []):
                    cur.execute(
                        """INSERT INTO project_faqs (snapshot_id, project_key, topic, question, answer)
                           VALUES (%s,%s,%s,%s,%s) ON CONFLICT (snapshot_id, question) DO NOTHING""",
                        (snapshot_id, key, faq["topic"], faq["question"], faq["answer"]),
                    )
                q = data.get("extraction_quality", {})
                if q:
                    cur.execute(
                        """INSERT INTO project_quality_audits (snapshot_id, project_key, parser_version, fields_checked, fields_present, completeness_pct, warnings, audit_details)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (snapshot_id) DO NOTHING""",
                        (snapshot_id, key, q.get("parser_version", PARSER_VERSION), q.get("fields_checked", 0), q.get("fields_present", 0),
                         q.get("completeness_pct", 0.0), Jsonb(q.get("warnings", [])), Jsonb(q)),
                    )
        try:
            from data_quality import validate_project_record, persist_quality_issues
            issues = validate_project_record(data)
            if issues:
                persist_quality_issues(issues, self.conn)
        except Exception as dq_err:
            LOG.debug("Data quality issue persistence notice: %s", dq_err)

        self.conn.commit()
        return key, is_new_snapshot


def authorize_expanded_collection(args: argparse.Namespace, area_urls: list[str], project_urls: list[str]) -> None:
    bulk_env = os.getenv("FLATNAMA_BULK_PERMISSION_CONFIRMED", "0") == "1"
    expanded = args.max_project_pages > 25 or args.max_area_pages > 5 or len(area_urls) > 5 or len(project_urls) > 25
    if expanded and (not args.authorized_bulk or not bulk_env):
        raise SystemExit(
            "Expanded collection is blocked by default. FlatNama's terms say not to copy the site as a whole. "
            "For bulk collection, obtain explicit permission, set FLATNAMA_BULK_PERMISSION_CONFIRMED=1, "
            "and pass --authorized-bulk. This guard is not a substitute for that permission."
        )
    if args.authorized_bulk and not bulk_env:
        raise SystemExit("--authorized-bulk requires FLATNAMA_BULK_PERMISSION_CONFIRMED=1 in .env after explicit site-owner permission.")


def is_analytics_url(url: str) -> bool:
    path = urlparse(canonical_url(url)).path.lower()
    return "analytics" in path or "/data/" in path


def parse_market_analytics_page(url: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True) if h1 else None)
    visible_text = soup.get_text("\n", strip=True)
    flat_text = clean_text(visible_text) or ""

    trends = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        if len(rows) > 1:
            headers = [h.lower() for h in rows[0]]
            for r in rows[1:]:
                row_dict = {}
                for idx, cell in enumerate(r):
                    header = headers[idx] if idx < len(headers) else f"col_{idx}"
                    row_dict[header] = cell
                trends.append(row_dict)

    return {
        "page_url": canonical_url(url),
        "page_title": title,
        "analytics_trends": trends,
        "source_notes": {
            "source": "FlatNama Market Analytics",
            "coverage": "Public MahaRERA records (2020 onward).",
        }
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Collect an exhaustive FlatNama research dataset into PostgreSQL and CSV.")
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("seed_urls.txt"), help="Text file with area/project URLs")
    parser.add_argument("--discover-project-links", action="store_true", help="Find project detail URLs on the supplied area pages")
    parser.add_argument("--max-area-pages", type=int, default=5, help="Maximum explicitly seeded area pages (default 5)")
    parser.add_argument("--max-project-pages", type=int, default=25, help="Maximum project pages per run (default 25)")
    parser.add_argument("--authorized-bulk", action="store_true", help="Required for expanded collection after written permission; also set permission env var")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse pages but do not write PostgreSQL project data")
    parser.add_argument("--report-json", type=Path, help="Optional path to write a structured extraction/QA report (including parsed project fields)")
    parser.add_argument("--export-csv", type=Path, help="Optional directory to automatically export comprehensive CSV tables upon run completion")
    args = parser.parse_args()

    try:
        seed_urls = read_url_file(args.input)
    except Exception as exc:
        LOG.error("Could not read input URL file: %s", exc)
        return 2
    if not seed_urls:
        LOG.error("No URLs in %s", args.input)
        return 2

    area_urls = [u for u in seed_urls if not is_project_url(u)]
    direct_projects = [u for u in seed_urls if is_project_url(u)]
    if len(area_urls) > args.max_area_pages:
        LOG.error("Seed list has %d area pages, above --max-area-pages=%d", len(area_urls), args.max_area_pages)
        return 2
    if len(direct_projects) > args.max_project_pages:
        LOG.error("Seed list has %d project URLs, above --max-project-pages=%d", len(direct_projects), args.max_project_pages)
        return 2
    try:
        authorize_expanded_collection(args, area_urls, direct_projects)
    except SystemExit as exc:
        LOG.error(str(exc))
        return 2

    user_agent = os.getenv("FLATNAMA_USER_AGENT", "")
    try:
        client = PoliteClient(
            user_agent=user_agent,
            delay_seconds=float(os.getenv("FLATNAMA_DELAY_SECONDS", "2.5")),
            timeout_seconds=float(os.getenv("FLATNAMA_TIMEOUT_SECONDS", "25")),
            max_retries=int(os.getenv("FLATNAMA_MAX_RETRIES", "2")),
        )
    except Exception as exc:
        LOG.error("Client configuration issue: %s", exc)
        return 2

    dsn = os.getenv("DATABASE_URL")
    store: Store | None = None
    if not args.dry_run:
        if not dsn:
            LOG.error("DATABASE_URL is missing in .env")
            return 2
        try:
            store = Store(dsn)
        except Exception as exc:
            LOG.error("Could not initialize PostgreSQL/schema: %s", exc)
            return 2

    run_id = uuid.uuid4()
    if store:
        store.start_run(run_id, "expanded-authorized" if args.authorized_bulk else "limited-research", len(seed_urls), str(args.input))

    area_seen = project_seen = succeeded = failed = 0
    access_stop = False
    report_projects: list[dict[str, Any]] = []
    area_discovery: list[dict[str, Any]] = []
    project_urls: list[str] = list(direct_projects)
    seen_project_urls = set(project_urls)

    def record_error(url: str, page_type: str, err: Exception) -> None:
        nonlocal failed
        import traceback
        failed += 1
        LOG.warning("Failed %s (%s): %s", url, page_type, err)
        LOG.error("Failure traceback for %s:\n%s", url, "".join(traceback.format_exception(type(err), err, err.__traceback__)))
        if store:
            try:
                store.add_source_page(run_id, url, page_type, None, None, "error", str(err)[:2000])
                store.conn.commit()
            except Exception:
                store.conn.rollback()

    # Fetch only explicit area seeds. Link discovery is bounded by max-project-pages.
    for area_url in area_urls[:args.max_area_pages]:
        try:
            result = client.fetch(area_url)
            area_seen += 1
            succeeded += 1
            area_data = parse_area_page(area_url, result.html)
            if args.discover_project_links:
                discovered, discovery_method = project_link_discovery_details(result.html, area_url)
            else:
                discovered, discovery_method = [], "disabled"
            if store:
                area_source_page_id = store.add_source_page(run_id, area_url, "area", result.status_code, result.content_sha256, "ok")
                store.conn.commit()
                store.save_area_snapshot(run_id, area_source_page_id, area_data, result.content_sha256)
                if discovered:
                    store.save_discovered_urls(run_id, area_url, discovered, discovery_method)
            LOG.info(
                "Fetched area page: %s; area=%s; listed projects=%s; hidden small projects=%s; project links discovered=%d; method=%s",
                area_url, area_data.get("area_name"), area_data.get("listed_project_count"),
                area_data.get("small_projects_hidden_count"), len(discovered), discovery_method,
            )
            if discovery_method.startswith("fallback"):
                LOG.warning("Area-page link discovery used fallback mode; discovered links may include related/nearby projects or omit hidden catalogue entries.")
            area_discovery.append({"area_url": area_url, "area_summary": area_data, "project_links_discovered": len(discovered), "discovery_method": discovery_method, "project_urls": discovered})
            for link in discovered:
                if link not in seen_project_urls:
                    seen_project_urls.add(link)
                    project_urls.append(link)
        except KeyboardInterrupt:
            LOG.warning("Interrupted by user while processing an area page; finalizing the partial run cleanly.")
            access_stop = True
            break
        except Exception as exc:
            record_error(area_url, "area", exc)
            if any(code in str(exc) for code in ("HTTP 403", "HTTP 429", "robots.txt disallows", "challenge/access restriction")):
                access_stop = True
                break

    if len(project_urls) > args.max_project_pages:
        LOG.warning("Project URL cap applied: %d discovered/seeded URLs, processing first %d only. This is a sample, not complete area coverage.", len(project_urls), args.max_project_pages)
    project_urls = project_urls[:args.max_project_pages]
    if store:
        store.mark_discovered_urls_selected(run_id, project_urls)
    for project_url in ([] if access_stop else project_urls):
        try:
            result = client.fetch(project_url)
            project_seen += 1
            data = parse_project_page(project_url, result.html)
            parse_ok = bool(data.get("project_name") and data.get("rera_number") and (data.get("developer") or data.get("locality") or data.get("total_units")))
            report_projects.append(data)
            if store:
                source_page_id = store.add_source_page(run_id, project_url, "project", result.status_code, result.content_sha256, "ok" if parse_ok else "partial")
                store.save_project(source_page_id, data, result.content_sha256)
                store.conn.commit()
                store.update_discovered_fetch_status(run_id, project_url, "parsed" if parse_ok else "partial_parse")
            succeeded += 1
            quality = data.get("extraction_quality", {})
            inventory = data.get("page_data_inventory", {})
            LOG.info(
                "Project parsed: %s | RERA=%s | stage=%s | annual price rows=%d | unit mix=%d | size bands=%d | progress rows=%d | faqs=%d | quality=%.1f%%",
                data.get("project_name"), data.get("rera_number"), data.get("construction_stage"),
                len(data.get("sale_year_stats", [])), len(data.get("flat_type_mix", [])), len(data.get("size_price_bands", [])),
                len(data.get("progress_updates", [])), len(data.get("faqs", [])), data.get("quality_score", 0.0),
            )
            for warning in quality.get("warnings", []):
                LOG.warning("Extraction QA [%s]: %s", data.get("rera_number") or data.get("project_name"), warning)
        except KeyboardInterrupt:
            LOG.warning("Interrupted by user while processing a project; finalizing the partial run cleanly.")
            access_stop = True
            break
        except Exception as exc:
            record_error(project_url, "project", exc)
            if store:
                try:
                    store.update_discovered_fetch_status(run_id, project_url, "error")
                except Exception:
                    store.conn.rollback()
            if any(code in str(exc) for code in ("HTTP 403", "HTTP 429", "robots.txt disallows", "challenge/access restriction")):
                access_stop = True
                break

    if store:
        store.finish_run(run_id, area_seen, project_seen, succeeded, failed)
        store.close()
    completion_label = "stopped/interrupted" if access_stop else "complete"
    report_dict = {
        "parser_version": PARSER_VERSION,
        "run_id": str(run_id),
        "status": completion_label,
        "seed_file": str(args.input),
        "started_scope": {"area_urls": area_urls, "direct_project_urls": direct_projects},
        "area_discovery": area_discovery,
        "counts": {"area_pages": area_seen, "project_pages": project_seen, "succeeded": succeeded, "failed": failed},
        "projects": report_projects,
    }

    if args.report_json:
        try:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            LOG.info("Structured QA report written: %s", args.report_json)
        except Exception as exc:
            LOG.exception("Could not write QA report to %s: %s", args.report_json, exc)

    if args.export_csv:
        try:
            import tempfile
            from export_data import export_from_json
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
                json.dump(report_dict, tf, ensure_ascii=False)
                tmp_name = tf.name
            try:
                csv_counts = export_from_json(Path(tmp_name), args.export_csv)
                LOG.info("Comprehensive CSV files exported to %s: %s", args.export_csv, csv_counts)
            finally:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        except Exception as exc:
            LOG.exception("Could not export CSVs to %s: %s", args.export_csv, exc)

    LOG.info("Run %s. run_id=%s area_pages=%d project_pages=%d succeeded=%d failed=%d", completion_label, run_id, area_seen, project_seen, succeeded, failed)
    if args.dry_run:
        LOG.info("Dry-run mode: PostgreSQL was not modified.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
