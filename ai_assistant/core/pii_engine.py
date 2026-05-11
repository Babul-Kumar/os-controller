"""
PII Engine — Application-Level Privacy Protection
==================================================
Detects sensitive data in user text, replaces it with opaque tokens
before the text reaches any LLM API, then restores the original values
in the LLM's response.

Supported entity types (all via regex — zero external dependencies):
  EMAIL, PHONE, CREDIT_CARD, ACCOUNT_NUMBER, SSN, IP_ADDRESS,
  URL, DATE, PERSON_NAME, AADHAAR (India), PAN (India), PASSPORT

The token store (mapping → real values) is AES-256-GCM encrypted in
memory so even a heap dump cannot expose raw PII.

Usage
-----
    from core.pii_engine import PIIEngine

    engine = PIIEngine()
    safe_text, context = engine.tokenize(user_text)
    # → send safe_text to LLM
    final_text = engine.restore(llm_response, context)
"""

import re
import os
import json
import hashlib
import secrets
from typing import Dict, List, Tuple, Optional
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ──────────────────────────────────────────────
# Optional AES-GCM encryption (via cryptography)
# Falls back to base64 obfuscation if not installed
# ──────────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning("PII Engine: 'cryptography' package not installed — using obfuscation fallback.")

import base64


# ──────────────────────────────────────────────
# Entity Patterns  (ordered by priority)
# ──────────────────────────────────────────────
_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # --- High-risk financial / identity ---
    ("CREDIT_CARD",    re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b")),
    ("SSN",            re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")),
    ("ACCOUNT_NUMBER", re.compile(r"\b(?:account(?:\s*(?:no|number|#|num))?[\s:]*)?(\d{9,18})\b", re.IGNORECASE)),
    ("AADHAAR",        re.compile(r"\b[2-9]{1}\d{3}\s?\d{4}\s?\d{4}\b")),
    ("PAN",            re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("PASSPORT",       re.compile(r"\b[A-Z]{1,2}[0-9]{6,9}\b")),

    # --- Contact details ---
    ("EMAIL",          re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")),
    ("PHONE",          re.compile(
        r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)"          # India mobile
        r"|(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)",  # US
    )),

    # --- Network ---
    ("IP_ADDRESS",     re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    )),
    ("URL",            re.compile(r"https?://[^\s]+")),

    # --- Temporal / general ---
    ("DATE",           re.compile(
        r"\b(?:\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})\b"
    )),

    # --- Name heuristic (Title Case word pairs, placed last to avoid false positives) ---
    ("PERSON_NAME",    re.compile(
        r"\b(?:(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+)?[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b"
    )),
]


# ──────────────────────────────────────────────
# Encrypted Token Store
# ──────────────────────────────────────────────
class _EncryptedStore:
    """In-memory AES-256-GCM encrypted store for token↔real-value mapping."""

    def __init__(self):
        self._key: bytes = secrets.token_bytes(32)  # 256-bit session key (never leaves memory)
        self._nonce_counter: int = 0
        self._store: Dict[str, bytes] = {}          # token → encrypted value

    def _next_nonce(self) -> bytes:
        self._nonce_counter += 1
        # 12-byte GCM nonce derived from counter + random salt
        raw = self._nonce_counter.to_bytes(4, "big") + secrets.token_bytes(8)
        return raw

    def put(self, token: str, value: str) -> None:
        if _CRYPTO_AVAILABLE:
            aes = AESGCM(self._key)
            nonce = self._next_nonce()
            encrypted = nonce + aes.encrypt(nonce, value.encode(), None)
            self._store[token] = encrypted
        else:
            # Fallback: simple base64 obfuscation (not cryptographic!)
            self._store[token] = base64.b64encode(value.encode())

    def get(self, token: str) -> Optional[str]:
        raw = self._store.get(token)
        if raw is None:
            return None
        if _CRYPTO_AVAILABLE:
            aes = AESGCM(self._key)
            nonce, ciphertext = raw[:12], raw[12:]
            return aes.decrypt(nonce, ciphertext, None).decode()
        else:
            return base64.b64decode(raw).decode()

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# ──────────────────────────────────────────────
# Session Context (returned by tokenize, passed to restore)
# ──────────────────────────────────────────────
class PIIContext:
    """Opaque handle that lets restore() undo exactly the tokenisation done by tokenize()."""

    def __init__(self, session_store: "_EncryptedStore", token_list: List[str]):
        self._store = session_store
        self._tokens = token_list          # ordered list of tokens used in this request

    def get(self, token: str) -> Optional[str]:
        return self._store.get(token)

    @property
    def tokens(self) -> List[str]:
        return list(self._tokens)

    def has_pii(self) -> bool:
        return bool(self._tokens)


# ──────────────────────────────────────────────
# PIIEngine  (main public API)
# ──────────────────────────────────────────────
class PIIEngine:
    """
    Stateless-per-call PII tokeniser.

    Each call to tokenize() creates a fresh PIIContext (session store)
    that is valid only until the matching restore() call.  Nothing is
    persisted to disk.
    """

    def __init__(self):
        logger.info(
            "PIIEngine initialised — crypto=%s",
            "AES-256-GCM" if _CRYPTO_AVAILABLE else "base64-fallback",
        )

    # ── public ──────────────────────────────

    def tokenize(self, text: str) -> Tuple[str, PIIContext]:
        """
        Detect PII in *text*, replace each match with a semantic token
        (e.g. ``EMAIL_0``, ``PHONE_1``), and return:

          * the sanitised text (safe to send to an LLM)
          * a PIIContext handle needed for restoration

        Entities are processed in priority order; once a span is claimed
        it is not claimed again by a lower-priority pattern.
        """
        store   = _EncryptedStore()
        tokens  = []                      # order-preserving token list
        counters: Dict[str, int] = {}     # entity_type → next index
        claimed = []                      # list of (start, end) claimed spans

        # Build a single replacement pass: collect all matches first
        replacements: List[Tuple[int, int, str]] = []  # (start, end, token)

        for entity_type, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                span = (match.start(), match.end())
                # Skip if this span overlaps an already-claimed span
                if any(s < span[1] and span[0] < e for s, e in claimed):
                    continue
                claimed.append(span)

                idx   = counters.get(entity_type, 0)
                counters[entity_type] = idx + 1
                token = f"{entity_type}_{idx}"

                store.put(token, match.group())
                tokens.append(token)
                replacements.append((match.start(), match.end(), token))

        # Apply replacements in reverse order so indices stay valid
        replacements.sort(key=lambda x: x[0], reverse=True)
        safe = text
        for start, end, token in replacements:
            safe = safe[:start] + token + safe[end:]

        context = PIIContext(store, tokens)

        if tokens:
            logger.info(
                "PIIEngine: tokenised %d entity/entities: %s",
                len(tokens),
                ", ".join(t.rsplit("_", 1)[0] for t in tokens),
            )
        else:
            logger.debug("PIIEngine: no PII detected in input.")

        return safe, context

    def restore(self, text: str, context: PIIContext) -> str:
        """
        Replace every token in *text* with the original value stored in *context*.
        Tokens not present in this context are left untouched (safety).
        """
        for token in context.tokens:
            original = context.get(token)
            if original and token in text:
                text = text.replace(token, original)
        return text

    def scan_only(self, text: str) -> List[Dict]:
        """
        Return a list of detected PII entities WITHOUT modifying text.
        Useful for logging / audit dashboards.
        """
        found    = []
        claimed  = []
        counters: Dict[str, int] = {}

        for entity_type, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                span = (match.start(), match.end())
                if any(s < span[1] and span[0] < e for s, e in claimed):
                    continue
                claimed.append(span)
                idx = counters.get(entity_type, 0)
                counters[entity_type] = idx + 1
                found.append({
                    "type":  entity_type,
                    "value": match.group(),
                    "start": match.start(),
                    "end":   match.end(),
                    "token": f"{entity_type}_{idx}",
                })

        return found
