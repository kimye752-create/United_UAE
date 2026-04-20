"""DoH(아부다비 보건부) 및 DHA(두바이 보건국) 참조 가격 리스트 크롤러.

타겟:
  DoH: https://www.doh.gov.ae/en/resources/Circulars (참조 가격 Excel .ashx)
  DHA: https://www.dha.gov.ae/en/HealthRegulationSector/DrugControl (약가표 XLSX)

수집 항목:
  성분명(INN), 원산지, 제조사, 로컬 에이전트,
  약국공급가(AED), 대중판매가(AED), POM 여부

결과는 Supabase uae_price_reference 테이블에 저장됩니다.
"""
from __future__ import annotations

import asyncio
import io
import re
from typing import Any

import httpx

# DoH 참조 가격 리스트 URL (공개 링크 — 변경 시 업데이트 필요)
DOH_PRICE_LIST_URL = (
    "https://www.doh.gov.ae/en/resources/reference-price-list"
)
DOH_CIRCULARS_URL = "https://www.doh.gov.ae/en/resources/Circulars"

# DHA 약가표 URL
DHA_PRICE_LIST_URL = (
    "https://www.dha.gov.ae/en/HealthRegulationSector/DrugControl"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UPharma-MarketBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# 인메모리 캐시 (세션당 1회 다운로드)
_doh_price_cache: list[dict[str, Any]] | None = None
_dha_price_cache: list[dict[str, Any]] | None = None


async def _download_excel_from_url(url: str) -> bytes | None:
    """URL에서 Excel 파일 다운로드. 실패 시 None."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "excel" in ct or "spreadsheet" in ct or "octet-stream" in ct or len(resp.content) > 10_000:
                    return resp.content
    except Exception:
        pass
    return None


async def _find_excel_link_on_page(page_url: str) -> str | None:
    """페이지 HTML에서 Excel/ASHX 다운로드 링크 탐색."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(page_url, headers=_HEADERS)
            if resp.status_code != 200:
                return None
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if any(ext in href.lower() for ext in [".xlsx", ".xls", ".ashx", "price", "pricelist"]):
                    if href.startswith("http"):
                        return href
                    elif href.startswith("/"):
                        from urllib.parse import urlparse
                        parsed = urlparse(page_url)
                        return f"{parsed.scheme}://{parsed.netloc}{href}"
    except Exception:
        pass
    return None


def _parse_price_excel(data: bytes, source_label: str) -> list[dict[str, Any]]:
    """Excel 바이너리를 파싱하여 가격 행 리스트 반환."""
    rows: list[dict[str, Any]] = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active

        header_row: list[str] = []
        header_idx: dict[str, int] = {}

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                header_row = [str(c or "").strip().lower() for c in row]
                # 컬럼 인덱스 매핑 (유연한 헤더 처리)
                col_aliases = {
                    "inn": ["inn", "active ingredient", "generic name", "innname", "active_ingredient"],
                    "trade_name": ["trade name", "brand", "product name", "tradename"],
                    "manufacturer": ["manufacturer", "mfr", "company"],
                    "origin": ["origin", "country", "country of origin"],
                    "agent": ["agent", "local agent", "distributor"],
                    "pharmacy_price": ["pharmacy price", "pharmacy", "pharm price", "supply price"],
                    "public_price": ["public price", "retail", "selling price", "mrp"],
                    "pom": ["pom", "prescription", "rx"],
                    "dosage_form": ["form", "dosage form", "formulation"],
                    "strength": ["strength", "dose", "concentration"],
                }
                for std_key, aliases in col_aliases.items():
                    for alias in aliases:
                        for hi, h in enumerate(header_row):
                            if alias in h:
                                header_idx[std_key] = hi
                                break
                        if std_key in header_idx:
                            break
                continue

            def _cell(key: str) -> str:
                idx = header_idx.get(key)
                if idx is not None and idx < len(row):
                    return str(row[idx] or "").strip()
                return ""

            inn_val = _cell("inn")
            if not inn_val or inn_val.lower() in ("inn", "active ingredient", ""):
                continue

            rows.append({
                "inn":            inn_val,
                "trade_name":     _cell("trade_name"),
                "manufacturer":   _cell("manufacturer"),
                "origin":         _cell("origin"),
                "agent":          _cell("agent"),
                "dosage_form":    _cell("dosage_form"),
                "strength":       _cell("strength"),
                "pharmacy_price_aed": _parse_aed(_cell("pharmacy_price")),
                "public_price_aed":   _parse_aed(_cell("public_price")),
                "pom":            "yes" in _cell("pom").lower() or _cell("pom") == "1",
                "source":         source_label,
            })

    except Exception:
        pass
    return rows


def _parse_aed(val: str) -> float | None:
    """'AED 12.50', '12.5', '12,500' 형식에서 float 추출."""
    if not val:
        return None
    cleaned = re.sub(r"[^\d.]", "", val.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


async def fetch_doh_prices() -> list[dict[str, Any]]:
    """DoH 참조 가격 리스트 다운로드 및 파싱."""
    global _doh_price_cache
    if _doh_price_cache is not None:
        return _doh_price_cache

    excel_url = await _find_excel_link_on_page(DOH_PRICE_LIST_URL)
    if not excel_url:
        excel_url = await _find_excel_link_on_page(DOH_CIRCULARS_URL)

    if excel_url:
        data = await _download_excel_from_url(excel_url)
        if data:
            _doh_price_cache = _parse_price_excel(data, "DoH Abu Dhabi")
            return _doh_price_cache

    # Jina AI 폴백 — 텍스트에서 가격 추출
    try:
        jina_url = f"https://r.jina.ai/{DOH_PRICE_LIST_URL}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(jina_url)
            if resp.status_code == 200:
                _doh_price_cache = _parse_text_prices(resp.text, "DoH Abu Dhabi (Jina)")
                return _doh_price_cache
    except Exception:
        pass

    _doh_price_cache = []
    return _doh_price_cache


async def fetch_dha_prices() -> list[dict[str, Any]]:
    """DHA 두바이 약가표 다운로드 및 파싱."""
    global _dha_price_cache
    if _dha_price_cache is not None:
        return _dha_price_cache

    excel_url = await _find_excel_link_on_page(DHA_PRICE_LIST_URL)
    if excel_url:
        data = await _download_excel_from_url(excel_url)
        if data:
            _dha_price_cache = _parse_price_excel(data, "DHA Dubai")
            return _dha_price_cache

    _dha_price_cache = []
    return _dha_price_cache


def _parse_text_prices(text: str, source: str) -> list[dict[str, Any]]:
    """텍스트(마크다운/HTML)에서 AED 가격 패턴 추출."""
    rows: list[dict[str, Any]] = []
    aed_pattern = re.compile(r"([A-Za-z\s\-]+)\s+(?:AED\s*)?([\d,]+\.?\d*)\s+(?:AED\s*)?([\d,]+\.?\d*)?")
    for line in text.split("\n"):
        m = aed_pattern.search(line)
        if m:
            rows.append({
                "inn": m.group(1).strip(),
                "pharmacy_price_aed": _parse_aed(m.group(2)),
                "public_price_aed": _parse_aed(m.group(3)) if m.group(3) else None,
                "source": source,
            })
    return rows[:100]


async def get_price_context_for_inn(inn: str) -> str | None:
    """INN에 대한 DoH/DHA 가격 컨텍스트 문자열 생성 (Claude 프롬프트용)."""
    if not inn or not inn.strip():
        return None

    inn_parts = [p.strip().lower() for p in re.split(r"[/+,]", inn) if p.strip()]

    try:
        doh_rows, dha_rows = await asyncio.gather(
            fetch_doh_prices(),
            fetch_dha_prices(),
        )
    except Exception:
        return None

    all_rows = doh_rows + dha_rows
    if not all_rows:
        return None

    matched: list[dict[str, Any]] = []
    for row in all_rows:
        row_inn = (row.get("inn") or "").lower()
        if any(part in row_inn for part in inn_parts):
            matched.append(row)

    if not matched:
        return None

    lines = [f"DoH/DHA 참조 가격 데이터 ({len(matched)}건 매칭, 성분: {inn}):"]
    for r in matched[:8]:
        ph = r.get("pharmacy_price_aed")
        pub = r.get("public_price_aed")
        ph_str = f"약국공급가 AED {ph:.2f}" if ph else ""
        pub_str = f"대중판매가 AED {pub:.2f}" if pub else ""
        price_str = " / ".join(filter(None, [ph_str, pub_str])) or "가격 미확인"
        pom = "처방전 의약품(POM)" if r.get("pom") else "일반의약품(OTC)"
        origin = r.get("origin", "")
        mfr = r.get("manufacturer", "")
        trade = r.get("trade_name", "")
        parts = [f"- {trade or r.get('inn', '')}"]
        if mfr:
            parts.append(f"제조사: {mfr}")
        if origin:
            parts.append(f"원산지: {origin}")
        parts.append(price_str)
        parts.append(pom)
        parts.append(f"[출처: {r.get('source', '')}]")
        lines.append(" | ".join(parts))

    return "\n".join(lines)


async def save_prices_to_supabase(rows: list[dict[str, Any]]) -> int:
    """수집된 가격 데이터를 Supabase uae_price_reference 테이블에 저장."""
    if not rows:
        return 0
    try:
        from utils.db import get_client
        from datetime import datetime, timezone
        sb = get_client()
        to_upsert = []
        for r in rows:
            to_upsert.append({
                "inn_name":            r.get("inn", ""),
                "trade_name":          r.get("trade_name", ""),
                "manufacturer":        r.get("manufacturer", ""),
                "origin_country":      r.get("origin", ""),
                "local_agent":         r.get("agent", ""),
                "dosage_form":         r.get("dosage_form", ""),
                "strength":            r.get("strength", ""),
                "pharmacy_price_aed":  r.get("pharmacy_price_aed"),
                "public_price_aed":    r.get("public_price_aed"),
                "is_pom":              r.get("pom", True),
                "source_label":        r.get("source", ""),
                "crawled_at":          datetime.now(timezone.utc).isoformat(),
            })
        result = sb.table("uae_price_reference").upsert(to_upsert).execute()
        return len(result.data or [])
    except Exception:
        return 0
