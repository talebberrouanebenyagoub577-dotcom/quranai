"""
Amazon public product page analyzer for Sahra AI.
Read-only: no orders, no login, no new laws.
"""

import json
import logging
import os
import re
import time
from html import unescape
from urllib.parse import urlparse

import requests

logger = logging.getLogger("sahra.amazon")

PRODUCT_MEMORY_FILE = "product_memory.json"
MEMORY_VERSION = 2

AMAZON_URL_PATTERNS = [
    re.compile(r"https?://(?:www\.)?amazon\.[a-z.]{2,15}/[^\s<>\"'\]]+", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?amzn\.[a-z.]{2,12}/[^\s<>\"'\]]+", re.IGNORECASE),
    re.compile(r"https?://a\.co/[^\s<>\"'\]]+", re.IGNORECASE),
    re.compile(
        r"(?:https?://)?(?:www\.)?amazon\.[a-z.]{2,15}/(?:dp|gp/product|gp/aw/d|exec/obidos/asin)/[^\s<>\"'\]]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:https?://)?(?:www\.)?amazon\.[a-z.]{2,15}/[^\s<>\"'\]]*/(?:dp|gp/product)/[A-Z0-9]{10}[^\s<>\"'\]]*",
        re.IGNORECASE,
    ),
]

ASIN_PATTERN = re.compile(
    r"(?:/dp/|/gp/product/|/gp/aw/d/|/exec/obidos/asin/|/product/)([A-Z0-9]{10})",
    re.IGNORECASE,
)

EXTRACTION_FAIL_MESSAGE = "تعذر استخراج بيانات المنتج من الرابط."

HTML_PREVIEW_LENGTH = 1000

CAPTCHA_MARKERS = (
    "captcha",
    "validatecaptcha",
    "robot check",
    "enter the characters you see below",
    "sorry, we just need to make sure you're not a robot",
    "type the characters you see in this image",
    "opfcaptcha",
    "automated access",
    "bot-detection",
    "csm-captcha",
    "api-services-support@amazon.com",
    "click the button below to continue shopping",
    "to discuss automated access to amazon data",
)

TITLE_SELECTORS = (
    ("productTitle", r'id=["\']productTitle["\'][^>]*>\s*(.*?)\s*</span>'),
    ("productTitle_h1", r'<h1[^>]+id=["\']productTitle["\'][^>]*>(.*?)</h1>'),
    ("og:title", r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)'),
    ("twitter:title", r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)'),
    ("meta_title", r'<meta[^>]+name=["\']title["\'][^>]+content=["\']([^"\']+)'),
    ("title_tag", r"<title[^>]*>(.*?)</title>"),
    ("json_title", r'"title"\s*:\s*"([^"]+)"'),
    ("h1_product", r'id=["\']title["\'][^>]*>(.*?)</'),
    ("asinTitle", r'"asinTitle"\s*:\s*"([^"]+)"'),
    ("product_title_json", r'"productTitle"\s*:\s*"([^"]+)"'),
    ("aria_product", r'id=["\']productTitle["\'][^>]*aria-label=["\']([^"\']+)'),
    ("ebook_title", r'id=["\']ebooksProductTitle["\'][^>]*>\s*(.*?)\s*</'),
)

PRICE_SELECTORS = (
    ("price_whole", r'class=["\']a-price-whole["\'][^>]*>([^<]+)'),
    ("price_fraction", r'class=["\']a-price-fraction["\'][^>]*>([^<]+)'),
    ("price_amount", r'"priceAmount"\s*:\s*([0-9.,]+)'),
    ("price_json", r'"price"\s*:\s*"([^"]+)"'),
    ("display_price", r'"displayPrice"\s*:\s*"([^"]+)"'),
    ("buying_option_price", r'"buyingOptionPrice"\s*:\s*"([^"]+)"'),
    ("apex_price", r'id=["\']apex_price["\'][^>]*>.*?class=["\']a-offscreen["\'][^>]*>\s*([^<]+)'),
    ("core_price", r'id=["\']corePrice_feature_div["\'][^>]*>.*?class=["\']a-offscreen["\'][^>]*>\s*([^<]+)'),
    ("priceblock", r'id=["\']priceblock_ourprice["\'][^>]*>\s*([^<]+)'),
    ("offscreen", r'class=["\']a-offscreen["\'][^>]*>\s*([^<]+)\s*</span>'),
    ("kindle_price", r'id=["\']kindle-price["\'][^>]*>\s*([^<]+)'),
    ("price_to_pay", r'data-a-color=["\']price["\'][^>]*>\s*([^<]+)<'),
)

RATING_SELECTORS = (
    ("icon_alt", r'class=["\']a-icon-alt["\'][^>]*>\s*([0-9.,]+)\s*(?:out of|من|stars)'),
    ("rating_json", r'"ratingValue"\s*:\s*"?([0-9.,]+)"?'),
    ("rating_hook", r'data-hook=["\']rating-out-of-text["\'][^>]*>\s*([0-9.,]+)'),
    ("average_star", r'data-hook=["\']average-star-rating["\'][^>]*>\s*([0-9.,]+)'),
    ("acr_popover", r'id=["\']acrPopover["\'][^>]*title=["\']([^"\']+)'),
    ("average_rating", r'"averageRating"\s*:\s*"?([0-9.,]+)"?'),
    ("review_stars", r'"reviewStars"\s*:\s*"?([0-9.,]+)"?'),
    ("star_alt", r'class=["\']a-star-\d[^"\']*["\'][^>]*aria-label=["\']([^"\']+)'),
)

REVIEW_COUNT_SELECTORS = (
    ("acr_reviews", r'id=["\']acrCustomerReviewText["\'][^>]*>\s*([^<]+)'),
    ("total_review_count", r'data-hook=["\']total-review-count["\'][^>]*>\s*([^<]+)'),
    ("review_count_json", r'"reviewCount"\s*:\s*"?([^",]+)"?'),
    ("rating_count_json", r'"ratingCount"\s*:\s*"?([^",]+)"?'),
    ("ratings_text", r'class=["\']a-size-base["\'][^>]*>\s*([0-9,.\s]+)\s*(?:ratings|تقييم|reviews)'),
    ("reviews_count", r'"reviewsCount"\s*:\s*"?([^",]+)"?'),
    ("acr_link", r'id=["\']acrCustomerReviewLink["\'][^>]*>\s*([^<]+)'),
)

def _build_browser_headers(profile="desktop", referer=None):
    if profile == "mobile":
        return {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": referer or "https://www.amazon.com/",
        }

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Referer": referer or "https://www.amazon.com/",
    }


