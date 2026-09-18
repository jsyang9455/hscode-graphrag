"""Convert ghko99/Hscode DATA+HSK into TradeFlow KCS CSV schema.

Source: https://github.com/ghko99/Hscode
Outputs: data/kcs/ghko99_hscode_enriched.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "kcs" / "ghko99_hscode_enriched.csv"
REPO_URL = "https://github.com/ghko99/Hscode.git"

# Cap aliases so title index stays useful and CSV stays manageable.
MAX_ALIASES_PER_CODE = 12
MAX_COMBINED_CHARS = 1200


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _norm10(value: str) -> str | None:
    d = _digits(value)
    if len(d) < 6:
        return None
    return d.zfill(10)[:10]


def _clone_or_use(src: Path | None) -> Path:
    if src and src.exists():
        return src
    tmp = Path(tempfile.mkdtemp(prefix="Hscode_"))
    subprocess.check_call(["git", "clone", "--depth", "1", REPO_URL, str(tmp / "repo")])
    return tmp / "repo"


def _load_hscode_names(data_dir: Path) -> dict[str, tuple[str, str]]:
    """Return digit-key -> (ko, en) from hscode.pickle (JSON or pickle)."""
    path = data_dir / "hscode.pickle"
    if not path.exists():
        return {}
    raw = path.read_bytes()
    if raw[:1] == b"{":
        payload = json.loads(raw.decode("utf-8"))
    else:
        try:
            payload = pickle.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
    out: dict[str, tuple[str, str]] = {}
    for key, val in payload.items():
        d = _digits(str(key))
        if not d:
            continue
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            ko, en = str(val[0] or ""), str(val[1] or "")
        elif isinstance(val, dict):
            ko = str(val.get("korean") or val.get("ko") or "")
            en = str(val.get("english") or val.get("en") or "")
        else:
            continue
        # Keys in pickle are often without leading zero (9–10 digits).
        for k in {d, d.zfill(10)[:10], d.lstrip("0") or "0"}:
            out[k] = (ko, en)
    return out


def _load_data_aliases(data_dir: Path) -> dict[str, dict[str, list[str]]]:
    path = data_dir / "DATA.csv"
    agg: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"ko": [], "en": []})
    seen: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = _norm10(row.get("hscode") or row.get("\ufeffhscode") or "")
            if not code:
                continue
            for lang, col in (("en", "english"), ("ko", "korean")):
                text = (row.get(col) or "").strip()
                if not text:
                    continue
                key = f"{lang}:{text.lower()}"
                if key in seen[code]:
                    continue
                seen[code].add(key)
                if len(agg[code][lang]) < MAX_ALIASES_PER_CODE:
                    agg[code][lang].append(text)
    return agg


def _load_hsk_rows(data_dir: Path) -> list[dict[str, str]]:
    path = data_dir / "HSK.csv"
    with path.open(encoding="cp949", newline="") as f:
        return list(csv.DictReader(f))


def convert(data_dir: Path, out_path: Path = OUT_CSV) -> dict[str, int]:
    names = _load_hscode_names(data_dir)
    aliases = _load_data_aliases(data_dir)
    hsk_rows = _load_hsk_rows(data_dir)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "HS_KEY",
        "세번2단위품명",
        "세번4단위품명",
        "세번6단위품명",
        "세번10단위품명",
        "hs_한글품목명",
        "hs_영문품목명",
        "data_source",
        "final_combined_text",
    ]
    written = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        seen_codes: set[str] = set()

        for row in hsk_rows:
            code = _norm10(row.get("HS10단위부호") or "")
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            ch2 = (row.get("세번2단위품명") or "").strip()
            ch4 = (row.get("세번4단위품명") or "").strip()
            ch6 = (row.get("세번6단위품명") or "").strip()
            ch10 = (row.get("세번10단위품명") or "").strip()

            pick = names.get(code) or names.get(code.lstrip("0") or "0") or ("", "")
            title_ko = pick[0] or " · ".join(x for x in (ch4, ch6, ch10) if x) or ch2
            title_en = pick[1] or ""

            alias = aliases.get(code) or {"ko": [], "en": []}
            # Prefer official titles first; then case-study aliases.
            parts = [
                ch2,
                ch4,
                ch6,
                ch10,
                title_ko,
                title_en,
                *alias["ko"][:MAX_ALIASES_PER_CODE],
                *alias["en"][:MAX_ALIASES_PER_CODE],
            ]
            # Deduplicate while preserving order
            combined_parts: list[str] = []
            seen_p: set[str] = set()
            for p in parts:
                p = (p or "").strip()
                if not p:
                    continue
                key = p.lower()
                if key in seen_p:
                    continue
                seen_p.add(key)
                combined_parts.append(p)
            combined = " | ".join(combined_parts)[:MAX_COMBINED_CHARS]

            writer.writerow(
                {
                    "HS_KEY": code,
                    "세번2단위품명": ch2,
                    "세번4단위품명": ch4,
                    "세번6단위품명": ch6,
                    "세번10단위품명": ch10,
                    "hs_한글품목명": title_ko,
                    "hs_영문품목명": title_en,
                    "data_source": "ghko99_hscode",
                    "final_combined_text": combined,
                }
            )
            written += 1

        # DATA-only codes not present in HSK (rare)
        for code, alias in aliases.items():
            if code in seen_codes:
                continue
            title_ko = (alias["ko"][0] if alias["ko"] else "") or ""
            title_en = (alias["en"][0] if alias["en"] else "") or ""
            if not title_ko and not title_en:
                continue
            combined = " | ".join([*alias["ko"], *alias["en"]])[:MAX_COMBINED_CHARS]
            writer.writerow(
                {
                    "HS_KEY": code,
                    "세번2단위품명": "",
                    "세번4단위품명": "",
                    "세번6단위품명": "",
                    "세번10단위품명": "",
                    "hs_한글품목명": title_ko,
                    "hs_영문품목명": title_en,
                    "data_source": "ghko99_hscode_case",
                    "final_combined_text": combined,
                }
            )
            written += 1
            seen_codes.add(code)

    return {
        "rows_written": written,
        "hsk_rows": len(hsk_rows),
        "alias_codes": len(aliases),
        "name_keys": len(names),
        "out_path": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=None,
        help="Local clone of ghko99/Hscode (default: shallow clone to temp)",
    )
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    args = parser.parse_args()

    repo = _clone_or_use(args.src)
    data_dir = repo / "data" if (repo / "data").exists() else repo
    stats = convert(data_dir, args.out)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"clone failed: {e}", file=sys.stderr)
        sys.exit(1)
