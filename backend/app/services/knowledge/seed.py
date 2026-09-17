"""Seed KCS-10D style demo cases for empirical runs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import ProductCase

SEED_CASES = [
    {
        "external_id": "KCS-001",
        "description": "Hydrating facial cream with hyaluronic acid for skin care, 50ml jar",
        "material": "cream emulsion",
        "function": "skin care",
        "origin_country": "KR",
        "ground_truth_hs": "3304.99.1000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-002",
        "description": "Vitamin C dietary supplement gummies, food preparation",
        "material": "gelatin gummy",
        "function": "nutrition",
        "origin_country": "US",
        "ground_truth_hs": "2106.90.9099",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-003",
        "description": "5G smartphone mobile phone with OLED display",
        "material": "electronics",
        "function": "communication",
        "origin_country": "CN",
        "ground_truth_hs": "8517.13.0000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-004",
        "description": "Men cotton T-shirt knitted apparel",
        "material": "cotton",
        "function": "clothing",
        "origin_country": "VN",
        "ground_truth_hs": "6109.10.0000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-005",
        "description": "Empty plastic bottle for packaging conveyance of liquids",
        "material": "PET plastic",
        "function": "packaging",
        "origin_country": "CN",
        "ground_truth_hs": "3923.30.0000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-006",
        "description": "Digital medical thermometer instrument used in medical sciences",
        "material": "plastic+sensor",
        "function": "medical measurement",
        "origin_country": "JP",
        "ground_truth_hs": "9018.90.9000",
        "difficulty": "hard",
    },
    {
        "external_id": "KCS-007",
        "description": "K-beauty serum skincare cosmetic lotion essence kit set",
        "material": "serum",
        "function": "beauty skin care",
        "origin_country": "KR",
        "ground_truth_hs": "3304.99.1000",
        "difficulty": "hard",
    },
    {
        "external_id": "KCS-008",
        "description": "Beauty make-up preparation foundation cream cosmetic",
        "material": "foundation",
        "function": "make-up",
        "origin_country": "KR",
        "ground_truth_hs": "3304.99.9000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-009",
        "description": "Other food preparations protein powder supplement blend",
        "material": "powder",
        "function": "food supplement",
        "origin_country": "US",
        "ground_truth_hs": "2106.90.9099",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-010",
        "description": "Smartphone phone multi accessory kit set with plastic packaging bottle",
        "material": "mixed",
        "function": "mixed kit",
        "origin_country": "CN",
        "ground_truth_hs": "8517.13.0000",
        "difficulty": "hard",
    },
    {
        "external_id": "KCS-011",
        "description": "Night repair facial cream lotion for care of the skin",
        "material": "cream",
        "function": "skin care",
        "origin_country": "FR",
        "ground_truth_hs": "3304.99.1000",
        "difficulty": "normal",
    },
    {
        "external_id": "KCS-012",
        "description": "Knitted cotton apparel T-shirt singlets",
        "material": "cotton knit",
        "function": "clothing",
        "origin_country": "BD",
        "ground_truth_hs": "6109.10.0000",
        "difficulty": "normal",
    },
]


def seed_cases(db: Session) -> int:
    added = 0
    for item in SEED_CASES:
        exists = db.query(ProductCase).filter(ProductCase.external_id == item["external_id"]).first()
        if exists:
            continue
        db.add(ProductCase(**item))
        added += 1
    db.commit()
    return added