DESKTOP_HEADERS = _build_browser_headers("desktop")
MOBILE_HEADERS = _build_browser_headers("mobile")

FETCH_HEADERS = DESKTOP_HEADERS

RECOMMENDATION_LABELS = {
    "suitable": "مناسب للبيع",
    "not_suitable": "غير مناسب للبيع",
    "needs_research": "يحتاج مزيد بحث قبل البيع",
}

PRODUCT_ANALYSIS_VERSION = "factual-v2"

RISK_WORDS = ("غش", "خداع", "تلاعب", "ممنوع", "يضر", "يدمر", "احتيال", "فساد")
POSITIVE_WORDS = ("جوده", "امانه", "ثقه", "عدل", "احسان", "طيب", "جيد", "نافع", "مباح", "شفاف")

LAW_REASON_RULES = (
    ("good_products", ("جيد", "طيب", "نافع", "مباح", "جوده"), "توجد قوانين تدعم بيع المنتجات الجيدة والنافعة."),
    ("trust", ("ثقه", "عملاء", "زبائن", "امانه"), "توجد قوانين تدعم بناء ثقة العملاء من خلال المنتجات الجيدة."),
    ("honesty", ("شفاف", "وضوح", "كيل", "ميزان", "مواصفات", "صدق"), "توجد قوانين تدعم الصدق في وصف المنتج ومواصفاته."),
)

PRODUCT_RISK_CONFLICT_MESSAGE = "توجد قوانين صحرا تشير إلى مخاطر أو محاذير مرتبطة بهذا المنتج."

INSUFFICIENT_LAWS_MESSAGE = "القوانين الحالية لا تكفي لإصدار حكم كامل على هذا المنتج."

MIN_LAW_MATCH_SCORE = 0.12

PRODUCT_KEYWORD_STOP_WORDS = {
    "من", "في", "على", "عن", "مع", "هذا", "هذه", "ذلك", "التي", "الذي", "و", "او",
    "the", "and", "for", "with", "from", "pack", "set", "piece", "pieces", "new",
    "amazon", "product", "item", "size", "color", "black", "white", "blue", "red",
}

CATEGORY_BUCKETS = {
    "car_accessories": {
        "label_ar": "إكسسوارات السيارات",
        "keywords": (
            "سيار", "سياره", "automotive", "vehicle", "car", "truck", "suv",
            "دفع", "شاحن", "مقعد", "اكواب", "حامل",
        ),
    },
    "electronics": {
        "label_ar": "إلكترونيات",
        "keywords": (
            "الكترون", "electronic", "computer", "phone", "mobile", "tablet",
            "laptop", "كمبيوتر", "هاتف", "شاحن", "usb", "cable", "سماع",
        ),
    },
    "home_products": {
        "label_ar": "منتجات المنزل",
        "keywords": (
            "منزل", "home", "kitchen", "مطبخ", "bedroom", "غرف", "اثاث",
            "furniture", "decor", "تنظيف", "cleaning",
        ),
    },
    "beauty_products": {
        "label_ar": "منتجات التجميل",
        "keywords": (
            "جمال", "beauty", "cosmetic", "عنايه", "skin", "hair", "مكياج",
            "perfume", "عطر", "cream", "serum",
        ),
    },
    "clothing": {
        "label_ar": "ملابس وأزياء",
        "keywords": ("ملابس", "clothing", "fashion", "shirt", "dress", "احذيه", "shoes"),
    },
    "sports": {
        "label_ar": "رياضة ولياقة",
        "keywords": ("رياض", "sport", "fitness", "gym", "outdoor", "outdoors"),
    },
    "toys": {
        "label_ar": "ألعاب وأطفال",
        "keywords": ("لعاب", "toy", "toys", "baby", "اطفال", "kids", "children"),
    },
    "other": {
        "label_ar": "فئات أخرى",
        "keywords": (),
    },
}

