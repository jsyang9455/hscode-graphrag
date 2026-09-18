"""Seed product cases per office (legacy-style e-commerce samples)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import ProductCase

SEED_CASES = [
    {"external_id": "KCS-001", "description": "히알루론산 수분 크림 스킨케어 50ml", "material": "cream", "function": "skin care", "origin_country": "KR", "ground_truth_hs": "3304.99.1000", "difficulty": "normal"},
    {"external_id": "KCS-002", "description": "비타민C 건강식품 구미 보충제", "material": "gummy", "function": "nutrition", "origin_country": "US", "ground_truth_hs": "2106.90.9099", "difficulty": "normal"},
    {"external_id": "KCS-003", "description": "5G 스마트폰 휴대폰 OLED", "material": "electronics", "function": "communication", "origin_country": "CN", "ground_truth_hs": "8517.13.0000", "difficulty": "normal"},
    {"external_id": "KCS-004", "description": "면 티셔츠 니트 의류", "material": "cotton", "function": "clothing", "origin_country": "VN", "ground_truth_hs": "6109.10.0000", "difficulty": "normal"},
    {"external_id": "KCS-005", "description": "플라스틱 포장용 병", "material": "PET", "function": "packaging", "origin_country": "CN", "ground_truth_hs": "3923.30.0000", "difficulty": "normal"},
    {"external_id": "KCS-006", "description": "의료용 디지털 체온계 기기", "material": "sensor", "function": "medical", "origin_country": "JP", "ground_truth_hs": "9018.90.9000", "difficulty": "hard"},
    {"external_id": "KCS-007", "description": "K뷰티 세럼 화장품 스킨케어 세트", "material": "serum", "function": "beauty", "origin_country": "KR", "ground_truth_hs": "3304.99.1000", "difficulty": "hard"},
    {"external_id": "KCS-008", "description": "파운데이션 메이크업 화장품", "material": "foundation", "function": "make-up", "origin_country": "KR", "ground_truth_hs": "3304.99.9000", "difficulty": "normal"},
]


def seed_cases_for_office(db: Session, office_id: int) -> int:
    added = 0
    for item in SEED_CASES:
        exists = (
            db.query(ProductCase)
            .filter(ProductCase.office_id == office_id, ProductCase.external_id == item["external_id"])
            .first()
        )
        if exists:
            continue
        db.add(ProductCase(office_id=office_id, **item))
        added += 1
    db.commit()
    return added


def seed_cases(db: Session) -> int:
    """Backward-compatible: seed into office_id=1 if exists else create demo office."""
    from backend.app.db.models import Office

    office = db.query(Office).filter(Office.code == "DEMO").first()
    if not office:
        office = Office(code="DEMO", name="데모 관세사무소")
        db.add(office)
        db.commit()
        db.refresh(office)
    return seed_cases_for_office(db, office.id)
