-- =============================================================================
-- UAE 전용 보조 테이블 DDL
--
-- ⚠️  안전 규칙:
--   · 이 파일의 CREATE TABLE은 모두 uae_* 접두사 테이블만 생성합니다.
--   · products 공유 테이블에는 절대 손대지 않습니다.
--   · IF NOT EXISTS → 이미 있으면 무시 (다른 팀 테이블 영향 없음).
--
-- 실행 방법:
--   Supabase Dashboard → SQL Editor → 이 파일 내용 붙여넣기 → Run
--   (INSERT는 scripts/setup_uae_db.py 가 Python으로 처리하므로 여기서 실행 불필요)
--
-- 공통 테이블(products, sources 등)은 이미 생성된 상태로 가정합니다.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. UAE 품목별 분석 컨텍스트
-- ─────────────────────────────────────────────────────────────────────────────
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
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. DoH(아부다비) / DHA(두바이) 참조 가격 리스트
-- ─────────────────────────────────────────────────────────────────────────────
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
  source_label          TEXT DEFAULT '',        -- 'DoH Abu Dhabi' | 'DHA Dubai'
  crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (inn_name, trade_name, source_label)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Rafed / ADGPG 공공 조달 입찰 이력
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS uae_tender_history (
  id                    BIGSERIAL PRIMARY KEY,
  tender_ref            TEXT DEFAULT '',
  description           TEXT DEFAULT '',
  issue_date            DATE,
  close_date            DATE,
  award_value_aed       NUMERIC(14,2),
  supplier              TEXT DEFAULT '',
  keyword_hit           TEXT DEFAULT '',
  source_label          TEXT DEFAULT '',        -- 'Rafed (Playwright)' | 'Perplexity'
  raw_text              TEXT DEFAULT '',
  crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tender_ref, source_label)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Tatmeen GS1 가이드라인 문서
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS uae_tatmeen_guide (
  id                    BIGSERIAL PRIMARY KEY,
  title                 TEXT NOT NULL,
  url                   TEXT DEFAULT '',
  date_str              TEXT DEFAULT '',
  source_url            TEXT DEFAULT '',
  guide_type            TEXT DEFAULT 'general', -- 'technical_guideline' | 'pdf_document' | 'general_info'
  crawled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (title, url)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. 세계 인구 데이터 (World Bank)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS uae_world_population (
  id                    BIGSERIAL PRIMARY KEY,
  country_name          TEXT NOT NULL,
  country_code          TEXT NOT NULL,
  year                  INT NOT NULL,
  population            BIGINT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (country_code, year)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. 보건 지출 데이터 (WHO GHED)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS uae_health_expenditure (
  id                    BIGSERIAL PRIMARY KEY,
  country_or_area       TEXT NOT NULL,
  series                TEXT NOT NULL,
  year                  INT NOT NULL,
  value                 NUMERIC(14,4),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (country_or_area, series, year)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. RLS(행 수준 보안) 정책 — UAE 전용 테이블만
--    ⚠️  products 공유 테이블의 RLS는 건드리지 않습니다.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE uae_product_context   ENABLE ROW LEVEL SECURITY;
ALTER TABLE uae_price_reference   ENABLE ROW LEVEL SECURITY;
ALTER TABLE uae_tender_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE uae_tatmeen_guide     ENABLE ROW LEVEL SECURITY;

-- 서비스 롤 전체 접근 허용 (정책 이미 존재하면 무시)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'uae_product_context' AND policyname = 'service_role_all'
  ) THEN
    CREATE POLICY "service_role_all" ON uae_product_context FOR ALL USING (TRUE);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'uae_price_reference' AND policyname = 'service_role_all'
  ) THEN
    CREATE POLICY "service_role_all" ON uae_price_reference FOR ALL USING (TRUE);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'uae_tender_history' AND policyname = 'service_role_all'
  ) THEN
    CREATE POLICY "service_role_all" ON uae_tender_history FOR ALL USING (TRUE);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'uae_tatmeen_guide' AND policyname = 'service_role_all'
  ) THEN
    CREATE POLICY "service_role_all" ON uae_tatmeen_guide FOR ALL USING (TRUE);
  END IF;
END $$;

-- =============================================================================
-- ✅ DDL 실행 완료
-- 다음 단계: scripts/setup_uae_db.py 실행으로 제품 데이터 삽입
--   python scripts/setup_uae_db.py
-- =============================================================================