PRODUCT_MEMORY_COMMANDS = {
    "stats": (
        "احصائيات ذاكرة المنتجات",
        "عرض احصائيات ذاكرة المنتجات",
        "product memory statistics",
        "show product memory statistics",
        "إحصائيات ذاكرة المنتجات",
        "عرض إحصائيات ذاكرة المنتجات",
    ),
    "top_categories": (
        "اكثر الفئات تحليلا",
        "اكثر الفئات تحليلاً",
        "most analyzed categories",
        "show most analyzed categories",
        "أكثر الفئات تحليلاً",
        "عرض أكثر الفئات تحليلاً",
    ),
    "top_laws": (
        "اكثر قوانين صحرا تطابقا",
        "اكثر قوانين صحرا تطابقاً",
        "most matched sahra laws",
        "show most matched sahra laws",
        "أكثر قوانين صحرا تطابقاً",
        "عرض أكثر قوانين صحرا تطابقاً",
    ),
    "top_keywords": (
        "اكثر كلمات المنتجات تكرارا",
        "اكثر كلمات المنتجات تكراراً",
        "top recurring product keywords",
        "show top recurring product keywords",
        "أكثر كلمات المنتجات تكراراً",
        "عرض أكثر كلمات المنتجات تكراراً",
    ),
}


def _normalize_url_text(text):
    if not text:
        return ""
    text = str(text).strip()
    text = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    text = text.replace("\u00a0", " ")
    return text


def _amazon_fetch_urls(url):
    asin = extract_asin(url)
    base = (url or "").split("#")[0].split("?")[0].rstrip("/")
    candidates = []
    if base:
        candidates.append(base)
        candidates.append(f"{base}?language=en_US")
    if asin:
        candidates.append(f"https://www.amazon.com/dp/{asin}")
        candidates.append(f"https://www.amazon.com/dp/{asin}?language=en_US")
        candidates.append(f"https://www.amazon.com/gp/aw/d/{asin}")
    deduped = []
    seen = set()
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _page_has_product(html, asin=None):
    if not html:
        return False
    if 'id="productTitle"' in html or "id='productTitle'" in html:
        return True
    if '"@type":"Product"' in html or '"@type": "Product"' in html:
        return True
    if asin and asin in html and ("add-to-cart" in html.lower() or "addToCart" in html):
        return True
    return False


def _extract_from_asin_json(html, asin):
    if not asin:
        return "", "", "", ""
    title = price = rating = review_count = ""
    title_match = re.search(
        rf'"{re.escape(asin)}"[\s\S]{{0,1200}}?"title"\s*:\s*"([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if title_match:
        title = _clean_text(title_match.group(1))

    for pattern in (
        rf'"asin"\s*:\s*"{re.escape(asin)}"[\s\S]{{0,1200}}?"price"\s*:\s*"?([0-9.,]+)"?',
        r'"priceAmount"\s*:\s*([0-9.,]+)',
    ):
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            price = _clean_text(match.group(1))
            break

    rating_match = re.search(
        rf'"{re.escape(asin)}"[\s\S]{{0,1200}}?"ratingValue"\s*:\s*"?([0-9.,]+)"?',
        html,
        re.IGNORECASE,
    )
    if rating_match:
        rating = _clean_text(rating_match.group(1))

    review_match = re.search(
        rf'"{re.escape(asin)}"[\s\S]{{0,1200}}?"reviewCount"\s*:\s*"?([^",]+)"?',
        html,
        re.IGNORECASE,
    )
    if review_match:
        review_count = _clean_text(review_match.group(1))

    return title, price, rating, review_count


def _warm_amazon_session(session):
    try:
        session.get(
            "https://www.amazon.com/",
            headers=_build_browser_headers("desktop"),
            timeout=15,
            allow_redirects=True,
        )
        logger.info("Amazon session warmup | homepage=ok")
    except requests.RequestException as exc:
        logger.warning("Amazon session warmup failed | error=%s", exc)


def _log_redirect_chain(response):
    if not response.history:
        return
    chain = " -> ".join(f"{item.status_code}:{item.url}" for item in response.history)
    logger.info("Amazon redirect chain | %s -> %s", chain, response.url)


def _fetch_html_once(session, url, profile="desktop"):
    headers = _build_browser_headers(profile, referer="https://www.amazon.com/")
    response = session.get(url, headers=headers, timeout=25, allow_redirects=True)
    _log_redirect_chain(response)
    return response


def fetch_product_page(url):
    logger.info("Amazon fetch start | url=%s", url)
    asin = extract_asin(url)
    session = requests.Session()
    last_response = None
    last_error = None
    captcha_hits = 0

    _warm_amazon_session(session)

    for fetch_url in _amazon_fetch_urls(url):
        for profile_name in ("desktop", "mobile"):
            try:
                response = _fetch_html_once(session, fetch_url, profile=profile_name)
                last_response = response
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Amazon fetch attempt failed | url=%s | profile=%s | error=%s",
                    fetch_url,
                    profile_name,
                    exc,
                )
                continue

            status_code = response.status_code
            final_url = response.url
            html = response.text or ""
            page_title = _extract_document_title(html)
            captcha = _is_captcha_page(html, page_title)

            logger.info(
                "Amazon fetch attempt | fetch_url=%s | profile=%s | status=%s | "
                "final_url=%s | html_len=%s | page_title=%s | captcha=%s | has_product=%s",
                fetch_url,
                profile_name,
                status_code,
                final_url,
                len(html),
                page_title or "غير متوفر",
                captcha,
                _page_has_product(html, asin),
            )
            _log_html_preview(html, final_url, status_code)

            if status_code >= 400:
                continue

            if captcha:
                captcha_hits += 1
                logger.error(
                    "Amazon CAPTCHA detected | fetch_url=%s | final_url=%s | page_title=%s",
                    fetch_url,
                    final_url,
                    page_title or "غير متوفر",
                )
                continue

            if len(html) < 1000:
                continue

            if _page_has_product(html, asin):
                return html, final_url, status_code

    if last_error and not last_response:
        logger.error("Amazon network error | url=%s | error=%s", url, last_error)
        raise ProductExtractionError(f"تعذر الاتصال بأمازون: {last_error}") from last_error

    if not last_response:
        raise ProductExtractionError(
            f"تعذر تحميل صفحة المنتج. ASIN: {asin or 'غير معروف'}. "
            f"جرّب لاحقاً — أمازون قد يحجب طلبات VPS."
        )

    status_code = last_response.status_code
    final_url = last_response.url
    html = last_response.text or ""
    page_title = _extract_document_title(html)
    captcha = _is_captcha_page(html, page_title)

    logger.error(
        "Amazon fetch exhausted | status=%s | final_url=%s | html_len=%s | "
        "page_title=%s | captcha=%s | captcha_hits=%s",
        status_code,
        final_url,
        len(html),
        page_title or "غير متوفر",
        captcha,
        captcha_hits,
    )
    _log_html_preview(html, final_url, status_code)

    if status_code >= 400:
        raise ProductExtractionError(
            f"أمازون أرجعت HTTP {status_code}. الرابط النهائي: {final_url}. "
            f"عنوان الصفحة: {page_title or 'غير متوفر'}"
        )

    if len(html) < 1000:
        raise ProductExtractionError(
            f"صفحة المنتج قصيرة جداً ({len(html)} حرف). الرابط النهائي: {final_url}. "
            f"عنوان الصفحة: {page_title or 'غير متوفر'}"
        )

    if captcha or captcha_hits > 0:
        raise ProductExtractionError(
            f"أمازون طلب تحقق CAPTCHA (حجب آلي على VPS). HTTP {status_code}. "
            f"الرابط النهائي: {final_url}. عنوان الصفحة: {page_title or 'Robot Check'}. "
            f"ASIN: {asin or 'غير معروف'}"
        )

    raise ProductExtractionError(
        f"صفحة أمازون بدون بيانات منتج. HTTP {status_code}. الرابط النهائي: {final_url}. "
        f"عنوان الصفحة: {page_title or 'غير متوفر'}. ASIN: {asin or 'غير معروف'}"
    )


