"""面向用户输出的敏感信息清洗工具。"""

import re


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password)\b\s*([:=])\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_RE = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}\b", re.I)
_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password)=)[^&\s]+")
_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\|/home/|/opt/|/var/|/tmp/)[^\s`<>\"']+")


def redact_sensitive_text(value: object) -> str:
    """清洗 API Key、Bearer、敏感查询参数和服务端绝对路径。"""
    text = str(value or "")
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[已隐藏]", text)
    text = _BEARER_RE.sub("Bearer [已隐藏]", text)
    text = _KEY_RE.sub("[已隐藏密钥]", text)
    text = _QUERY_SECRET_RE.sub(r"\1[已隐藏]", text)
    return _PATH_RE.sub("[内部路径]", text)
