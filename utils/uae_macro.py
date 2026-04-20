"""UAE(아랍에미리트) 거시지표.

정적 폴백값 기준: EDE 신설 후 최신 통계 (2025년 기준).
동적 소스: Supabase uae_health_expenditure / uae_world_population (향후 연동 예정).
"""
from __future__ import annotations

from typing import Any

_STATIC_MACRO: list[dict] = [
    {"label": "제약 시장 규모",   "value": "USD 44.5억",  "sub": "2025  ·  IMARC Group / Ken Research"},
    {"label": "연평균 성장률",    "value": "6.1% CAGR",   "sub": "2025-2033  ·  EDE 출범 후 전망"},
    {"label": "1인당 GDP",        "value": "USD 41,000+", "sub": "2024  ·  IMF / FCSC"},
    {"label": "인구",              "value": "1,090만 명",  "sub": "2024  ·  FCSC(연방통계청)"},
]

_cache: list[dict] | None = None


def get_uae_macro() -> list[dict[str, Any]]:
    """Supabase에서 UAE 거시지표 조회. 실패 시 정적 폴백."""
    global _cache
    if _cache is not None:
        return _cache

    try:
        from utils.db import get_client
        sb = get_client()

        pop_row = (
            sb.table("uae_world_population")
            .select("population,year")
            .eq("country_code", "ARE")
            .order("year", desc=True)
            .limit(1)
            .execute()
            .data
        )
        exp_row = (
            sb.table("uae_health_expenditure")
            .select("value,year,series")
            .eq("country_or_area", "United Arab Emirates")
            .order("year", desc=True)
            .limit(1)
            .execute()
            .data
        )

        result = list(_STATIC_MACRO)
        if pop_row:
            p = pop_row[0]
            result[3] = {
                "label": "인구",
                "value": f"{p['population']:,}명",
                "sub": f"{p['year']}  ·  World Bank",
            }
        if exp_row:
            e = exp_row[0]
            result[0] = {
                "label": "보건 지출/인구",
                "value": f"USD {e['value']:,.0f}",
                "sub": f"{e['year']}  ·  WHO GHED",
            }

        _cache = result
        return result
    except Exception:
        return _STATIC_MACRO


UAE_MACRO = _STATIC_MACRO
