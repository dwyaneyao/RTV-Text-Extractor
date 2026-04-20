#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import queue
import re
import string
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


SUPPORTED_EXTENSIONS = {".gd", ".tscn", ".tres", ".cfg"}
MOD_ARCHIVE_EXTENSIONS = {".vmz", ".zip"}
RESOURCE_DISPLAY_PROPERTIES = {
    "text",
    "tooltip_text",
    "placeholder_text",
    "title",
    "description",
    "label",
}
CFG_DISPLAY_KEYS = {
    "name",
    "tooltip",
    "description",
    "label",
    "title",
    "friendlyName",
    "modFriendlyName",
    "modFriendlyDescription",
}
MCM_MOD_ID_RE = re.compile(r"\bMCM_MOD_ID\s*:?\s*=\s*([\"'])(.*?)\1")
GENERIC_MOD_ID_RE = re.compile(r"\bMOD_ID\s*:?\s*=\s*([\"'])(.*?)\1")
MANIFEST_VALUE_RE = re.compile(r'^([a-zA-Z0-9_]+)\s*=\s*"?(.+?)"?$')
GD_DICT_KEY_RE = re.compile(
    r"""(?ix)
    (?:["'])(name|tooltip|description|label|title|friendlyname|modfriendlyname|modfriendlydescription|options|rename|hover|message)(?:["'])
    \s*[:=]\s*$
    """
)
# camelCase canonical forms for MCM dict keys that are commonly spelled in lowercase
# in source but must be emitted with the right casing to match Main.gd's match rules.
GD_PROPERTY_CANONICAL_NAMES = {
    "friendlyname": "friendlyName",
    "modfriendlyname": "modFriendlyName",
    "modfriendlydescription": "modFriendlyDescription",
}
GD_FUNC_DEF_RE = re.compile(r"^(\s*)(?:static\s+)?func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)")
GD_DISPLAY_PARAM_ASSIGN_RE = re.compile(
    r"""(?x)
    \.(text|tooltip_text|placeholder_text|title|description|label|phrase)
    \s*=\s*
    ([A-Za-z_]\w*)
    \b
    """
)
# Per-extraction-run thread-local state so helpers like `infer_gd_property_name`
# can consult auto-detected sinks without threading the map through every caller.
_extract_context = threading.local()
PUNCTUATION_ONLY_RE = re.compile(r"^[%s\s]+$" % re.escape(string.punctuation))
NUMERIC_ONLY_RE = re.compile(r"^[\d\s\.\,\+\-\/\(\)\[\]\{\}\:\;%]+$")
IDENTIFIER_ONLY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PATHISH_RE = re.compile(
    r"^(?:[A-Za-z]:)?[\\/]|res://|user://|^.+\.(?:gd|tscn|tres|cfg|png|jpg|jpeg|ogg|wav|mp3|txt|json)$",
    re.IGNORECASE,
)
FORMAT_PLACEHOLDER_RE = re.compile(r"%(?:[-+#0-9\.\s]*)[sdif]")
GD_SET_VALUE_CALL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.set_value\(")
GD_PROPERTY_ASSIGN_RE = re.compile(
    r"""(?ix)
    (?:\.(text|tooltip_text|placeholder_text|title|description|label)\s*=)
    |
    (?:(["'])(name|tooltip|description|label|title|category|friendlyname|modfriendlyname|modfriendlydescription|options)\2\s*[:=])
    """
)
GD_CONST_STRING_ARRAY_RE = re.compile(
    r"""(?imsx)
    ^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[
    (.*?)
    \]
    \s*$
    """
)
GD_VAR_STRING_ARRAY_RE = re.compile(
    r"""(?imsx)
    ^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*[^=]+)?\s*=\s*\[
    (.*?)
    \]
    \s*$
    """
)
# String-based node lookups. Any literal captured here is treated as referenced
# by runtime name, so translating it could break `get_node`-style lookups.
GD_LOOKUP_CALL_RE = re.compile(
    r'\b(?:get_node(?:_or_null)?|find_child|find_node|has_node|NodePath)\s*\(\s*(["\'])([^"\']+)\1'
)
GD_DOLLAR_PATH_RE = re.compile(
    r'\$(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z_][A-Za-z0-9_/]*))'
)
GD_PERCENT_PATH_RE = re.compile(
    r'(?<![\w\)\]"\'])%(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z_][A-Za-z0-9_]*))'
)
GD_NAME_CMP_RE = re.compile(
    r'''(?:\bname\s*==\s*(["\'])([^"\']+)\1)|(?:(["\'])([^"\']+)\3\s*==\s*(?:\w+\.)?name\b)'''
)

LOCALE_LABELS = {
    "ar_ar": "Arabic (ar_ar)",
    "de_de": "Deutsch (de_de)",
    "es_es": "Espanol (es_es)",
    "it_it": "Italiano (it_it)",
    "ja_jp": "Japanese (ja_jp)",
    "ko_kr": "Korean (ko_kr)",
    "pt_br": "Portugues (pt_br)",
    "ru_ru": "Russian (ru_ru)",
    "us_us": "English (US) (us_us)",
    "zh_cn": "Chinese Simplified (zh_cn)",
    "zh_tw": "Chinese Traditional (zh_tw)",
}
LOCALE_ORDER = [
    "ar_ar",
    "de_de",
    "es_es",
    "it_it",
    "ja_jp",
    "ko_kr",
    "pt_br",
    "ru_ru",
    "us_us",
    "zh_cn",
    "zh_tw",
]

UI_LANGUAGE_LABELS = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
}

UI_TEXT = {
    "en": {
        "window_title": "RTV Text Extractor",
        "ui_language": "UI Language",
        "input_mode": "Input Mode",
        "mode_folder": "Whole mods folder",
        "mode_file": "Single mod archive (.vmz / .zip)",
        "input_path": "Input Path",
        "output_dir": "Output Directory",
        "export_locale": "Export Locale",
        "browse": "Browse",
        "start": "Start Extraction",
        "log": "Log",
        "file_dialog_title": "Select a mod archive (.vmz / .zip)",
        "folder_dialog_title": "Select the mods folder",
        "output_dialog_title": "Select the output directory",
        "error_title": "RTV Text Extractor",
        "missing_input": "Please choose an input path first.",
        "missing_output": "Please choose an output directory first.",
        "missing_locale": "Please choose an export locale first.",
        "start_log": "Starting extraction | mode={mode} | locale={locale}",
        "input_log": "Input: {path}",
        "output_log": "Output: {path}",
        "summary": "Extraction finished: processed={processed} skipped={skipped} failures={failures}",
    },
    "zh": {
        "window_title": "RTV 文本提取工具",
        "ui_language": "界面语言",
        "input_mode": "输入模式",
        "mode_folder": "整个 mods 文件夹",
        "mode_file": "单个 mod 压缩包（.vmz / .zip）",
        "input_path": "输入路径",
        "output_dir": "输出目录",
        "export_locale": "导出语言",
        "browse": "浏览",
        "start": "开始提取",
        "log": "日志",
        "file_dialog_title": "选择 mod 压缩包（.vmz / .zip）",
        "folder_dialog_title": "选择 mods 文件夹",
        "output_dialog_title": "选择输出目录",
        "error_title": "RTV 文本提取工具",
        "missing_input": "请先选择输入路径。",
        "missing_output": "请先选择输出目录。",
        "missing_locale": "请先选择导出语言。",
        "start_log": "开始提取 | mode={mode} | locale={locale}",
        "input_log": "输入：{path}",
        "output_log": "输出：{path}",
        "summary": "提取完成：processed={processed} skipped={skipped} failures={failures}",
    },
    "ja": {
        "window_title": "RTV テキスト抽出ツール",
        "ui_language": "UI 言語",
        "input_mode": "入力モード",
        "mode_folder": "mods フォルダー全体",
        "mode_file": "単一の mod アーカイブ（.vmz / .zip）",
        "input_path": "入力パス",
        "output_dir": "出力フォルダー",
        "export_locale": "出力ロケール",
        "browse": "参照",
        "start": "抽出開始",
        "log": "ログ",
        "file_dialog_title": "mod アーカイブを選択（.vmz / .zip）",
        "folder_dialog_title": "mods フォルダーを選択",
        "output_dialog_title": "出力フォルダーを選択",
        "error_title": "RTV テキスト抽出ツール",
        "missing_input": "先に入力パスを選択してください。",
        "missing_output": "先に出力フォルダーを選択してください。",
        "missing_locale": "先に出力ロケールを選択してください。",
        "start_log": "抽出を開始します | mode={mode} | locale={locale}",
        "input_log": "入力: {path}",
        "output_log": "出力: {path}",
        "summary": "抽出完了: processed={processed} skipped={skipped} failures={failures}",
    },
}


