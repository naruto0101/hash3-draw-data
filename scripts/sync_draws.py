#!/usr/bin/env python3
"""Fetch Hash3 results, verify available block-hash proofs, and publish deltas."""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "archive" / "history.csv"
MANIFEST = ROOT / "data" / "manifest.json"
UPDATES = ROOT / "data" / "updates"
PROOFS = ROOT / "data" / "proofs.jsonl"
MARKET = "NEWHASH3FC"
API_CODE = "trxbh3fc"
LATEST_URL = "https://qqtj666.com/api/trial/draw-result"
HISTORY_URL = "https://qqtj666.com/api/trial/draw-result-by-datetime"
CSV_FIELDS = ["market", "issue", "opendate", "w", "q", "b", "s", "g"]
PERIODS_PER_DAY = 480
USER_AGENT = "Hash3DrawDataRelay/1.0"


def request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError(f"开奖接口返回失败：{payload!r}")
    return payload


def normalize_issue(value: object) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"(\d{8})-?(\d{1,4})", raw)
    if not match:
        raise ValueError(f"无法识别期号：{raw!r}")
    return f"{match.group(1)}-{match.group(2).zfill(4)}"


def draw_digits(value: object) -> list[str]:
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        parts = [part.strip() for part in str(value or "").split(",")]
    if len(parts) != 5 or any(not re.fullmatch(r"\d", part) for part in parts):
        raise ValueError(f"开奖号不是五个 0–9 数字：{value!r}")
    return parts


def normalize_record(item: dict) -> dict:
    issue = normalize_issue(item.get("issue"))
    digits = draw_digits(item.get("drawResult"))
    draw_time = str(item.get("drawTime") or item.get("opendate") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", draw_time):
        raise ValueError(f"{issue} 的开奖时间格式异常：{draw_time!r}")
    return {
        "market": MARKET,
        "issue": issue,
        "opendate": draw_time,
        "w": digits[0],
        "q": digits[1],
        "b": digits[2],
        "s": digits[3],
        "g": digits[4],
    }


def verify_hash(item: dict, record: dict) -> dict | None:
    context = item.get("context")
    if not isinstance(context, dict):
        return None
    block_hash = str(context.get("hash") or "").lower()
    block_number = str(context.get("block") or "")
    numeric_tail = re.sub(r"\D", "", block_hash)[-5:]
    digits = "".join(record[field] for field in ("w", "q", "b", "s", "g"))
    if len(numeric_tail) != 5 or numeric_tail != digits:
        raise RuntimeError(
            f"{record['issue']} 的区块哈希末尾数字 {numeric_tail!r} "
            f"与接口开奖号 {digits!r} 不一致；已停止写入。"
        )
    return {
        "issue": record["issue"],
        "drawTime": record["opendate"],
        "block": block_number,
        "hash": block_hash,
        "drawResult": digits,
    }


def load_archive() -> dict[str, dict]:
    if not ARCHIVE.exists():
        raise FileNotFoundError(f"初始历史文件不存在：{ARCHIVE}")
    result: dict[str, dict] = {}
    with ARCHIVE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(f"历史 CSV 字段异常：{reader.fieldnames!r}")
        for row in reader:
            record = {field: str(row.get(field, "")).strip() for field in CSV_FIELDS}
            record["issue"] = normalize_issue(record["issue"])
            if record["market"] != MARKET:
                raise ValueError(f"发现非哈希三分记录：{record['market']!r}")
            draw_digits([record[field] for field in ("w", "q", "b", "s", "g")])
            if record["issue"] in result:
                raise ValueError(f"历史文件有重复期号：{record['issue']}")
            result[record["issue"]] = record
    if not result:
        raise ValueError("历史文件没有开奖记录")
    return result


def next_issue(issue: str) -> str:
    day_text, period_text = issue.split("-")
    current_day = datetime.strptime(day_text, "%Y%m%d").date()
    period = int(period_text)
    if period >= PERIODS_PER_DAY:
        current_day += timedelta(days=1)
        period = 1
    else:
        period += 1
    return f"{current_day:%Y%m%d}-{period:04d}"


def fetch_latest() -> list[dict]:
    url = f"{LATEST_URL}?{urlencode({'code': API_CODE, 'rows': 10})}"
    items = request_json(url).get("data")
    if not isinstance(items, list) or not items:
        raise RuntimeError("最新开奖接口没有返回开奖记录")
    return items


def fetch_history(start_time: str, end_time: str) -> list[dict]:
    records: list[dict] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        query = urlencode({
            "code": API_CODE,
            "rows": 100,
            "start_time": start_time,
            "end_time": end_time,
            "page": page,
        })
        payload = request_json(f"{HISTORY_URL}?{query}")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise RuntimeError("历史开奖接口的分页数据格式异常")
        records.extend(data["data"])
        page_info = data.get("page") or {}
        total_pages = int(page_info.get("total") or 1)
        page += 1
    return records


def write_archive(records: dict[str, dict]) -> None:
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for issue in sorted(records):
            writer.writerow(records[issue])


def write_update_chunks(new_records: list[dict]) -> None:
    grouped: dict[Path, list[dict]] = {}
    for record in new_records:
        draw_time = datetime.strptime(record["opendate"], "%Y-%m-%d %H:%M:%S")
        path = UPDATES / f"{draw_time:%Y}" / f"{draw_time:%m}" / f"{draw_time:%d}" / f"{draw_time:%H}.csv"
        grouped.setdefault(path, []).append(record)
    for path, additions in grouped.items():
        combined: dict[str, dict] = {}
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    combined[normalize_issue(row["issue"])] = {field: row[field] for field in CSV_FIELDS}
        for record in additions:
            combined[record["issue"]] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, lineterminator="\n")
            writer.writeheader()
            for issue in sorted(combined):
                writer.writerow(combined[issue])


