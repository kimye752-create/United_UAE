"""UAE(아랍에미리트) 1공정 수출 적합성 분석 엔진.

LLM 우선순위:
  1. Claude API (기본: claude-haiku-4-5-20251001) — 1차 분석·판단·근거 생성 (Primary)
  2. Perplexity API (sonar-pro)    — Claude 조건부 판정 시에만 보조 검색 후 재분석
  3. 정적 폴백                     — API 미설정 시

흐름:
  Claude 1차 분석 → verdict_confidence 낮으면 → Perplexity 보조 검색
  → Claude 2차 분석 (보강된 컨텍스트) → 최종 결과

출력 스키마 (품목별):
  product_id, trade_name, verdict(적합/부적합/조건부),
  rationale, key_factors, sources, analyzed_at

환경변수:
  CLAUDE_API_KEY 또는 ANTHROPIC_API_KEY
  CLAUDE_ANALYSIS_MODEL (선택, 기본 claude-haiku-4-5-20251001)
  PERPLEXITY_API_KEY  (선택)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass


# ── PRODUCT_META: UAE 8개 품목 ────────────────────────────────────────────────

_meta_cache: list[dict[str, Any]] | None = None

_FALLBACK_PRODUCT_META: list[dict[str, str]] = [
    {
        "product_id": "UAE_sereterol_activair",
        "trade_name": "Sereterol Activair",
        "inn": "Fluticasone / Salmeterol",
        "dosage_form": "Inhaler",
        "market_segment": "처방전 의약품",
        "product_type": "일반제",
        "atc": "R03AK06",
        "therapeutic_area": "호흡기계 / 천식·COPD",
        "ede_reg": "EDE 등재 여부 확인 필요",
        "key_risk": "Seretide(GSK) 등 다국적 오리지널과의 직접 경쟁, 흡입제 조작 교육 필요",
    },
    {
        "product_id": "UAE_omethyl_omega3_2g",
        "trade_name": "Omethyl Cutielet",
        "inn": "Omega-3-Acid Ethyl Esters 90 2g",
        "dosage_form": "Pouch",
        "market_segment": "처방전 의약품",
        "product_type": "개량신약",
        "atc": "C10AX06",
        "therapeutic_area": "고중성지방혈증",
        "ede_reg": "EDE 등재 여부 확인 필요",
        "key_risk": "Lovaza/Vascepa 등 오리지널 경쟁, 파우치 제형 현지 유통 관리",
    },
    {
        "product_id": "UAE_hydrine_hydroxyurea_500",
        "trade_name": "Hydrine",
        "inn": "Hydroxyurea 500mg",
        "dosage_form": "Cap",
        "market_segment": "항암제",
        "product_type": "항암제",
        "atc": "L01XX05",
        "therapeutic_area": "혈액종양학 / 겸상적혈구·골수증식질환",
        "ede_reg": "EDE 항암제 등재 여부 확인 필요",
        "key_risk": "SKMC·Cleveland Clinic Abu Dhabi 등 공공병원 Formulary 등재 선결, Tatmeen 패키징 의무",
    },
    {
        "product_id": "UAE_gadvoa_gadobutrol_604",
        "trade_name": "Gadvoa Inj.",
        "inn": "Gadobutrol 604.72mg",
        "dosage_form": "PFS",
        "market_segment": "처방전 의약품",
        "product_type": "일반제",
        "atc": "V08CA09",
        "therapeutic_area": "방사선과 / MRI 조영제",
        "ede_reg": "EDE 조영제 등재 여부 확인 필요",
        "key_risk": "Gadovist(Bayer) 오리지널 대비 가격 경쟁, 냉장 물류 공급망 요건",
    },
    {
        "product_id": "UAE_rosumeg_combigel",
        "trade_name": "Rosumeg Combigel",
        "inn": "Rosuvastatin + Omega-3-EE90",
        "dosage_form": "Cap",
        "market_segment": "처방전 의약품",
        "product_type": "개량신약",
        "atc": "C10AA07 + C10AX06",
        "therapeutic_area": "이상지질혈증",
        "ede_reg": "복합제 EDE 별도 허가 필요",
        "key_risk": "복합제 UAE 등록 전례 분석 필요, DoH/DHA 가격 상한 준수",
    },
    {
        "product_id": "UAE_atmeg_combigel",
        "trade_name": "Atmeg Combigel",
        "inn": "Atorvastatin + Omega-3-EE90",
        "dosage_form": "Cap",
        "market_segment": "처방전 의약품",
        "product_type": "개량신약",
        "atc": "C10AA05 + C10AX06",
        "therapeutic_area": "이상지질혈증",
        "ede_reg": "복합제 EDE 별도 허가 필요",
        "key_risk": "Lipitor(Pfizer) 경쟁, 복합제 임상 데이터 현지 제출 요건",
    },
    {
        "product_id": "UAE_ciloduo_cilosta_rosuva",
        "trade_name": "Ciloduo",
        "inn": "Cilostazol + Rosuvastatin",
        "dosage_form": "Tab",
        "market_segment": "처방전 의약품",
        "product_type": "개량신약",
        "atc": "B01AC23 + C10AA07",
        "therapeutic_area": "심혈관계",
        "ede_reg": "복합제 EDE 별도 허가 필요",
        "key_risk": "복합제 현지 등록 전례 부족, Rafed 공공조달 입찰 참여 요건",
    },
    {
        "product_id": "UAE_gastiin_cr_mosapride",
        "trade_name": "Gastiin CR",
        "inn": "Mosapride Citrate 15mg",
        "dosage_form": "Tab",
        "market_segment": "처방전 의약품",
        "product_type": "개량신약",
        "atc": "A03FA05",
        "therapeutic_area": "소화기계",
        "ede_reg": "EDE 등재 여부 확인 필요",
        "key_risk": "위장관 운동 촉진제 시장 경쟁, SR(서방형) 제형 차별화 근거 제출",
    },
]


def _merge_with_fallback_meta(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pid: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = str(row.get("product_id", "") or "").strip()
        if pid:
            by_pid[pid] = row

    for fallback in _FALLBACK_PRODUCT_META:
        pid = fallback["product_id"]
        if pid in by_pid:
            current = by_pid[pid]
            for key, value in fallback.items():
                if key == "product_id":
                    continue
                if not str(current.get(key, "") or "").strip():
                    current[key] = value
            current.setdefault("atc", "")
            current.setdefault("therapeutic_area", "")
            current.setdefault("ede_reg", "")
            current.setdefault("key_risk", "")
            current.setdefault("manufacturer", "Korea United Pharm. Inc.")
            continue

        by_pid[pid] = {
            "product_id": pid,
            "trade_name": fallback["trade_name"],
            "inn": fallback["inn"],
            "atc": fallback.get("atc", ""),
            "dosage_form": fallback["dosage_form"],
            "market_segment": fallback["market_segment"],
            "therapeutic_area": fallback.get("therapeutic_area", ""),
            "ede_reg": fallback.get("ede_reg", ""),
            "key_risk": fallback.get("key_risk", ""),
            "product_type": fallback["product_type"],
            "manufacturer": "Korea United Pharm. Inc.",
        }
    return list(by_pid.values())


def _load_product_meta() -> list[dict[str, Any]]:
    from utils.db import get_client
    sb = get_client()
    try:
        rows = (
            sb.table("products")
            .select("product_id,trade_name,active_ingredient,inn_name,strength,"
                    "dosage_form,market_segment,registration_number,"
                    "manufacturer,country_specific")
            .eq("country", "UAE")
            .eq("source_name", "UAE:kup_pipeline")
            .is_("deleted_at", "null")
            .execute()
            .data or []
        )
    except Exception:
        rows = []

    result = []
    for r in rows:
        cs = r.get("country_specific") or {}
        result.append({
            "product_id":       r.get("product_id", ""),
            "trade_name":       r.get("trade_name", ""),
            "inn":              r.get("inn_name") or r.get("active_ingredient", ""),
            "atc":              cs.get("atc", ""),
            "dosage_form":      r.get("dosage_form", ""),
            "market_segment":   r.get("market_segment", ""),
            "therapeutic_area": cs.get("therapeutic_area", ""),
            "ede_reg":          cs.get("ede_reg", ""),
            "key_risk":         cs.get("key_risk", ""),
            "product_type":     cs.get("product_type", "일반제"),
            "manufacturer":     r.get("manufacturer", "Korea United Pharm. Inc."),
        })
    return _merge_with_fallback_meta(result)


def _get_product_meta() -> list[dict[str, Any]]:
    global _meta_cache
    if _meta_cache is None:
        _meta_cache = _load_product_meta()
    return _meta_cache


def _get_meta_by_pid() -> dict[str, dict[str, Any]]:
    return {m["product_id"]: m for m in _get_product_meta()}


# ── 유틸리티 ──────────────────────────────────────────────────────────────────

def _extract_assistant_text(message: object) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", None) or ():
        if getattr(block, "type", None) == "text":
            t = getattr(block, "text", "") or ""
            if t:
                parts.append(t)
    return "\n".join(parts).strip()


def _read_env_secret(*names: str) -> str | None:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and (s := str(raw).strip()):
            return s
    return None


def _claude_analysis_model_id() -> str:
    raw = os.environ.get("CLAUDE_ANALYSIS_MODEL", "")
    s = str(raw).strip()
    return s if s else "claude-haiku-4-5-20251001"


def _parse_claude_analysis_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    candidates: list[str] = [text]
    if "```" in text:
        for seg in text.split("```"):
            s = seg.strip()
            if s.lower().startswith("json"):
                s = s[4:].lstrip()
            if s.startswith("{"):
                candidates.append(s)

    for cand in candidates:
        start = 0
        while True:
            j = cand.find("{", start)
            if j < 0:
                break
            try:
                obj, _end = decoder.raw_decode(cand, j)
            except json.JSONDecodeError:
                start = j + 1
                continue
            coerced = _coerce_analysis_dict(obj)
            if coerced is not None:
                return coerced
            start = j + 1
    return None


def _coerce_analysis_dict(obj: object) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    out: dict[str, Any] = dict(obj)
    if "verdict" not in out:
        for k, v in list(out.items()):
            if isinstance(k, str) and k.lower() == "verdict":
                out["verdict"] = v
                break
    return out if "verdict" in out else None


# ── Perplexity 보조 검색 ──────────────────────────────────────────────────────

async def _perplexity_search(query: str, api_key: str) -> str | None:
    try:
        import httpx
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a UAE pharmaceutical regulatory expert. "
                        "Provide factual, concise information about drug regulatory status "
                        "in the UAE (Emirates Drug Establishment, MOHAP, DoH Abu Dhabi, DHA Dubai). "
                        "Always cite sources when available."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "max_tokens": 600,
            "return_citations": True,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


# ── UAE 전용 Claude 분석 프롬프트 ─────────────────────────────────────────────

def _build_uae_analysis_prompt(
    meta: dict[str, Any],
    db_row: dict[str, Any] | None,
    perplexity_context: str | None,
    doh_price_context: str | None = None,
    static_context_text: str | None = None,
) -> str:
    reg_context = perplexity_context or "미수행"
    product_type = meta.get("product_type", "일반제")
    db_facts = _build_db_facts(db_row)

    doh_section = ""
    if doh_price_context:
        doh_section = f"\n## DoH/DHA 참조 가격 데이터\n{doh_price_context}\n"

    static_section = ""
    if static_context_text:
        static_section = f"\n## 시장 조사 데이터 (EDE + 브로슈어)\n{static_context_text}\n"

    return f"""당신은 UAE(아랍에미리트) 의약품 수출 가능성을 분석하는 전문 컨설턴트입니다.