def _clean_extracted_url(url):
    url = url.strip().rstrip(".,;:!?)]}\"'»«")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url


def extract_amazon_url(text):
    text = _normalize_url_text(text)
    if not text:
        return None

    for pattern in AMAZON_URL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _clean_extracted_url(match.group(0))

    return None


def is_amazon_message(text):
    return extract_amazon_url(text) is not None


def extract_asin(url):
    match = ASIN_PATTERN.search(url)
    return match.group(1).upper() if match else None


def _clean_text(value):
    if not value:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _first_match(patterns, html):
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = _clean_text(match.group(1))
            if value:
                return value
    return ""


def _first_match_named(selectors, html, sanitize_title=False):
    for name, pattern in selectors:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = _clean_text(match.group(1))
            if sanitize_title:
                value = _sanitize_product_title(value)
            if value:
                return value, name
    return "", ""


def _extract_document_title(html):
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


def _is_captcha_page(html, page_title=""):
    lower_html = (html or "").lower()
    if any(marker in lower_html for marker in CAPTCHA_MARKERS):
        return True
    if page_title and re.search(r"robot|captcha|automated access", page_title, re.IGNORECASE):
        return True
    if lower_html and 'id="productTitle"' not in lower_html and "validatecaptcha" in lower_html:
        return True
    return False


def _log_html_preview(html, final_url, status_code):
    preview = re.sub(r"\s+", " ", (html or "")[:HTML_PREVIEW_LENGTH])
    logger.info(
        "Amazon HTML preview (%s chars) | status=%s | final_url=%s | preview=%s",
        HTML_PREVIEW_LENGTH,
        status_code,
        final_url,
        preview,
    )


def _sanitize_product_title(text):
    text = _clean_text(text)
    if not text:
        return ""
    text = re.sub(r"^Amazon\.com\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*:\s*Amazon\.com.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*:\s*Amazon\.[a-z.]+\s*$", "", text, flags=re.IGNORECASE)
    if text.lower() in ("amazon.com", "amazon.com: online shopping"):
        return ""
    return text.strip()


def _selector_diagnostics(selectors, html):
    results = []
    for name, pattern in selectors:
        match = re.search(pattern, html or "", re.IGNORECASE | re.DOTALL)
        results.append(f"{name}:{'hit' if match else 'miss'}")
    return ", ".join(results)


def _combine_price(whole, fraction):
    whole = (whole or "").strip()
    fraction = (fraction or "").strip()
    if whole and fraction:
        return f"{whole}.{fraction}"
    return whole or fraction


def _parse_json_ld_products(html):
    products = []
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Product":
                products.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                products.extend(x for x in graph if isinstance(x, dict) and x.get("@type") == "Product")
    return products