@dataclass(frozen=True)
class EntryRecord:
    source_path: str
    source_kind: str
    text: str
    where: dict


class ExtractionError(Exception):
    pass


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def normalize_locale(locale: str) -> str:
    return locale.strip().lower().replace("-", "_")


def parse_manifest(text: str) -> dict:
    manifest: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = MANIFEST_VALUE_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2).strip().strip('"')
        manifest[key] = value
    return manifest


def read_manifest_from_vmz(vmz_path: Path) -> dict:
    with zipfile.ZipFile(vmz_path, "r") as zf:
        manifest_names = [name for name in zf.namelist() if Path(name).name.lower() == "mod.txt"]
        if not manifest_names:
            raise ExtractionError("missing mod.txt")
        manifest_text = decode_text(zf.read(manifest_names[0]))
    manifest = parse_manifest(manifest_text)
    if not manifest.get("id"):
        raise ExtractionError("mod.txt missing id")
    return manifest


def find_vmz_files(mode: str, input_path: Path) -> list[Path]:
    if mode == "file":
        if input_path.suffix.lower() not in MOD_ARCHIVE_EXTENSIONS:
            raise ExtractionError("selected file is not a .vmz or .zip mod archive")
        return [input_path]
    if not input_path.is_dir():
        raise ExtractionError("selected folder does not exist")
    return sorted(
        path for path in input_path.iterdir()
        if path.is_file() and path.suffix.lower() in MOD_ARCHIVE_EXTENSIONS
    )


