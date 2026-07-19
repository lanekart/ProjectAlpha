"""Deterministic Pine identifier sanitation and source rewriting."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# Pine's documented reserved words plus language declarations, namespaces, and
# built-ins that must never be emitted as Alpha-owned identifiers.
PINE_RESERVED_IDENTIFIERS = frozenset(
    {
        "and",
        "as",
        "bool",
        "break",
        "catch",
        "class",
        "color",
        "const",
        "continue",
        "do",
        "else",
        "ellipse",
        "enum",
        "export",
        "false",
        "float",
        "for",
        "if",
        "import",
        "in",
        "indicator",
        "input",
        "int",
        "is",
        "library",
        "method",
        "na",
        "not",
        "or",
        "polygon",
        "range",
        "return",
        "series",
        "simple",
        "strategy",
        "string",
        "struct",
        "switch",
        "text",
        "throw",
        "true",
        "try",
        "type",
        "var",
        "varip",
        "while",
    }
)

PINE_UNSAFE_IDENTIFIERS = PINE_RESERVED_IDENTIFIERS | frozenset(
    {
        "array",
        "bar_index",
        "box",
        "close",
        "high",
        "label",
        "line",
        "low",
        "map",
        "matrix",
        "open",
        "plot",
        "table",
        "time",
        "volume",
    }
)

_READABLE_REPLACEMENTS = {
    "array": "arrayValue",
    "box": "boxValue",
    "close": "barClose",
    "export": "exportedValue",
    "for": "loopIndex",
    "high": "barHigh",
    "if": "conditionValue",
    "import": "importedValue",
    "indicator": "indicatorName",
    "label": "labelValue",
    "line": "lineValue",
    "low": "barLow",
    "map": "mapValue",
    "matrix": "matrixValue",
    "method": "methodName",
    "open": "barOpen",
    "plot": "plotValue",
    "range": "priceRange",
    "strategy": "strategyName",
    "switch": "switchValue",
    "table": "tableValue",
    "time": "barTime",
    "type": "typeName",
    "var": "persistentValue",
    "varip": "intrabarPersistentValue",
    "volume": "barVolume",
    "while": "loopCondition",
}

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:(?:export|const|input|simple|series|var|varip)\s+)*"
    r"(?:(?:bool|int|float|string|color|line|label|box|table|"
    r"array(?:<[^>]+>)?|map(?:<[^>]+>)?|matrix(?:<[^>]+>)?)\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)"
)
_FUNCTION_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:method\s+)?([A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\(([^)]*)\)\s*=>"
)
_TUPLE_PATTERN = re.compile(r"^\s*\[([^]]+)]\s*=(?!=)")
_FOR_PATTERN = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")


def sanitize_identifier(value: str) -> str:
    """Return a readable, deterministic Pine-safe identifier."""

    identifier = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    identifier = re.sub(r"_+", "_", identifier).strip("_")
    if not identifier:
        identifier = "alpha_value"
    if identifier[0].isdigit():
        identifier = f"alpha_{identifier}"
    if identifier in PINE_UNSAFE_IDENTIFIERS:
        identifier = _READABLE_REPLACEMENTS.get(identifier, f"alpha_{identifier}")
    if identifier in PINE_UNSAFE_IDENTIFIERS:
        identifier = f"alpha_{identifier}"
    return identifier


def build_identifier_map(values: Iterable[str]) -> dict[str, str]:
    """Build a stable rename map and reject ambiguous output collisions."""

    originals = tuple(sorted(set(values)))
    existing = set(originals)
    replacements: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for original in originals:
        sanitized = sanitize_identifier(original)
        if sanitized == original:
            continue
        conflict = claimed.get(sanitized)
        if conflict is not None or sanitized in existing:
            other = conflict or sanitized
            raise ValueError(
                f"Pine identifier collision: {original!r} and {other!r} "
                f"both resolve to {sanitized!r}"
            )
        replacements[original] = sanitized
        claimed[sanitized] = original
    return replacements


def extract_declared_identifiers(source: str) -> tuple[str, ...]:
    """Extract declared variables, functions, parameters, and loop variables."""

    identifiers: list[str] = []
    for raw_line in source.splitlines():
        line = _strip_line_comment(raw_line)
        function_match = _FUNCTION_PATTERN.match(line)
        if function_match is not None:
            identifiers.append(function_match.group(1))
            identifiers.extend(_parameter_identifiers(function_match.group(2)))
            continue
        tuple_match = _TUPLE_PATTERN.match(line)
        if tuple_match is not None:
            identifiers.extend(
                item.strip()
                for item in tuple_match.group(1).split(",")
                if _IDENTIFIER_PATTERN.fullmatch(item.strip())
            )
            continue
        declaration_match = _DECLARATION_PATTERN.match(line)
        if declaration_match is not None:
            identifiers.append(declaration_match.group(1))
        for_match = _FOR_PATTERN.match(line)
        if for_match is not None:
            identifiers.append(for_match.group(1))
    return tuple(identifiers)


def sanitize_source_identifiers(source: str) -> str:
    """Sanitize Alpha-owned declarations and every corresponding code reference."""

    declarations = extract_declared_identifiers(source)
    unsafe = (name for name in declarations if name in PINE_UNSAFE_IDENTIFIERS)
    return rewrite_identifiers(source, build_identifier_map(unsafe))


def rewrite_identifiers(source: str, replacements: Mapping[str, str]) -> str:
    """Rewrite identifier tokens outside strings and line comments."""

    if not replacements:
        return source
    output: list[str] = []
    index = 0
    in_string = False
    while index < len(source):
        char = source[index]
        if in_string:
            output.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                output.append(source[index])
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(source) and source[index + 1] == "/":
            newline = source.find("\n", index)
            if newline == -1:
                output.append(source[index:])
                break
            output.append(source[index:newline])
            index = newline
            continue
        match = _IDENTIFIER_PATTERN.match(source, index)
        if match is not None:
            identifier = match.group(0)
            output.append(replacements.get(identifier, identifier))
            index = match.end()
            continue
        output.append(char)
        index += 1
    return "".join(output)


def code_without_strings_or_comments(source: str) -> str:
    """Replace strings/comments with whitespace while retaining line structure."""

    output: list[str] = []
    index = 0
    in_string = False
    while index < len(source):
        char = source[index]
        if in_string:
            if char == "\\" and index + 1 < len(source):
                output.extend((" ", " "))
                index += 2
                continue
            output.append("\n" if char == "\n" else " ")
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(" ")
            index += 1
            continue
        if char == "/" and index + 1 < len(source) and source[index + 1] == "/":
            newline = source.find("\n", index)
            if newline == -1:
                output.extend(" " for _ in source[index:])
                break
            output.extend(" " for _ in source[index:newline])
            index = newline
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _parameter_identifiers(parameters: str) -> tuple[str, ...]:
    identifiers: list[str] = []
    for parameter in parameters.split(","):
        left = parameter.split("=", maxsplit=1)[0].strip()
        tokens = _IDENTIFIER_PATTERN.findall(left)
        if tokens:
            identifiers.append(tokens[-1])
    return tuple(identifiers)


def _strip_line_comment(line: str) -> str:
    return code_without_strings_or_comments(line)
