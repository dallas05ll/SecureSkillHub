"""
Compiled regex patterns for deterministic code analysis.

Each pattern group is a list of (name, compiled_regex) tuples.
All patterns are pre-compiled for performance and use re.IGNORECASE
where appropriate to catch trivial case-variation obfuscation.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class PatternEntry(NamedTuple):
    """A single named regex pattern used for scanning."""
    name: str
    pattern: re.Pattern[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile(name: str, raw: str, flags: int = 0) -> PatternEntry:
    return PatternEntry(name=name, pattern=re.compile(raw, flags))


# ---------------------------------------------------------------------------
# DANGEROUS_CALLS — shell execution, eval, dynamic code loading
# ---------------------------------------------------------------------------

DANGEROUS_CALLS: list[PatternEntry] = [
    # Python
    _compile("py_os_system",        r"\bos\s*\.\s*system\s*\(", re.IGNORECASE),
    _compile("py_os_popen",         r"\bos\s*\.\s*popen\s*\(", re.IGNORECASE),
    _compile("py_os_exec",          r"\bos\s*\.\s*exec[lv]p?e?\s*\(", re.IGNORECASE),
    _compile("py_os_spawn",         r"\bos\s*\.\s*spawn[lv]p?e?\s*\(", re.IGNORECASE),
    _compile("py_subprocess_call",  r"\bsubprocess\s*\.\s*(call|run|Popen|check_output|check_call|getoutput|getstatusoutput)\s*\("),
    _compile("py_eval",             r"\beval\s*\("),
    _compile("py_exec",             r"\bexec\s*\("),
    _compile("py_compile",          r"\bcompile\s*\(.*['\"]exec['\"]"),
    _compile("py_importlib",        r"\bimportlib\s*\.\s*import_module\s*\("),
    _compile("py___import__",       r"\b__import__\s*\("),
    _compile("py_ctypes",           r"\bctypes\s*\.\s*(cdll|windll|CDLL|WinDLL)"),
    _compile("py_pickle_loads",     r"\bpickle\s*\.\s*(loads?|Unpickler)\s*\("),
    # JavaScript / TypeScript
    _compile("js_child_process",    r"\bchild_process\s*\.\s*(exec|execFile|spawn|fork|execSync|spawnSync)\s*\("),
    _compile("js_eval",             r"\beval\s*\("),
    _compile("js_function_ctor",    r"\bnew\s+Function\s*\("),
    _compile("js_require_child",    r"""require\s*\(\s*['"]child_process['"]\s*\)"""),
    _compile("js_vm_run",           r"\bvm\s*\.\s*(runInNewContext|runInThisContext|createScript)\s*\("),
    _compile("js_setTimeout_str",   r"\bsetTimeout\s*\(\s*['\"]"),
    _compile("js_setInterval_str",  r"\bsetInterval\s*\(\s*['\"]"),
    _compile("shell_backtick_exec", r"`[^`]*\$\(.*\)[^`]*`"),
]

# ---------------------------------------------------------------------------
# NETWORK_OPS — outbound connections, HTTP clients, sockets
# ---------------------------------------------------------------------------