def read_vmz_text_files(vmz_path: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    with zipfile.ZipFile(vmz_path, "r") as zf:
        for name in sorted(zf.namelist()):
            suffix = Path(name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                continue
            files[name] = decode_text(zf.read(name))
    return files


def scan_string_literal(text: str, start_index: int, delimiter: str) -> tuple[str, int] | None:
    i = start_index + 1
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue
        if ch == delimiter:
            return text[start_index + 1 : i], i + 1
        i += 1
    return None


def infer_gd_property_name(prefix: str) -> str:
    lowered = prefix.lower()
    if ".text =" in lowered:
        return "text"
    if ".tooltip_text =" in lowered:
        return "tooltip_text"
    if ".placeholder_text =" in lowered:
        return "placeholder_text"
    if ".title =" in lowered:
        return "title"
    if ".description =" in lowered:
        return "description"
    if ".label =" in lowered:
        return "label"
    if ".phrase =" in lowered:
        # RtV item-action verb shown in the right-click menu (e.g. "Heal", "Read",
        # "Tear into rags"). Items' phrase field drives the verb label the player sees.
        return "phrase"

    match = GD_DICT_KEY_RE.search(prefix)
    if match:
        key = match.group(1)
        lowered_key = key.lower()
        if lowered_key in GD_PROPERTY_CANONICAL_NAMES:
            return GD_PROPERTY_CANONICAL_NAMES[lowered_key]
        if lowered_key == "category":
            return "category"
        return key
    register_property = infer_register_mcm_property(prefix)
    if register_property:
        return register_property
    auto = infer_auto_sink_property(prefix)
    if auto:
        return auto
    return ""


def normalize_gd_property_name(property_name: str) -> str:
    return GD_PROPERTY_CANONICAL_NAMES.get(property_name.lower(), property_name)


def infer_active_gd_property_name(prefix: str) -> str:
    direct = infer_gd_property_name(prefix)
    if direct:
        return direct

    active_property = ""
    active_pos = -1
    for match in GD_PROPERTY_ASSIGN_RE.finditer(prefix):
        if match.start() < active_pos:
            continue
        if match.group(1):
            active_property = match.group(1)
        else:
            active_property = normalize_gd_property_name(match.group(3))
        active_pos = match.start()

    set_value_property = infer_set_value_argument_property(prefix)
    if set_value_property:
        return set_value_property

    register_property = infer_register_mcm_property(prefix)
    if register_property:
        return register_property
    return active_property


def count_top_level_commas(text: str) -> int:
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    i = 0
    count = 0
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(text, i, ch)
            if parsed:
                _, i = parsed
                continue
        elif ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        elif ch == "{":
            depth_brace += 1
        elif ch == "}" and depth_brace > 0:
            depth_brace -= 1
        elif ch == "," and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
            count += 1
        i += 1
    return count


def _split_gd_param_names(raw: str) -> list[str]:
    # Split a GDScript parameter list on top-level commas and return the leading
    # identifier of each entry. Handles `name`, `name: Type`, `name := default`,
    # and nested types like `Array[String]`.
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in raw:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    names: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        m = re.match(r"([A-Za-z_]\w*)", stripped)
        if m:
            names.append(m.group(1))
    return names


def _iter_gd_function_bodies(source_text: str):
    # Yield (name, params, body_lines) for each top-level or nested func. Body
    # is collected while indentation exceeds the function header's own indent.
    lines = source_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = GD_FUNC_DEF_RE.match(line)
        if not m:
            i += 1
            continue
        header_indent = len(m.group(1))
        name = m.group(2)
        params = _split_gd_param_names(m.group(3))
        body: list[str] = []
        i += 1
        while i < len(lines):
            nline = lines[i]
            if not nline.strip():
                body.append(nline)
                i += 1
                continue
            cur_indent = len(nline) - len(nline.lstrip())
            if cur_indent <= header_indent:
                break
            body.append(nline)
            i += 1
        yield name, params, body


def _extract_call_args_after_paren(text: str, start_after_open_paren: int) -> list[str]:
    # Return the comma-separated arg strings between the open paren at
    # start_after_open_paren-1 and its matching close paren. Returns [] if
    # the call is unterminated.
    depth = 1
    i = start_after_open_paren
    args: list[str] = []
    cur = ""
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(text, i, ch)
            if not parsed:
                return []
            _, end = parsed
            cur += text[i:end]
            i = end
            continue
        if ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                if cur.strip() or args:
                    args.append(cur)
                return args
            cur += ch
        elif ch == "," and depth == 1:
            args.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    return []


def build_auto_sinks(source_text: str) -> dict[str, dict[int, str]]:
    # Auto-detect display-sink wrapper functions: user-defined funcs whose
    # string parameter is directly assigned to a display property (e.g.
    # `btn.text = text`) or forwarded into an already-known sink. Returns a
    # map `{func_name: {arg_index: property_name}}`. Transitive closure
    # propagates through chains like `_combo` → `_make_button` → `btn.text`.
    sinks: dict[str, dict[int, str]] = {}
    funcs = list(_iter_gd_function_bodies(source_text))

    for name, params, body in funcs:
        if not params:
            continue
        param_index = {p: i for i, p in enumerate(params)}
        for raw_line in body:
            if is_gd_comment_line(raw_line):
                continue
            for m in GD_DISPLAY_PARAM_ASSIGN_RE.finditer(raw_line):
                prop = m.group(1)
                rhs = m.group(2)
                if rhs in param_index:
                    sinks.setdefault(name, {}).setdefault(param_index[rhs], prop)

    changed = True
    while changed:
        changed = False
        for name, params, body in funcs:
            if not params:
                continue
            param_index = {p: i for i, p in enumerate(params)}
            body_text = "\n".join(body)
            for callee, slots in list(sinks.items()):
                call_re = re.compile(rf"(?<![\w.]){re.escape(callee)}\s*\(")
                for call_match in call_re.finditer(body_text):
                    args = _extract_call_args_after_paren(body_text, call_match.end())
                    if not args:
                        continue
                    for slot_idx, prop in slots.items():
                        if slot_idx >= len(args):
                            continue
                        arg_text = args[slot_idx].strip()
                        id_m = re.match(r"([A-Za-z_]\w*)", arg_text)
                        if not id_m:
                            continue
                        arg_name = id_m.group(1)
                        if arg_name not in param_index:
                            continue
                        a_idx = param_index[arg_name]
                        existing = sinks.setdefault(name, {}).get(a_idx)
                        if existing != prop:
                            sinks.setdefault(name, {})[a_idx] = prop
                            changed = True
    return sinks


def _current_auto_sinks() -> dict[str, dict[int, str]]:
    return getattr(_extract_context, "auto_sinks", None) or {}


def infer_auto_sink_property(prefix: str) -> str:
    sinks = _current_auto_sinks()
    if not sinks:
        return ""
    # Walk right-to-left over `prefix` to locate the innermost unclosed `(`;
    # that paren is the call that directly contains the upcoming literal.
    depth = 0
    i = len(prefix) - 1
    open_paren_pos = -1
    while i >= 0:
        ch = prefix[i]
        if ch in ("'", '"'):
            # Skip over a string literal by scanning left to the matching quote,
            # respecting backslash escapes.
            j = i - 1
            found = -1
            while j >= 0:
                if prefix[j] == ch:
                    backslashes = 0
                    k = j - 1
                    while k >= 0 and prefix[k] == "\\":
                        backslashes += 1
                        k -= 1
                    if backslashes % 2 == 0:
                        found = j
                        break
                j -= 1
            if found < 0:
                return ""
            i = found - 1
            continue
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                open_paren_pos = i
                break
            depth -= 1
        i -= 1
    if open_paren_pos < 0:
        return ""
    name_end = open_paren_pos
    j = name_end - 1
    while j >= 0 and (prefix[j].isalnum() or prefix[j] == "_"):
        j -= 1
    func_name = prefix[j + 1 : name_end]
    if not func_name or func_name not in sinks:
        return ""
    # Reject method-call syntax (`foo.bar(...)`) to avoid collisions with
    # unrelated `obj.bar(` accessors that happen to share the helper name.
    if j >= 0 and prefix[j] == ".":
        return ""
    args_prefix = prefix[open_paren_pos + 1 :]
    arg_index = count_top_level_commas(args_prefix)
    return sinks[func_name].get(arg_index, "")


def first_string_literal(text: str) -> str:
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(text, i, ch)
            if parsed:
                literal, _ = parsed
                return literal
        i += 1
    return ""


def infer_set_value_argument_property(prefix: str) -> str:
    lowered = prefix.lower()
    for marker in (".set_value(", ".get_value("):
        marker_pos = lowered.rfind(marker)
        if marker_pos < 0:
            continue

        args_prefix = prefix[marker_pos + len(marker) :]
        comma_count = count_top_level_commas(args_prefix)
        if comma_count != 1:
            continue

        if marker == ".get_value(":
            return "config_key"

        first_arg = first_string_literal(args_prefix).lower()
        if first_arg == "category":
            return "category"
        return "config_key"
    return ""


def infer_register_mcm_property(prefix: str) -> str:
    lowered = prefix.lower()
    markers = (
        "registerconfiguration(",
        "registerconfigruation(",
        "_call_mcm_register_configuration(",
        ".call(",
    )
    marker_pos = -1
    marker_text = ""
    for marker in markers:
        pos = lowered.rfind(marker)
        if pos > marker_pos:
            marker_pos = pos
            marker_text = marker
    if marker_pos < 0:
        return ""

    args_prefix = prefix[marker_pos + len(marker_text) :]
    comma_count = args_prefix.count(",")
    if marker_text == ".call(":
        if not args_prefix.strip().startswith("register_method"):
            return ""
        if comma_count == 2:
            return "friendlyName"
        if comma_count == 4:
            return "description"
        return ""
    if marker_text == "_call_mcm_register_configuration(":
        if comma_count == 0:
            return "friendlyName"
        if comma_count == 1:
            return "description"
        return ""

    if comma_count == 1:
        return "friendlyName"
    if comma_count == 3:
        return "description"
    return ""


def infer_gd_is_mcm_context(prefix: str) -> bool:
    lowered = prefix.lower()
    return any(
        token in lowered
        for token in (
            "mcm_",
            "registerconfiguration(",
            "registerconfigruation(",
            "checkconfigurationhasupdated(",
            "checkconfigruationhasupdated(",
        )
    ) or GD_SET_VALUE_CALL_RE.search(prefix) is not None


def is_gd_comment_line(raw_line: str) -> bool:
    return raw_line.lstrip().startswith("#")


def strip_gd_comment_lines(text: str) -> str:
    return "\n".join("" if is_gd_comment_line(line) else line for line in text.splitlines())


def is_non_display_gd_prefix(prefix: str) -> bool:
    lowered = prefix.rstrip().lower()
    stripped = lowered.lstrip()

    if stripped.startswith("const "):
        return True
    return any(
        lowered.endswith(token)
        for token in (
            ".file =",
            "file =",
            ".inventory =",
            "inventory =",
            ".equipment =",
            "equipment =",
            ".rotated =",
            "rotated =",
            ".section =",
            "section =",
            ".key =",
            "key =",
            ".value =",
            "value =",
            ".type =",
            "type =",
            ".path =",
            "path =",
            ".nodepath =",
            "nodepath =",
        )
    )


def is_gd_indexer_key(prefix: str, suffix: str) -> bool:
    trimmed_prefix = prefix.rstrip()
    if trimmed_prefix.endswith("["):
        return True

    lowered = trimmed_prefix.lower()
    if lowered.endswith(".get(") or lowered.endswith("get("):
        return True
    if lowered.endswith(".has(") or lowered.endswith("has("):
        return True
    if lowered.endswith(".get_value(") or lowered.endswith("get_value("):
        return True

    return suffix.lstrip().startswith("]")


def is_gd_dict_key(prefix: str, suffix: str) -> bool:
    trimmed_suffix = suffix.lstrip()
    if trimmed_suffix.startswith(":"):
        return True
    if trimmed_suffix.startswith("=") and not trimmed_suffix.startswith(("==", "=~", "=>")):
        return True
    return False


GD_NAME_ASSIGN_RE = re.compile(r"(?:^|\W)(?:[A-Za-z_]\w*\.)?name\s*=$")


def is_gd_node_name_assign(prefix: str) -> bool:
    """Detect `node.name = "X"` or bare `name = "X"` — node-name assignment.

    Distinct from `display_name = "X"` (whose prefix has no `.name =` boundary).
    """
    trimmed = prefix.rstrip()
    stripped = trimmed.lstrip()
    if stripped == "name =" or stripped == "self.name =":
        return True
    return bool(GD_NAME_ASSIGN_RE.search(trimmed))


def should_skip_literal(literal: str, prefix: str, property_name: str, is_mcm: bool) -> bool:
    text = literal.strip()
    prefix_lower = prefix.rstrip().lower()

    if not text:
        return True
    if PATHISH_RE.search(text):
        return True
    if PUNCTUATION_ONLY_RE.match(text):
        return True
    if NUMERIC_ONLY_RE.match(text):
        return True
    if FORMAT_PLACEHOLDER_RE.search(text):
        # Only skip if the format string has no translatable content besides placeholders
        # (e.g. "%d/%d" or "%s"). Keep strings like "Enemies Killed: %s/%s".
        stripped_fmt = FORMAT_PLACEHOLDER_RE.sub("", text)
        if not re.search(r"[A-Za-z\u00c0-\uffff]{2,}", stripped_fmt):
            return True
    if "\n" in text and not re.search(r"[A-Za-z\u0080-\uffff]", text):
        return True
    if len(text) <= 2 and re.fullmatch(r"[A-Za-z]+", text):
        return True
    if len(text) <= 2 and not any(ch.isalnum() for ch in text):
        return True
    if prefix_lower.endswith(".name =") or prefix_lower.endswith("name ="):
        return True
    if prefix_lower.endswith(".id =") or prefix_lower.endswith("id ="):
        return True
    if prefix_lower.endswith("class_name"):
        return True
    if prefix_lower.endswith("get_node(") or prefix_lower.endswith("has_node("):
        return True
    if prefix_lower.endswith("load(") or prefix_lower.endswith("preload("):
        return True
    if is_non_display_gd_prefix(prefix):
        return True
    if not property_name:
        return True
    if property_name in {"config_key", "config_type"}:
        return True
    if not is_mcm and property_name == "name":
        return True
    if IDENTIFIER_ONLY_RE.match(text) and not is_mcm and property_name not in {"text", "title", "label", "category", "rename", "hover", "message", "phrase"}:
        return True
    return False


def canonical_where(where: dict) -> str:
    return json.dumps(where, ensure_ascii=False, sort_keys=True)


def build_file_where(source_path: str, source_kind: str, is_mcm: bool, mcm_mod_ids: list[str], property_name: str) -> dict:
    where: dict[str, object] = {}
    if source_kind == "script":
        where["script_path_contains"] = source_path
    else:
        where["scene_path_contains"] = source_path
    if is_mcm:
        where["is_mcm"] = True
        if mcm_mod_ids:
            where["mcm_mod_id"] = mcm_mod_ids[0] if len(mcm_mod_ids) == 1 else list(mcm_mod_ids)
    if property_name:
        where["property"] = "options"
        if property_name != "options":
            where["property"] = property_name
    return where


def build_gd_line_contexts(text: str) -> dict[int, bool]:
    contexts: dict[int, bool] = {}
    in_mcm_set_value = False
    in_mcm_register = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if is_gd_comment_line(raw_line):
            contexts[line_number] = False
            continue
        line = raw_line.strip()

        if GD_SET_VALUE_CALL_RE.search(raw_line):
            in_mcm_set_value = True
        if "RegisterConfiguration(" in raw_line or "RegisterConfigruation(" in raw_line or "_call_mcm_register_configuration(" in raw_line:
            in_mcm_register = True

        contexts[line_number] = in_mcm_set_value or in_mcm_register

        if in_mcm_set_value and line.endswith("})"):
            in_mcm_set_value = False
        if in_mcm_register and line == ")":
            in_mcm_register = False

    return contexts


def collect_gd_lookup_names(text_files: dict[str, str]) -> set[str]:
    """Collect every literal referenced via string-based node lookups across a mod.

    A literal appearing here is known to drive runtime behavior (get_node,
    find_child, $Path, %UniqueName, name == "X", etc.), so translating its
    .name = assignment would risk breaking those lookups.
    """
    names: set[str] = set()

    def _add_path(raw: str) -> None:
        if not raw:
            return
        for segment in raw.split("/"):
            segment = segment.strip()
            if len(segment) < 2 or segment in {".", ".."}:
                continue
            names.add(segment)

    for source_path, text in text_files.items():
        if not source_path.lower().endswith(".gd"):
            continue
        active_text = strip_gd_comment_lines(text)
        for match in GD_LOOKUP_CALL_RE.finditer(active_text):
            _add_path(match.group(2))
        for match in GD_DOLLAR_PATH_RE.finditer(active_text):
            _add_path(match.group(1) or match.group(2) or match.group(3))
        for match in GD_PERCENT_PATH_RE.finditer(active_text):
            _add_path(match.group(1) or match.group(2) or match.group(3))
        for match in GD_NAME_CMP_RE.finditer(active_text):
            value = match.group(2) or match.group(4)
            if value:
                names.add(value)
    return names


def collect_ambiguous_gd_literals(text: str, lookup_names: set[str] | None = None) -> set[str]:
    line_contexts = build_gd_line_contexts(text)
    literal_states: dict[str, dict[str, bool]] = {}

    for line_number, line in enumerate(text.splitlines(), start=1):
        if is_gd_comment_line(line):
            continue
        i = 0
        while i < len(line):
            ch = line[i]
            if ch not in ("'", '"'):
                i += 1
                continue

            parsed = scan_string_literal(line, i, ch)
            if not parsed:
                i += 1
                continue

            literal, end_index = parsed
            prefix = line[:i]
            property_name = infer_active_gd_property_name(prefix)
            is_mcm = line_contexts.get(line_number, False) or infer_gd_is_mcm_context(prefix)
            suffix = line[end_index:]
            if property_name == "config_key":
                i = end_index
                continue
            is_safe = (
                property_name
                and not is_gd_indexer_key(prefix, suffix)
                and not is_gd_dict_key(prefix, suffix)
                and not should_skip_literal(literal, prefix, property_name, is_mcm)
            )
            state = literal_states.setdefault(
                literal,
                {"safe": False, "unsafe": False, "unsafe_only_name_assign": True},
            )
            if is_safe:
                state["safe"] = True
            else:
                state["unsafe"] = True
                # A literal is a promotion candidate only if EVERY unsafe
                # occurrence is a pure node-name assignment (node.name = "X").
                # Dict keys, match cases, indexer keys, or other non-display
                # contexts indicate real code structure — never promote those.
                is_pure_name_assign = (
                    is_gd_node_name_assign(prefix)
                    and not is_gd_indexer_key(prefix, suffix)
                    and not is_gd_dict_key(prefix, suffix)
                )
                if not is_pure_name_assign:
                    state["unsafe_only_name_assign"] = False
            i = end_index

    ambiguous: set[str] = set()
    for literal, state in literal_states.items():
        if not (state["safe"] and state["unsafe"]):
            continue
        # Promote to safe only when:
        #   - every unsafe occurrence is a `.name =` node-name assignment, AND
        #   - no code path looks the literal up by string (get_node, $X, %X, ...).
        if (
            lookup_names is not None
            and state["unsafe_only_name_assign"]
            and literal not in lookup_names
        ):
            continue
        ambiguous.add(literal)
    return ambiguous


def extract_gd_options_arrays(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
    ambiguous_literals: set[str],
) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    active_text = strip_gd_comment_lines(text)
    pattern = re.compile(r'["\']options["\']\s*[:=]\s*\[(.*?)\]', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(active_text):
        block = match.group(1)
        for quote_match in re.finditer(r'(["\'])(.*?)(?<!\\)\1', block, re.DOTALL):
            literal = quote_match.group(2)
            if literal in ambiguous_literals:
                continue
            if should_skip_literal(literal, "", "options", True):
                continue
            where = build_file_where(source_path, "script", True, mcm_mod_ids, "options")
            key = (literal, canonical_where(where))
            if key in seen:
                continue
            seen.add(key)
            records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))
    return records


def find_call_block_end(text: str, start_index: int) -> int:
    depth = 0
    i = start_index
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(text, i, ch)
            if not parsed:
                return -1
            _, end_index = parsed
            i = end_index
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def iter_call_string_arguments(block: str) -> Iterable[tuple[int, str]]:
    open_paren = block.find("(")
    if open_paren < 0:
        return []

    arg_index = 0
    depth = 1
    i = open_paren + 1
    results: list[tuple[int, str]] = []
    while i < len(block):
        ch = block[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(block, i, ch)
            if not parsed:
                break
            literal, end_index = parsed
            if depth == 1:
                results.append((arg_index, literal))
            i = end_index
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth <= 0:
                break
        elif ch == "," and depth == 1:
            arg_index += 1
        i += 1
    return results


def iter_call_identifier_arguments(block: str) -> Iterable[tuple[int, str]]:
    """Yield (arg_index, identifier) for bare identifier arguments at top level.

    Skips literals, calls, dotted access, expressions. Used to resolve simple
    constant references like RegisterConfiguration(MOD_ID, MOD_NAME, ...).
    """
    open_paren = block.find("(")
    if open_paren < 0:
        return []

    results: list[tuple[int, str]] = []
    arg_index = 0
    depth = 1
    i = open_paren + 1
    token_start = i

    def _flush(end: int) -> None:
        token = block[token_start:end].strip()
        if IDENTIFIER_ONLY_RE.match(token):
            results.append((arg_index, token))

    while i < len(block):
        ch = block[i]
        if ch in ("'", '"'):
            parsed = scan_string_literal(block, i, ch)
            if not parsed:
                break
            i = parsed[1]
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth <= 0:
                _flush(i)
                break
        elif ch == "," and depth == 1:
            _flush(i)
            arg_index += 1
            token_start = i + 1
        i += 1
    return results


def scan_gd_string_constants(text: str) -> dict[str, str]:
    """Map file-scope string constants (`const NAME := "..."`) to their values.

    Supports optional type annotation and both `=` and `:=` assignment. Only
    single-line definitions whose RHS is a lone string literal are captured;
    concatenations, expressions, and multi-line forms are skipped.
    """
    constants: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("const "):
            continue
        remainder = stripped[len("const ") :].lstrip()
        j = 0
        while j < len(remainder) and (remainder[j].isalnum() or remainder[j] == "_"):
            j += 1
        name = remainder[:j]
        if not name:
            continue
        rest = remainder[j:].lstrip()
        if rest.startswith(":"):
            rest = rest[1:].lstrip()
            while rest and (rest[0].isalnum() or rest[0] == "_"):
                rest = rest[1:]
            rest = rest.lstrip()
        if rest.startswith(":="):
            rest = rest[2:].lstrip()
        elif rest.startswith("="):
            rest = rest[1:].lstrip()
        else:
            continue
        if not rest or rest[0] not in ("'", '"'):
            continue
        parsed = scan_string_literal(rest, 0, rest[0])
        if not parsed:
            continue
        literal, end_index = parsed
        trailing = rest[end_index:].strip()
        if trailing and not trailing.startswith("#"):
            continue
        constants[name] = literal
    return constants


def extract_gd_register_calls(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
    ambiguous_literals: set[str],
) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    active_text = strip_gd_comment_lines(text)
    constants = scan_gd_string_constants(active_text)
    patterns = (
        "RegisterConfiguration(",
        "RegisterConfigruation(",
        "_call_mcm_register_configuration(",
        ".call(",
    )

    def _property_for(matched_pattern: str, block: str, arg_index: int) -> str:
        if matched_pattern == ".call(":
            if not block[6:].lstrip().startswith("register_method"):
                return ""
            if arg_index == 2:
                return "friendlyName"
            if arg_index == 4:
                return "description"
            return ""
        if matched_pattern == "_call_mcm_register_configuration(":
            if arg_index == 0:
                return "friendlyName"
            if arg_index == 1:
                return "description"
            return ""
        if arg_index == 1:
            return "friendlyName"
        if arg_index == 3:
            return "description"
        return ""

    i = 0
    while i < len(active_text):
        matched_pattern = ""
        matched_index = -1
        for pattern in patterns:
            pos = active_text.find(pattern, i)
            if pos >= 0 and (matched_index < 0 or pos < matched_index):
                matched_pattern = pattern
                matched_index = pos
        if matched_index < 0:
            break

        block_end = find_call_block_end(active_text, matched_index)
        if block_end < 0:
            break

        block = active_text[matched_index:block_end]
        if matched_pattern == ".call(" and not block.startswith(".call("):
            i = block_end
            continue

        resolved: list[tuple[int, str]] = list(iter_call_string_arguments(block))
        captured_indices = {arg_index for arg_index, _ in resolved}
        for arg_index, identifier in iter_call_identifier_arguments(block):
            if arg_index in captured_indices:
                continue
            literal = constants.get(identifier)
            if literal is None:
                continue
            resolved.append((arg_index, literal))
            captured_indices.add(arg_index)

        for arg_index, literal in resolved:
            if literal in ambiguous_literals:
                continue
            property_name = _property_for(matched_pattern, block, arg_index)
            if not property_name:
                continue
            if should_skip_literal(literal, "", property_name, True):
                continue

            where = build_file_where(source_path, "script", True, mcm_mod_ids, property_name)
            key = (literal, canonical_where(where))
            if key in seen:
                continue
            seen.add(key)
            records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))

        i = block_end
    return records


