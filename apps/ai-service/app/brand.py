import re


REPLACEMENTS = (
    (re.compile(r"Shopee\s*VIP", re.IGNORECASE), "OmniVIP"),
    (re.compile(r"SPayLater", re.IGNORECASE), "OmniPayLater"),
    (re.compile(r"ShopeeFood", re.IGNORECASE), "OmniFood"),
    (re.compile(r"Shopee\s+Xu", re.IGNORECASE), "Omni Xu"),
    (re.compile(r"Shopee", re.IGNORECASE), "Omni"),
)


def omni_brand_text(value: str) -> str:
    result = value
    for pattern, replacement in REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result
