"""Tatmeen 의약품 이력 추적 시스템 공지 모니터링.

타겟: https://tatmeen.ae
수집:
  - GS1 DataMatrix 기술 가이드라인 업데이트
  - 의무화 타임라인 공지
  - API B2B 연동 기술 문서 링크

결과는 Supabase uae_tatmeen_guide 테이블에 저장됩니다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

TATMEEN_BASE_URL = "https://tatmeen.ae"
TATMEEN_ABOUT_URL = "https://tatmeen.ae/about"
TATMEEN_NEWS_URL = "https://tatmeen.ae/news"
TATMEEN_RESOURCES_URL = "https://tatmeen.ae/resources"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UPharma-MarketBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

_GS1_REQUIREMENTS = {
    "mandatory_elements": [
        "GTIN (Global Trade Item Number)",
        "Serial Number (무작위 일련번호)",
        "Batch/Lot Number (배치·로트 번호)",
        "Expiry Date (유통기한)",
    ],
    "barcode_standard": "GS1 DataMatrix (ISO/IEC 16022)",
    "packaging_level": "2차 포장(Secondary Packaging) 의무",
    "aggregation": "Unit → Case → Pallet 단위 어그리게이션 필요",
    "reporting": "B2B API(System-to-System) 실시간 전송 의무",
    "participant_count": "11,000개 이상 유통업자·약국·병원 참여",
    "legal_basis": "MOHAP 연방 규정 + EVOTEQ 파트너십",
}


async def fetch_tatmeen_notices() -> list[dict[str, Any]]:
    """Tatmeen 포털에서 최신 공지 및 가이드라인 수집."""
    notices: list[dict[str, Any]] = []

    urls_to_check = [TATMEEN_ABOUT_URL, TATMEEN_NEWS_URL, TATMEEN_RESOURCES_URL]

    for url in urls_to_check:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code != 200:
                    continue

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")

                # 뉴스/공지 항목 추출
                for item in soup.select("article, .news-item, .notice-item, .update-item, li"):
                    title_el = item.select_one("h1, h2, h3, h4, a")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue

                    link_el = item.select_one("a[href]")
                    link = ""
                    if link_el:
                        href = link_el.get("href", "")
                        if href.startswith("http"):
                            link = href
                        elif href.startswith("/"):
                            link = f"{TATMEEN_BASE_URL}{href}"

                    date_el = item.select_one("time, .date, .published")
                    date_str = date_el.get_text(strip=True) if date_el else ""

                    # GS1/DataMatrix 관련 항목 우선 수집
                    keywords = ["gs1", "datamatrix", "barcode", "serialization", "track", "mandate", "deadline", "compliance"]
                    if any(kw in title.lower() for kw in keywords):
                        notices.append({
                            "title":      title[:200],
                            "url":        link,
                            "date_str":   date_str,
                            "source_url": url,
                            "type":       "technical_guideline",
                            "crawled_at": datetime.now(timezone.utc).isoformat(),
                        })

                # PDF 링크 추출 (가이드라인 문서)
                for a in soup.select("a[href$='.pdf'], a[href*='guide'], a[href*='manual']"):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    if not href or not text:
                        continue
                    if href.startswith("/"):
                        href = f"{TATMEEN_BASE_URL}{href}"
                    notices.append({
                        "title":      text[:200],
                        "url":        href,
                        "date_str":   "",
                        "source_url": url,
                        "type":       "pdf_document",
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                    })

        except Exception:
            continue

    # Jina AI 폴백
    if not notices:
        try:
            jina_url = f"https://r.jina.ai/{TATMEEN_ABOUT_URL}"
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(jina_url)
                if resp.status_code == 200:
                    notices.append({
                        "title":      "Tatmeen 공식 소개 및 GS1 요건 (Jina 수집)",
                        "url":        TATMEEN_ABOUT_URL,
                        "date_str":   "",
                        "source_url": TATMEEN_ABOUT_URL,
                        "type":       "general_info",
                        "content_preview": resp.text[:500],
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                    })
        except Exception:
            pass

    return notices


def get_tatmeen_compliance_summary() -> dict[str, Any]:
    """Tatmeen 준수 요건 정적 요약 (실시간 크롤링 없이 즉시 반환)."""
    return {
        "system_name":        "Tatmeen — UAE 국가 의약품 이력 추적 시스템",
        "operator":           "MOHAP (보건예방부) + EVOTEQ",
        "portal_url":         TATMEEN_BASE_URL,
        "gs1_requirements":   _GS1_REQUIREMENTS,
        "mandatory_for":      "UAE 수입·제조 모든 의약품 (8개 수출 품목 전량 포함)",
        "compliance_steps": [
            "1. GS1 Korea에서 GTIN(바코드 번호) 발급",
            "2. 2차 포장에 GS1 DataMatrix 인쇄 (4요소 암호화)",
            "3. Tatmeen 포털에 제조사·GLN(글로벌 위치번호) 등록",
            "4. 선적 전 B2B API로 제품 고유 식별 번호 보고",
            "5. Unit→Case→Pallet 어그리게이션 데이터 전송",
        ],
        "risk_if_non_compliant": "UAE 세관 억류, 수입 허가 취소, EDE 등록 무효화",
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }


async def save_notices_to_supabase(notices: list[dict[str, Any]]) -> int:
    """Tatmeen 공지를 Supabase uae_tatmeen_guide 테이블에 저장."""
    if not notices:
        return 0
    try:
        from utils.db import get_client
        sb = get_client()
        to_upsert = []
        for n in notices:
            to_upsert.append({
                "title":        n.get("title", "")[:200],
                "url":          n.get("url", ""),
                "date_str":     n.get("date_str", ""),
                "source_url":   n.get("source_url", ""),
                "guide_type":   n.get("type", "general"),
                "crawled_at":   n.get("crawled_at", datetime.now(timezone.utc).isoformat()),
            })
        result = sb.table("uae_tatmeen_guide").upsert(to_upsert).execute()
        return len(result.data or [])
    except Exception:
        return 0