def collect_string_literals(block: str) -> list[str]:
    literals: list[str] = []
    i = 0
    while i < len(block):
        ch = block[i]
        if ch not in ("'", '"'):
            i += 1
            continue
        parsed = scan_string_literal(block, i, ch)
        if not parsed:
            i += 1
            continue
        literal, end_index = parsed
        literals.append(literal)
        i = end_index
    return literals


def is_safe_const_usage_line(line: str, variable_name: str, line_is_mcm: bool) -> tuple[bool, bool]:
    if not re.search(rf"\b{re.escape(variable_name)}\b", line):
        return False, False
    stripped = line.strip()
    if not stripped or stripped.startswith("const "):
        return False, False

    prefix_match = re.match(rf"^(.*?\b{re.escape(variable_name)}\b)", line)
    prefix = prefix_match.group(1) if prefix_match else line
    property_name = infer_active_gd_property_name(prefix)
    is_mcm = line_is_mcm or infer_gd_is_mcm_context(prefix)
    return bool(property_name or is_mcm), is_mcm


def has_display_array_usage(lines: list[str], line_contexts: dict[int, bool], variable_name: str) -> bool:
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("const ") or stripped.startswith("var "):
            continue
        match = re.search(rf"\b{re.escape(variable_name)}\b", line)
        if not match:
            continue
        prefix = line[:match.start()]
        if infer_active_gd_property_name(prefix) or line_contexts.get(line_number, False) or infer_gd_is_mcm_context(prefix):
            return True
    return False


