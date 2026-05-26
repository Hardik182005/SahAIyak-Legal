import re


_PATTERNS = [
    (r'\b[6-9]\d{9}\b', '[PHONE]'),
    (r'[\w.\-]+@[\w.\-]+\.\w{2,}', '[EMAIL]'),
    (r'\b\d{12}\b', '[AADHAR]'),
    (r'\b[A-Z]{5}\d{4}[A-Z]\b', '[PAN]'),
    (r'\b\d{6}\b', '[PINCODE]'),
    (r'(?i)\bAADHAR\s*:?\s*\d[\d\s]{10,}\d\b', '[AADHAR]'),
]


def anonymize(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text
