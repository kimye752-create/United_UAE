"""대시보드에 표시할 UAE 규제 사이트 라벨 (한국어)."""

from __future__ import annotations

from typing import Any, TypedDict


class SiteDef(TypedDict):
    id: str
    name: str
    hint: str
    domain: str


DASHBOARD_SITES: tuple[SiteDef, ...] = (
    {
        "id": "ede",
        "name": "EDE · 에미리트 의약품청",
        "hint": "의약품 디렉토리 — 등재 현황·eCTD 등록 절차·수입 허가 (httpx+Jina 폴백)",
        "domain": "ede.gov.ae",
    },
    {
        "id": "doh",
        "name": "DoH · 아부다비 보건부",
        "hint": "참조 가격 리스트 Excel(.ashx) — 성분명·원산지·약국공급가·대중판매가(AED) 수집",
        "domain": "doh.gov.ae",
    },
    {
        "id": "dha",
        "name": "DHA · 두바이 보건국",
        "hint": "두바이 약가표 XLSX — POM/OTC 분류·처방 가이드라인·통제 약물 플랫폼 규정",
        "domain": "dha.gov.ae",
    },
    {
        "id": "rafed",
        "name": "Rafed · UAE 의료 GPO",
        "hint": "SEHA 공공 의료조달 RFP/입찰 공고 — Playwright 헤드리스 동적 파싱",
        "domain": "rafeduae.ae",
    },
    {
        "id": "tatmeen",
        "name": "Tatmeen · 의약품 추적 포털",
        "hint": "GS1 DataMatrix 기술 가이드라인·의무화 타임라인·B2B API 문서 모니터링",
        "domain": "tatmeen.ae",
    },
)


def initial_site_states() -> dict[str, dict[str, Any]]:
    return {
        s["id"]: {
            "status": "pending",
            "message": "아직 시작 전이에요",
            "ts": 0.0,
        }
        for s in DASHBOARD_SITES
    }
