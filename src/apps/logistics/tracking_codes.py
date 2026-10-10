"""Shared tracking-code formats: preserve legacy bearer secrets alongside V2."""

import re

TRACKING_CODE_PREFIX = "MM-PCL-"
TRACKING_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TRACKING_CODE_SUFFIX_LENGTH = 39
# 39 * log2(31) = 193.213 bits, preserving the legacy token_hex(24) strength.
TRACKING_CODE_BODY_PATTERN = r"(?:[A-F0-9]{48}|MM-PCL-[A-HJKM-NP-Z2-9]{39})"
TRACKING_CODE_REGEX = r"\A" + TRACKING_CODE_BODY_PATTERN + r"\Z"
TRACKING_CODE_PATTERN = re.compile(TRACKING_CODE_REGEX)
TRACKING_CODE_INPUT_ERROR = "Enter a complete parcel tracking code (MM-PCL-… or a legacy code)."
