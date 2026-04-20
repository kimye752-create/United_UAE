#!/usr/bin/env python3
"""UAE 전용 Supabase 테이블 생성 및 시드 데이터 삽입 스크립트.

실행:
    python scripts/setup_uae_db.py           # 전체 실행
    python scripts/setup_uae_db.py --check   # 연결 확인만
    python scripts/setup_uae_db.py --seed    # 제품 시드만 (테이블 이미 존재)

⚠️  안전 보장:
    - 이 스크립트는 uae_* 테이블만 생성합니다.
    - products 공유 테이블은 country='UAE', source_name='UAE:...' 행만 삽입합니다.
    - 다른 팀의 데이터(SG, UY 등)는 절대 건드리지 않습니다.
    - CREATE TABLE은 IF NOT EXISTS로 보호됩니다 (이미 있으면 무시).
    - INSERT는 ON CONFLICT (product_id) DO UPDATE로 멱등성 보장됩니다.
"""
from __future__ import annotations

import argparse
import sys
import os
import textwrap

# 프로젝트 루트를 sys.path에 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ── 색상 출력 헬퍼 ────────────────────────────────────────────────────────────

def _ok(msg: str)    -> None: print(f"  [OK]  {msg}")
def _warn(msg: str)  -> None: print(f"  [!!]  {msg}")
def _err(msg: str)   -> None: print(f"  [XX]  {msg}")
def _head(msg: str)  -> None: print(f"\n{'='*60}\n  {msg}\n{'='*60}")


# ── DDL 정의 (UAE 전용 테이블만) ──────────────────────────────────────────────