def extract_safe_const_array_entries(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    lines = text.splitlines()
    line_contexts = build_gd_line_contexts(text)

    for match in GD_CONST_STRING_ARRAY_RE.finditer(text):
        variable_name = match.group(1)
        literals = [literal for literal in collect_string_literals(match.group(2)) if literal.strip()]
        if not literals:
            continue

        usage_lines = []
        mcm_only = True
        safe = True
        for line_number, line in enumerate(lines, start=1):
            if not re.search(rf"\b{re.escape(variable_name)}\b", line):
                continue
            if line.strip().startswith("const "):
                continue
            used, is_mcm = is_safe_const_usage_line(line, variable_name, line_contexts.get(line_number, False))
            if not used:
                safe = False
                break
            usage_lines.append(line)
            if not is_mcm:
                mcm_only = False

        if not safe or not usage_lines:
            continue

        where = build_file_where(source_path, "script", mcm_only, mcm_mod_ids if mcm_only else [], "text")
        for literal in literals:
            if should_skip_literal(literal, "", "text", mcm_only):
                continue
            key = (literal, canonical_where(where))
            if key in seen:
                continue
            seen.add(key)
            records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))

    return records


def extract_display_var_array_entries(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    lines = text.splitlines()
    line_contexts = build_gd_line_contexts(text)

    for match in GD_VAR_STRING_ARRAY_RE.finditer(text):
        variable_name = match.group(1)
        literals = [literal for literal in collect_string_literals(match.group(2)) if literal.strip()]
        if not literals:
            continue
        if not has_display_array_usage(lines, line_contexts, variable_name):
            continue

        for literal in literals:
            is_mcm = False
            for line_number, line in enumerate(lines, start=1):
                match_usage = re.search(rf"\b{re.escape(variable_name)}\b", line)
                if not match_usage:
                    continue
                prefix = line[:match_usage.start()]
                if infer_active_gd_property_name(prefix) or line_contexts.get(line_number, False) or infer_gd_is_mcm_context(prefix):
                    is_mcm = line_contexts.get(line_number, False) or infer_gd_is_mcm_context(prefix)
                    break

            if should_skip_literal(literal, "", "text", is_mcm):
                continue
            where = build_file_where(source_path, "script", is_mcm, mcm_mod_ids if is_mcm else [], "text")
            key = (literal, canonical_where(where))
            if key in seen:
                continue
            seen.add(key)
            records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))

    return records


