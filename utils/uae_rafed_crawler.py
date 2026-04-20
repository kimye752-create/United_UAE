"""Rafed(UAE 의료 그룹구매조직) 공공 조달 입찰 크롤러.

타겟: https://rafeduae.ae (Playwright 헤드리스 브라우저 사용)
수집: 입찰번호, 품목명, 발주일, 마감일, 낙찰가, 공급업체

Playwright 미설치 시 Perplexity API 폴백으로 입찰 정보를 검색합니다.
결과는 Supabase uae_tender_history 테이블에 저장됩니다.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

RAFED_BASE_URL = "https://rafeduae.ae"
RAFED_TENDER_URL = "https://rafeduae.ae/tenders"
ADGPG_TENDER_URL = "https://www.adgpg.gov.ae/en/For-Suppliers/Public-Tenders"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UPharma-MarketBot/1.0)",
}


async def _crawl_with_playwright(
    inn_keywords: list[str],
    emit: Callable[[str, str], Coroutine] | None = None,
) -> list[dict[str, Any]]:
    """Playwright로 Rafed 동적 입찰 목록 크롤링."""
    results: list[dict[str, Any]] = []

    async def _log(msg: str) -> None:
        if emit:
            await emit(msg, "info")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await _log("Playwright 미설치 — Perplexity 폴백으로 전환합니다.")
        return []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_HEADERS["User-Agent"])
            await _log(f"Rafed 입찰 포털 접속 중: {RAFED_TENDER_URL}")
            await page.goto(RAFED_TENDER_URL, wait_until="networkidle", timeout=30_000)

            for keyword in inn_keywords[:5]:
                await _log(f"키워드 검색: {keyword}")
                try:
                    search_input = page.locator("input[type='search'], input[placeholder*='search' i], input[placeholder*='Search' i]")
                    if await search_input.count() > 0:
                        await search_input.first.fill(keyword)
                        await search_input.first.press("Enter")
                        await page.wait_for_timeout(2000)

                    rows = page.locator("table tbody tr, .tender-item, .rfp-row")
                    count = await rows.count()
                    for i in range(min(count, 10)):
                        row = rows.nth(i)
                        text = await row.inner_text()
                        if keyword.lower() in text.lower():
                            cells = await row.locator("td").all_inner_texts()
                            results.append({
                                "tender_ref":   cells[0].strip() if len(cells) > 0 else "",
                                "description":  cells[1].strip() if len(cells) > 1 else text[:120],
                                "issue_date":   cells[2].strip() if len(cells) > 2 else "",
                                "close_date":   cells[3].strip() if len(cells) > 3 else "",
                                "award_value":  cells[4].strip() if len(cells) > 4 else "",
                                "keyword_hit":  keyword,
                                "source":       "Rafed (Playwright)",
                                "crawled_at":   datetime.now(timezone.utc).isoformat(),
                            })
                except Exception as e:
                    await _log(f"키워드 {keyword} 검색 오류: {e}")

            await browser.close()
            await _log(f"Rafed 크롤링 완료 — {len(results)}건")

    except Exception as e:
        await _log(f"Playwright 크롤링 실패: {e}")

    return results


async def _search_via_perplexity(
    inn_keywords: list[str],
    emit: Callable[[str, str], Coroutine] | None = None,
) -> list[dict[str, Any]]:
    """Perplexity API로 Rafed 입찰 정보 검색 (Playwright 폴백)."""
    import os
    import httpx

    px_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not px_key:
        return []

    results: list[dict[str, Any]] = []
    query_terms = " OR ".join(inn_keywords[:4])
    query = (
        f"Rafed UAE procurement tender RFP for pharmaceutical: {query_terms}. "
        f"Include tender reference number, description, issue date, close date, award value. "
        f"Source: rafeduae.ae or UAE government procurement."
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {px_key}", "Content-Type": "application/json"},
                json={
                    "model": "sonar-pro",
                    "messages": [
                        {"role": "system", "content": "You are a UAE pharmaceutical procurement expert. Provide factual tender information from Rafed UAE."},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 800,
                    "return_citations": True,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            results.append({
                "tender_ref":   "Perplexity 검색 결과",
                "description":  content[:600],
                "keyword_hit":  query_terms,
                "source":       "Perplexity sonar-pro",
                "crawled_at":   datetime.now(timezone.utc).isoformat(),
            })
    except Exception:
        pass

    return results


async def crawl_rafed_tenders(
    inn_keywords: list[str],
    emit: Callable[[str, str], Coroutine] | None = None,
) -> list[dict[str, Any]]:
    """Rafed 입찰 데이터 수집 (Playwright 우선 → Perplexity 폴백)."""
    results = await _crawl_with_playwright(inn_keywords, emit)

    if not results:
        if emit:
            await emit("Rafed Playwright 크롤링 결과 없음 — Perplexity 폴백 실행", "warn")
        results = await _search_via_perplexity(inn_keywords, emit)

    return results


async def get_tender_context_for_product(
    trade_name: str,
    inn: str,
) -> str | None:
    """품목에 대한 Rafed 입찰 컨텍스트 문자열 생성 (Claude 프롬프트용)."""
    inn_parts = [p.strip() for p in re.split(r"[/+,]", inn) if p.strip()]
    keywords = [trade_name] + inn_parts[:2]

    try:
        tenders = await crawl_rafed_tenders(keywords)
    except Exception:
        return None

    if not tenders:
        return None

    lines = [f"Rafed UAE 조달 입찰 데이터 ({len(tenders)}건):"]
    for t in tenders[:5]:
        ref = t.get("tender_ref", "")
        desc = t.get("description", "")[:100]
        val = t.get("award_value", "")
        lines.append(f"- [{ref}] {desc} | 낙찰가: {val or '미확인'} | {t.get('source', '')}")

    return "\n".join(lines)


async def save_tenders_to_supabase(rows: list[dict[str, Any]]) -> int:
    """입찰 데이터를 Supabase uae_tender_history 테이블에 저장."""
    if not rows:
        return 0
    try:
        from utils.db import get_client
        sb = get_client()
        to_insert = []
        for r in rows:
            to_insert.append({
                "tender_ref":     r.get("tender_ref", ""),
                "description":    r.get("description", "")[:500],
                "issue_date":     r.get("issue_date") or None,
                "close_date":     r.get("close_date") or None,
                "award_value_aed": _parse_aed(r.get("award_value", "")),
                "keyword_hit":    r.get("keyword_hit", ""),
                "source_label":   r.get("source", ""),
                "raw_text":       r.get("description", "")[:1000],
                "crawled_at":     r.get("crawled_at", datetime.now(timezone.utc).isoformat()),
            })
        result = sb.table("uae_tender_history").upsert(to_insert).execute()
        return len(result.data or [])
    except Exception:
        return 0


def _parse_aed(val: str) -> float | None:
    if not val:
        return None
    cleaned = re.sub(r"[^\d.]", "", val.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None