def write_proofs(proofs: list[dict]) -> None:
    if not proofs:
        return
    existing: dict[str, dict] = {}
    if PROOFS.exists():
        with PROOFS.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    item = json.loads(line)
                    existing[item["issue"]] = item
    for proof in proofs:
        existing[proof["issue"]] = proof
    PROOFS.parent.mkdir(parents=True, exist_ok=True)
    with PROOFS.open("w", encoding="utf-8", newline="\n") as file:
        for issue in sorted(existing):
            file.write(json.dumps(existing[issue], ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    archive_records = load_archive()
    latest_issue = max(archive_records)
    latest_items = fetch_latest()
    latest_records = {normalize_issue(item.get("issue")): normalize_record(item) for item in latest_items}
    api_latest_issue = max(latest_records)

    # Keep proof metadata for the recent rows returned by the latest-results API.
    proof_rows = []
    for item in latest_items:
        record = normalize_record(item)
        proof = verify_hash(item, record)
        if proof:
            proof_rows.append(proof)

    if api_latest_issue <= latest_issue:
        print(f"No new draw. Local latest={latest_issue}; API latest={api_latest_issue}.")
        return 0

    start_time = archive_records[latest_issue]["opendate"]
    end_time = latest_records[api_latest_issue]["opendate"]
    raw_history = fetch_history(start_time, end_time)
    fetched = {normalize_issue(item.get("issue")): normalize_record(item) for item in raw_history}
    fetched.update(latest_records)

    expected = []
    cursor = latest_issue
    while cursor < api_latest_issue:
        cursor = next_issue(cursor)
        expected.append(cursor)
        if len(expected) > 2000:
            raise RuntimeError("本次缺口超过 2,000 期，停止自动补录以便人工检查")
    missing = [issue for issue in expected if issue not in fetched]
    if missing:
        raise RuntimeError(f"历史接口未返回全部缺期，缺少：{', '.join(missing[:20])}")

    new_records = [fetched[issue] for issue in expected]
    archive_records.update({record["issue"]: record for record in new_records})
    write_archive(archive_records)
    write_update_chunks(new_records)
    write_proofs(proof_rows)

    manifest = {
        "schemaVersion": 1,
        "market": MARKET,
        "sourceCode": API_CODE,
        "latestIssue": api_latest_issue,
        "latestDrawTime": fetched[api_latest_issue]["opendate"],
        "recordCount": len(archive_records),
        "archiveFile": "data/archive/history.csv",
        "updateChunkFormat": "data/updates/YYYY/MM/DD/HH.csv",
        "proofFile": "data/proofs.jsonl",
        "lastUpdated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Added {len(new_records)} draws: {latest_issue} -> {api_latest_issue}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        raise SystemExit(1)

