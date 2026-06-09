from flask import Flask, request, render_template, jsonify
import hashlib
import json
import logging
import math
import os
import re
import socket
import subprocess
import requests

from config import config
from deploy_utils import initialize_runtime

initialize_runtime()

from brain import NeuralBrain
from conversations import ConversationNotFoundError, ConversationStore
from product_analyzer import (
    EXTRACTION_FAIL_MESSAGE,
    INSUFFICIENT_LAWS_MESSAGE,
    ProductExtractionError,
    ProductMemory,
    build_analysis_query,
    detect_product_memory_command,
    extract_amazon_url,
    extract_product_data,
    format_product_report,
    infer_recommendation,
    is_cache_valid,
    laws_are_sufficient,
    PRODUCT_ANALYSIS_VERSION,
)

logger = logging.getLogger("sahra")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

if config.BEHIND_PROXY:
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        logger.info("ProxyFix enabled for reverse proxy deployment")
    except ImportError:
        logger.warning("ProxyFix unavailable — install werkzeug for proxy support")

UI_VERSION = "chatgpt-v8"
APP_PORT = config.PORT
APP_HOST = config.HOST


def get_lan_ip():
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object { $_.IPAddress -match '^192\\.168\\.' } | "
                "Select-Object -First 1 -ExpandProperty IPAddress",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ip = (result.stdout or "").strip()
        if ip:
            return ip
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object { $_.IPAddress -notmatch '^(127\\.|169\\.254\\.)' } | "
                "Select-Object -First 1 -ExpandProperty IPAddress",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ip = (result.stdout or "").strip()
        if ip:
            return ip
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


