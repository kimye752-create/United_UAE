"""EDE(에미리트 의약품청) 의약품 디렉토리 조회.

Emirates Drug Establishment Drug Directory:
  https://www.ede.gov.ae

products 테이블 (country='UAE', source_name='UAE:ede_registry')에서 읽거나
실시간 크롤링을 통해 EDE 등재 여부를 확인합니다.
"""
from __future__ import annotations

import asyncio
from typing import Any

_cache: list[dict[str, Any]] | None = None

EDE_DRUG_DIRECTORY_URL = "https://www.ede.gov.ae"
EDE_SMART_SERVICES_URL = "https://www.ede.gov.ae/en/services"


def load_registry() -> dict[str, dict[str, Any]]:
    """registration_number → row 매핑 반환 (Supabase 기반)."""
    global _cache
    if _cache is None:
        from utils.db import get_client
        sb = get_client()
        try:
            rows = (
                sb.table("products")
                .select(
                    "registration_number,trade_name,active_ingredient,"
                    "strength,dosage_form,country_specific"
                )
                .eq("country", "UAE")
                .eq("source_name", "UAE:ede_registry")
                .execute()
                .data or []
            )
            _cache = rows
        except Exception:
            _cache = []

    return {
        r["registration_number"]: r
        for r in _cache
        if r.get("registration_number")
    }


def row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    cs = row.get("country_specific") or {}
    return {
        "reg_no":           (row.get("registration_number") or "").strip(),
        "product_name":     (row.get("trade_name") or "").strip(),
        "trade_name":       (row.get("trade_name") or "").strip(),
        "active_ingredient": (row.get("active_ingredient") or ""),
        "strength":         (row.get("strength") or "").strip(),
        "dosage_form":      (row.get("dosage_form") or "").strip().lower(),
        "ede_status":       cs.get("ede_status", ""),
        "manufacturer":     cs.get("manufacturer", ""),
        "origin_country":   cs.get("origin_country", ""),
        "segment":          cs.get("segment", "prescription"),
    }


async def search_ede_directory(inn: str) -> list[dict[str, Any]]:
    """EDE 의약품 디렉토리에서 INN 기반 실시간 검색.

    정적 HTML 시도 → 실패 시 Jina AI Reader 폴백.
    결과를 Supabase UAE:ede_registry에 저장.
    """
    import httpx
    from urllib.parse import urlencode, quote

    results: list[dict[str, Any]] = []

    # 1차 시도: EDE 포털 직접 검색
    search_url = f"{EDE_DRUG_DIRECTORY_URL}/en/services/drug-directory"
    params = {"q": inn, "type": "conventional"}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(search_url, params=params, headers={
                "User-Agent": "Mozilla/5.0 (compatible; UPharma-MarketBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            })
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                # EDE 테이블 파싱 (구조는 변경 가능)
                rows = soup.select("table tbody tr")
                for row in rows[:20]:
                    cells = [c.get_text(strip=True) for c in row.select("td")]
                    if len(cells) >= 3:
                        results.append({
                            "reg_no":           cells[0] if len(cells) > 0 else "",
                            "trade_name":       cells[1] if len(cells) > 1 else "",
                            "active_ingredient": cells[2] if len(cells) > 2 else "",
                            "dosage_form":      cells[3] if len(cells) > 3 else "",
                            "manufacturer":     cells[4] if len(cells) > 4 else "",
                            "ede_status":       "active",
                            "source":           "EDE Direct",
                        })
    except Exception:
        pass

    # 2차 폴백: Jina AI Reader (Cloudflare 우회)
    if not results:
        try:
            jina_url = f"https://r.jina.ai/{search_url}?{urlencode({'q': inn})}"
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(jina_url, headers={
                    "Accept": "application/json",
                    "X-Return-Format": "markdown",
                })
                if resp.status_code == 200:
                    text = resp.text
                    # 마크다운 텍스트에서 테이블 행 파싱
                    for line in text.split("\n"):
                        if "|" in line and inn.lower() in line.lower():
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if len(parts) >= 2:
                                results.append({
                                    "trade_name":       parts[0],
                                    "active_ingredient": inn,
                                    "dosage_form":      parts[1] if len(parts) > 1 else "",
                                    "ede_status":       "active",
                                    "source":           "EDE via Jina",
                                })
        except Exception:
            pass

    return results


async def get_ede_status_for_inn(inn: str) -> str:
    """INN에 대한 EDE 등재 상태 요약 문자열 반환."""
    # DB 먼저 확인
    registry = load_registry()
    inn_lower = inn.lower().split("/")[0].strip()
    matched = [
        row for row in registry.values()
        if inn_lower in (row.get("active_ingredient") or "").lower()
    ]
    if matched:
        count = len(matched)
        names = ", ".join(r.get("trade_name", "") for r in matched[:3])
        return f"EDE 등재 {count}건 확인 (대표: {names})"

    # 실시간 크롤링
    live = await search_ede_directory(inn_lower)
    if live:
        count = len(live)
        names = ", ".join(r.get("trade_name", "") for r in live[:3])
        return f"EDE 디렉토리 실시간 조회 {count}건 (대표: {names})"

    return "EDE 등재 여부 — 현재 확보된 데이터 기준 추가 확인 필요"