아래 품목에 대해 UAE 1공정(규제 적합성·시장 진입 가능성) 관점에서 수출 적합성을 판단하세요.

사실 우선순위:
1) EDE(에미리트 의약품청), MOHAP, DoH(아부다비 보건부), DHA(두바이 보건국) 공식 자료
2) DoH/DHA 참조 가격 리스트 데이터(있을 때)
3) Perplexity 실시간 컨텍스트(있을 때만 보강)
4) 일반 추론

근거가 불충분하면 단정하지 말고 조건부/리스크로 명시하세요.

## 품목 정보
- 브랜드명: {meta['trade_name']}
- INN(성분): {meta['inn']}
- ATC 코드: {meta.get('atc', '미확인')}
- 제형: {meta['dosage_form']}
- 제품 유형: {product_type}
- 시장 세그먼트: {meta['market_segment']}
- 치료 영역: {meta.get('therapeutic_area', '미지정')}
- EDE 등재 상태: {meta.get('ede_reg', '미확인')}
- 주요 리스크: {meta.get('key_risk', '미확인')}

## 내부 저장 데이터
{db_facts}
{doh_section}{static_section}
## 실시간 규제·시장 정보 (Perplexity)
{reg_context}

## 분석 과제
1. EDE(에미리트 의약품청) 등재 상태 및 진입 경로 (신규 eCTD Full / 동등성 Abridged / 복합제 별도 등록)
2. Tatmeen GS1 DataMatrix 2차 포장 바코드 의무 — GTIN·일련번호·배치번호·유통기한 4요소 충족 여부
3. Rafed/ADGPG 공공 조달 입찰 주기 기반 SEHA 병원 공급 가능성 및 ICV(국내 가치) 점수 파트너 필요 여부
4. DoH(아부다비)/DHA(두바이) 참조 가격 기반 경쟁 약물 가격 포지셔닝 (AED 단위)
5. MOHAP 통제 의약품 스케줄 해당 여부 — 연방 법령 30호(2021) 기준
6. 최종 판정: 적합(EDE 등재·채널 확보) / 조건부(등록 선결 후 가능) / 부적합

