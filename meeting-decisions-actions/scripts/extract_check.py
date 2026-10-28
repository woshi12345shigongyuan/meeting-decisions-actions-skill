#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate JSON produced by the meeting-decisions-actions skill.

Usage:
    python extract_check.py output.json
    python extract_check.py output.json --notes meeting.md
    python extract_check.py output.json --notes meeting.md --strict

Exit codes:
    0  valid (warnings allowed unless --strict)
    1  validation errors
    2  input / JSON parse errors

Standard library only; Python 3.8+.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime

UNSPECIFIED = "未指定"
PRIORITIES = {"高", "中", "低", UNSPECIFIED}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

SECTION_SPEC = {
    "decisions": {
        "prefix": "D",
        "required": {"id": str, "decision": str, "evidence": str},
        "optional": {"rationale": (str, type(None))},
    },
    "action_items": {
        "prefix": "A",
        "required": {
            "id": str,
            "task": str,
            "owner": str,
            "due": str,
            "priority": str,
            "evidence": str,
        },
        "optional": {"due_raw": (str, type(None))},
    },
    "risks": {
        "prefix": "R",
        "required": {"id": str, "risk": str, "evidence": str},
        "optional": {"impact": (str, type(None))},
    },
    "open_questions": {
        "prefix": "Q",
        "required": {"id": str, "question": str, "owner": str, "evidence": str},
        "optional": {},
    },
}

TOP_LEVEL = ("meeting", "summary", "decisions", "action_items", "risks", "open_questions")

SECTION_LABELS = {
    "decisions": "决策",
    "action_items": "待办",
    "risks": "风险",
    "open_questions": "待解决问题",
}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.quote_total = 0
        self.quote_missing = 0
        self.unspecified_owner = 0
        self.unspecified_due = 0

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)


def normalize(text):
    """Drop whitespace and punctuation so quotes can be matched loosely."""
    kept = []
    for ch in text:
        if ch.isspace():
            continue
        if unicodedata.category(ch)[0] in ("P", "Z"):
            continue
        kept.append(ch.lower())
    return "".join(kept)


