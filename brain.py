"""
Sahra AI — Digital Neural Memory System

Each law in quran_memory.json is a neuron (read-only).
This module learns ONLY: keywords, tags, connections, usage statistics.
It NEVER creates, modifies, or deletes laws.
"""

import hashlib
import json
import logging
import os
import re
from collections import defaultdict

logger = logging.getLogger("sahra.neural")

BRAIN_MEMORY_FILE = "brain_memory.json"
BRAIN_VERSION = 1
MIN_WORD_LEN = 2
MAX_KEYWORDS_PER_NEURON = 40
MAX_TAGS_PER_NEURON = 30
MAX_RELATED_PER_NEURON = 25

STOP_WORDS = {
    "كيف", "ما", "هل", "من", "في", "على", "عن", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "التى", "ان", "او", "و", "لا", "لم", "لن", "اذا", "متى",
    "اين", "لماذا", "ماذا", "اي", "بين", "عند", "كل", "قد", "كان", "يكون",
    "هو", "هي", "هم", "نحن", "انت", "ان", "ثم", "لكن", "بل", "حتى",
    "الى", "إلى", "عندما", "اذ", "إذ", "انها", "انه", "هناك",
}


def normalize_arabic(text):
    text = text.lower()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(src, dst)
    return text


def tokenize(text):
    text = normalize_arabic(text)
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


def law_text(item):
    return item.get("result", "").strip()


