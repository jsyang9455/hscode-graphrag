# Legacy Integration Plan — jsyang9455/hscode_prj → HSCode-GraphRAG

## Source assets reused

| Legacy (hscode_prj) | Target (region_gonggu) |
|---------------------|------------------------|
| `corrected_integrated_data_*.xlsx` (37,049 HSK) | `data/kcs/kcs_hsk_master.csv` → `hs_code_records` |
| Login / RegisterModal / AuthContext | Auth API + frontend login/signup (office=company) |
| HS recommend page (query/material/usage) | Classify + candidate list UI |
| User.company field | `Office` tenant isolation |
| Dashboard / report concepts | Metrics + opinion queue + empirical report |
| US tariff xlsx (optional later) | Tariff comparison hooks in opinion conditions |

## Target product flow

1. Signup with **관세사 사무실(회사)코드/이름** → dedicated Office tenant
2. Login (JWT) → all GraphRAG/K_history scoped by `office_id`
3. HS 분류: material/usage/query → system recommends HS + Opinion draft
4. 관세사 HITL: confirm/change HS + select conditions + detail opinion
5. Learning applicator updates office-scoped keyword weights + K_history + K_guard
6. Dashboard shows office metrics / pending opinions

## Data truthfulness

- **Before:** demo ~12 seed cases, ~25 fake KG nodes
- **After:** real KCS-integrated HSK master from prior project (`data_source=hsk_with_hs`) + WCO HS fallback

## Non-goals (this iteration)

- Full Spring Boot / ChromaDB / LangGraph stack port
- OCR / US converter microservices (keep as future adapters)
