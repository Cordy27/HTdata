"""Prompt construction for analyst-facing incremental news briefs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .utils import clean_text, format_dt


SYSTEM_PROMPT = (
    "你是面向二级市场互联网行业行研分析师的新闻快报助手。"
    "你的任务是从增量新闻中筛选真正值得进入快报的信息，写成可直接复制到微信群、飞书群或短信里的逐条快讯，并给出重要程度评分。"
    "只能使用输入新闻标题、摘要、来源、标签和时间中明示的信息；不得补充外部事实，不得推测影响，不得给投资建议。"
    "整体语气应客观、中立、专业，像卖方行研晨会快讯，不要写成网页摘要、营销文案或AI生成说明。"
)


def build_brief_messages(
    candidates: list[dict[str, Any]],
    now: datetime,
    prior_latest: datetime | None,
    min_brief_items: int,
    max_brief_items: int,
) -> list[dict[str, str]]:
    selection_rule = (
        f"筛选 {min_brief_items} 到 {max_brief_items} 条进入快报；不重要的信息不要写入。"
        if min_brief_items > 0
        else f"最多筛选 {max_brief_items} 条进入快报；不重要的信息不要写入。"
    )
    prompt_items = [
        {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "sourceName": item.get("sourceName", ""),
            "sourceType": item.get("sourceType", ""),
            "rank": item.get("rank"),
            "tags": item.get("tags", []),
            "matchedTerms": item.get("matchedTerms", []),
            "summary": clean_text(item.get("summary"))[:180],
            "publishedAt": item.get("publishedAt", ""),
            "latestSeenAt": item.get("latestSeenAt", ""),
            "url": item.get("url", ""),
            "relatedSources": item.get("relatedSources", []),
            "relatedIds": item.get("relatedIds", []),
        }
        for item in candidates
    ]
    request = {
        "task": "生成本轮增量新闻快报",
        "audience": "二级市场互联网行业行研分析师",
        "windowStart": format_dt(prior_latest) if prior_latest else "",
        "windowEnd": format_dt(now),
        "rules": [
            selection_rule,
            "每条新闻给出 0-100 的 importance score，越高代表越值得优先阅读。",
            "每条入选新闻必须提供 flashTitle、flashText 和 smsText；三者都要脱离网页上下文后仍能独立阅读。",
            "flashTitle 不超过 22 个汉字，使用事实主语和核心事件，不写情绪化判断。",
            "flashText 写 1 句，60-110 个汉字；采用“来源/主体 + 事实 + 明确口径”的外发快讯写法，不使用“本轮”“下方”“详见”等网页提示语。",
            "smsText 写 1 句，不超过 70 个汉字，用于短信或群聊精简转发。",
            "summary 写成快报导语，40-90 个汉字，只概括本次增量信息主线，不要写分析结论。",
            "fact 字段只写标题或摘要中可以确认的事实。",
            "同一事件如果来自多个来源，只保留一条快讯，并在表述中综合引用 relatedSources，不要重复入选。",
            "viewpoint 字段只写文中或摘要中明确出现的观点；没有就留空。",
            "reason 字段说明为什么对互联网行业研究有跟踪价值，但不能做无依据推演。",
            "输出必须是 JSON 对象，不要 Markdown，不要解释过程。",
        ],
        "schema": {
            "title": "不超过 20 个汉字的快报标题",
            "summary": "40-90 字，适合作为外发快报导语；无重要新闻则留空",
            "items": [{
                "id": "必须来自候选新闻 id",
                "score": "0-100",
                "flashTitle": "可外发快讯标题，不超过 22 个汉字",
                "flashText": "可外发快讯正文，1 句，60-110 个汉字",
                "smsText": "短信/群聊精简版，1 句，不超过 70 个汉字",
                "reason": "入选理由",
                "fact": "事实表述",
                "viewpoint": "文中观点或空字符串",
                "followUp": "后续可跟踪问题",
                "relatedSources": "候选新闻提供的来源列表，必须原样保留",
                "relatedIds": "被合并的候选新闻 id 列表，必须原样保留",
            }],
        },
        "candidates": prompt_items,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ]