def _extract_from_json_ld(product):
    title = _clean_text(product.get("name"))
    rating = ""
    review_count = ""
    price = ""
    category = ""

    agg = product.get("aggregateRating") or {}
    if isinstance(agg, dict):
        rating = _clean_text(agg.get("ratingValue"))
        review_count = _clean_text(agg.get("reviewCount") or agg.get("ratingCount"))

    offers = product.get("offers")
    if isinstance(offers, dict):
        price = _clean_text(offers.get("price") or offers.get("lowPrice") or offers.get("highPrice"))
    elif isinstance(offers, list) and offers:
        first = offers[0]
        if isinstance(first, dict):
            price = _clean_text(first.get("price") or first.get("lowPrice"))

    category = _clean_text(product.get("category"))
    return title, price, rating, review_count, category


def extract_product_data(url):
    html, final_url, status_code = fetch_product_page(url)
    asin = extract_asin(final_url) or extract_asin(url)
    page_title = _extract_document_title(html)

    title = price = rating = review_count = category = ""
    title_source = price_source = rating_source = review_source = "json_ld"

    for product in _parse_json_ld_products(html):
        t, p, r, rc, c = _extract_from_json_ld(product)
        title = title or t
        price = price or p
        rating = rating or r
        review_count = review_count or rc
        category = category or c

    if not title:
        jt, jp, jr, jrc = _extract_from_asin_json(html, asin)
        title = title or jt
        price = price or jp
        rating = rating or jr
        review_count = review_count or jrc
        if jt:
            title_source = "asin_json"

    if not title:
        title, title_source = _first_match_named(TITLE_SELECTORS, html, sanitize_title=True)

    if not rating:
        star_alt, star_source = _first_match_named((RATING_SELECTORS[7],), html)
        if star_alt:
            rating_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", star_alt)
            if rating_match:
                rating = rating_match.group(1)
                rating_source = star_source

    if not price:
        price, price_source = _first_match_named(PRICE_SELECTORS, html)
        if not price:
            whole, _ = _first_match_named((PRICE_SELECTORS[0],), html)
            fraction, _ = _first_match_named((PRICE_SELECTORS[1],), html)
            combined = _combine_price(whole, fraction)
            if combined:
                price = combined
                price_source = "price_whole+fraction"

    if not rating:
        rating, rating_source = _first_match_named(RATING_SELECTORS, html)
        if not rating:
            popover, _ = _first_match_named((RATING_SELECTORS[3],), html)
            rating_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", popover or "")
            if rating_match:
                rating = rating_match.group(1)
                rating_source = "acr_popover"

    if not review_count:
        review_count, review_source = _first_match_named(REVIEW_COUNT_SELECTORS, html)

    category = category or _first_match(
        [
            r'id=["\']wayfinding-breadcrumbs_feature_div["\'][^>]*>(.*?)</div>',
            r'class=["\']a-breadcrumb["\'][^>]*>(.*?)</ul>',
            r'"browseNodeInfo"[^}]*"contextFreeName"\s*:\s*"([^"]+)"',
        ],
        html,
    )

    if category:
        parts = re.findall(r">([^<>{}\n]+)<", category)
        cleaned = [p.strip() for p in parts if p.strip() and p.strip() not in ("›", "»", "/")]
        category = " > ".join(cleaned[:5]) if cleaned else _clean_text(category)

    if not title:
        missing_fields = []
        if not price:
            missing_fields.append("السعر")
        if not rating:
            missing_fields.append("التقييم")
        if not review_count:
            missing_fields.append("عدد المراجعات")

        captcha = _is_captcha_page(html, page_title)
        title_diag = _selector_diagnostics(TITLE_SELECTORS, html)
        price_diag = _selector_diagnostics(PRICE_SELECTORS, html)
        rating_diag = _selector_diagnostics(RATING_SELECTORS, html)
        review_diag = _selector_diagnostics(REVIEW_COUNT_SELECTORS, html)

        logger.error(
            "Amazon extraction failed | url=%s | status=%s | final_url=%s | asin=%s | "
            "page_title=%s | html_len=%s | missing=%s | captcha=%s | "
            "title_selectors=%s | price_selectors=%s | rating_selectors=%s | review_selectors=%s",
            url,
            status_code,
            final_url,
            asin or "غير معروف",
            page_title or "غير متوفر",
            len(html),
            ",".join(missing_fields) or "العنوان",
            captcha,
            title_diag,
            price_diag,
            rating_diag,
            review_diag,
        )
        _log_html_preview(html, final_url, status_code)

        missing_text = "، ".join(missing_fields) if missing_fields else "العنوان"
        if captcha:
            raise ProductExtractionError(
                f"أمازون طلب تحقق CAPTCHA (حجب آلي على VPS). HTTP {status_code}. "
                f"الرابط النهائي: {final_url}. عنوان الصفحة: {page_title or 'Robot Check'}. "
                f"ASIN: {asin or 'غير معروف'}"
            )

        raise ProductExtractionError(
            f"تعذر استخراج عنوان المنتج (ASIN: {asin or 'غير معروف'}). "
            f"HTTP {status_code}. الرابط النهائي: {final_url}. "
            f"عنوان الصفحة: {page_title or 'غير متوفر'}. "
            f"الحقول الناقصة: {missing_text}. "
            f"محددات العنوان: {title_diag}"
        )

    logger.info(
        "Amazon extraction success | asin=%s | title_source=%s | price_source=%s | "
        "rating_source=%s | review_source=%s | title=%s",
        asin or "غير معروف",
        title_source,
        price_source if price else "none",
        rating_source if rating else "none",
        review_source if review_count else "none",
        title[:80],
    )

    if price:
        price = price.strip().rstrip(",")

    return {
        "url": final_url,
        "asin": asin or "",
        "title": title,
        "price": price or "غير متوفر",
        "rating": rating or "غير متوفر",
        "review_count": review_count or "غير متوفر",
        "category": category or "غير متوفر",
    }