def law_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def laws_fingerprint(laws):
    payload = json.dumps(
        [{"result": law_text(l)} for l in laws],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def extract_law_keywords(text):
    words = tokenize(text)
    seen = set()
    keywords = []
    for word in words:
        if word not in seen:
            seen.add(word)
            keywords.append(word)
    return keywords[:20]


def pair_key(a, b):
    a, b = int(a), int(b)
    return f"{min(a, b)}|{max(a, b)}"


class NeuralBrain:
    """In-memory neural graph over read-only Sahra laws."""

    def __init__(self, laws, memory_path=BRAIN_MEMORY_FILE):
        self.laws = laws
        self.memory_path = memory_path
        self.laws_fingerprint = laws_fingerprint(laws)

        self.neurons = {}
        self.question_memory = {}
        self.co_activation = {}
        self.keyword_index = defaultdict(set)

        self._load()
        self._sync_neurons()
        self._rebuild_keyword_index()

        if self._needs_auto_links():
            self.build_automatic_links()
            self.save()

    def _empty_state(self):
        return {
            "version": BRAIN_VERSION,
            "laws_fingerprint": self.laws_fingerprint,
            "neurons": {},
            "question_memory": {},
            "co_activation": {},
        }

    def _load(self):
        if not os.path.exists(self.memory_path):
            state = self._empty_state()
            self._apply_state(state)
            return

        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = self._empty_state()

        if state.get("laws_fingerprint") != self.laws_fingerprint:
            old_neurons = state.get("neurons", {})
            state = self._empty_state()
            state["neurons"] = self._migrate_neurons(old_neurons)

        self._apply_state(state)

    def _apply_state(self, state):
        self.neurons = state.get("neurons", {})
        self.question_memory = state.get("question_memory", {})
        self.co_activation = state.get("co_activation", {})

    def _migrate_neurons(self, old_neurons):
        migrated = {}
        hash_to_old = {}
        for nid, neuron in old_neurons.items():
            h = neuron.get("law_hash")
            if h:
                hash_to_old[h] = neuron

        for idx, law in enumerate(self.laws):
            text = law_text(law)
            h = law_hash(text)
            old = hash_to_old.get(h, {})
            migrated[str(idx)] = {
                "id": str(idx),
                "law_index": idx,
                "law_hash": h,
                "law_text": text,
                "keywords": old.get("keywords", extract_law_keywords(text)),
                "tags": old.get("tags", []),
                "related": old.get("related", {}),
                "strength": old.get("strength", 1.0),
                "usage_count": old.get("usage_count", 0),
            }
        return migrated

    def _sync_neurons(self):
        for idx, law in enumerate(self.laws):
            text = law_text(law)
            h = law_hash(text)
            nid = str(idx)

            if nid not in self.neurons:
                self.neurons[nid] = {
                    "id": nid,
                    "law_index": idx,
                    "law_hash": h,
                    "law_text": text,
                    "keywords": extract_law_keywords(text),
                    "tags": [],
                    "related": {},
                    "strength": 1.0,
                    "usage_count": 0,
                }
                continue

            neuron = self.neurons[nid]
            neuron["law_index"] = idx
            neuron["law_hash"] = h
            neuron["law_text"] = text

            if not neuron.get("keywords"):
                neuron["keywords"] = extract_law_keywords(text)

            neuron.setdefault("tags", [])
            neuron.setdefault("related", {})
            neuron.setdefault("strength", 1.0)
            neuron.setdefault("usage_count", 0)

        stale = [nid for nid in self.neurons if int(nid) >= len(self.laws)]
        for nid in stale:
            del self.neurons[nid]

    def _rebuild_keyword_index(self):
        self.keyword_index = defaultdict(set)
        for nid, neuron in self.neurons.items():
            for word in neuron.get("keywords", []) + neuron.get("tags", []):
                self.keyword_index[word].add(nid)

    def _needs_auto_links(self):
        if len(self.neurons) < 2:
            return False
        return not any(n.get("related") for n in self.neurons.values())

    def _trim_list(self, items, limit):
        return items[-limit:] if len(items) > limit else items

    def _strengthen_related(self, id_a, id_b, amount):
        if id_a == id_b:
            return

        for src, dst in ((id_a, id_b), (id_b, id_a)):
            neuron = self.neurons.get(src)
            if not neuron:
                continue
            related = neuron.setdefault("related", {})
            current = related.get(dst, 0.1)
            related[dst] = min(1.0, current + amount)

            if len(related) > MAX_RELATED_PER_NEURON:
                weakest = min(related, key=related.get)
                del related[weakest]

    def build_automatic_links(self):
        ids = list(self.neurons.keys())
        for i, id_a in enumerate(ids):
            words_a = set(self.neurons[id_a].get("keywords", []))
            if not words_a:
                continue

            for id_b in ids[i + 1 :]:
                words_b = set(self.neurons[id_b].get("keywords", []))
                shared = words_a & words_b
                if len(shared) >= 2:
                    strength = min(0.6, 0.15 + (len(shared) * 0.08))
                    self._strengthen_related(id_a, id_b, strength)

    def save(self):
        state = {
            "version": BRAIN_VERSION,
            "laws_fingerprint": self.laws_fingerprint,
            "neurons": self.neurons,
            "question_memory": self.question_memory,
            "co_activation": self.co_activation,
        }
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _question_key(self, question):
        return normalize_arabic(question).strip()

    def _similar_questions(self, terms):
        if not terms:
            return []

        q_terms = set(terms)
        matches = []
        for key, memory in self.question_memory.items():
            stored = set(memory.get("keywords", []))
            if not stored:
                continue
            overlap = len(q_terms & stored) / max(len(q_terms), 1)
            if overlap >= 0.45:
                matches.append((overlap, memory))
        return matches

    def apply_neural_scores(self, question, terms, base_scores):
        if not self.neurons or not base_scores:
            return base_scores

        boosts = [0.0] * len(base_scores)
        q_terms = set(terms) if terms else set(tokenize(question))
        q_key = self._question_key(question)

        exact_memory = self.question_memory.get(q_key)
        if exact_memory:
            repeat_boost = min(0.45, exact_memory.get("count", 0) * 0.06)
            for idx in exact_memory.get("law_indices", []):
                if 0 <= idx < len(boosts):
                    boosts[idx] += repeat_boost

        for overlap, memory in self._similar_questions(list(q_terms)):
            hist_boost = overlap * 0.22
            for idx in memory.get("law_indices", []):
                if 0 <= idx < len(boosts):
                    boosts[idx] += hist_boost

        candidate_ids = set()
        for term in q_terms:
            candidate_ids.update(self.keyword_index.get(term, ()))

        if not candidate_ids:
            candidate_ids = set(self.neurons.keys())

        activated = set()
        for nid in candidate_ids:
            neuron = self.neurons.get(nid)
            if not neuron:
                continue

            idx = neuron["law_index"]
            if idx >= len(boosts):
                continue

            neuron_words = set(neuron.get("keywords", []) + neuron.get("tags", []))
            if q_terms:
                match_ratio = len(q_terms & neuron_words) / len(q_terms)
            else:
                match_ratio = 0.0

            strength = float(neuron.get("strength", 1.0))
            usage = int(neuron.get("usage_count", 0))
            usage_boost = min(0.18, usage * 0.012)

            neural_score = (match_ratio * strength * 0.2) + usage_boost
            boosts[idx] += neural_score

            if match_ratio > 0.1:
                activated.add(nid)

        for nid in activated:
            neuron = self.neurons.get(nid)
            if not neuron:
                continue
            src_idx = neuron["law_index"]
            for rel_id, rel_strength in neuron.get("related", {}).items():
                rel = self.neurons.get(rel_id)
                if not rel:
                    continue
                rel_idx = rel["law_index"]
                if rel_idx < len(boosts):
                    boosts[rel_idx] += float(rel_strength) * 0.14

        activated_indices = {
            self.neurons[n]["law_index"] for n in activated if n in self.neurons
        }
        for key, co_strength in self.co_activation.items():
            parts = key.split("|")
            if len(parts) != 2:
                continue
            a, b = int(parts[0]), int(parts[1])
            if a in activated_indices and b < len(boosts):
                boosts[b] += float(co_strength) * 0.1
            if b in activated_indices and a < len(boosts):
                boosts[a] += float(co_strength) * 0.1

        return [base + boost for base, boost in zip(base_scores, boosts)]

    def learn(self, question, law_indices):
        if not law_indices:
            return

        terms = tokenize(question)
        q_key = self._question_key(question)

        if q_key not in self.question_memory:
            self.question_memory[q_key] = {
                "count": 0,
                "law_indices": [],
                "keywords": [],
            }

        q_memory = self.question_memory[q_key]
        q_memory["count"] = q_memory.get("count", 0) + 1
        q_memory["keywords"] = list(set(q_memory.get("keywords", []) + terms))[:30]
        q_memory["law_indices"] = list(set(q_memory.get("law_indices", []) + law_indices))

        unique_indices = sorted(set(law_indices))
        for idx in unique_indices:
            nid = str(idx)
            neuron = self.neurons.get(nid)
            if not neuron:
                continue

            neuron["usage_count"] = neuron.get("usage_count", 0) + 1
            neuron["strength"] = min(5.0, 1.0 + neuron["usage_count"] * 0.04)

            for term in terms[:12]:
                if term not in neuron["keywords"] and term not in neuron.get("tags", []):
                    neuron.setdefault("tags", []).append(term)
                    self.keyword_index[term].add(nid)

            neuron["keywords"] = self._trim_list(neuron.get("keywords", []), MAX_KEYWORDS_PER_NEURON)
            neuron["tags"] = self._trim_list(neuron.get("tags", []), MAX_TAGS_PER_NEURON)

        for i, idx_a in enumerate(unique_indices):
            for idx_b in unique_indices[i + 1 :]:
                key = pair_key(idx_a, idx_b)
                self.co_activation[key] = min(1.0, self.co_activation.get(key, 0.1) + 0.07)
                self._strengthen_related(str(idx_a), str(idx_b), 0.06)

        logger.info(
            "Neural memory learn | laws=%s | terms=%s | question=%s",
            unique_indices,
            terms[:8],
            q_key[:80],
        )
        self.save()

    def get_neuron_summary(self, law_index):
        neuron = self.neurons.get(str(law_index))
        if not neuron:
            return None
        return {
            "strength": neuron.get("strength"),
            "usage_count": neuron.get("usage_count"),
            "related_count": len(neuron.get("related", {})),
            "keywords_count": len(neuron.get("keywords", [])),
        }