@app.after_request
def set_encoding_and_cache(response):
    content_type = response.content_type or ""

    if "text/html" in content_type:
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    elif "text/css" in content_type:
        response.headers["Content-Type"] = "text/css; charset=utf-8"
    elif "javascript" in content_type:
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    elif "application/json" in content_type:
        response.headers["Content-Type"] = "application/json; charset=utf-8"

    if (
        "text/html" in content_type
        or "text/css" in content_type
        or "javascript" in content_type
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

OLLAMA_BASE = config.OLLAMA_BASE
OLLAMA_MODEL = config.OLLAMA_MODEL
EMBED_MODEL = config.EMBED_MODEL
MEMORY_FILE = config.MEMORY_FILE
EMBED_CACHE_FILE = config.EMBED_CACHE_FILE
INDEX_VERSION = "sahra-result-v3"
MAX_LAWS = 8
MIN_WORD_LEN = 2
MIN_MATCH_SCORE = 0.01

STOP_WORDS = {
    "كيف", "ما", "هل", "من", "في", "على", "عن", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "التى", "ان", "او", "و", "لا", "لم", "لن", "اذا", "متى",
    "اين", "لماذا", "ماذا", "اي", "بين", "عند", "كل", "قد", "كان", "يكون",
    "هو", "هي", "هم", "نحن", "انت", "ان", "ثم", "قد", "لكن", "بل", "حتى",
    "الى", "إلى", "عندما", "اذ", "إذ", "انها", "انه", "ذلك", "هناك",
}

TOPIC_EXPANSIONS = {
    "اسراف": ["اسراف", "مصاريف", "مخزون", "اعلانات", "صرف", "تبذير", "ميزانيه", "تجنب"],
    "رزق": ["رزق", "ارباح", "مبيعات", "دخل", "نجاح", "ربح", "توسع"],
    "عهد": ["عهد", "وعود", "عقود", "ميثاق", "التزام", "نقض"],
    "ثقه": ["ثقه", "امانه", "مصداقيه", "سمعه", "ولاء"],
    "عملاء": ["عملاء", "زبائن", "خدمه", "شكاوى", "رسائل", "احترام"],
    "ابني": ["ابني", "بناء", "تعزيز", "كسب"],
    "غش": ["غش", "خداع", "تلاعب", "احتيال", "تزوير"],
    "عدل": ["عدل", "انصاف", "حق", "عدالة"],
    "امانه": ["امانه", "صدق", "شفافيه"],
    "بيع": ["بيع", "تسويق", "منتج", "منتجات", "متجر", "تجاره", "تجارة", "سوق"],
    "منتج": ["منتج", "منتجات", "سلعه", "سلعة", "بضاعه", "بضاعة"],
    "سعر": ["سعر", "اسعار", "أسعار", "تخفيض", "ربح", "خسارة"],
    "شحن": ["شحن", "توصيل", "تسليم", "مورد", "موردين"],
    "جوده": ["جوده", "جودة", "فحص", "ضمان", "مواصفات"],
    "تسويق": ["تسويق", "اعلان", "إعلان", "اعلانات", "حمله", "حملة"],
}

VERSE_KEYWORDS = (
    "آية", "اية", "الآية", "الاية", "قرآن", "قران", "القرآن", "القران", "verse",
)

def load_memory():
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def memory_fingerprint():
    stat = os.stat(MEMORY_FILE)
    raw = f"{INDEX_VERSION}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_arabic(text):
    text = text.lower()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(src, dst)
    return text


def tokenize(text):
    text = normalize_arabic(text)
    text = re.sub(r"[؟،؛:!?.,؛]+", " ", text)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    words = re.findall(r"[\u0600-\u06FF]+", text)

    cleaned = []
    for word in words:
        if len(word) <= MIN_WORD_LEN or word in STOP_WORDS:
            continue
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        cleaned.append(word)

    return cleaned


def sahra_law(item):
    return item.get("result", "").strip()


def user_wants_verse(question):
    normalized = normalize_arabic(question)
    return any(keyword in normalized for keyword in VERSE_KEYWORDS)


def expand_terms(terms):
    expanded = []
    seen = set()

    for term in terms:
        if term not in seen:
            seen.add(term)
            expanded.append(term)

        for key, synonyms in TOPIC_EXPANSIONS.items():
            if term == key or term in synonyms:
                for synonym in synonyms:
                    if synonym not in seen:
                        seen.add(synonym)
                        expanded.append(synonym)

    return expanded


def ollama_generate(prompt, timeout=120):
    response = requests.post(
        f"{OLLAMA_BASE}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def ollama_embed(text, timeout=60):
    response = requests.post(
        f"{OLLAMA_BASE}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def parse_json_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


def extract_concepts(question):
    local_terms = tokenize(question)
    if local_terms:
        return {"keywords": local_terms, "concepts": [], "related": []}

    prompt = f"""أنت محلل لمنصة صحرا.
استخرج كلمات ومفاهيم تجارية وأخلاقية من السؤال للبحث عن قوانين صحرا وليس آيات قرآنية.

السؤال:
{question}

أجب بصيغة JSON فقط:
{{
  "keywords": ["كلمة1", "كلمة2"],
  "concepts": ["مفهوم1", "مفهوم2"],
  "related": ["مرادف1", "موضوع قريب"]
}}"""

    try:
        raw = ollama_generate(prompt, timeout=20)
        data = parse_json_object(raw)
        keywords = [str(x).strip() for x in data.get("keywords", []) if str(x).strip()]
        concepts = [str(x).strip() for x in data.get("concepts", []) if str(x).strip()]
        related = [str(x).strip() for x in data.get("related", []) if str(x).strip()]
        if keywords or concepts or related:
            return {"keywords": keywords, "concepts": concepts, "related": related}
    except requests.RequestException:
        pass

    return {"keywords": raw_question_terms(question), "concepts": [], "related": []}


def raw_question_terms(question):
    text = normalize_arabic(question)
    text = re.sub(r"[؟،؛:!?.,؛]+", " ", text)
    words = re.findall(r"[\u0600-\u06FF]+", text)
    cleaned = []
    for word in words:
        if len(word) <= MIN_WORD_LEN or word in STOP_WORDS:
            continue
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        cleaned.append(word)
    return cleaned


def build_search_terms(question, concepts):
    terms = []
    seen = set()
    sources = [question]
    sources.extend(concepts.get("keywords", []))
    sources.extend(concepts.get("concepts", []))
    sources.extend(concepts.get("related", []))

    for source in sources:
        for word in tokenize(str(source)):
            if word not in seen:
                seen.add(word)
                terms.append(word)

    return expand_terms(terms)


def term_matches(term, text):
    if term in text:
        return True
    if len(term) > 4 and term[:-1] in text:
        return True
    if len(term) > 5 and term[:-2] in text:
        return True
    return False


def keyword_score(law, terms):
    result_text = normalize_arabic(sahra_law(law))
    if not terms:
        return 0.0

    hits = sum(1 for term in terms if term_matches(term, result_text))
    return hits / len(terms)


def intent_boost(law, terms):
    result_text = normalize_arabic(sahra_law(law))
    boost = 0.0
    term_set = set(terms)

    if term_set & {"خطر", "مخاطر", "نقض", "فساد"}:
        if any(word in result_text for word in ("يدمر", "يضر", "خطر", "فساد", "فقدان", "عقوب")):
            boost += 0.35

    if term_set & {"ابني", "بناء", "تعزيز", "كسب"}:
        if any(word in result_text for word in ("يبني", "بناء", "اساس", "يزيد ثقه")):
            boost += 0.3
        if any(word in result_text for word in ("يدمر", "يضر", "فقدان")):
            boost -= 0.25

    if term_set & {"ازيد", "رزق", "ارباح"} and "رزق" in result_text:
        boost += 0.35

    if term_set & {"اسراف", "تجنب", "اتجنب"} and "اسراف" in result_text:
        boost += 0.35

    if term_set & {"عهد", "وعود", "عقود"} and any(
        word in result_text for word in ("عهد", "وعود", "عقود", "التزام")
    ):
        boost += 0.2

    return boost


class LawRetriever:
    def __init__(self, laws):
        self.laws = laws
        self.embeddings = []
        self.embeddings_ready = False
        self._index_built = False

    def _load_embeddings_cache(self):
        if self._index_built:
            return

        fingerprint = memory_fingerprint()
        if os.path.exists(EMBED_CACHE_FILE):
            try:
                with open(EMBED_CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if (
                    cache.get("fingerprint") == fingerprint
                    and cache.get("model") == EMBED_MODEL
                    and cache.get("index_version") == INDEX_VERSION
                    and len(cache.get("embeddings", [])) == len(self.laws)
                ):
                    self.embeddings = cache["embeddings"]
                    self.embeddings_ready = True
            except (json.JSONDecodeError, OSError, KeyError):
                pass

        self._index_built = True

    def _semantic_scores(self, search_text, terms):
        lexical_scores = [
            keyword_score(law, terms) + intent_boost(law, terms)
            for law in self.laws
        ]

        if not self.embeddings_ready:
            return lexical_scores

        try:
            query_vec = ollama_embed(search_text)
        except requests.RequestException:
            return lexical_scores

        scores = []
        for idx, law in enumerate(self.laws):
            semantic = cosine_similarity(query_vec, self.embeddings[idx])
            lexical = lexical_scores[idx]
            scores.append(lexical + (semantic * 0.35))
        return scores

    def _broad_fallback(self, question, limit):
        words = raw_question_terms(question)
        if not words:
            words = re.findall(r"[\u0600-\u06FF]{3,}", normalize_arabic(question))

        if not words:
            return [], 0.0

        ranked = []
        for law in self.laws:
            result_text = normalize_arabic(sahra_law(law))
            hits = sum(1 for word in words if term_matches(word, result_text))
            if hits:
                ranked.append((hits / len(words), law, self.laws.index(law)))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            return [], 0.0, []

        top = ranked[:limit]
        return [law for _, law, _ in top], top[0][0], [idx for _, _, idx in top]

    def find_relevant(self, question, limit=MAX_LAWS):
        self._load_embeddings_cache()
        concepts = extract_concepts(question)
        terms = build_search_terms(question, concepts)
        search_text = " ".join(
            [question]
            + concepts.get("keywords", [])
            + concepts.get("concepts", [])
            + concepts.get("related", [])
        )

        scores = self._semantic_scores(search_text, terms)
        scores = NEURAL_BRAIN.apply_neural_scores(question, terms, scores)

        ranked = sorted(
            ((score, law, idx) for idx, (score, law) in enumerate(zip(scores, self.laws))),
            key=lambda item: item[0],
            reverse=True,
        )

        if not ranked or ranked[0][0] < MIN_MATCH_SCORE:
            return self._broad_fallback(question, limit)

        top = ranked[:limit]
        return [law for _, law, _ in top], top[0][0], [idx for _, _, idx in top]


def build_laws_context(laws, include_verse=False):
    if not laws:
        return "لا يوجد قانون مطابق."

    parts = []
    for index, item in enumerate(laws, start=1):
        block = f"{index}. القانون:\n{sahra_law(item)}"
        if include_verse:
            block += f"\nالآية:\n{item.get('aya', '')}"
        parts.append(block)

    return "\n\n".join(parts)


def build_answer(question, laws):
    primary_law = sahra_law(laws[0])
    include_verse = user_wants_verse(question)
    laws_context = build_laws_context(laws, include_verse=include_verse)

    prompt = f"""You are Sahra AI.
Answer only using the Sahra laws stored in the database.
Do not quote Quran verses unless requested.
Do not invent information.
Return the law and its explanation in Arabic.

قوانين صحرا المتاحة:
{laws_context}

السؤال:
{question}

اكتب الإجابة بهذا الشكل فقط:
القانون:
{primary_law}

الشرح:
[شرح عربي مبسط مستند فقط إلى القانون أعلاه دون ذكر آيات قرآنية]"""

    explanation = ollama_generate(prompt)
    explanation = strip_verse_quotes(explanation, question)

    if "القانون:" in explanation and "الشرح:" in explanation:
        return explanation

    return f"القانون:\n{primary_law}\n\nالشرح:\n{explanation}"


def strip_verse_quotes(text, question):
    if user_wants_verse(question):
        return text

    lines = []
    for line in text.splitlines():
        normalized = normalize_arabic(line)
        if normalized.startswith("الايه:") or normalized.startswith("اية:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


MEMORY_DATA = load_memory()
NEURAL_BRAIN = NeuralBrain(MEMORY_DATA, memory_path=config.BRAIN_MEMORY_FILE)
RETRIEVER = LawRetriever(MEMORY_DATA)
PRODUCT_MEMORY = ProductMemory(path=config.PRODUCT_MEMORY_FILE)
CONVERSATION_STORE = ConversationStore(path=config.CONVERSATIONS_FILE)
logger.info(
    "Sahra AI initialized | env=%s | laws=%s | host=%s | port=%s",
    config.ENV,
    len(MEMORY_DATA),
    APP_HOST,
    APP_PORT,
)


def resolve_message_text(data):
    for key in ("question", "url", "message", "text"):
        value = (data.get(key) or "").strip()
        if value:
            return value
    return ""


def resolve_amazon_url(data):
    for key in ("question", "url", "message", "text"):
        value = (data.get(key) or "").strip()
        if not value:
            continue
        found = extract_amazon_url(value)
        if found:
            return found
    return None


def handle_product_memory_command(question):
    command = detect_product_memory_command(question)
    if not command:
        return None
    logger.info("Product memory command: %s", command)
    return PRODUCT_MEMORY.handle_command(command)


def process_question(question, force_product_url=None):
    memory_report = handle_product_memory_command(question)
    if memory_report:
        return memory_report

    amazon_url = force_product_url or extract_amazon_url(question)
    if amazon_url:
        logger.info("Amazon URL detected: %s", amazon_url)
        return analyze_amazon_product(amazon_url)

    laws, _score, law_indices = RETRIEVER.find_relevant(question)

    if not laws:
        return "لا يوجد قانون مناسب في قاعدة صحرا."

    NEURAL_BRAIN.learn(question, law_indices)
    return build_answer(question, laws)


def analyze_amazon_product(url):
    logger.info("Starting Amazon product analysis for: %s", url)

    cached = PRODUCT_MEMORY.get(url=url)
    if is_cache_valid(cached):
        logger.info("Cache hit for Amazon product: %s", cached.get("title", ""))
        cached = PRODUCT_MEMORY.record_reanalysis(cached)
        return format_product_report(
            cached,
            cached.get("laws", []),
            cached.get("recommendation", "needs_research"),
            cached.get("recommendation_label", "يحتاج مزيد بحث"),
            cached.get("justifications", []),
            sufficient=cached.get("sufficient", True),
            cached=True,
        )

    try:
        product = extract_product_data(url)
        logger.info("Extraction success | title: %s", product.get("title", ""))
    except ProductExtractionError as exc:
        reason = str(exc).strip() or EXTRACTION_FAIL_MESSAGE
        logger.error("Extraction failure for %s | reason: %s", url, reason)
        return reason

    cached = PRODUCT_MEMORY.get(url=product.get("url"), asin=product.get("asin"))
    if is_cache_valid(cached):
        cached = PRODUCT_MEMORY.record_reanalysis(cached)
        return format_product_report(
            cached,
            cached.get("laws", []),
            cached.get("recommendation", "needs_research"),
            cached.get("recommendation_label", "يحتاج مزيد بحث"),
            cached.get("justifications", []),
            sufficient=cached.get("sufficient", True),
            cached=True,
        )

    analysis_query = build_analysis_query(product)
    laws, match_score, law_indices = RETRIEVER.find_relevant(analysis_query)

    if not laws:
        return "لا يوجد قانون مناسب في قاعدة صحرا."

    law_texts = [sahra_law(law) for law in laws]
    sufficient = laws_are_sufficient(product, law_texts, match_score)

    if not sufficient:
        logger.info("Insufficient Sahra laws for product: %s (score=%.3f)", product.get("title"), match_score)
        analysis = {
            "recommendation": "insufficient",
            "recommendation_label": INSUFFICIENT_LAWS_MESSAGE,
            "law_indices": law_indices,
            "laws": law_texts,
            "justifications": [INSUFFICIENT_LAWS_MESSAGE],
            "sufficient": False,
            "analysis_version": PRODUCT_ANALYSIS_VERSION,
        }
        NEURAL_BRAIN.learn(analysis_query, law_indices)
        PRODUCT_MEMORY.store(product, analysis)
        return format_product_report(
            product,
            law_texts,
            "insufficient",
            INSUFFICIENT_LAWS_MESSAGE,
            [INSUFFICIENT_LAWS_MESSAGE],
            sufficient=False,
            cached=False,
        )

    recommendation_key, recommendation_label, justifications = infer_recommendation(
        product, law_texts
    )

    NEURAL_BRAIN.learn(analysis_query, law_indices)

    analysis = {
        "recommendation": recommendation_key,
        "recommendation_label": recommendation_label,
        "law_indices": law_indices,
        "laws": law_texts,
        "justifications": justifications,
        "sufficient": True,
        "analysis_version": PRODUCT_ANALYSIS_VERSION,
    }
    PRODUCT_MEMORY.store(product, analysis)

    return format_product_report(
        product,
        law_texts,
        recommendation_key,
        recommendation_label,
        justifications,
        sufficient=True,
        cached=False,
    )


@app.route("/health", methods=["GET"])
def health():
    checks = {
        "quran_memory": os.path.exists(config.MEMORY_FILE),
        "brain_memory": os.path.exists(config.BRAIN_MEMORY_FILE),
        "product_memory": os.path.exists(config.PRODUCT_MEMORY_FILE),
        "conversations": os.path.exists(config.CONVERSATIONS_FILE),
        "logs_writable": os.access(config.LOG_DIR, os.W_OK),
        "backups_writable": os.access(config.BACKUP_DIR, os.W_OK),
    }

    try:
        response = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        checks["ollama"] = response.status_code == 200
    except requests.RequestException:
        checks["ollama"] = False

    return jsonify({
        "status": "ok",
        "env": config.ENV,
        "host": APP_HOST,
        "port": APP_PORT,
        "checks": checks,
    })


@app.route("/", methods=["GET"])
def home():
    lan_ip = get_lan_ip()
    return render_template(
        "index.html",
        ui_version=UI_VERSION,
        lan_ip=lan_ip,
        app_port=APP_PORT,
        phone_url=f"http://{lan_ip}:{APP_PORT}",
    )


@app.route("/api/server-info", methods=["GET"])
def api_server_info():
    lan_ip = get_lan_ip()
    return jsonify({
        "lan_ip": lan_ip,
        "port": APP_PORT,
        "phone_url": f"http://{lan_ip}:{APP_PORT}",
        "pc_url": f"http://127.0.0.1:{APP_PORT}",
    })


@app.route("/api/conversations", methods=["GET"])
def api_list_conversations():
    return jsonify(CONVERSATION_STORE.list_all())


@app.route("/api/conversations", methods=["POST"])
def api_create_conversation():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "محادثة جديدة").strip() or "محادثة جديدة"
    messages = data.get("messages") or []
    conversation = CONVERSATION_STORE.create(title=title, messages=messages)
    return jsonify(conversation), 201


@app.route("/api/conversations/import", methods=["POST"])
def api_import_conversations():
    data = request.get_json(silent=True) or {}
    try:
        result = CONVERSATION_STORE.import_conversations(
            data.get("conversations") or [],
            active_id=data.get("active_id"),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/conversations/active", methods=["PUT"])
def api_set_active_conversation():
    data = request.get_json(silent=True) or {}
    active_id = data.get("active_id")
    if active_id is not None and not isinstance(active_id, str):
        return jsonify({"error": "معرّف المحادثة غير صالح"}), 400

    try:
        result = CONVERSATION_STORE.set_active(active_id)
        return jsonify(result)
    except ConversationNotFoundError:
        return jsonify({"error": "المحادثة غير موجودة"}), 404


@app.route("/api/conversations/<conversation_id>", methods=["GET"])
def api_get_conversation(conversation_id):
    try:
        return jsonify(CONVERSATION_STORE.get(conversation_id))
    except ConversationNotFoundError:
        return jsonify({"error": "المحادثة غير موجودة"}), 404


@app.route("/api/conversations/<conversation_id>", methods=["PUT"])
def api_update_conversation(conversation_id):
    data = request.get_json(silent=True) or {}
    try:
        conversation = CONVERSATION_STORE.update(
            conversation_id,
            title=data.get("title"),
            messages=data.get("messages"),
            updated_at=data.get("updatedAt"),
        )
        return jsonify(conversation)
    except ConversationNotFoundError:
        return jsonify({"error": "المحادثة غير موجودة"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/conversations/<conversation_id>/rename", methods=["PUT"])
def api_rename_conversation(conversation_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "عنوان المحادثة فارغ"}), 400

    try:
        conversation = CONVERSATION_STORE.rename(conversation_id, title)
        return jsonify(conversation)
    except ConversationNotFoundError:
        return jsonify({"error": "المحادثة غير موجودة"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/conversations/<conversation_id>", methods=["DELETE"])
def api_delete_conversation(conversation_id):
    try:
        result = CONVERSATION_STORE.delete(conversation_id)
        return jsonify(result)
    except ConversationNotFoundError:
        return jsonify({"error": "المحادثة غير موجودة"}), 404


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = resolve_message_text(data)

    if not message:
        return jsonify({"error": "السؤال فارغ"}), 400

    amazon_url = resolve_amazon_url(data)
    if amazon_url:
        logger.info("API /api/chat -> product mode | URL: %s", amazon_url)
        try:
            answer = analyze_amazon_product(amazon_url)
            return jsonify({"answer": answer, "mode": "product", "amazon_url": amazon_url})
        except requests.RequestException as exc:
            return jsonify({"error": f"خطأ في تحليل المنتج: {exc}"}), 500

    logger.info("API /api/chat -> law mode | message: %s", message[:120])
    try:
        answer = process_question(message)
        return jsonify({"answer": answer, "mode": "law"})
    except requests.RequestException as exc:
        return jsonify({"error": f"خطأ في الاتصال بـ Ollama: {exc}"}), 500


@app.route("/api/product-memory/<report_type>", methods=["GET"])
def api_product_memory_report(report_type):
    command_map = {
        "statistics": "stats",
        "categories": "top_categories",
        "laws": "top_laws",
        "keywords": "top_keywords",
    }
    command = command_map.get(report_type)
    if not command:
        return jsonify({"error": "نوع التقرير غير مدعوم"}), 400

    return jsonify({
        "report_type": report_type,
        "answer": PRODUCT_MEMORY.handle_command(command),
    })


@app.route("/api/analyze-product", methods=["POST"])
def api_analyze_product():
    data = request.get_json(silent=True) or {}
    amazon_url = resolve_amazon_url(data)

    if not amazon_url:
        logger.warning("API /api/analyze-product -> no Amazon URL in payload: %s", data)
        return jsonify({"error": "يرجى إرسال رابط منتج أمازون صالح."}), 400

    logger.info("API /api/analyze-product | URL: %s", amazon_url)
    try:
        answer = analyze_amazon_product(amazon_url)
        return jsonify({"answer": answer, "mode": "product", "amazon_url": amazon_url})
    except ProductExtractionError as exc:
        reason = str(exc).strip() or EXTRACTION_FAIL_MESSAGE
        logger.error("API /api/analyze-product extraction failure | URL: %s | reason: %s", amazon_url, reason)
        return jsonify({"answer": reason, "mode": "product"}), 200
    except requests.RequestException as exc:
        return jsonify({"error": f"خطأ في تحليل المنتج: {exc}"}), 500


@app.errorhandler(Exception)
def handle_unhandled_exception(exc):
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return exc
    logger.exception("Unhandled error: %s", exc)
    if request.path.startswith("/api/"):
        return jsonify({"error": "حدث خطأ داخلي في الخادم"}), 500
    return "حدث خطأ داخلي في الخادم", 500


if __name__ == "__main__":
    lan_ip = get_lan_ip()
    logger.info(
        "Sahra AI development server | local: http://127.0.0.1:%s | lan: http://%s:%s",
        APP_PORT,
        lan_ip,
        APP_PORT,
    )
    app.run(host=APP_HOST, port=APP_PORT, debug=config.DEBUG)