NETWORK_OPS: list[PatternEntry] = [
    # Python
    _compile("py_requests",         r"\brequests\s*\.\s*(get|post|put|delete|patch|head|options|request)\s*\("),
    _compile("py_urllib",           r"\burllib\s*\.\s*request\s*\.\s*(urlopen|urlretrieve|Request)\s*\("),
    _compile("py_urllib3",          r"\burllib3\s*\.\s*(PoolManager|HTTPConnectionPool|HTTPSConnectionPool)"),
    _compile("py_httpx",           r"\bhttpx\s*\.\s*(get|post|put|delete|patch|AsyncClient|Client)\s*\("),
    _compile("py_aiohttp",         r"\baiohttp\s*\.\s*ClientSession\s*\("),
    _compile("py_http_client",     r"\bhttp\s*\.\s*client\s*\.\s*(HTTPConnection|HTTPSConnection)\s*\("),
    _compile("py_socket",          r"\bsocket\s*\.\s*socket\s*\("),
    _compile("py_smtplib",         r"\bsmtplib\s*\.\s*SMTP\s*\("),
    _compile("py_ftplib",          r"\bftplib\s*\.\s*FTP\s*\("),
    _compile("py_paramiko",        r"\bparamiko\s*\.\s*(SSHClient|Transport)\s*\("),
    # JavaScript / TypeScript
    _compile("js_fetch",           r"\bfetch\s*\("),
    _compile("js_axios",           r"\baxios\s*\.\s*(get|post|put|delete|patch|request)\s*\("),
    _compile("js_http_request",    r"\bhttp[s]?\s*\.\s*(request|get)\s*\("),
    _compile("js_xmlhttprequest",  r"\bnew\s+XMLHttpRequest\s*\("),
    _compile("js_websocket",       r"\bnew\s+WebSocket\s*\("),
    _compile("js_net_socket",      r"\bnet\s*\.\s*(createConnection|createServer|Socket)\s*\("),
    _compile("js_dgram",          r"\bdgram\s*\.\s*createSocket\s*\("),
]

# ---------------------------------------------------------------------------
# FILE_OPS — filesystem reads, writes, deletions
# ---------------------------------------------------------------------------

FILE_OPS: list[PatternEntry] = [
    # Python
    _compile("py_open",            r"\bopen\s*\("),
    _compile("py_pathlib_write",   r"\bPath\s*\(.*\)\s*\.\s*(write_text|write_bytes|open)\s*\("),
    _compile("py_shutil",         r"\bshutil\s*\.\s*(copy|copy2|copytree|move|rmtree|make_archive)\s*\("),
    _compile("py_os_remove",      r"\bos\s*\.\s*(remove|unlink|rmdir|removedirs|rename|makedirs|mkdir)\s*\("),
    _compile("py_os_path",        r"\bos\s*\.\s*path\s*\.\s*(exists|join|abspath|realpath)\s*\("),
    _compile("py_tempfile",       r"\btempfile\s*\.\s*(NamedTemporaryFile|mkstemp|mkdtemp|TemporaryDirectory)\s*\("),
    _compile("py_glob",           r"\bglob\s*\.\s*(glob|iglob)\s*\("),
    _compile("py_io_open",        r"\bio\s*\.\s*open\s*\("),
    # JavaScript / TypeScript
    _compile("js_fs_write",       r"\bfs\s*\.\s*(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream)\s*\("),
    _compile("js_fs_read",        r"\bfs\s*\.\s*(readFile|readFileSync|readdir|readdirSync|createReadStream)\s*\("),
    _compile("js_fs_unlink",      r"\bfs\s*\.\s*(unlink|unlinkSync|rmdir|rmdirSync|rm|rmSync)\s*\("),
    _compile("js_fs_mkdir",       r"\bfs\s*\.\s*(mkdir|mkdirSync)\s*\("),
    _compile("js_fs_rename",      r"\bfs\s*\.\s*(rename|renameSync)\s*\("),
    _compile("js_fs_promises",    r"\bfs\s*\.\s*promises\s*\.\s*(readFile|writeFile|unlink|mkdir|rmdir|rename)\s*\("),
]

# ---------------------------------------------------------------------------
# ENV_ACCESS — environment variables, dotenv, config secrets
# ---------------------------------------------------------------------------

