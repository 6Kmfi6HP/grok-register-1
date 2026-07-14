#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import ast
import json

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "grok_register_ttk.py"
CONFIG_EXAMPLE = ROOT / "config.example.json"


def read(path):
    return path.read_text(encoding="utf-8-sig")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


main = read(MAIN)

main = replace_once(
    main,
    '    "grok2api_allow_legacy_full_save": False,\n}',
    '    "grok2api_allow_legacy_full_save": False,\n'
    '    "email_provider": "duckmail",\n'
    '    "yyds_api_key": "",\n'
    '    "yyds_jwt": "",\n'
    '    "defaultDomains": "",\n'
    '}',
    "complete default config",
)

main = replace_once(
    main,
    '''    for key, allowed in enums.items():
        value = cfg.get(key, DEFAULT_CONFIG.get(key, ""))
        if value not in allowed:
            raise ConfigError(f"配置项 {key} 的值无效: {value!r}; 允许值: {sorted(allowed)}")
        cfg[key] = value
    return cfg
''',
    '''    for key, allowed in enums.items():
        value = cfg.get(key, DEFAULT_CONFIG.get(key, ""))
        if value not in allowed:
            raise ConfigError(f"配置项 {key} 的值无效: {value!r}; 允许值: {sorted(allowed)}")
        cfg[key] = value

    api_path_keys = {
        "cloudflare_path_domains", "cloudflare_path_accounts",
        "cloudflare_path_token", "cloudflare_path_messages",
        "cloudmail_path_messages",
    }
    for key in api_path_keys:
        value = cfg[key]
        if value and not value.startswith("/"):
            value = "/" + value
        cfg[key] = value

    url_keys = {
        "cloudflare_api_base", "cloudmail_api_base",
        "grok2api_remote_base", "cpa_base_url",
    }
    for key in url_keys:
        value = cfg[key]
        if not value:
            continue
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"配置项 {key} 必须是有效的 http/https URL")

    for key in path_keys:
        value = cfg[key]
        if value.startswith("~"):
            cfg[key] = os.path.expanduser(value)
    return cfg
''',
    "normalize validated config",
)

main = replace_once(
    main,
    '''    save_headers = dict(headers)
    if etag:
        save_headers["If-Match"] = etag
    elif log_callback:
        log_callback("[!] 旧版远端接口未提供 ETag；已由显式配置允许，但仍不建议多实例并发")
''',
    '''    if not etag:
        raise RemoteTokenCompatibilityError(
            "旧版远端接口未提供 ETag，无法保证并发安全，已拒绝全量保存"
        )
    save_headers = dict(headers)
    save_headers["If-Match"] = etag
''',
    "require ETag for legacy save",
)

main = replace_once(
    main,
    '''                if kind == "log":
                    line = event[1]
                    self.log_text.insert(tk.END, f"{line}\\n")
                    self.log_text.see(tk.END)
                elif kind == "stats":
''',
    '''                if kind == "log":
                    line = event[1]
                    self.log_text.insert(tk.END, f"{line}\\n")
                    self.log_text.see(tk.END)
                elif kind == "clear_log":
                    self.log_text.delete(1.0, tk.END)
                elif kind == "stats":
''',
    "GUI clear event",
)

main = replace_once(
    main,
    '''    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
''',
    '''    def clear_log(self):
        self.ui_queue.put(("clear_log",))
''',
    "queue clear log",
)

ast.parse(main, filename=str(MAIN))
MAIN.write_text(main, encoding="utf-8")

if CONFIG_EXAMPLE.exists():
    data = json.loads(read(CONFIG_EXAMPLE))
    data.setdefault("email_provider", "duckmail")
    data.setdefault("yyds_api_key", "")
    data.setdefault("yyds_jwt", "")
    data.setdefault("defaultDomains", "")
    data.setdefault("cpa_oidc_request_timeout_sec", 15)
    data.setdefault("cpa_oidc_poll_timeout_sec", 15)
    data.setdefault("grok2api_allow_legacy_full_save", False)
    CONFIG_EXAMPLE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

print("remaining review fixes applied")