▶ 출력 형식 규칙 (반드시 준수):
- basis_market_medical, basis_regulatory, basis_trade, risks_conditions, price_positioning 필드는
  반드시 자연스러운 산문(연속 문장)으로 작성하세요.
- 줄바꿈(\\n), 불릿 기호(-, •, *), 번호 목록, 소제목을 절대 사용하지 마세요.
- 각 필드는 2~3개의 연속된 문장으로만 구성하세요.
- 제조사명을 본문에 언급하지 마세요.
- 두괄식 판정 근거에는 반드시 기관+자료명을 명시하세요 (예: "EDE 의약품 디렉토리 기준…", "DoH 참조 가격 리스트에 따르면…").
- 가격은 반드시 AED(디르함) 단위로 표기하세요.

문장 톤 규칙:
- "불가능", "확인 불가", "제공되지 않아" 같은 단정적 결핍 표현 금지.
- 대신 "현재 확보된 데이터 기준", "추가 확인 필요" 등 실행 가능한 제안형 표현 사용.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "verdict": "적합" | "부적합" | "조건부",
  "verdict_en": "SUITABLE" | "UNSUITABLE" | "CONDITIONAL",
  "rationale": "<한 문단 요약. UAE 시장 맥락 포함. 최대 320자>",
  "basis_market_medical": "<시장/의료 근거 2~3문장. UAE 의료 인프라·만성질환 유병률 언급>",
  "basis_regulatory": "<EDE/MOHAP/DoH/DHA 규제 근거 2~3문장. eCTD 경로·Tatmeen 준수 포함>",
  "basis_trade": "<무역/유통 근거 2~3문장. Rafed 조달·AED 가격·ICV 파트너 언급>",
  "key_factors": ["<요인1>", "<요인2>", "<요인3>"],
  "entry_pathway": "<권장 진입 경로: EDE eCTD Full / Abridged / 복합제 별도 / Rafed 조달 입찰>",
  "price_positioning": "<가격 포지셔닝 2~3문장. DoH/DHA 참조 가격 또는 경쟁품 AED 가격 언급>",
  "tatmeen_note": "<Tatmeen GS1 DataMatrix 준수 요건 1~2문장>",
  "risks_conditions": "<진입 시 리스크/조건 2~3문장>",
  "sources": [
    {{"name": "<출처명>", "url": "<URL 또는 '내부 데이터'>"}}
  ],
  "confidence_note": "<판단 근거의 신뢰도 설명>"
}}"""


def _build_db_facts(db_row: dict[str, Any] | None) -> str:
    if not db_row:
        return "- DB 행 없음"
    facts: list[str] = []
    for key in (
        "product_key",
        "trade_name",
        "market_segment",
        "regulatory_id",
        "source_name",
        "source_url",
        "confidence",
    ):
        val = db_row.get(key)
        if val not in (None, ""):
            facts.append(f"- {key}: {val}")
    raw = db_row.get("raw_payload")
    if isinstance(raw, dict):
        for rk in (
            "uae_source_type",
            "uae_ede_registered",
            "uae_rafed_tender",
            "uae_doh_price_aed",
            "uae_tatmeen_compliant",
        ):
            if rk in raw and raw.get(rk) not in (None, "", []):
                facts.append(f"- raw_payload.{rk}: {raw.get(rk)}")
    if not facts:
        return "- DB 주요 필드 없음"
    return "\n".join(facts[:20])


# ── 후처리 ────────────────────────────────────────────────────────────────────

def _soften_limit_phrase(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    repl = [
        ("제공되지 않아", "현재 확보된 범위에서"),
        ("확인이 불가능", "현 시점에서는 추가 확인이 필요"),
        ("확인 불가", "추가 확인 필요"),
        ("불가능합니다", "제한적입니다"),
        ("불가능", "제한적"),
        ("없어", "제한적이어서"),
        ("없습니다.", "제한적입니다."),
    ]
    out = s
    for a, b in repl:
        out = out.replace(a, b)
    return out


def _soften_analysis_language(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    for k in (
        "rationale",
        "basis_market_medical",
        "basis_regulatory",
        "basis_trade",
        "entry_pathway",
        "price_positioning",
        "tatmeen_note",
        "risks_conditions",
        "confidence_note",
    ):
        if k in out and isinstance(out.get(k), str):
            out[k] = _soften_limit_phrase(out[k])
    if isinstance(out.get("key_factors"), list):
        out["key_factors"] = [_soften_limit_phrase(str(x)) for x in out["key_factors"]]
    return out


def _normalize_sources(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    src_raw = out.get("sources")
    if not isinstance(src_raw, list):
        out["sources"] = []
        return out

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for s in src_raw:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "") or "").strip()
        url = str(s.get("url", "") or "").strip()
        if name and "supabase" in name.lower():
            continue
        if not name and url:
            if "ede.gov.ae" in url:
                name = "Emirates Drug Establishment (EDE)"
            elif "mohap.gov.ae" in url:
                name = "MOHAP UAE"
            elif "doh.gov.ae" in url:
                name = "DoH Abu Dhabi"
            elif "dha.gov.ae" in url:
                name = "DHA Dubai"
            elif "tatmeen.ae" in url:
                name = "Tatmeen"
            elif "rafeduae.ae" in url:
                name = "Rafed UAE"
            else:
                name = "공개 출처"
        if not name:
            continue
        key = (name.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"name": name, "url": url})
    out["sources"] = normalized
    return out


# ── DoH 참조 가격 컨텍스트 빌더 ───────────────────────────────────────────────

async def _fetch_doh_price_context(inn: str) -> str | None:
    """DoH 가격 크롤러에서 INN 기반 참조 가격 텍스트 생성."""
    try:
        from utils.uae_doh_crawler import get_price_context_for_inn
        return await get_price_context_for_inn(inn)
    except Exception:
        return None


# ── Claude 분석 (Primary) ────────────────────────────────────────────────────

async def _claude_analyze(
    meta: dict[str, Any],
    db_row: dict[str, Any] | None,
    api_key: str,
    *,
    perplexity_context: str | None = None,
    doh_price_context: str | None = None,
    static_context_text: str | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        import anthropic
    except ImportError:
        return None, "anthropic 패키지 미설치"

    resolved_model = (model or "").strip() or _claude_analysis_model_id()
    prompt = _build_uae_analysis_prompt(
        meta, db_row, perplexity_context, doh_price_context, static_context_text
    )

    def _sync_call() -> tuple[dict[str, Any] | None, str | None]:
        try:
            client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
            response = client.messages.create(
                model=resolved_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _extract_assistant_text(response)
            if not raw:
                return None, "empty_model_text"
            parsed = _parse_claude_analysis_json(raw)
            if parsed is None:
                head = raw[:160].replace("\n", " ")
                return None, f"json_parse_failed(len={len(raw)} head={head!r})"
            return parsed, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"[:400]

    return await asyncio.wait_for(asyncio.to_thread(_sync_call), timeout=90.0)


# ── 단일 품목 분석 ─────────────────────────────────────────────────────────────

async def analyze_product(
    product_id: str,
    db_row: dict[str, Any] | None = None,
    *,
    use_perplexity: bool = True,
) -> dict[str, Any]:
    meta = _get_meta_by_pid().get(product_id)
    if meta is None:
        return {
            "product_id": product_id,
            "error": f"알 수 없는 product_id: {product_id}",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    claude_key = _read_env_secret("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")
    perplexity_key = _read_env_secret("PERPLEXITY_API_KEY") if use_perplexity else None
    claude_model_id = _claude_analysis_model_id()
    claude_error_detail: str | None = None

    # DoH 참조 가격 컨텍스트
    doh_price_context: str | None = None
    try:
        doh_price_context = await _fetch_doh_price_context(meta.get("inn", ""))
    except Exception:
        pass

    # 정적 컨텍스트 (EDE 브로슈어 등)
    static_context_text: str | None = None
    try:
        from utils.static_data import get_product_context, context_to_prompt_text
        ctx = get_product_context(product_id)
        if ctx:
            static_context_text = context_to_prompt_text(ctx)
    except Exception:
        pass

    result: dict[str, Any] | None = None
    analysis_model = "static_fallback"
    analysis_error: str | None = None

    # Step 1: Claude 1차 분석
    if claude_key:
        result, claude_error_detail = await _claude_analyze(
            meta, db_row, claude_key,
            perplexity_context=None,
            doh_price_context=doh_price_context,
            static_context_text=static_context_text,
            model=claude_model_id,
        )
        if result:
            analysis_model = claude_model_id

    # Step 2: 조건부 판정 시 Perplexity 보조 검색
    if (
        result is not None
        and perplexity_key
        and result.get("verdict") == "조건부"
        and claude_key
    ):
        query = (
            f"UAE EDE regulatory status and DoH/DHA formulary for "
            f"{meta['trade_name']} ({meta['inn']}). "
            f"Include EDE drug directory listing, Tatmeen compliance requirements, "
            f"and Rafed procurement history. Recent updates only."
        )
        perplexity_context = await _perplexity_search(query, perplexity_key)
        if perplexity_context:
            result2, err2 = await _claude_analyze(
                meta, db_row, claude_key,
                perplexity_context=perplexity_context,
                doh_price_context=doh_price_context,
                static_context_text=static_context_text,
                model=claude_model_id,
            )
            if result2:
                result = result2
                analysis_model = f"{claude_model_id}+perplexity"
            elif err2:
                claude_error_detail = err2

    # API 미설정 또는 분석 실패
    if result is None:
        no_api = not bool(claude_key)
        analysis_error = "no_api_key" if no_api else "claude_failed"
        result = {
            "verdict": None,
            "verdict_en": None,
            "rationale": (
                "Claude API 키 미설정 — CLAUDE_API_KEY 또는 ANTHROPIC_API_KEY "
                "환경변수를 설정하면 실제 분석이 실행됩니다."
                if no_api else
                "Claude API 분석 실패 — API 키를 확인하거나 잠시 후 다시 시도하세요."
            ),
            "basis_market_medical": "",
            "basis_regulatory": "",
            "basis_trade": "",
            "key_factors": [],
            "entry_pathway": "",
            "price_positioning": (
                doh_price_context or
                "DoH/DHA 참조 가격 데이터 미확보 — 추가 수집 후 정밀화 가능합니다."
            ),
            "tatmeen_note": (
                "Tatmeen GS1 DataMatrix(GTIN·일련번호·배치번호·유통기한) 2차 포장 의무 준수 필요."
            ),
            "risks_conditions": "",
            "sources": [],
            "confidence_note": "API 미설정" if no_api else "분석 실패",
        }

    result = _soften_analysis_language(result)
    result = _normalize_sources(result)

    return {
        "product_id": product_id,
        "trade_name": meta["trade_name"],
        "inn": meta["inn"],
        "market_segment": meta["market_segment"],
        "product_type": meta.get("product_type", ""),
        "ede_reg": meta.get("ede_reg", ""),
        "verdict": result.get("verdict"),
        "verdict_en": result.get("verdict_en"),
        "rationale": result.get("rationale", ""),
        "basis_market_medical": result.get("basis_market_medical", ""),
        "basis_regulatory": result.get("basis_regulatory", ""),
        "basis_trade": result.get("basis_trade", ""),
        "key_factors": result.get("key_factors", []),
        "entry_pathway": result.get("entry_pathway", ""),
        "price_positioning": result.get("price_positioning", ""),
        "tatmeen_note": result.get("tatmeen_note", ""),
        "risks_conditions": result.get("risks_conditions", ""),
        "section_source_map": {
            "제품 식별": "supabase.products (UAE:kup_pipeline)",
            "핵심 판정": (
                f"Claude Haiku ({claude_model_id})"
                if analysis_error is None else "fallback (API 미설정/실패)"
            ),
            "두괄식 근거 - 시장/의료": (
                "Claude Haiku + EDE/DoH/DHA 공개기관 컨텍스트"
                if analysis_error is None else "fallback"
            ),
            "두괄식 근거 - 규제": (
                "Claude Haiku + EDE/MOHAP 컨텍스트"
                if analysis_error is None else "fallback"
            ),
            "두괄식 근거 - 무역": (
                "Claude Haiku + Rafed/DoH 가격 컨텍스트"
                if analysis_error is None else "fallback"
            ),
        },
        "sources": result.get("sources", []),
        "confidence_note": result.get("confidence_note", ""),
        "analysis_model": analysis_model,
        "analysis_error": analysis_error,
        "claude_model_id": claude_model_id,
        "claude_error_detail": claude_error_detail if analysis_error == "claude_failed" else None,
        "doh_price_context": doh_price_context or "",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 커스텀 신약 분석 ──────────────────────────────────────────────────────────

async def analyze_custom_product(
    trade_name: str,
    inn: str,
    dosage_form: str = "",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "product_id":       "custom",
        "trade_name":       trade_name,
        "inn":              inn,
        "atc":              "",
        "dosage_form":      dosage_form,
        "market_segment":   "처방전 의약품",
        "therapeutic_area": "",
        "ede_reg":          "미등재(신약)",
        "key_risk":         "",
        "manufacturer":     "",
        "product_type":     "신약",
    }

    claude_key = _read_env_secret("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")
    claude_model_id = _claude_analysis_model_id()

    doh_price_context: str | None = None
    try:
        doh_price_context = await _fetch_doh_price_context(inn)
    except Exception:
        pass

    result: dict[str, Any] | None = None
    analysis_error: str | None = None

    if claude_key:
        result, analysis_error = await _claude_analyze(
            meta, None, claude_key,
            doh_price_context=doh_price_context,
            model=claude_model_id,
        )

    if result is not None:
        result = _soften_analysis_language(result)
        result = _normalize_sources(result)

    if result is None:
        result = {
            "verdict": None,
            "verdict_en": None,
            "rationale": "Claude API 키 미설정 또는 분석 실패." if not claude_key else f"분석 오류: {analysis_error}",
            "basis_market_medical": "",
            "basis_regulatory": "",
            "basis_trade": "",
            "key_factors": [],
            "entry_pathway": "",
            "price_positioning": doh_price_context or "",
            "tatmeen_note": "Tatmeen GS1 DataMatrix 2차 포장 의무 준수 필요.",
            "risks_conditions": "",
            "sources": [],
            "confidence_note": "미분석",
        }

    return {
        "product_id":           "custom",
        "trade_name":           trade_name,
        "inn":                  inn,
        "inn_label":            f"{inn} {dosage_form}".strip(),
        "market_segment":       "처방전 의약품",
        "product_type":         "신약",
        "ede_reg":              "미등재(신약)",
        "verdict":              result.get("verdict"),
        "verdict_en":           result.get("verdict_en"),
        "rationale":            result.get("rationale", ""),
        "basis_market_medical": result.get("basis_market_medical", ""),
        "basis_regulatory":     result.get("basis_regulatory", ""),
        "basis_trade":          result.get("basis_trade", ""),
        "key_factors":          result.get("key_factors", []),
        "entry_pathway":        result.get("entry_pathway", ""),
        "price_positioning":    result.get("price_positioning", ""),
        "tatmeen_note":         result.get("tatmeen_note", ""),
        "risks_conditions":     result.get("risks_conditions", ""),
        "sources":              result.get("sources", []),
        "confidence_note":      result.get("confidence_note", ""),
        "analysis_model":       claude_model_id if claude_key else "미설정",
        "analysis_error":       analysis_error,
        "doh_price_context":    doh_price_context or "",
        "analyzed_at":          datetime.now(timezone.utc).isoformat(),
    }


# ── 전체 8품목 배치 분석 ──────────────────────────────────────────────────────

async def analyze_all(
    *,
    use_perplexity: bool = True,
) -> list[dict[str, Any]]:
    from utils.db import fetch_kup_products
    kup_rows = fetch_kup_products("UAE")
    db_rows = {r["product_id"]: r for r in kup_rows}

    tasks = [
        analyze_product(
            meta["product_id"],
            db_rows.get(meta["product_id"]),
            use_perplexity=use_perplexity,
        )
        for meta in _get_product_meta()
        if meta["product_id"].startswith("UAE_")
    ]
    return list(await asyncio.gather(*tasks))