def extract_formatted_item_name_entries(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
) -> list[EntryRecord]:
    if "DEFAULT_ITEM_USES" not in text or "_format_item_name" not in text:
        return []
    if 'return item_key.replace("_", " ")' not in text and 'return item_key.replace("_", \' \')' not in text:
        return []
    if "_format_item_name(item_key)" not in text:
        return []
    if '"name": "Uses: " + display_name' not in text and '"name" = "Uses: " + display_name' not in text:
        return []

    dict_match = re.search(
        r"""(?imsx)
        const\s+DEFAULT_ITEM_USES\s*(?::=|=)\s*\{
        (.*?)
        \}
        """,
        text,
    )
    if not dict_match:
        return []

    records: list[EntryRecord] = []
    key_block = dict_match.group(1)
    display_names = []
    for match in re.finditer(r'["\']([^"\']+)["\']\s*:', key_block):
        raw_key = match.group(1).strip()
        if not raw_key:
            continue
        display_name = raw_key.replace("_", " ")
        if display_name not in display_names:
            display_names.append(display_name)

    where = build_file_where(source_path, "script", True, mcm_mod_ids, "text")
    for display_name in display_names:
        if should_skip_literal(display_name, "", "text", True):
            continue
        key = (display_name, canonical_where(where))
        if key in seen:
            continue
        seen.add(key)
        records.append(EntryRecord(source_path=source_path, source_kind="script", text=display_name, where=where))
    return records


def extract_trader_display_name_entries(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    seen: set[tuple[str, str]],
) -> list[EntryRecord]:
    if "const TRADERS" not in text or "var trader_name = TRADERS[t]" not in text:
        return []
    if '"name" = trader_name +' not in text and '"tooltip" = "Rep needed for " + trader_name +' not in text:
        return []

    match = re.search(r"""(?imsx)const\s+TRADERS\s*=\s*\[(.*?)\]""", text)
    if not match:
        return []

    records: list[EntryRecord] = []
    where = build_file_where(source_path, "script", True, mcm_mod_ids, "text")
    for literal in collect_string_literals(match.group(1)):
        if should_skip_literal(literal, "", "text", True):
            continue
        key = (literal, canonical_where(where))
        if key in seen:
            continue
        seen.add(key)
        records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))
    return records


def extract_gd_entries(
    source_path: str,
    text: str,
    mcm_mod_ids: list[str],
    lookup_names: set[str] | None = None,
) -> list[EntryRecord]:
    # Auto-detected sink wrappers are kept in thread-local state so that all
    # helpers reached from this call (infer_*, collect_ambiguous_gd_literals,
    # extract_safe_const_array_entries, ...) can read them transparently
    # without threading the dict through every signature.
    prev_sinks = getattr(_extract_context, "auto_sinks", None)
    _extract_context.auto_sinks = build_auto_sinks(text)
    try:
        records: list[EntryRecord] = []
        seen: set[tuple[str, str]] = set()
        line_contexts = build_gd_line_contexts(text)
        ambiguous_literals = collect_ambiguous_gd_literals(text, lookup_names)

        for line_number, line in enumerate(text.splitlines(), start=1):
            if is_gd_comment_line(line):
                continue
            i = 0
            while i < len(line):
                ch = line[i]
                if ch not in ("'", '"'):
                    i += 1
                    continue

                parsed = scan_string_literal(line, i, ch)
                if not parsed:
                    i += 1
                    continue

                literal, end_index = parsed
                prefix = line[:i]
                property_name = infer_active_gd_property_name(prefix)
                is_mcm = line_contexts.get(line_number, False) or infer_gd_is_mcm_context(prefix)
                if property_name == "config_key":
                    i = end_index
                    continue
                if literal in ambiguous_literals:
                    i = end_index
                    continue
                if is_gd_dict_key(prefix, line[end_index:]):
                    i = end_index
                    continue
                if is_gd_indexer_key(prefix, line[end_index:]):
                    i = end_index
                    continue
                if not should_skip_literal(literal, prefix, property_name, is_mcm):
                    where = build_file_where(source_path, "script", is_mcm, mcm_mod_ids, property_name)
                    key = (literal, canonical_where(where))
                    if key not in seen:
                        seen.add(key)
                        records.append(EntryRecord(source_path=source_path, source_kind="script", text=literal, where=where))

                i = end_index

        records.extend(extract_gd_options_arrays(source_path, text, mcm_mod_ids, seen, ambiguous_literals))
        records.extend(extract_gd_register_calls(source_path, text, mcm_mod_ids, seen, ambiguous_literals))
        records.extend(extract_safe_const_array_entries(source_path, text, mcm_mod_ids, seen))
        records.extend(extract_display_var_array_entries(source_path, text, mcm_mod_ids, seen))
        records.extend(extract_formatted_item_name_entries(source_path, text, mcm_mod_ids, seen))
        records.extend(extract_trader_display_name_entries(source_path, text, mcm_mod_ids, seen))
        return records
    finally:
        _extract_context.auto_sinks = prev_sinks


