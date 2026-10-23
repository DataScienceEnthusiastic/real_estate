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

PARSER_VERSION = "0.1.0"
BASE_HOSTS = {"flatnama.com", "www.flatnama.com"}
PROJECT_SLUG_RE = re.compile(r"^/(?:pune/)(?P<rera>(?:p\d{8,}|p[rmcp]\d{7,}|pr\d{7,}|pm\d{7,}|pc\d{7,}|pp\d{7,}))-[^/]+/?$", re.I)
RERA_RE = re.compile(r"\b(?:P\d{9,}|PR\d{8,}|PM\d{8,}|PC\d{8,}|PP\d{8,})\b", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
MONEY_RE = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)")
KNOWN_STAGES = ("Ready to move", "Nearing possession", "Mid-construction", "Early stage")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("flatnama-collector")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


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
    return val * factor


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
        return float(m.group(1)) * factor, float(m.group(2)) * factor
    single = parse_indian_price(text)
    return single, single


def project_links_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        try:
            href = canonical_url(href)
        except ValueError:
            continue
        if is_project_url(href):
            links.append(href)
    return list(dict.fromkeys(links))


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
    context_match = re.search(r"\bby\s+(.+?)\.\s+([^,\n]{2,100}),\s*Pune\s+(\d{6})\b", flat_text, re.I)
    if context_match:
        developer = clean_text(context_match.group(1))
        locality = clean_text(context_match.group(2))
        pin_code = context_match.group(3)

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
    original_possession = first_group(r"first date registered\s*[:：]?\s*([A-Z][a-z]+\s+20\d{2})")
    maharera_status = first_group(r"MahaRERA status\s+(?:is\s+)?([A-Za-z][A-Za-z -]+?)(?:\s+Its registered possession|\s+It was launched|\.)")

    def first_int(pattern: str) -> int | None:
        value = first_group(pattern)
        if not value:
            return None
        try:
            return int(value.replace(",", ""))
        except ValueError:
            return None

    total_units = first_int(r"Total units\s*([\d,]+)")
    building_count = first_int(r"([\d,]+)\s+buildings?\b")
    complaint_count = first_int(r"Complaints on MahaRERA[^\d]{0,90}(\d+)\b")
    land_match = re.search(r"([\d.]+)\s+acres?\b", flat_text, re.I)
    land_acres = float(land_match.group(1)) if land_match else None

    rcc_match = re.search(r"Concrete structure\s*\(RCC\)\s*(\d{1,3}(?:\.\d+)?)%", flat_text, re.I)
    rcc_pct = float(rcc_match.group(1)) if rcc_match else None
    excavation_pct = finishing_pct = None

    # Booking values appear in several layouts, so preserve raw text and parse only clear patterns.
    units_booked = units_for_sale = None
    booking_pct = None
    booking_match = re.search(r"([\d,]+)\s+units booked,\s*out of\s*([\d,]+)\s+units for sale", flat_text, re.I)
    if booking_match:
        units_booked = int(booking_match.group(1).replace(",", ""))
        units_for_sale = int(booking_match.group(2).replace(",", ""))
    else:
        booking_match = re.search(r"([\d,]+)\s+of\s+([\d,]+)\s+units booked", flat_text, re.I)
        if booking_match:
            units_booked = int(booking_match.group(1).replace(",", ""))
            units_for_sale = int(booking_match.group(2).replace(",", ""))
    not_for_sale_units = first_int(r"([\d,]+)\s+not for sale")
    if units_for_sale is None and total_units is not None and not_for_sale_units is not None:
        units_for_sale = max(0, total_units - not_for_sale_units)
    if units_booked is not None and units_for_sale:
        booking_pct = round(units_booked / units_for_sale * 100, 2)
    if re.search(r"bookings not reported", flat_text, re.I):
        booking_status = "not_reported"
    elif re.search(r"all units for sale are booked|all booked", flat_text, re.I):
        booking_status = "all_booked"
    elif units_booked is not None:
        booking_status = "reported_count"
    else:
        booking_status = "unknown"

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
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = clean_text(heading.get_text(" ", strip=True)) or ""
        if "flat sizes sold here" not in heading_text.lower():
            continue
        for sibling in heading.find_next_siblings():
            if sibling.name in {"h2", "h3", "h4"}:
                break
            for size_match in re.finditer(r"([\d,]+(?:\.\d+)?)\s*sq\s*ft", sibling.get_text(" ", strip=True), re.I):
                flat_sizes_sold_sqft.append(float(size_match.group(1).replace(",", "")))
    flat_sizes_sold_sqft = sorted(set(flat_sizes_sold_sqft))
    band_year_match = re.search(r"Based on flats sold in\s+(20\d{2})", flat_text, re.I)
    band_year_label = band_year_match.group(1) if band_year_match else None
    progress_updates: list[dict[str, Any]] = []
    comparables: list[dict[str, Any]] = []

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
                comparables.append({"comparable_name": row[0], "raw_row": row})

    # Deduplicate parsed arrays that can appear in more than one on-page table.
    unit_mix = list({(x["flat_type"], x["unit_count"]): x for x in unit_mix}.values())
    sale_year_stats = list({(x["sales_year"], x["year_label"], x["price_per_sqft_80pct"], x["sale_count"]): x for x in sale_year_stats}.values())
    size_price_bands = list({(x["raw_size_label"], x["raw_price_label"]): x for x in size_price_bands}.values())
    progress_updates = list({(x["update_label"], tuple(x["raw_row"])): x for x in progress_updates}.values())

    # Set top-level year/rate from the most recent sale summary, without confusing this for a transaction-level record.
    latest_stat = max(sale_year_stats, key=lambda x: (x["sales_year"], "so far" in x["year_label"].lower()), default=None)
    latest_sale_year = latest_stat["sales_year"] if latest_stat else None
    price_per_sqft_80pct = latest_stat["price_per_sqft_80pct"] if latest_stat else None
    latest_sale_count = latest_stat["sale_count"] if latest_stat else None
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
    for img in soup.find_all("img", src=True):
        src = urljoin(url, img["src"])
        if src.startswith("https://"):
            images.append(src)
    images = list(dict.fromkeys(images))[:30]  # metadata only; images are not downloaded.

    context_keywords = ("rate about", "up ", "lower than", "higher than", "since ", "was due", "months away",
                        "promised", "not for sale", "booked recently", "bookings not reported", "last reported",
                        "possession date unchanged", "extended", "revised")
    market_context = [line for line in lines if any(k in line.lower() for k in context_keywords)]
    meta_description_tag = soup.find("meta", attrs={"name": "description"})
    page_title_tag = soup.find("title")
    not_for_sale_flag_derived = bool(units_for_sale is not None and not_for_sale_units is not None and
                                     not re.search(r"units for sale", flat_text, re.I))

    return {
        "project_url": canonical_url(url),
        "page_title": clean_text(page_title_tag.get_text(" ", strip=True) if page_title_tag else None),
        "meta_description": clean_text(meta_description_tag.get("content") if meta_description_tag else None),
        "project_name": name or url.rstrip("/").split("/")[-1],
        "rera_number": rera,
        "developer": developer,
        "locality": locality,
        "pin_code": pin_code,
        "maharera_status": maharera_status,
        "construction_stage": status,
        "launch_date_text": launch_date,
        "promised_timeline_text": promised_timeline,
        "possession_date_text": possession_date,
        "original_possession_date_text": original_possession,
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
        "latest_sale_year": latest_sale_year,
        "price_per_sqft_80pct": price_per_sqft_80pct,
        "latest_sale_count": latest_sale_count,
        "map_url": map_url,
        "flat_type_mix": unit_mix,
        "sale_year_stats": sale_year_stats,
        "size_price_bands": size_price_bands,
        "flat_sizes_sold_sqft": flat_sizes_sold_sqft,
        "market_context_snippets": market_context,
        "progress_updates": progress_updates,
        "comparables": comparables,
        "image_urls_metadata_only": images,
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

    def save_project(self, source_page_id: int, data: dict[str, Any], content_hash: str) -> tuple[str, bool]:
        from psycopg.types.json import Jsonb
        key = project_key(data)
        now = utcnow()
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO projects (
                    project_key, rera_number, project_name, developer, locality, pin_code, project_url,
                    maharera_status, construction_stage, launch_date_text, possession_date_text,
                    original_possession_date_text, total_units, units_for_sale, units_booked, booking_pct,
                    building_count, land_acres, excavation_pct, rcc_pct, finishing_pct, complaint_count,
                    latest_sale_year, price_per_sqft_80pct, latest_sale_count, map_url, last_content_sha256, raw_latest,
                    first_seen_at, last_seen_at, last_scraped_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (project_key) DO UPDATE SET
                    rera_number=COALESCE(EXCLUDED.rera_number, projects.rera_number),
                    project_name=COALESCE(EXCLUDED.project_name, projects.project_name),
                    developer=COALESCE(EXCLUDED.developer, projects.developer),
                    locality=COALESCE(EXCLUDED.locality, projects.locality),
                    pin_code=COALESCE(EXCLUDED.pin_code, projects.pin_code),
                    project_url=EXCLUDED.project_url,
                    maharera_status=COALESCE(EXCLUDED.maharera_status, projects.maharera_status),
                    construction_stage=COALESCE(EXCLUDED.construction_stage, projects.construction_stage),
                    launch_date_text=COALESCE(EXCLUDED.launch_date_text, projects.launch_date_text),
                    possession_date_text=COALESCE(EXCLUDED.possession_date_text, projects.possession_date_text),
                    original_possession_date_text=COALESCE(EXCLUDED.original_possession_date_text, projects.original_possession_date_text),
                    total_units=COALESCE(EXCLUDED.total_units, projects.total_units),
                    units_for_sale=COALESCE(EXCLUDED.units_for_sale, projects.units_for_sale),
                    units_booked=COALESCE(EXCLUDED.units_booked, projects.units_booked),
                    booking_pct=COALESCE(EXCLUDED.booking_pct, projects.booking_pct),
                    building_count=COALESCE(EXCLUDED.building_count, projects.building_count),
                    land_acres=COALESCE(EXCLUDED.land_acres, projects.land_acres),
                    excavation_pct=COALESCE(EXCLUDED.excavation_pct, projects.excavation_pct),
                    rcc_pct=COALESCE(EXCLUDED.rcc_pct, projects.rcc_pct),
                    finishing_pct=COALESCE(EXCLUDED.finishing_pct, projects.finishing_pct),
                    complaint_count=COALESCE(EXCLUDED.complaint_count, projects.complaint_count),
                    latest_sale_year=COALESCE(EXCLUDED.latest_sale_year, projects.latest_sale_year),
                    price_per_sqft_80pct=COALESCE(EXCLUDED.price_per_sqft_80pct, projects.price_per_sqft_80pct),
                    latest_sale_count=COALESCE(EXCLUDED.latest_sale_count, projects.latest_sale_count),
                    map_url=COALESCE(EXCLUDED.map_url, projects.map_url),
                    last_content_sha256=EXCLUDED.last_content_sha256,
                    raw_latest=EXCLUDED.raw_latest,
                    last_seen_at=EXCLUDED.last_seen_at,
                    last_scraped_at=EXCLUDED.last_scraped_at""",
                (
                    key, data.get("rera_number"), data["project_name"], data.get("developer"), data.get("locality"),
                    data.get("pin_code"), data["project_url"], data.get("maharera_status"), data.get("construction_stage"),
                    data.get("launch_date_text"), data.get("possession_date_text"), data.get("original_possession_date_text"),
                    data.get("total_units"), data.get("units_for_sale"), data.get("units_booked"), data.get("booking_pct"),
                    data.get("building_count"), data.get("land_acres"), data.get("excavation_pct"), data.get("rcc_pct"),
                    data.get("finishing_pct"), data.get("complaint_count"), data.get("latest_sale_year"),
                    data.get("price_per_sqft_80pct"), data.get("latest_sale_count"), data.get("map_url"), content_hash, Jsonb(data),
                    now, now, now,
                ),
            )
            cur.execute(
                """INSERT INTO project_snapshots (project_key, source_page_id, content_sha256, parser_version, data)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (project_key, content_sha256) DO NOTHING RETURNING snapshot_id""",
                (key, source_page_id, content_hash, PARSER_VERSION, Jsonb(data)),
            )
            snapshot_row = cur.fetchone()
            is_new_snapshot = snapshot_row is not None
            if is_new_snapshot:
                snapshot_id = snapshot_row[0]
                for item in data.get("flat_type_mix", []):
                    cur.execute(
                        "INSERT INTO project_unit_mix (snapshot_id, project_key, flat_type, unit_count) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (snapshot_id, key, item["flat_type"], item.get("unit_count")),
                    )
                for item in data.get("sale_year_stats", []):
                    cur.execute(
                        """INSERT INTO project_sale_year_stats (snapshot_id, project_key, sales_year, year_label, price_per_sqft_80pct, sale_count, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item["sales_year"], item.get("year_label") or str(item["sales_year"]), item.get("price_per_sqft_80pct"), item.get("sale_count"), Jsonb(item.get("raw_row", []))),
                    )
                for item in data.get("size_price_bands", []):
                    cur.execute(
                        """INSERT INTO project_size_price_bands (snapshot_id, project_key, year_label, min_size_sqft, max_size_sqft, min_price_inr, max_price_inr, raw_size_label, raw_price_label)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item.get("year_label"), item.get("min_size_sqft"), item.get("max_size_sqft"), item.get("min_price_inr"), item.get("max_price_inr"), item.get("raw_size_label") or "unknown", item.get("raw_price_label") or "unknown"),
                    )
                for item in data.get("progress_updates", []):
                    cur.execute(
                        """INSERT INTO project_progress_updates (snapshot_id, project_key, update_label, excavation_pct, rcc_pct, finishing_pct, units_booked, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, item["update_label"], item.get("excavation_pct"), item.get("rcc_pct"), item.get("finishing_pct"), item.get("units_booked"), Jsonb(item.get("raw_row", []))),
                    )
                for item in data.get("comparables", []):
                    label = item.get("comparable_name") or "unknown"
                    cur.execute(
                        """INSERT INTO project_comparables (snapshot_id, project_key, comparable_name, launch_date_text, possession_date_text, rcc_pct, booking_text, raw_row)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (snapshot_id, key, label, item.get("launch_date_text"), item.get("possession_date_text"), item.get("rcc_pct"), item.get("booking_text"), Jsonb(item.get("raw_row", []))),
                    )
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


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Collect a limited, polite FlatNama research sample into PostgreSQL.")
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("seed_urls.txt"), help="Text file with area/project URLs")
    parser.add_argument("--discover-project-links", action="store_true", help="Find project detail URLs on the supplied area pages")
    parser.add_argument("--max-area-pages", type=int, default=5, help="Maximum explicitly seeded area pages (default 5)")
    parser.add_argument("--max-project-pages", type=int, default=25, help="Maximum project pages per run (default 25)")
    parser.add_argument("--authorized-bulk", action="store_true", help="Required for expanded collection after written permission; also set permission env var")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse pages but do not write PostgreSQL project data")
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
    project_urls: list[str] = list(direct_projects)
    seen_project_urls = set(project_urls)

    def record_error(url: str, page_type: str, err: Exception) -> None:
        nonlocal failed
        failed += 1
        LOG.warning("Failed %s (%s): %s", url, page_type, err)
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
            discovered = project_links_from_html(result.html, area_url) if args.discover_project_links else []
            if store:
                store.add_source_page(run_id, area_url, "area", result.status_code, result.content_sha256, "ok")
                store.conn.commit()
            LOG.info("Fetched area page: %s; project links discovered=%d", area_url, len(discovered))
            for link in discovered:
                if link not in seen_project_urls:
                    seen_project_urls.add(link)
                    project_urls.append(link)
        except Exception as exc:
            record_error(area_url, "area", exc)
            # Stop after access-control/rate-limit signals; do not retry or work around them.
            if any(code in str(exc) for code in ("HTTP 403", "HTTP 429", "robots.txt disallows", "challenge/access restriction")):
                access_stop = True
                break

    project_urls = project_urls[:args.max_project_pages]
    for project_url in ([] if access_stop else project_urls):
        try:
            result = client.fetch(project_url)
            project_seen += 1
            data = parse_project_page(project_url, result.html)
            parse_ok = bool(data.get("project_name") and data.get("rera_number") and (data.get("developer") or data.get("locality") or data.get("total_units")))
            if store:
                source_page_id = store.add_source_page(run_id, project_url, "project", result.status_code, result.content_sha256, "ok" if parse_ok else "partial")
                store.save_project(source_page_id, data, result.content_sha256)
                store.conn.commit()
            succeeded += 1
            LOG.info("Project parsed: %s | RERA=%s | sales-year summaries=%d | progress rows=%d",
                     data.get("project_name"), data.get("rera_number"), len(data.get("sale_year_stats", [])), len(data.get("progress_updates", [])))
        except Exception as exc:
            record_error(project_url, "project", exc)
            if any(code in str(exc) for code in ("HTTP 403", "HTTP 429", "robots.txt disallows", "challenge/access restriction")):
                access_stop = True
                break

    if store:
        store.finish_run(run_id, area_seen, project_seen, succeeded, failed)
        store.close()
    LOG.info("Run complete. run_id=%s area_pages=%d project_pages=%d succeeded=%d failed=%d", run_id, area_seen, project_seen, succeeded, failed)
    if args.dry_run:
        LOG.info("Dry-run mode: PostgreSQL was not modified.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