ENV_ACCESS: list[PatternEntry] = [
    # Python
    _compile("py_os_environ",      r"\bos\s*\.\s*environ\b"),
    _compile("py_os_getenv",       r"\bos\s*\.\s*getenv\s*\("),
    _compile("py_dotenv_load",     r"\b(load_dotenv|dotenv_values)\s*\("),
    _compile("py_os_putenv",       r"\bos\s*\.\s*putenv\s*\("),
    # JavaScript / TypeScript
    _compile("js_process_env",     r"\bprocess\s*\.\s*env\b"),
    _compile("js_dotenv_config",   r"\bdotenv\s*\.\s*config\s*\("),
    _compile("js_dotenv_require",  r"""require\s*\(\s*['"]dotenv['"]\s*\)"""),
    # Generic secret patterns
    _compile("generic_api_key",    r"""['"](?:api[_-]?key|api[_-]?secret|auth[_-]?token|access[_-]?token|secret[_-]?key)['"]\s*[:=]""", re.IGNORECASE),
    _compile("generic_password",   r"""['"](?:password|passwd|pwd|db_pass)['"]\s*[:=]\s*['"][^'"]+['"]""", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# OBFUSCATION — encoding tricks, dynamic string building, hex/unicode
#
# Split into HIGH_RISK (triggers safety override — real obfuscation) and
# LOW_RISK (reported as findings but doesn't trigger nuclear override —
# standard base64/encoding used for images, auth tokens, etc.)
# ---------------------------------------------------------------------------

OBFUSCATION_HIGH_RISK: list[PatternEntry] = [
    # These are rarely used in legitimate code and strongly signal obfuscation
    _compile("py_rot13",           r"""codecs\s*\.\s*decode\s*\(.*['\"]rot.?13['"]""", re.IGNORECASE),
    _compile("py_marshal_loads",   r"\bmarshal\s*\.\s*loads\s*\("),
    _compile("py_chr_concat",      r"\bchr\s*\(\s*\d+\s*\)\s*\+\s*chr\s*\("),
    _compile("js_string_fromCharCode", r"\bString\s*\.\s*fromCharCode\s*\("),
    _compile("hex_escape_seq",     r"(?:\\x[0-9a-fA-F]{2}){4,}"),
    _compile("unicode_escape_seq", r"(?:\\u[0-9a-fA-F]{4}){3,}"),
]

OBFUSCATION_LOW_RISK: list[PatternEntry] = [
    # Standard library usage — common in image handling, auth, data transfer
    _compile("py_base64_decode",   r"\bbase64\s*\.\s*(b64decode|b32decode|b16decode|decodebytes|urlsafe_b64decode)\s*\("),
    _compile("py_base64_encode",   r"\bbase64\s*\.\s*(b64encode|b32encode|b16encode|encodebytes|urlsafe_b64encode)\s*\("),
    _compile("py_codecs_decode",   r"\bcodecs\s*\.\s*decode\s*\("),
    _compile("py_zlib_decompress", r"\bzlib\s*\.\s*decompress\s*\("),
    _compile("js_atob",            r"\batob\s*\("),
    _compile("js_btoa",            r"\bbtoa\s*\("),
    _compile("js_buffer_from",     r"\bBuffer\s*\.\s*from\s*\(.*['\"](?:base64|hex)['\"]"),
    _compile("js_unescape",        r"\bunescape\s*\("),
    _compile("js_decodeURI",       r"\bdecodeURIComponent\s*\("),
    _compile("long_base64_literal", r"""['"][A-Za-z0-9+/=]{60,}['"]"""),
]

# Combined list for backward compatibility (scanner iterates this)
OBFUSCATION: list[PatternEntry] = OBFUSCATION_HIGH_RISK + OBFUSCATION_LOW_RISK

# ---------------------------------------------------------------------------
# INJECTION_PATTERNS — prompt injection / jailbreak attempts in code/docs
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: list[PatternEntry] = [
    _compile("system_override",    r"\bSYSTEM\s*:\s*(?:ignore|override|forget|disregard)", re.IGNORECASE),
    _compile("ignore_previous",    r"IGNORE\s+(ALL\s+)?PREVIOUS\s+(INSTRUCTIONS?|PROMPTS?)", re.IGNORECASE),
    _compile("forget_instructions", r"FORGET\s+(YOUR\s+)?(INSTRUCTIONS?|RULES?|GUIDELINES?)", re.IGNORECASE),
    _compile("you_are_now",        r"YOU\s+ARE\s+NOW\b", re.IGNORECASE),
    _compile("act_as",             r"\bACT\s+AS\s+(?:a\s+)?(?:DAN|unrestricted|unfiltered|jailbroken)", re.IGNORECASE),
    _compile("pretend_to_be",      r"\bPRETEND\s+(?:TO\s+BE|YOU\s+ARE)\s+(?:a\s+)?(?:DAN|unrestricted|unfiltered|jailbroken)", re.IGNORECASE),
    _compile("disregard",          r"\bDISREGARD\s+(ALL\s+)?(PREVIOUS|PRIOR|ABOVE)\b", re.IGNORECASE),
    _compile("new_instructions",   r"\bNEW\s+INSTRUCTIONS?\s*:", re.IGNORECASE),
    _compile("override_role",      r"\bOVERRIDE\s+(ROLE|MODE|SYSTEM)\b", re.IGNORECASE),
    _compile("jailbreak",          r"\b(JAILBREAK|DAN\s+MODE)\b", re.IGNORECASE),
    _compile("do_anything_now",    r"\bDO\s+ANYTHING\s+NOW\b", re.IGNORECASE),
    _compile("ignore_safety",      r"\bIGNORE\s+(SAFETY|RESTRICTIONS?|FILTERS?|GUARDRAILS?)\b", re.IGNORECASE),
    _compile("roleplay_escape",    r"\b(END|EXIT|LEAVE)\s+(ROLEPLAY|CHARACTER|SIMULATION)\b", re.IGNORECASE),
    _compile("hidden_instruction",  r"<!--.*?(?:SYSTEM\s*:|IGNORE\s+(?:PREVIOUS|ABOVE|ALL)|OVERRIDE\s+(?:ROLE|MODE)|INSTRUCTION\s*:).*?-->", re.IGNORECASE),
    # Only match when javascript:/data:/vbscript: is the URL protocol (right after open paren).
    # Previous pattern matched data: ANYWHERE in the URL, causing false positives on
    # shields.io badges with logo=data:image/svg+xml;base64,... (46 skills affected).
    _compile("markdown_injection", r"\[.*\]\(\s*(?:javascript|data|vbscript):.*\)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# SUSPICIOUS_URLS — potential exfiltration or C2 endpoints in code
# ---------------------------------------------------------------------------

SUSPICIOUS_URLS: list[PatternEntry] = [
    _compile("raw_ip_url",         r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"),
    _compile("ngrok_url",          r"https?://[a-z0-9-]+\.ngrok\.(io|app|dev)"),
    _compile("pastebin_url",       r"https?://(www\.)?pastebin\.(com|ca|org)"),
    _compile("webhook_site",       r"https?://webhook\.site"),
    _compile("requestbin_url",     r"https?://(www\.)?requestbin\.(com|net)"),
    _compile("pipedream_url",      r"https?://[a-z0-9]+\.m\.pipedream\.net"),
    _compile("burpcollaborator",   r"https?://[a-z0-9]+\.burpcollaborator\.net"),
    _compile("interactsh_url",     r"https?://[a-z0-9]+\.interactsh\.(com|net)"),
    _compile("discord_webhook",    r"https?://discord(app)?\.com/api/webhooks/"),
    _compile("telegram_bot_api",   r"https?://api\.telegram\.org/bot"),
    _compile("slack_webhook",      r"https?://hooks\.slack\.com/"),
    _compile("dynamic_dns",        r"https?://[a-z0-9-]+\.(duckdns\.org|no-ip\.(com|org)|dynu\.com|freedns\.afraid\.org)"),
    _compile("localhost_non_std",  r"https?://localhost:\d{4,5}(?!/api/v)"),
    _compile("data_uri_embed",     r"data:(?:text|application)/[a-z]+;base64,"),
]

# ---------------------------------------------------------------------------
# ALL_PATTERN_GROUPS — convenience mapping for iteration
# ---------------------------------------------------------------------------

ALL_PATTERN_GROUPS: dict[str, list[PatternEntry]] = {
    "dangerous_calls": DANGEROUS_CALLS,
    "network_ops": NETWORK_OPS,
    "file_ops": FILE_OPS,
    "env_access": ENV_ACCESS,
    "obfuscation": OBFUSCATION,
    "injection_patterns": INJECTION_PATTERNS,
    "suspicious_urls": SUSPICIOUS_URLS,
}

# Names of high-risk obfuscation patterns (triggers safety override)
OBFUSCATION_HIGH_RISK_NAMES: frozenset[str] = frozenset(
    entry.name for entry in OBFUSCATION_HIGH_RISK
)