class ProductExtractionError(Exception):
    pass


def _empty_learning():
    return {
        "category_buckets": {},
        "raw_categories": {},
        "keywords": {},
        "matched_laws": {},
    }


def _tokenize_product_text(text):
    text = _normalize_simple(text or "")
    text = re.sub(r"[›»/\\|>,;:!?.\-]+", " ", text)
    tokens = []

    for word in re.findall(r"[\u0600-\u06FF]+", text):
        if len(word) <= 2 or word in PRODUCT_KEYWORD_STOP_WORDS:
            continue
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        tokens.append(word)

    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) <= 2 or word in PRODUCT_KEYWORD_STOP_WORDS:
            continue
        tokens.append(word)

    return tokens


def classify_category_bucket(category, title=""):
    combined = _normalize_simple(f"{category} {title}")
    for bucket_id, bucket in CATEGORY_BUCKETS.items():
        if bucket_id == "other":
            continue
        if any(keyword in combined for keyword in bucket["keywords"]):
            return bucket_id
    return "other"


def detect_product_memory_command(question):
    normalized = _normalize_simple(question or "").strip()
    if not normalized:
        return None

    for command, phrases in PRODUCT_MEMORY_COMMANDS.items():
        for phrase in phrases:
            if _normalize_simple(phrase) in normalized:
                return command
    return None