def is_valid_date(value):
    if not DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def read_text(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def load_json(path, report):
    try:
        raw = read_text(path)
    except OSError as exc:
        report.error("无法读取文件 %s: %s" % (path, exc))
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        report.error("JSON 解析失败: %s" % exc)
        return None


def check_string(value, label, report, allow_empty=False):
    if not isinstance(value, str):
        report.error("%s 应为字符串" % label)
        return
    if not allow_empty and not value.strip():
        report.error("%s 不能为空" % label)
    if value.strip() in ("无", "暂无", "N/A", "n/a", "None"):
        report.warn("%s 使用了占位词「%s」，应改为 null 或「未指定」" % (label, value))


def check_meeting(meeting, report):
    if not isinstance(meeting, dict):
        report.error("meeting 应为对象")
        return
    for key in ("title", "date", "participants"):
        if key not in meeting:
            report.error("meeting 缺少字段: %s" % key)
    title = meeting.get("title")
    if title is not None:
        check_string(title, "meeting.title", report)
    date = meeting.get("date")
    if date is not None:
        check_string(date, "meeting.date", report)
        if isinstance(date, str) and not is_valid_date(date):
            report.error("meeting.date 必须是 YYYY-MM-DD 或 null: %r" % date)
    participants = meeting.get("participants", [])
    if not isinstance(participants, list):
        report.error("meeting.participants 应为数组")
    else:
        for index, name in enumerate(participants):
            check_string(name, "meeting.participants[%d]" % index, report)


def check_item(section, spec, item, index, report):
    label = "%s[%d]" % (section, index)
    if not isinstance(item, dict):
        report.error("%s 应为对象" % label)
        return None
    for key, expected in spec["required"].items():
        if key not in item:
            report.error("%s 缺少字段: %s" % (label, key))
            continue
        if not isinstance(item[key], expected):
            report.error("%s.%s 类型错误" % (label, key))
    for key, expected in spec["optional"].items():
        if key in item and not isinstance(item[key], expected):
            report.error("%s.%s 类型错误" % (label, key))
    allowed = set(spec["required"]) | set(spec["optional"]) | {"id"}
    for key in item:
        if key not in allowed:
            report.warn("%s 含未知字段: %s" % (label, key))

    item_id = item.get("id")
    if isinstance(item_id, str):
        if not re.fullmatch(spec["prefix"] + r"\d+", item_id):
            report.error("%s.id 应形如 %s1: %r" % (label, spec["prefix"], item_id))

    for key in spec["required"]:
        if key in ("id", "owner"):
            continue
        value = item.get(key)
        if isinstance(value, str):
            check_string(value, "%s.%s" % (label, key), report)

    if section in ("action_items", "open_questions"):
        owner = item.get("owner")
        if isinstance(owner, str) and not owner.strip():
            report.error("%s.owner 不能为空，未知请填「未指定」" % label)

    if section == "action_items":
        due = item.get("due")
        if isinstance(due, str):
            if due != UNSPECIFIED and not is_valid_date(due):
                report.error("%s.due 必须是 YYYY-MM-DD 或「未指定」: %r" % (label, due))
        priority = item.get("priority")
        if isinstance(priority, str) and priority not in PRIORITIES:
            report.error("%s.priority 只能是 高/中/低/未指定: %r" % (label, priority))

    return item_id


def validate(data, notes_text):
    report = Report()
    if not isinstance(data, dict):
        report.error("顶层必须是 JSON 对象")
        return report, {}

    for key in TOP_LEVEL:
        if key not in data:
            report.error("缺少顶层字段: %s" % key)

    if "meeting" in data:
        check_meeting(data.get("meeting"), report)

    summary = data.get("summary")
    if "summary" in data:
        check_string(summary, "summary", report)

    counts = {}
    quotes = []
    seen_ids = {}
    unspecified_owner = 0
    unspecified_due = 0

    for section, spec in SECTION_SPEC.items():
        if section not in data:
            continue
        items = data.get(section)
        if not isinstance(items, list):
            report.error("%s 应为数组" % section)
            continue
        counts[section] = len(items)
        for index, item in enumerate(items):
            item_id = check_item(section, spec, item, index, report)
            if isinstance(item_id, str) and item_id:
                if item_id in seen_ids:
                    report.error("编号重复: %s（出现在 %s 与 %s）" % (item_id, seen_ids[item_id], section))
                else:
                    seen_ids[item_id] = section
            if isinstance(item, dict):
                evidence = item.get("evidence")
                if isinstance(evidence, str) and evidence.strip():
                    label = item_id if isinstance(item_id, str) else "%s[%d]" % (section, index)
                    quotes.append((label, evidence))
                if section == "action_items":
                    if item.get("owner") == UNSPECIFIED:
                        unspecified_owner += 1
                    if item.get("due") == UNSPECIFIED:
                        unspecified_due += 1

    missing = 0
    if notes_text is not None:
        normalized_notes = normalize(notes_text)
        for label, quote in quotes:
            if normalize(quote) not in normalized_notes:
                report.error("%s 的 evidence 无法在原文中逐字定位: %r" % (label, quote))
                missing += 1
    else:
        report.warn("未提供 --notes，已跳过 evidence 原文核对")

    report.quote_total = len(quotes)
    report.quote_missing = missing
    report.unspecified_owner = unspecified_owner
    report.unspecified_due = unspecified_due
    return report, counts


def emit(report, counts, notes_checked, strict=False):
    total = sum(counts.values())
    summary = " / ".join("%s %d" % (SECTION_LABELS[key], counts.get(key, 0)) for key in SECTION_SPEC)
    print("[OK] JSON 结构可解析，共 %d 条：%s" % (total, summary))
    if report.quote_total:
        if notes_checked:
            marker = "OK" if report.quote_missing == 0 else "ERR"
            print("[%s] 证据核对：%d/%d 条 evidence 可在原文定位" % (
                marker, report.quote_total - report.quote_missing, report.quote_total))
        else:
            print("[INFO] 待核对 evidence %d 条（未提供原文）" % report.quote_total)
    if report.unspecified_owner or report.unspecified_due:
        print("[INFO] 未指定负责人 %d 条；未指定截止日期 %d 条（允许，需在说明中列出）" % (
            report.unspecified_owner, report.unspecified_due))

    for message in report.warnings:
        print("[WARN] %s" % message)
    for message in report.errors:
        print("[ERR] %s" % message)

    if report.errors:
        print("结果：失败（%d 个错误，%d 个警告）" % (len(report.errors), len(report.warnings)))
        return 1
    if strict and report.warnings:
        print("结果：失败（--strict 模式下警告视为错误）")
        return 1
    print("结果：通过（0 错误，%d 个警告）" % len(report.warnings))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="校验会议纪要提取结果 JSON 的结构与证据引用。")
    parser.add_argument("json_path", help="待校验的 JSON 文件，使用 - 表示从标准输入读取")
    parser.add_argument("--notes", help="会议原文文件，用于核对 evidence 是否逐字引用")
    parser.add_argument("--strict", action="store_true", help="把警告也视为失败")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    report = Report()
    data = load_json(args.json_path, report)
    if data is None:
        for message in report.errors:
            print("[ERR] %s" % message)
        return 2

    notes_text = None
    if args.notes:
        try:
            notes_text = read_text(args.notes)
        except OSError as exc:
            print("[ERR] 无法读取原文 %s: %s" % (args.notes, exc))
            return 2
        if not notes_text.strip():
            print("[ERR] 原文为空，无法核对 evidence")
            return 2

    report, counts = validate(data, notes_text)
    return emit(report, counts, notes_text is not None, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
