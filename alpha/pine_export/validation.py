"""Deterministic Pine v6 generation-safety validation."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from alpha.pine_export.identifiers import (
    PINE_UNSAFE_IDENTIFIERS,
    code_without_strings_or_comments,
    extract_declared_identifiers,
)
from alpha.pine_export.models import (
    PineFileValidation,
    PineSourceMetrics,
    PineValidationIssue,
    PineValidationReport,
    ValidationSeverity,
)

_REQUIRED_WARNING_LINES = (
    "DATA SOURCE: TRADINGVIEW",
    "NOT ALPHA MARKET TRUTH ENGINE",
    "CORPORATE-ACTION AND SYMBOL-HISTORY SEMANTICS MAY DIFFER",
    "RESULTS ARE INDEPENDENT VALIDATION, NOT AUTHORITATIVE ALPHA REPLAY",
)
_PROHIBITED = (
    "lookahead_on",
    "barmerge.lookahead_on",
    "request.seed(",
)
_PYTHON_TOKENS = ("None", "True", "False", "Decimal(")
_REQUIRED_STRATEGY_INPUTS = (
    "Start date",
    "End date",
    "Order size",
    "Commission",
    "Slippage",
    "Long only",
    "Next-bar execution",
    "Same-bar conflict policy",
    "Trading session",
)
_INVISIBLE_CHARACTERS = {
    "\u00a0": "NO_BREAK_SPACE",
    "\u200b": "ZERO_WIDTH_SPACE",
    "\u200c": "ZERO_WIDTH_NON_JOINER",
    "\u200d": "ZERO_WIDTH_JOINER",
    "\ufeff": "BYTE_ORDER_MARK",
}
_REASSIGNMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|\+=|-=|\*=|/=|%=)"
)
_GLOBAL_ASSIGNMENT_PATTERN = re.compile(
    r"^(?:(?:export|const|input|simple|series|var|varip)\s+)*"
    r"(?:(?:bool|int|float|string|color|line|label|box|table|"
    r"array(?:<[^>]+>)?|map(?:<[^>]+>)?|matrix(?:<[^>]+>)?)\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)"
)
_GLOBAL_FUNCTION_PATTERN = re.compile(
    r"^(?:export\s+)?(?:method\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*=>"
)
_EXACT_NA_PATTERN = re.compile(
    r"^\s*(?P<prefix>.*?)\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*na\s*$"
)
_TYPE_TOKEN_PATTERN = re.compile(
    r"\b(?:bool|int|float|string|color|line|label|box|table|array|map|matrix)\b"
)
_LEADING_FRAGMENT_PATTERN = re.compile(
    r"^\s*(?:>=|<=|==|!=|>|<|\+|\*|/|%|\?|:|and\b|or\b)"
)
_TRAILING_FRAGMENT_PATTERN = re.compile(
    r"(?:=|:=|\+=|-=|\*=|/=|%=|>=|<=|==|!=|>|<|\+|-|\*|/|%|\?|:|"
    r"\band|\bor)\s*$"
)
_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+[A-Za-z_][A-Za-z0-9_]*/[A-Za-z_][A-Za-z0-9_]*/\d+"
    r"\s+as\s+[A-Za-z_][A-Za-z0-9_]*\s*$"
)


class PineStaticValidator:
    """Reject deterministic Pine defects before TradingView compilation."""

    def validate_directory(self, root: Path) -> PineValidationReport:
        files = tuple(sorted(root.rglob("*.pine")))
        return PineValidationReport(
            files=tuple(self.validate_file(path) for path in files)
        )

    def validate_file(self, path: Path) -> PineFileValidation:
        raw = path.read_bytes()
        byte_issues: list[PineValidationIssue] = []
        if raw.startswith(b"\xef\xbb\xbf"):
            byte_issues.append(
                self._error(path, "UTF8_BOM", "UTF-8 BOM precedes the Pine header.")
            )
        if b"\r" in raw:
            byte_issues.append(
                self._error(path, "LINE_ENDINGS", "Pine source must use LF endings.")
            )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            issue = self._error(
                path,
                "UTF8_ENCODING",
                f"Pine source is not valid UTF-8 at byte {exc.start}.",
            )
            return PineFileValidation(
                path=path,
                issues=tuple((*byte_issues, issue)),
                metrics=PineSourceMetrics(0, 0, 0, 0, 0),
            )
        result = self.validate_source_result(path, source)
        return PineFileValidation(
            path=path,
            issues=tuple((*byte_issues, *result.issues)),
            metrics=result.metrics,
        )

    def validate_source(
        self,
        path: Path,
        source: str,
    ) -> tuple[PineValidationIssue, ...]:
        """Retain the v1.0 issue-only API for in-memory validation."""

        return self.validate_source_result(path, source).issues

    def validate_source_result(self, path: Path, source: str) -> PineFileValidation:
        issues: list[PineValidationIssue] = []
        code = code_without_strings_or_comments(source)
        declarations = extract_declared_identifiers(source)

        if not source.startswith("//@version=6"):
            issues.append(
                self._error(
                    path,
                    "PINE_VERSION",
                    "Pine v6 header must begin at byte zero.",
                    line=1,
                )
            )
        if "```" in source:
            issues.append(
                self._error(path, "MARKDOWN_FENCE", "Markdown fences are not Pine.")
            )
        for character, name in _INVISIBLE_CHARACTERS.items():
            if character in source:
                issues.append(
                    self._error(
                        path,
                        "INVISIBLE_CHARACTER",
                        f"Unsupported invisible character {name} found.",
                    )
                )
        for line_number, character in self._control_characters(source):
            issues.append(
                self._error(
                    path,
                    "CONTROL_CHARACTER",
                    f"Unsupported control character U+{ord(character):04X}.",
                    line=line_number,
                )
            )

        script_declarations = re.findall(
            r"(?m)^(?:strategy|indicator|library)\s*\(", code
        )
        if len(script_declarations) != 1:
            issues.append(
                self._error(
                    path,
                    "DECLARATION_COUNT",
                    "Expected exactly one strategy(), indicator(), or library().",
                )
            )

        for token in _PROHIBITED:
            if token in code:
                issues.append(
                    self._error(path, "REPAINTING_CONSTRUCT", f"Prohibited {token}.")
                )
        for token in _PYTHON_TOKENS:
            if re.search(rf"\b{re.escape(token)}", code):
                issues.append(
                    self._error(
                        path,
                        "PYTHON_TOKEN",
                        f"Unsupported Python token {token!r} found.",
                    )
                )
        if "range" not in declarations and re.search(r"\brange\b", code):
            issues.append(
                self._error(
                    path,
                    "RESERVED_IDENTIFIER_USE",
                    "Reserved Pine identifier 'range' is used without a declaration.",
                )
            )

        issues.extend(self._check_lines(path, source, code, set(declarations)))
        issues.extend(self._check_delimiters(path, code))
        issues.extend(self._check_declarations(path, source, declarations))

        if re.search(r"(?m)^strategy\s*\(", code):
            for warning in _REQUIRED_WARNING_LINES:
                if warning not in source:
                    issues.append(
                        self._error(
                            path,
                            "DATA_WARNING",
                            f"Required warning missing: {warning}",
                        )
                    )
            for label in _REQUIRED_STRATEGY_INPUTS:
                if label not in source:
                    issues.append(
                        self._error(
                            path,
                            "BACKTEST_INPUT",
                            f"Required backtest control missing: {label}",
                        )
                    )

        metrics = self._metrics(code, declarations)
        issues.extend(self._check_platform_limits(path, metrics))
        return PineFileValidation(path=path, issues=tuple(issues), metrics=metrics)

    def _check_lines(
        self,
        path: Path,
        source: str,
        code: str,
        declarations: set[str],
    ) -> list[PineValidationIssue]:
        issues: list[PineValidationIssue] = []
        source_lines = source.splitlines()
        code_lines = code.splitlines()
        for line_number, (source_line, code_line) in enumerate(
            zip(source_lines, code_lines, strict=True), start=1
        ):
            stripped = code_line.strip()
            expression_shape = self._expression_shape(source_line)
            if not stripped:
                continue
            if "request.security(" in code_line:
                if "lookahead=barmerge.lookahead_off" not in source_line:
                    issues.append(
                        self._error(
                            path,
                            "SECURITY_LOOKAHEAD_EXPLICIT",
                            "request.security() must set lookahead_off explicitly.",
                            line=line_number,
                        )
                    )
                if code_line.count("(") != code_line.count(")"):
                    issues.append(
                        self._error(
                            path,
                            "MULTILINE_SECURITY_REQUEST",
                            "request.security() must be emitted on one complete line.",
                            line=line_number,
                        )
                    )
            if stripped.startswith("import "):
                if _IMPORT_PATTERN.fullmatch(code_line) is None:
                    issues.append(
                        self._error(
                            path,
                            "INVALID_IMPORT",
                            "Pine imports must include an explicit library version.",
                            line=line_number,
                        )
                    )
                if "generated" in path.parts:
                    issues.append(
                        self._error(
                            path,
                            "GENERATED_IMPORT",
                            "Generated strategies must be self-contained.",
                            line=line_number,
                        )
                    )
            reassignment = _REASSIGNMENT_PATTERN.match(code_line)
            if reassignment is not None and reassignment.group(1) not in declarations:
                issues.append(
                    self._error(
                        path,
                        "UNDECLARED_REASSIGNMENT",
                        f"{reassignment.group(1)!r} is reassigned before declaration.",
                        line=line_number,
                    )
                )
            na_match = _EXACT_NA_PATTERN.match(code_line)
            if (
                na_match is not None
                and _TYPE_TOKEN_PATTERN.search(na_match.group("prefix")) is None
            ):
                issues.append(
                    self._error(
                        path,
                        "NA_TYPE_REQUIRED",
                        "A variable initialized only with na needs an explicit type.",
                        line=line_number,
                    )
                )
            if _LEADING_FRAGMENT_PATTERN.match(expression_shape):
                issues.append(
                    self._error(
                        path,
                        "BARE_EXPRESSION_FRAGMENT",
                        "Line begins with a detached operator or comparison.",
                        line=line_number,
                    )
                )
            if not stripped.endswith("=>") and _TRAILING_FRAGMENT_PATTERN.search(
                expression_shape.strip()
            ):
                issues.append(
                    self._error(
                        path,
                        "DANGLING_EXPRESSION",
                        (
                            "Line ends with an incomplete assignment, operator, "
                            "or comparison."
                        ),
                        line=line_number,
                    )
                )
        return issues

    def _check_delimiters(
        self,
        path: Path,
        code: str,
    ) -> list[PineValidationIssue]:
        issues: list[PineValidationIssue] = []
        stack: list[tuple[str, int]] = []
        pairs = {")": "(", "]": "[", "}": "{"}
        line_number = 1
        for character in code:
            if character == "\n":
                line_number += 1
            elif character in "([{":
                stack.append((character, line_number))
            elif character in pairs:
                if not stack or stack[-1][0] != pairs[character]:
                    issues.append(
                        self._error(
                            path,
                            "UNBALANCED_DELIMITER",
                            f"Unexpected closing delimiter {character!r}.",
                            line=line_number,
                        )
                    )
                    return issues
                stack.pop()
        for opening, opening_line in stack:
            issues.append(
                self._error(
                    path,
                    "UNBALANCED_DELIMITER",
                    f"Unclosed delimiter {opening!r}.",
                    line=opening_line,
                )
            )
        return issues

    def _check_declarations(
        self,
        path: Path,
        source: str,
        declarations: tuple[str, ...],
    ) -> list[PineValidationIssue]:
        issues: list[PineValidationIssue] = []
        for identifier in sorted(set(declarations) & PINE_UNSAFE_IDENTIFIERS):
            issues.append(
                self._error(
                    path,
                    "UNSAFE_IDENTIFIER",
                    (
                        f"Alpha-owned identifier {identifier!r} is reserved or "
                        "unsafe in Pine."
                    ),
                )
            )
        global_names: list[str] = []
        for raw_line in source.splitlines():
            if raw_line[:1].isspace():
                continue
            code_line = code_without_strings_or_comments(raw_line)
            match = _GLOBAL_FUNCTION_PATTERN.match(code_line)
            if match is None:
                match = _GLOBAL_ASSIGNMENT_PATTERN.match(code_line)
            if match is not None:
                global_names.append(match.group(1))
        for identifier, count in sorted(Counter(global_names).items()):
            if count > 1:
                issues.append(
                    self._error(
                        path,
                        "DUPLICATE_GLOBAL_IDENTIFIER",
                        f"Global identifier {identifier!r} is declared {count} times.",
                    )
                )
        return issues

    def _metrics(
        self,
        code: str,
        declarations: tuple[str, ...],
    ) -> PineSourceMetrics:
        return PineSourceMetrics(
            characters=len(code),
            plot_calls=len(
                re.findall(
                    r"\b(?:plot|plotarrow|plotbar|plotcandle|plotchar|plotshape)\s*\(",
                    code,
                )
            ),
            request_calls=len(
                re.findall(r"\brequest\.[A-Za-z_][A-Za-z0-9_]*\s*\(", code)
            ),
            table_calls=len(re.findall(r"\btable\.new\s*\(", code)),
            declared_identifiers=len(declarations),
        )

    def _check_platform_limits(
        self,
        path: Path,
        metrics: PineSourceMetrics,
    ) -> list[PineValidationIssue]:
        issues: list[PineValidationIssue] = []
        if metrics.characters > 5_000_000:
            issues.append(
                self._error(
                    path,
                    "COMPILATION_REQUEST_SIZE",
                    "Source exceeds TradingView's 5 MB compilation request limit.",
                )
            )
        elif metrics.characters > 100_000:
            issues.append(
                self._warning(
                    path,
                    "SOURCE_SIZE",
                    (
                        "Source exceeds 100,000 characters; compiled-token usage "
                        "needs manual verification."
                    ),
                )
            )
        if metrics.plot_calls > 64:
            issues.append(
                self._error(
                    path,
                    "PLOT_LIMIT",
                    "Source has more than 64 plot calls.",
                )
            )
        if metrics.table_calls > 9:
            issues.append(
                self._error(path, "TABLE_LIMIT", "Source has more than 9 tables.")
            )
        if metrics.request_calls > 40:
            issues.append(
                self._error(
                    path,
                    "REQUEST_LIMIT",
                    (
                        "Source has more than 40 request calls; plan-dependent "
                        "limits may differ."
                    ),
                )
            )
        if metrics.declared_identifiers > 1_000:
            issues.append(
                self._warning(
                    path,
                    "VARIABLE_SCOPE_LIMIT",
                    (
                        "Source has more than 1,000 declarations; per-scope usage "
                        "needs manual verification."
                    ),
                )
            )
        return issues

    def _control_characters(self, source: str) -> tuple[tuple[int, str], ...]:
        found: list[tuple[int, str]] = []
        line_number = 1
        for character in source:
            if character == "\n":
                line_number += 1
            elif ord(character) < 32 and character not in {"\t"}:
                found.append((line_number, character))
        return tuple(found)

    def _expression_shape(self, line: str) -> str:
        without_strings = re.sub(r'"(?:\\.|[^"\\])*"', "STRING", line)
        return without_strings.split("//", maxsplit=1)[0]

    def _error(
        self,
        path: Path,
        code: str,
        message: str,
        *,
        line: int | None = None,
    ) -> PineValidationIssue:
        return PineValidationIssue(
            path=path,
            code=code,
            message=message,
            severity=ValidationSeverity.ERROR,
            line=line,
        )

    def _warning(
        self,
        path: Path,
        code: str,
        message: str,
    ) -> PineValidationIssue:
        return PineValidationIssue(
            path=path,
            code=code,
            message=message,
            severity=ValidationSeverity.WARNING,
        )