class ProductMemory:
    def __init__(self, path=PRODUCT_MEMORY_FILE):
        self.path = path
        self.data = {
            "version": MEMORY_VERSION,
            "products": {},
            "learning": _empty_learning(),
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.data = {
                "version": MEMORY_VERSION,
                "products": {},
                "learning": _empty_learning(),
            }
            return

        self.data.setdefault("products", {})
        self.data.setdefault("learning", _empty_learning())
        learning = self.data["learning"]
        learning.setdefault("category_buckets", {})
        learning.setdefault("raw_categories", {})
        learning.setdefault("keywords", {})
        learning.setdefault("matched_laws", {})

        changed = False
        for record in self.data.get("products", {}).values():
            if record.pop("summary", None) is not None:
                changed = True
            if "analysis_count" not in record:
                record["analysis_count"] = 1
                changed = True
            if "last_analyzed_at" not in record:
                record["last_analyzed_at"] = record.get("analyzed_at", "")
                changed = True
            if record.get("analysis_version") != PRODUCT_ANALYSIS_VERSION:
                for stale_key in ("justifications", "recommendation", "recommendation_label"):
                    if record.pop(stale_key, None) is not None:
                        changed = True

        if self.data.get("version") != MEMORY_VERSION:
            self.data["version"] = MEMORY_VERSION
            changed = True

        if changed:
            self.save()

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _key(self, product):
        return product.get("asin") or product.get("url")

    def get(self, url=None, asin=None):
        products = self.data.get("products", {})
        if asin and asin in products:
            return products[asin]
        if url:
            for item in products.values():
                if item.get("url") == url:
                    return item
        return None

    def _increment_counter(self, bucket, key, amount=1):
        bucket[key] = int(bucket.get(key, 0)) + amount

    def _learn_from_product(self, product, analysis):
        learning = self.data.setdefault("learning", _empty_learning())
        category = product.get("category", "") or "غير متوفر"
        title = product.get("title", "") or ""

        bucket_id = classify_category_bucket(category, title)
        self._increment_counter(learning.setdefault("category_buckets", {}), bucket_id)

        raw_key = category.strip() or "غير متوفر"
        self._increment_counter(learning.setdefault("raw_categories", {}), raw_key)

        for keyword in _tokenize_product_text(f"{title} {category}"):
            self._increment_counter(learning.setdefault("keywords", {}), keyword)

        matched_laws = learning.setdefault("matched_laws", {})
        law_indices = analysis.get("law_indices", [])
        laws = analysis.get("laws", [])
        for index, law_text in zip(law_indices, laws):
            law_key = str(index)
            entry = matched_laws.setdefault(
                law_key,
                {"law_index": index, "text": law_text, "count": 0},
            )
            entry["text"] = law_text
            entry["count"] = int(entry.get("count", 0)) + 1

    def store(self, product, analysis):
        key = self._key(product) or f"product_{int(time.time())}"
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        products = self.data.setdefault("products", {})
        existing = products.get(key)

        if existing:
            analysis_count = int(existing.get("analysis_count", 1)) + 1
            first_analyzed_at = existing.get("first_analyzed_at") or existing.get("analyzed_at", now)
        else:
            analysis_count = 1
            first_analyzed_at = now

        record = {
            "url": product.get("url"),
            "asin": product.get("asin", ""),
            "title": product.get("title"),
            "category": product.get("category"),
            "price": product.get("price"),
            "rating": product.get("rating"),
            "review_count": product.get("review_count"),
            "first_analyzed_at": first_analyzed_at,
            "analyzed_at": first_analyzed_at,
            "last_analyzed_at": now,
            "analysis_count": analysis_count,
            "recommendation": analysis.get("recommendation"),
            "recommendation_label": analysis.get("recommendation_label"),
            "law_indices": analysis.get("law_indices", []),
            "laws": analysis.get("laws", []),
            "justifications": analysis.get("justifications", []),
            "sufficient": analysis.get("sufficient", True),
            "analysis_version": analysis.get("analysis_version", PRODUCT_ANALYSIS_VERSION),
        }
        products[key] = record
        self._learn_from_product(product, analysis)
        self.save()
        return record

    def record_reanalysis(self, record):
        if not record:
            return None

        key = record.get("asin") or record.get("url")
        if not key:
            return None

        products = self.data.setdefault("products", {})
        existing = products.get(key) or record
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        existing["analysis_count"] = int(existing.get("analysis_count", 1)) + 1
        existing["last_analyzed_at"] = now
        existing.setdefault("first_analyzed_at", existing.get("analyzed_at", now))
        products[key] = existing

        self._learn_from_product(
            existing,
            {
                "law_indices": existing.get("law_indices", []),
                "laws": existing.get("laws", []),
            },
        )
        self.save()
        return existing

    def _sorted_counter_items(self, counter, limit=10):
        items = sorted(counter.items(), key=lambda item: item[1], reverse=True)
        return items[:limit]

    def get_statistics(self):
        products = list(self.data.get("products", {}).values())
        learning = self.data.get("learning", _empty_learning())
        recommendations = {}
        total_analyses = 0

        for product in products:
            label = product.get("recommendation_label") or product.get("recommendation") or "غير محدد"
            recommendations[label] = recommendations.get(label, 0) + 1
            total_analyses += int(product.get("analysis_count", 1))

        return {
            "unique_products": len(products),
            "total_analyses": total_analyses,
            "recommendations": recommendations,
            "category_buckets": learning.get("category_buckets", {}),
            "raw_categories": learning.get("raw_categories", {}),
            "keywords": learning.get("keywords", {}),
            "matched_laws": learning.get("matched_laws", {}),
        }

    def format_statistics_report(self):
        stats = self.get_statistics()
        lines = [
            "إحصائيات ذاكرة المنتجات",
            "",
            f"عدد المنتجات المحللة: {stats['unique_products']}",
            f"إجمالي مرات التحليل: {stats['total_analyses']}",
            "",
            "توزيع التوصيات:",
        ]

        if stats["recommendations"]:
            for label, count in sorted(
                stats["recommendations"].items(),
                key=lambda item: item[1],
                reverse=True,
            ):
                lines.append(f"• {label}: {count}")
        else:
            lines.append("• لا توجد تحليلات محفوظة بعد.")

        lines.extend(["", "ملاحظة: ذاكرة المنتجات للتعلم السوقي فقط. قوانين صحرا هي مصدر القرار الوحيد."])
        return "\n".join(lines)

    def format_top_categories_report(self, limit=10):
        stats = self.get_statistics()
        lines = ["أكثر الفئات تحليلاً", ""]

        bucket_items = self._sorted_counter_items(stats["category_buckets"], limit=limit)
        if bucket_items:
            lines.append("الفئات العامة:")
            for bucket_id, count in bucket_items:
                label = CATEGORY_BUCKETS.get(bucket_id, {}).get("label_ar", bucket_id)
                lines.append(f"• {label}: {count}")
        else:
            lines.append("• لا توجد فئات محفوظة بعد.")

        raw_items = self._sorted_counter_items(stats["raw_categories"], limit=limit)
        if raw_items:
            lines.extend(["", "مسارات الفئات من أمازون:"])
            for category, count in raw_items:
                lines.append(f"• {category}: {count}")

        return "\n".join(lines)

    def format_top_laws_report(self, limit=10):
        stats = self.get_statistics()
        lines = ["أكثر قوانين صحرا تطابقاً في تحليل المنتجات", ""]

        law_entries = list(stats["matched_laws"].values())
        law_entries.sort(key=lambda item: int(item.get("count", 0)), reverse=True)

        if not law_entries:
            lines.append("• لا توجد قوانين مطابقة محفوظة بعد.")
            return "\n".join(lines)

        for entry in law_entries[:limit]:
            lines.append(f"• ({entry.get('count', 0)}) {entry.get('text', '')}")

        return "\n".join(lines)

    def format_top_keywords_report(self, limit=15):
        stats = self.get_statistics()
        lines = ["أكثر كلمات المنتجات تكراراً", ""]

        keyword_items = self._sorted_counter_items(stats["keywords"], limit=limit)
        if not keyword_items:
            lines.append("• لا توجد كلمات مفتاحية محفوظة بعد.")
            return "\n".join(lines)

        for keyword, count in keyword_items:
            lines.append(f"• {keyword}: {count}")

        return "\n".join(lines)

    def handle_command(self, command):
        handlers = {
            "stats": self.format_statistics_report,
            "top_categories": self.format_top_categories_report,
            "top_laws": self.format_top_laws_report,
            "top_keywords": self.format_top_keywords_report,
        }
        handler = handlers.get(command)
        return handler() if handler else None


def _normalize_simple(text):
    text = str(text).lower()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي")):
        text = text.replace(src, dst)
    return text


def _tokenize_simple(text):
    text = _normalize_simple(text)
    text = re.sub(r"[؟،؛:!?.,؛]+", " ", text)
    words = re.findall(r"[\u0600-\u06FF]+", text)
    cleaned = []
    for word in words:
        if len(word) > 2:
            if word.startswith("ال") and len(word) > 4:
                word = word[2:]
            cleaned.append(word)
    return cleaned


def _parse_rating(product):
    rating_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", str(product.get("rating", "")))
    if not rating_match:
        return None
    try:
        return float(rating_match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_review_count(product):
    review_digits = re.sub(r"[^\d]", "", str(product.get("review_count", "")))
    return int(review_digits) if review_digits else 0


def laws_are_sufficient(product, law_texts, match_score):
    if not law_texts:
        return False
    if match_score < MIN_LAW_MATCH_SCORE:
        return False

    product_terms = set(_tokenize_simple(product.get("title", "") + " " + product.get("category", "")))
    for law in law_texts:
        law_terms = set(_tokenize_simple(law))
        if product_terms & law_terms:
            return True

    return match_score >= 0.3


def build_analysis_query(product):
    return (
        f"تحليل منتج تجاري: {product['title']}. "
        f"الفئة: {product['category']}. "
        f"السعر: {product['price']}. "
        f"التقييم: {product['rating']}. "
        f"عدد المراجعات: {product['review_count']}. "
        f"هل هذا المنتج مناسب للتجارة الأخلاقية؟"
    )


def _matching_law_lines(laws):
    return [f"• {law}" for law in laws] if laws else ["• لا يوجد قانون مطابق."]


def _product_facts_block(product):
    return (
        f"العنوان: {product['title']}\n"
        f"السعر: {product['price']}\n"
        f"التقييم: {product['rating']}\n"
        f"عدد المراجعات: {product['review_count']}\n"
        f"الفئة: {product['category']}"
    )


def _law_text_normalized(laws):
    return _normalize_simple(" ".join(laws))


def _product_terms(product):
    return set(
        _tokenize_simple(
            f"{product.get('title', '')} {product.get('category', '')}"
        )
    )


def _law_terms(law):
    return set(_tokenize_simple(law))


def _product_law_conflict(product, laws):
    product_terms = _product_terms(product)
    if not product_terms:
        return False

    for law in laws:
        law_norm = _normalize_simple(law)
        if not any(risk_word in law_norm for risk_word in RISK_WORDS):
            continue
        if product_terms & _law_terms(law):
            return True
    return False


def _count_law_hits(law_norm, words):
    return sum(1 for word in words if word in law_norm)


def build_recommendation_reasons(product, laws):
    rating_value = _parse_rating(product)
    review_count = _parse_review_count(product)
    law_norm = _law_text_normalized(laws)
    reasons = []

    if rating_value is not None:
        reasons.append(f"التقييم المستخرج: {rating_value}")
    else:
        reasons.append("التقييم المستخرج: غير متوفر")

    reasons.append(f"عدد المراجعات المستخرج: {review_count}")

    if _product_law_conflict(product, laws):
        reasons.append(PRODUCT_RISK_CONFLICT_MESSAGE)
    else:
        reasons.append("المنتج لا يخالف أي قانون من قوانين صحرا.")

    for _key, keywords, message in LAW_REASON_RULES:
        if any(keyword in law_norm for keyword in keywords):
            if message not in reasons:
                reasons.append(message)

    return reasons


def infer_recommendation(product, laws):
    rating_value = _parse_rating(product)
    review_count = _parse_review_count(product)
    reasons = build_recommendation_reasons(product, laws)
    law_norm = _law_text_normalized(laws)

    has_conflict = _product_law_conflict(product, laws)
    positive_hits = _count_law_hits(law_norm, POSITIVE_WORDS)

    if has_conflict:
        return "not_suitable", RECOMMENDATION_LABELS["not_suitable"], reasons

    if rating_value is not None and rating_value < 3.5:
        return "needs_research", RECOMMENDATION_LABELS["needs_research"], reasons

    if review_count < 20:
        return "needs_research", RECOMMENDATION_LABELS["needs_research"], reasons

    if (
        positive_hits > 0
        and rating_value is not None
        and rating_value >= 4.0
        and review_count >= 20
    ):
        return "suitable", RECOMMENDATION_LABELS["suitable"], reasons

    if positive_hits > 0 and rating_value is not None and rating_value >= 3.5:
        return "suitable", RECOMMENDATION_LABELS["suitable"], reasons

    return "needs_research", RECOMMENDATION_LABELS["needs_research"], reasons


def _reasons_block(reasons):
    if not reasons:
        return ""
    lines = ["أسباب التوصية:"]
    for reason in reasons:
        lines.append(f"* {reason}")
    return "\n".join(lines)


def format_product_report(
    product,
    laws,
    recommendation_key,
    recommendation_label,
    justifications,
    sufficient=True,
    cached=False,
):
    cache_note = "\n\n[محفوظ من تحليل سابق]" if cached else ""

    facts = _product_facts_block(product)
    laws_block = "\n".join(_matching_law_lines(laws))
    reasons_block = _reasons_block(justifications)

    if not sufficient:
        return (
            "1) بيانات المنتج\n"
            f"{facts}\n\n"
            "2) قوانين صحرا المطابقة\n"
            f"{laws_block}\n\n"
            f"التوصية: {INSUFFICIENT_LAWS_MESSAGE}"
            f"{cache_note}"
        )

    parts = [
        "1) بيانات المنتج",
        facts,
        "",
        "2) قوانين صحرا المطابقة",
        laws_block,
        "",
        f"التوصية: {recommendation_label}",
    ]
    if reasons_block:
        parts.extend(["", reasons_block])
    if cache_note:
        parts.append(cache_note)

    return "\n".join(parts)


def is_cache_valid(cached):
    if not cached:
        return False
    return cached.get("analysis_version") == PRODUCT_ANALYSIS_VERSION