_CFG_MCM_SECTIONS = {"string", "bool", "int", "float", "dropdown"}


def _extract_kv_display_entries(
    source_path: str,
    text: str,
    display_keys: set[str],
    mcm_mod_ids: list[str],
    is_cfg: bool,
) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    seen: set[tuple[str, str]] = set()
    current_section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if is_cfg:
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
        if "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if key not in display_keys:
            continue
        if len(raw_value) < 2 or raw_value[0] != '"':
            continue
        parsed = scan_string_literal(raw_value, 0, '"')
        if not parsed:
            continue
        literal, _ = parsed
        is_mcm = is_cfg and current_section.lower() in _CFG_MCM_SECTIONS
        if should_skip_literal(literal, "", key, is_mcm):
            continue
        where = build_file_where(source_path, "resource", is_mcm, mcm_mod_ids, key)
        dedupe_key = (literal, canonical_where(where))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        records.append(EntryRecord(source_path=source_path, source_kind="resource", text=literal, where=where))
    return records


def extract_resource_entries(source_path: str, text: str) -> list[EntryRecord]:
    return _extract_kv_display_entries(source_path, text, RESOURCE_DISPLAY_PROPERTIES, [], False)


def extract_cfg_entries(source_path: str, text: str, mcm_mod_ids: list[str]) -> list[EntryRecord]:
    return _extract_kv_display_entries(source_path, text, CFG_DISPLAY_KEYS, mcm_mod_ids, True)


def detect_mcm_mod_ids(text_files: dict[str, str]) -> list[str]:
    ids: list[str] = []
    for source_path, text in text_files.items():
        if not source_path.lower().endswith(".gd"):
            continue
        for match in MCM_MOD_ID_RE.finditer(text):
            value = match.group(2).strip()
            if value and value not in ids:
                ids.append(value)
        if ids:
            continue
        if any(
            token in text
            for token in (
                "RegisterConfiguration(",
                "RegisterConfigruation(",
                "_call_mcm_register_configuration(",
                "CheckConfigurationHasUpdated(",
                "CheckConfigruationHasUpdated(",
                "user://MCM/",
            )
        ):
            for match in GENERIC_MOD_ID_RE.finditer(text):
                value = match.group(2).strip()
                if value and value not in ids:
                    ids.append(value)
    return ids


def collect_entries(text_files: dict[str, str], mcm_mod_ids: list[str]) -> list[EntryRecord]:
    records: list[EntryRecord] = []
    lookup_names = collect_gd_lookup_names(text_files)
    for source_path, text in sorted(text_files.items()):
        suffix = Path(source_path).suffix.lower()
        if suffix == ".gd":
            records.extend(extract_gd_entries(source_path, text, mcm_mod_ids, lookup_names))
        elif suffix in {".tscn", ".tres"}:
            records.extend(extract_resource_entries(source_path, text))
        elif suffix == ".cfg":
            records.extend(extract_cfg_entries(source_path, text, mcm_mod_ids))
    records.sort(key=lambda record: (record.source_path.lower(), record.text.lower(), canonical_where(record.where)))
    return records


def build_pack(mod_id: str, mcm_mod_ids: list[str], entries: list[EntryRecord]) -> dict:
    json_entries = []
    for record in entries:
        entry = {
            "match": "exact",
            "from": record.text,
            "to": "",
        }
        if record.where:
            entry["where"] = record.where
        json_entries.append(entry)
    return {
        "pack_version": 1,
        "mod_id": mod_id,
        "mcm_mod_ids": mcm_mod_ids,
        "entries": json_entries,
    }


def write_pack(output_root: Path, mod_id: str, locale: str, pack: dict) -> Path:
    target_dir = output_root / mod_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{locale}.json"
    with target_path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target_path


def extract_vmz(vmz_path: Path, output_root: Path, locale: str) -> tuple[Path, dict]:
    manifest = read_manifest_from_vmz(vmz_path)
    mod_id = str(manifest["id"]).strip()
    text_files = read_vmz_text_files(vmz_path)
    mcm_mod_ids = detect_mcm_mod_ids(text_files)
    entries = collect_entries(text_files, mcm_mod_ids)
    pack = build_pack(mod_id, mcm_mod_ids, entries)
    output_path = write_pack(output_root, mod_id, locale, pack)
    stats = {
        "mod_id": mod_id,
        "entries": len(entries),
        "mcm_mod_ids": mcm_mod_ids,
        "output_path": str(output_path),
        "text_files": len(text_files),
    }
    return output_path, stats


def run_extraction(mode: str, input_path: Path, output_root: Path, locale: str, log: Callable[[str], None]) -> dict:
    vmz_files = find_vmz_files(mode, input_path)
    if not vmz_files:
        raise ExtractionError("no .vmz / .zip mod archives found")

    output_root.mkdir(parents=True, exist_ok=True)
    processed = 0
    skipped = 0
    failures = 0
    generated_files: list[str] = []

    for vmz_path in vmz_files:
        try:
            output_path, stats = extract_vmz(vmz_path, output_root, locale)
            processed += 1
            generated_files.append(str(output_path))
            log(
                "[OK] %s -> %s | entries=%d | text_files=%d | mcm_ids=%s"
                % (
                    vmz_path.name,
                    output_path,
                    stats["entries"],
                    stats["text_files"],
                    ", ".join(stats["mcm_mod_ids"]) if stats["mcm_mod_ids"] else "-",
                )
            )
        except ExtractionError as exc:
            skipped += 1
            log(f"[SKIP] {vmz_path.name}: {exc}")
        except Exception as exc:  # pragma: no cover
            failures += 1
            log(f"[FAIL] {vmz_path.name}: {exc}")

    return {
        "processed": processed,
        "skipped": skipped,
        "failures": failures,
        "generated_files": generated_files,
    }


class ExtractorApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("860x620")
        self.root.minsize(760, 560)

        self.ui_language_var = tk.StringVar(value="en")
        self.mode_var = tk.StringVar(value="folder")
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.locale_var = tk.StringVar(value="us_us")
        self.running = False
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.locale_choice_to_code: dict[str, str] = {}
        self.locale_code_to_choice: dict[str, str] = {}

        self._build_ui()
        self._refresh_locale_choices()
        self._apply_ui_language()
        self.root.after(100, self._pump_logs)

    def _t(self, key: str) -> str:
        language = self.ui_language_var.get()
        if language not in UI_TEXT:
            language = "en"
        return UI_TEXT[language][key]

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self.language_frame = ttk.LabelFrame(container, padding=10)
        self.language_frame.pack(fill=tk.X)
        self.language_combo = ttk.Combobox(
            self.language_frame,
            state="readonly",
            values=[UI_LANGUAGE_LABELS["zh"], UI_LANGUAGE_LABELS["en"], UI_LANGUAGE_LABELS["ja"]],
            width=18,
        )
        self.language_combo.pack(side=tk.LEFT)
        self.language_combo.set(UI_LANGUAGE_LABELS[self.ui_language_var.get()])
        self.language_combo.bind("<<ComboboxSelected>>", self._on_ui_language_changed)

        self.mode_frame = ttk.LabelFrame(container, padding=10)
        self.mode_frame.pack(fill=tk.X, pady=(10, 0))
        self.mode_folder_radio = ttk.Radiobutton(self.mode_frame, variable=self.mode_var, value="folder")
        self.mode_folder_radio.pack(side=tk.LEFT, padx=(0, 12))
        self.mode_file_radio = ttk.Radiobutton(self.mode_frame, variable=self.mode_var, value="file")
        self.mode_file_radio.pack(side=tk.LEFT)

        self.input_frame = ttk.LabelFrame(container, padding=10)
        self.input_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Entry(self.input_frame, textvariable=self.input_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_browse_button = ttk.Button(self.input_frame, command=self._choose_input)
        self.input_browse_button.pack(side=tk.LEFT, padx=(8, 0))

        self.output_frame = ttk.LabelFrame(container, padding=10)
        self.output_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Entry(self.output_frame, textvariable=self.output_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.output_browse_button = ttk.Button(self.output_frame, command=self._choose_output)
        self.output_browse_button.pack(side=tk.LEFT, padx=(8, 0))

        self.locale_frame = ttk.LabelFrame(container, padding=10)
        self.locale_frame.pack(fill=tk.X, pady=(10, 0))
        self.locale_combo = ttk.Combobox(self.locale_frame, state="readonly", width=34)
        self.locale_combo.pack(side=tk.LEFT)

        action_frame = ttk.Frame(container)
        action_frame.pack(fill=tk.X, pady=(12, 0))
        self.start_button = ttk.Button(action_frame, command=self._start_extraction)
        self.start_button.pack(side=tk.LEFT)

        self.log_frame = ttk.LabelFrame(container, padding=10)
        self.log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.log_widget = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        self.log_widget.pack(fill=tk.BOTH, expand=True)

    def _refresh_locale_choices(self) -> None:
        choices = []
        self.locale_choice_to_code.clear()
        self.locale_code_to_choice.clear()
        for code in LOCALE_ORDER:
            label = LOCALE_LABELS[code]
            choices.append(label)
            self.locale_choice_to_code[label] = code
            self.locale_code_to_choice[code] = label
        self.locale_combo.configure(values=choices)
        current_code = normalize_locale(self.locale_var.get())
        if current_code in self.locale_code_to_choice:
            self.locale_combo.set(self.locale_code_to_choice[current_code])
        elif choices:
            self.locale_combo.set(choices[0])
            self.locale_var.set(self.locale_choice_to_code[choices[0]])

    def _apply_ui_language(self) -> None:
        self.root.title(self._t("window_title"))
        self.language_frame.configure(text=self._t("ui_language"))
        self.mode_frame.configure(text=self._t("input_mode"))
        self.mode_folder_radio.configure(text=self._t("mode_folder"))
        self.mode_file_radio.configure(text=self._t("mode_file"))
        self.input_frame.configure(text=self._t("input_path"))
        self.output_frame.configure(text=self._t("output_dir"))
        self.locale_frame.configure(text=self._t("export_locale"))
        self.input_browse_button.configure(text=self._t("browse"))
        self.output_browse_button.configure(text=self._t("browse"))
        self.start_button.configure(text=self._t("start"))
        self.log_frame.configure(text=self._t("log"))

    def _on_ui_language_changed(self, _event: object | None = None) -> None:
        reverse_map = {label: code for code, label in UI_LANGUAGE_LABELS.items()}
        self.ui_language_var.set(reverse_map.get(self.language_combo.get(), "en"))
        self._apply_ui_language()

    def _choose_input(self) -> None:
        if self.mode_var.get() == "file":
            path = filedialog.askopenfilename(
                title=self._t("file_dialog_title"),
                filetypes=[("Mod archives", "*.vmz *.zip"), ("VMZ files", "*.vmz"), ("ZIP files", "*.zip"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title=self._t("folder_dialog_title"))
        if path:
            self.input_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title=self._t("output_dialog_title"))
        if path:
            self.output_var.set(path)

    def _append_log(self, message: str) -> None:
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def _pump_logs(self) -> None:
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._pump_logs)

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _start_extraction(self) -> None:
        if self.running:
            return

        mode = self.mode_var.get()
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        selected_locale = self.locale_combo.get().strip()
        locale = self.locale_choice_to_code.get(selected_locale, normalize_locale(self.locale_var.get()))
        self.locale_var.set(locale)

        if not input_path:
            messagebox.showerror(self._t("error_title"), self._t("missing_input"))
            return
        if not output_path:
            messagebox.showerror(self._t("error_title"), self._t("missing_output"))
            return
        if not locale:
            messagebox.showerror(self._t("error_title"), self._t("missing_locale"))
            return

        self.running = True
        self.start_button.configure(state=tk.DISABLED)
        self._log("=" * 72)
        self._log(self._t("start_log").format(mode=mode, locale=locale))
        self._log(self._t("input_log").format(path=input_path))
        self._log(self._t("output_log").format(path=output_path))

        def worker() -> None:
            try:
                result = run_extraction(
                    mode=mode,
                    input_path=Path(input_path),
                    output_root=Path(output_path),
                    locale=locale,
                    log=self._log,
                )
                summary = self._t("summary").format(
                    processed=result["processed"],
                    skipped=result["skipped"],
                    failures=result["failures"],
                )
                self._log(summary)
                self.root.after(0, lambda: messagebox.showinfo(self._t("window_title"), summary))
            except Exception as exc:
                self._log(f"[ERROR] {exc}")
                self.root.after(0, lambda: messagebox.showerror(self._t("error_title"), str(exc)))
            finally:
                self.root.after(0, self._finish_run)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_run(self) -> None:
        self.running = False
        self.start_button.configure(state=tk.NORMAL)

    def run(self) -> None:
        self.root.mainloop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RTV mod text extractor")
    parser.add_argument("--mode", choices=("file", "folder"), help="input mode")
    parser.add_argument("--input", dest="input_path", help="input vmz file or folder")
    parser.add_argument("--output", dest="output_path", help="output root directory")
    parser.add_argument("--locale", default="us_us", help="target locale, default: us_us")
    parser.add_argument("--no-gui", action="store_true", help="run in CLI mode")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if not args.mode or not args.input_path or not args.output_path:
        raise ExtractionError("--mode, --input, and --output are required in CLI mode")

    result = run_extraction(
        mode=args.mode,
        input_path=Path(args.input_path),
        output_root=Path(args.output_path),
        locale=normalize_locale(args.locale),
        log=print,
    )
    print(
        "Done. processed=%d skipped=%d failures=%d"
        % (result["processed"], result["skipped"], result["failures"])
    )
    return 0 if result["failures"] == 0 else 1


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.no_gui or args.mode or args.input_path or args.output_path:
        return run_cli(args)
    ExtractorApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
