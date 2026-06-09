"""
Sahra AI — Memory inspection layer (read-only).

Inspects brain, quran, product, and conversation memory without
modifying laws or the reasoning engine.
"""

import json
import re
from pathlib import Path

from config import config

BASE_DIR = Path(__file__).resolve().parent

MEMORY_FILE_MAP = {
    "brain_memory.json": config.BRAIN_MEMORY_FILE,
    "quran_memory.json": config.MEMORY_FILE,
    "product_memory.json": config.PRODUCT_MEMORY_FILE,
    "conversations.json": config.CONVERSATIONS_FILE,
}

MEMORY_STATS_COMMANDS = [
    "اعرض إحصائيات الذاكرة",
    "احصائيات الذاكرة",
    "إحصائيات الذاكرة",
]

KEYWORDS_COMMANDS = [
    "اعرض الكلمات المفتاحية المتعلمة",
    "الكلمات المفتاحية المتعلمة",
]

NEURAL_LINKS_COMMANDS = [
    "اعرض الروابط العصبية",
    "كم عدد الروابط العصبية",
]

TOP_LAWS_COMMANDS = [
    "اعرض أكثر القوانين استخداماً",
]

MEMORY_COMMAND_GROUPS = {
    "memory_stats": MEMORY_STATS_COMMANDS,
    "keywords": KEYWORDS_COMMANDS,
    "neural_links": NEURAL_LINKS_COMMANDS,
    "top_laws": TOP_LAWS_COMMANDS,
}


def load_json(name):
    path = Path(MEMORY_FILE_MAP.get(name, BASE_DIR / name))
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_command_text(text):
    text = str(text or "").lower().strip()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي")):
        text = text.replace(src, dst)
    return text


def detect_memory_inspection_command(question):
    normalized = _normalize_command_text(question)
    if not normalized:
        return None

    for command, phrases in MEMORY_COMMAND_GROUPS.items():
        for phrase in phrases:
            if _normalize_command_text(phrase) in normalized:
                return command
    return None


def _quran_laws_list(quran):
    if isinstance(quran, list):
        return quran
    laws = quran.get("laws", [])
    if isinstance(laws, dict):
        return list(laws.values())
    if isinstance(laws, list):
        return laws
    return []


def _brain_keywords(brain):
    keywords = brain.get("keywords")
    if isinstance(keywords, dict) and keywords:
        return keywords

    aggregated = {}
    for neuron in brain.get("neurons", {}).values():
        for keyword in neuron.get("keywords", []):
            aggregated[keyword] = aggregated.get(keyword, 0) + 1
        for tag in neuron.get("tags", []):
            aggregated[tag] = aggregated.get(tag, 0) + 1
    return aggregated


def _brain_neural_links(brain):
    links = brain.get("neural_links")
    if isinstance(links, dict) and links:
        return links
    return dict(brain.get("co_activation", {}))


def get_memory_stats():
    brain = load_json("brain_memory.json")
    quran = load_json("quran_memory.json")
    product = load_json("product_memory.json")
    conversations = load_json("conversations.json")

    keywords = _brain_keywords(brain)
    neural_links = _brain_neural_links(brain)
    laws = _quran_laws_list(quran)
    products = product.get("products", {})
    chats = conversations.get("conversations", [])

    return {
        "laws_count": len(laws),
        "keywords_count": len(keywords),
        "neural_links_count": len(neural_links),
        "conversations_count": len(chats),
        "products_count": len(products),
    }


def get_keywords(limit=500):
    brain = load_json("brain_memory.json")
    keywords = _brain_keywords(brain)
    return list(keywords.keys())[:limit]


def get_neural_links():
    brain = load_json("brain_memory.json")
    links = _brain_neural_links(brain)
    return {
        "total_links": len(links),
        "links": links,
    }


def _law_usage_map(brain, quran):
    usage = quran.get("law_usage", {}) if isinstance(quran, dict) else {}
    if usage:
        return usage

    usage = {}
    for law_id, neuron in brain.get("neurons", {}).items():
        count = int(neuron.get("usage_count", 0))
        if count > 0:
            usage[law_id] = count
    return usage


def _law_text_for_index(quran, law_index):
    laws = _quran_laws_list(quran)
    try:
        idx = int(law_index)
    except (TypeError, ValueError):
        return ""
    if 0 <= idx < len(laws):
        item = laws[idx]
        if isinstance(item, dict):
            return item.get("result", "").strip()
    return ""


def get_top_laws(limit=20):
    brain = load_json("brain_memory.json")
    quran = load_json("quran_memory.json")
    usage = _law_usage_map(brain, quran)

    ranked = sorted(usage.items(), key=lambda x: x[1], reverse=True)[:limit]
    enriched = []
    for law_id, count in ranked:
        enriched.append({
            "law_index": law_id,
            "usage_count": count,
            "law_text": _law_text_for_index(quran, law_id),
        })
    return enriched


def format_memory_stats_response():
    stats = get_memory_stats()
    return (
        f"عدد القوانين: {stats['laws_count']}\n"
        f"عدد الكلمات المفتاحية: {stats['keywords_count']}\n"
        f"عدد الروابط العصبية: {stats['neural_links_count']}\n"
        f"عدد المحادثات: {stats['conversations_count']}\n"
        f"عدد المنتجات المحفوظة: {stats['products_count']}"
    )


def format_keywords_response(limit=500):
    keywords = get_keywords(limit=limit)
    if not keywords:
        return "لا توجد كلمات مفتاحية متعلمة بعد."
    return "\n".join(f"• {keyword}" for keyword in keywords)


def format_neural_links_response():
    data = get_neural_links()
    return f"إجمالي الروابط العصبية: {data['total_links']}"


def format_top_laws_response(limit=20):
    top_laws = get_top_laws(limit=limit)
    if not top_laws:
        return "لا توجد بيانات استخدام للقوانين بعد."

    lines = ["أكثر القوانين استخداماً:"]
    for item in top_laws:
        law_text = item.get("law_text") or "نص غير متوفر"
        lines.append(
            f"• القانون #{item['law_index']} — الاستخدام: {item['usage_count']} — {law_text}"
        )
    return "\n".join(lines)


def handle_memory_inspection_command(command):
    handlers = {
        "memory_stats": format_memory_stats_response,
        "keywords": format_keywords_response,
        "neural_links": format_neural_links_response,
        "top_laws": format_top_laws_response,
    }
    handler = handlers.get(command)
    if not handler:
        return None
    return handler()


def get_admin_memory_snapshot():
    brain = load_json("brain_memory.json")
    quran = load_json("quran_memory.json")
    product = load_json("product_memory.json")
    conversations = load_json("conversations.json")

    keywords = _brain_keywords(brain)
    neural_links = _brain_neural_links(brain)
    laws = _quran_laws_list(quran)
    products = product.get("products", {})
    chats = conversations.get("conversations", [])

    return {
        "brain_memory": {
            "keywords": keywords,
            "neural_links": neural_links,
            "neurons_count": len(brain.get("neurons", {})),
        },
        "quran_memory": {
            "laws_count": len(laws),
        },
        "product_memory": {
            "products_count": len(products),
            "products": products,
        },
        "conversations": {
            "count": len(chats),
        },
        "top_laws": get_top_laws(limit=20),
        "learned_keywords": get_keywords(limit=500),
        "neural_connections": get_neural_links(),
        "stats": get_memory_stats(),
    }