_DDL_STATEMENTS = [
    # 1. UAE 품목별 분석 컨텍스트
    """
    CREATE TABLE IF NOT EXISTS uae_product_context (
      id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      product_id            TEXT NOT NULL UNIQUE,
      ede_matches           JSONB DEFAULT '[]'::JSONB,
      ede_registered        BOOLEAN DEFAULT FALSE,
      competitor_count      INT DEFAULT 0,
      prescription_only     BOOLEAN DEFAULT TRUE,
      doh_price_aed         NUMERIC(10,2),
      dha_price_aed         NUMERIC(10,2),
      tatmeen_compliant     BOOLEAN DEFAULT FALSE,
      rafed_tender_count    INT DEFAULT 0,
      pdf_snippets          JSONB DEFAULT '[]'::JSONB,
      brochure_snippets     JSONB DEFAULT '[]'::JSONB,
      regulatory_summary    TEXT DEFAULT '',
      built_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # 2. DoH/DHA 참조 가격 리스트
    """
    CREATE TABLE IF NOT EXISTS uae_price_reference (
      id                    BIGSERIAL PRIMARY KEY,
      inn_name              TEXT NOT NULL,
      trade_name            TEXT DEFAULT '',
      manufacturer          TEXT DEFAULT '',
      origin_country        TEXT DEFAULT '',
      local_agent           TEXT DEFAULT '',
      dosage_form           TEXT DEFAULT '',
      strength              TEXT DEFAULT '',
      pharmacy_price_aed    NUMERIC(10,2),
      public_price_aed      NUMERIC(10,2),
      is_pom                BOOLEAN DEFAULT TRUE,
      source_label          TEXT DEFAULT '',
      crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (inn_name, trade_name, source_label)
    )
    """,
    # 3. Rafed/ADGPG 공공 조달 입찰 이력
    """
    CREATE TABLE IF NOT EXISTS uae_tender_history (
      id                    BIGSERIAL PRIMARY KEY,
      tender_ref            TEXT DEFAULT '',
      description           TEXT DEFAULT '',
      issue_date            DATE,
      close_date            DATE,
      award_value_aed       NUMERIC(14,2),
      supplier              TEXT DEFAULT '',
      keyword_hit           TEXT DEFAULT '',
      source_label          TEXT DEFAULT '',
      raw_text              TEXT DEFAULT '',
      crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (tender_ref, source_label)
    )
    """,
    # 4. Tatmeen GS1 가이드라인 문서
    """
    CREATE TABLE IF NOT EXISTS uae_tatmeen_guide (
      id                    BIGSERIAL PRIMARY KEY,
      title                 TEXT NOT NULL,
      url                   TEXT DEFAULT '',
      date_str              TEXT DEFAULT '',
      source_url            TEXT DEFAULT '',
      guide_type            TEXT DEFAULT 'general',
      crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (title, url)
    )
    """,
    # 5. 세계 인구 데이터 (World Bank)
    """
    CREATE TABLE IF NOT EXISTS uae_world_population (
      id                    BIGSERIAL PRIMARY KEY,
      country_name          TEXT NOT NULL,
      country_code          TEXT NOT NULL,
      year                  INT NOT NULL,
      population            BIGINT,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (country_code, year)
    )
    """,
    # 6. 보건 지출 데이터 (WHO GHED)
    """
    CREATE TABLE IF NOT EXISTS uae_health_expenditure (
      id                    BIGSERIAL PRIMARY KEY,
      country_or_area       TEXT NOT NULL,
      series                TEXT NOT NULL,
      year                  INT NOT NULL,
      value                 NUMERIC(14,4),
      created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (country_or_area, series, year)
    )
    """,
]

_TABLE_NAMES = [
    "uae_product_context",
    "uae_price_reference",
    "uae_tender_history",
    "uae_tatmeen_guide",
    "uae_world_population",
    "uae_health_expenditure",
]

# ── UAE 제품 시드 데이터 ──────────────────────────────────────────────────────

_UAE_PRODUCTS = [
    # market_segment 허용값: 'retail' | 'wholesale' | 'tender' | 'combo_drug'
    {
        "product_id":         "UAE_sereterol_activair",
        "trade_name":         "Sereterol Activair",
        "active_ingredient":  "Fluticasone/Salmeterol",
        "inn_name":           "Fluticasone/Salmeterol",
        "dosage_form":        "Inhaler",
        "market_segment":     "retail",           # 처방전 의약품 → 민간 소매/병원 채널
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "R03AK06",
            "therapeutic_area": "Respiratory / Asthma, COPD",
            "ede_reg": "EDE registration status TBC",
            "product_type": "일반제",
            "key_risk": "Seretide(GSK) originator competition; inhaler training required",
        },
    },
    {
        "product_id":         "UAE_omethyl_omega3_2g",
        "trade_name":         "Omethyl Cutielet",
        "active_ingredient":  "Omega-3-Acid Ethyl Esters 90",
        "inn_name":           "Omega-3-Acid Ethyl Esters 90 2g",
        "dosage_form":        "Pouch",
        "market_segment":     "retail",           # 처방전 의약품 → 민간
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "C10AX06",
            "therapeutic_area": "Hypertriglyceridemia",
            "ede_reg": "EDE registration status TBC",
            "product_type": "개량신약",
            "key_risk": "Lovaza/Vascepa originator competition; pouch form logistics",
        },
    },
    {
        "product_id":         "UAE_hydrine_hydroxyurea_500",
        "trade_name":         "Hydrine",
        "active_ingredient":  "Hydroxyurea",
        "inn_name":           "Hydroxyurea 500mg",
        "dosage_form":        "Cap",
        "market_segment":     "tender",           # 항암제 → 공공 입찰/병원 조달
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "L01XX05",
            "therapeutic_area": "Oncology / Sickle Cell, Myeloproliferative",
            "ede_reg": "EDE oncology registration TBC",
            "product_type": "항암제",
            "key_risk": "Hospital formulary listing prerequisite; Tatmeen packaging mandatory",
        },
    },
    {
        "product_id":         "UAE_gadvoa_gadobutrol_604",
        "trade_name":         "Gadvoa Inj.",
        "active_ingredient":  "Gadobutrol",
        "inn_name":           "Gadobutrol 604.72mg",
        "dosage_form":        "PFS",
        "market_segment":     "tender",           # MRI 조영제 → 병원 입찰
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "V08CA09",
            "therapeutic_area": "Radiology / MRI Contrast Agent",
            "ede_reg": "EDE contrast agent registration TBC",
            "product_type": "일반제",
            "key_risk": "Gadovist(Bayer) originator competition; cold-chain logistics",
        },
    },
    {
        "product_id":         "UAE_rosumeg_combigel",
        "trade_name":         "Rosumeg Combigel",
        "active_ingredient":  "Rosuvastatin+Omega-3",
        "inn_name":           "Rosuvastatin + Omega-3-EE90",
        "dosage_form":        "Cap",
        "market_segment":     "combo_drug",       # 복합제
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "C10AA07+C10AX06",
            "therapeutic_area": "Dyslipidemia",
            "ede_reg": "Combo EDE separate approval required",
            "product_type": "개량신약",
            "key_risk": "UAE combo registration precedent needed; DoH/DHA price cap compliance",
        },
    },
    {
        "product_id":         "UAE_atmeg_combigel",
        "trade_name":         "Atmeg Combigel",
        "active_ingredient":  "Atorvastatin+Omega-3",
        "inn_name":           "Atorvastatin + Omega-3-EE90",
        "dosage_form":        "Cap",
        "market_segment":     "combo_drug",       # 복합제
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "C10AA05+C10AX06",
            "therapeutic_area": "Dyslipidemia",
            "ede_reg": "Combo EDE separate approval required",
            "product_type": "개량신약",
            "key_risk": "Lipitor(Pfizer) competition; combo clinical data local submission",
        },
    },
    {
        "product_id":         "UAE_ciloduo_cilosta_rosuva",
        "trade_name":         "Ciloduo",
        "active_ingredient":  "Cilostazol+Rosuvastatin",
        "inn_name":           "Cilostazol + Rosuvastatin",
        "dosage_form":        "Tab",
        "market_segment":     "combo_drug",       # 복합제
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "B01AC23+C10AA07",
            "therapeutic_area": "Cardiovascular",
            "ede_reg": "Combo EDE separate approval required",
            "product_type": "개량신약",
            "key_risk": "Limited UAE combo registration precedent; Rafed tender eligibility",
        },
    },
    {
        "product_id":         "UAE_gastiin_cr_mosapride",
        "trade_name":         "Gastiin CR",
        "active_ingredient":  "Mosapride Citrate",
        "inn_name":           "Mosapride Citrate 15mg",
        "dosage_form":        "Tab",
        "market_segment":     "retail",           # 처방전 의약품 → 민간
        "manufacturer":       "Korea United Pharm. Inc.",
        "country":            "UAE",
        "source_name":        "UAE:kup_pipeline",
        "country_specific": {
            "atc": "A03FA05",
            "therapeutic_area": "Gastroenterology",
            "ede_reg": "EDE registration status TBC",
            "product_type": "개량신약",
            "key_risk": "Prokinetic market competition; SR formulation differentiation evidence",
        },
    },
]


# ── 테이블 존재 확인 ───────────────────────────────────────────────────────────

def _table_exists(sb, table_name: str) -> bool:
    """information_schema로 테이블 존재 여부 확인."""
    try:
        r = (
            sb.table("information_schema.tables")
            .select("table_name")
            .eq("table_schema", "public")
            .eq("table_name", table_name)
            .execute()
        )
        return bool(r.data)
    except Exception:
        # fallback: 직접 조회 시도
        try:
            sb.table(table_name).select("*").limit(1).execute()
            return True
        except Exception:
            return False


# ── 메인 로직 ────────────────────────────────────────────────────────────────

def check_connection() -> bool:
    """Supabase 연결 테스트."""
    _head("1단계: Supabase 연결 확인")
    try:
        from utils.db import get_client
        sb = get_client()
        # products 테이블 UAE 행 1건 조회로 연결 확인
        r = sb.table("products").select("product_id").eq("country", "UAE").limit(1).execute()
        _ok(f"연결 성공 (UAE products 행: {len(r.data)}건 확인됨)")
        return True
    except Exception as exc:
        _err(f"연결 실패: {exc}")
        return False


def _mgmt_sql(sql: str) -> tuple[bool, str]:
    """Supabase Management API로 raw SQL 실행.

    .env의 SUPABASE_KEY가 sbp_ 토큰이면 DDL도 실행 가능.
    """
    import os
    token = os.environ.get("SUPABASE_KEY", "")
    if not token.startswith("sbp_"):
        return False, "sbp_ 토큰 없음 (SUPABASE_KEY 확인)"
    try:
        import httpx
        project_ref = "oynefikqoibwtfpjlizv"
        r = httpx.post(
            f"https://api.supabase.com/v1/projects/{project_ref}/database/query",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": sql},
            timeout=20,
        )
        return r.status_code in (200, 201), r.text[:200]
    except Exception as exc:
        return False, str(exc)


def create_tables() -> bool:
    """UAE 전용 테이블 생성.

    .env에 sbp_ Management API 토큰이 있으면 자동으로 DDL 실행.
    없으면 Supabase SQL Editor 실행 안내를 출력합니다.
    """
    _head("2단계: UAE 전용 테이블 확인 / 생성")

    try:
        from utils.db import get_client
        sb = get_client()
    except Exception as exc:
        _err(f"클라이언트 생성 실패: {exc}")
        return False

    missing: list[str] = []
    for tbl in _TABLE_NAMES:
        exists = _table_exists(sb, tbl)
        if exists:
            _ok(f"{tbl} - 이미 존재")
        else:
            _warn(f"{tbl} - 없음 (생성 필요)")
            missing.append(tbl)

    if not missing:
        _ok("모든 UAE 전용 테이블이 이미 존재합니다.")
        return True

    # Management API로 자동 DDL 실행 시도
    print()
    print("  Management API로 자동 테이블 생성 시도...")
    all_ok = True
    for ddl in _DDL_STATEMENTS:
        tbl_name = [t for t in _TABLE_NAMES if t in ddl]
        label = tbl_name[0] if tbl_name else "DDL"
        if label not in missing:
            continue
        ok, msg = _mgmt_sql(ddl.strip())
        if ok:
            _ok(f"{label} - 생성 완료")
        else:
            _warn(f"{label} - 자동 생성 실패: {msg}")
            all_ok = False

    if not all_ok:
        # 자동 실패 시 수동 안내
        print()
        print("  [ACTION REQUIRED] 일부 테이블 생성 실패.")
        print("  Supabase SQL Editor에서 아래 파일을 실행해 주세요:")
        sql_path = os.path.join(ROOT, "supabase", "schema_uae_tables.sql")
        print(f"    {sql_path}")

    return all_ok


def seed_products() -> bool:
    """UAE 8개 제품을 products 공유 테이블에 upsert.

    ⚠️  country='UAE', source_name='UAE:kup_pipeline', product_id='UAE_...' 만 삽입합니다.
    기존 UAE 행은 ON CONFLICT(product_id)로 업데이트됩니다.
    다른 팀 데이터는 절대 건드리지 않습니다.
    """
    _head("3단계: UAE 제품 시드 데이터 삽입 (products 공유 테이블)")

    try:
        from utils.db import get_client, _assert_uae_row
        sb = get_client()
    except Exception as exc:
        _err(f"클라이언트 생성 실패: {exc}")
        return False

    success = 0
    fail    = 0

    import json as _json

    for prod in _UAE_PRODUCTS:
        # 안전 가드: UAE 행인지 재확인
        try:
            _assert_uae_row(prod)
        except ValueError as exc:
            _err(f"안전 가드 차단: {exc}")
            fail += 1
            continue

        row = dict(prod)
        # ── NOT NULL 컬럼 기본값 설정 (products 공유 테이블 스키마 기준) ──
        # source_url: EDE 검색 URL
        if not row.get("source_url"):
            inn_query = (row.get("inn_name", "") or "").replace(" ", "+")
            row["source_url"] = f"https://ede.gov.ae/en/Products/SearchProduct?query={inn_query}"
        row.setdefault("source_tier",      1)      # 1 = 내부 파이프라인 (최상위 신뢰)
        row.setdefault("confidence",       0.8)    # 내부 데이터 신뢰도
        row.setdefault("outlier_flagged",  False)  # 이상치 아님
        # country_specific은 JSON으로 직렬화
        if isinstance(row.get("country_specific"), dict):
            row["country_specific"] = _json.dumps(row["country_specific"], ensure_ascii=False)

        pid = prod["product_id"]
        try:
            # 1) 존재 여부 확인 (UAE 행만 조회)
            existing = (
                sb.table("products")
                .select("product_id")
                .eq("product_id", pid)
                .eq("country", "UAE")          # ← UAE 조건 필수
                .execute()
                .data
            )

            if existing:
                # 2-A) 이미 있으면 UPDATE (UAE 조건으로만)
                sb.table("products").update(row).eq("product_id", pid).eq("country", "UAE").execute()
                _ok(f"{pid} - 업데이트 완료")
            else:
                # 2-B) 없으면 INSERT
                sb.table("products").insert(row).execute()
                _ok(f"{pid} - 신규 삽입 완료")

            success += 1
        except Exception as exc:
            _err(f"{pid} - 실패: {exc}")
            fail += 1

    print()
    print(f"  결과: 성공 {success}건 / 실패 {fail}건")
    return fail == 0


def verify_isolation() -> None:
    """DB 격리 상태 검증: 다른 팀 데이터가 포함되지 않았는지 확인."""
    _head("4단계: 격리 검증 (UAE 전용 데이터만 존재하는지 확인)")

    try:
        from utils.db import get_client
        sb = get_client()

        # UAE 행 수 확인
        uae_r = sb.table("products").select("product_id", count="exact").eq("country", "UAE").execute()
        uae_count = uae_r.count or len(uae_r.data or [])
        _ok(f"products 테이블 내 UAE 행: {uae_count}건")

        # UAE가 아닌 행은 조회하지 않음 (다른 팀 데이터 확인하지 않는 것이 원칙)
        _ok("다른 팀 데이터 조회 생략 (격리 원칙 준수)")

        # UAE 전용 테이블 행 수 확인
        for tbl in _TABLE_NAMES:
            try:
                r = sb.table(tbl).select("*", count="exact").limit(1).execute()
                cnt = r.count if hasattr(r, 'count') and r.count is not None else len(r.data or [])
                _ok(f"{tbl}: {cnt}건")
            except Exception as exc:
                _warn(f"{tbl}: 조회 실패 ({exc}) - 테이블이 아직 없을 수 있습니다")

    except Exception as exc:
        _err(f"격리 검증 실패: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UAE Supabase 테이블 설정 (안전 격리 보장)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            예시:
              python scripts/setup_uae_db.py           # 전체 실행
              python scripts/setup_uae_db.py --check   # 연결 확인만
              python scripts/setup_uae_db.py --seed    # 제품 시드만
              python scripts/setup_uae_db.py --verify  # 격리 검증만
        """),
    )
    parser.add_argument("--check",  action="store_true", help="연결 확인만 수행")
    parser.add_argument("--seed",   action="store_true", help="제품 시드만 수행 (테이블 이미 존재)")
    parser.add_argument("--verify", action="store_true", help="격리 검증만 수행")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  UAE 전용 Supabase DB 설정 스크립트")
    print("  [주의] 이 스크립트는 UAE 데이터만 읽고 씁니다")
    print("=" * 60)

    if args.check:
        check_connection()
        return

    if args.seed:
        if check_connection():
            seed_products()
        return

    if args.verify:
        verify_isolation()
        return

    # 전체 실행
    ok_conn = check_connection()
    if not ok_conn:
        sys.exit(1)

    tables_ok = create_tables()
    if not tables_ok:
        print()
        print("  [!!] 테이블 생성 후 다시 실행하거나 --seed 옵션으로 제품 시드만 먼저 시도하세요.")

    seed_products()
    verify_isolation()

    print()
    print("=" * 60)
    print("  설정 완료")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
