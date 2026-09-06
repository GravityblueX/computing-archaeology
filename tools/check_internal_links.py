#!/usr/bin/env python3
"""Fail when a rendered Markdown link points to a missing repository path."""

from __future__ import annotations

import re
import string
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import unquote

try:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline
    from markdown_it.token import Token
    from mdit_py_plugins.footnote import footnote_plugin
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(
        "Markdown link-checker dependencies are missing; install the hash-pinned "
        "tools/requirements.txt before running this tool"
    ) from error


ASCII_PUNCTUATION = frozenset(string.punctuation)
GFM_WHITESPACE = " \t\n\v\f\r"
GFM_WHITESPACE_RE = re.compile(r"[ \t\n\v\f\r]+")
MAX_REFERENCE_LABEL = 999
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
GFM_BARE_URL_START_RE = re.compile(
    r"(?<![^ \t\n\v\f\r*_~(])" r"(?:(?P<scheme>(?i:https?|ftp)://)|(?P<www>www\.))"
)
GFM_DOMAIN_PUNCTUATION = frozenset("_.-")
GFM_TRAILING_PUNCTUATION = frozenset("?!.,:*_~")
GFM_ENTITY_SUFFIX_RE = re.compile(r"&[A-Za-z0-9]+;$")


def iter_markdown_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        if ".git" not in path.parts:
            yield path


def _unescape_markdown(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if (
            value[index] == "\\"
            and index + 1 < len(value)
            and value[index + 1] in ASCII_PUNCTUATION
        ):
            index += 1
        result.append(value[index])
        index += 1
    return "".join(result)


def _target_path(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = _unescape_markdown(target)
    return target.split("#", 1)[0].split("?", 1)[0]


def _decode_target_path(raw: str) -> str:
    """Decode a repository path without replacement text or impossible NULs."""

    target = unquote(raw, errors="strict")
    if "\x00" in target:
        raise ValueError("repository paths cannot contain NUL")
    return target


def normalize_target(raw: str) -> str:
    return _decode_target_path(_target_path(raw))


def _is_external_or_fragment(raw: str) -> bool:
    target = _unescape_markdown(raw.strip())
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return (
        not target
        or target.startswith("#")
        or target.startswith("//")
        or URI_SCHEME_RE.match(target) is not None
    )


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _unused_placeholders(text: str) -> Iterable[str]:
    """Yield non-whitespace private-use characters absent from the source."""

    reserved = set(text)
    for start, end in (
        (0xE000, 0xF900),
        (0xF0000, 0xFFFFE),
        (0x100000, 0x10FFFE),
    ):
        for codepoint in range(start, end):
            character = chr(codepoint)
            if character not in reserved:
                yield character


def _next_placeholder(placeholders: Iterator[str]) -> str:
    try:
        return next(placeholders)
    except StopIteration as error:
        raise ValueError(
            "Markdown source exhausts all Unicode private-use placeholders"
        ) from error


def _bracket_pairs(text: str) -> list[tuple[int, int]]:
    """Return balanced, unescaped bracket pairs in closing order."""

    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, character in enumerate(text):
        if character == "[" and not _is_escaped(text, index):
            stack.append(index)
        elif character == "]" and not _is_escaped(text, index) and stack:
            pairs.append((stack.pop(), index))
    return pairs


def _inline_destination_ranges(
    text: str,
    bracket_pairs: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Locate parenthesized destinations so their brackets stay untouched."""

    candidates = sorted(
        {
            closer + 1
            for _, closer in bracket_pairs
            if closer + 1 < len(text) and text[closer + 1] == "("
        }
    )
    if not candidates:
        return []

    # Index the prefix balance of every unescaped parenthesis. A destination's
    # closing parenthesis is then the next prefix at its starting balance,
    # instead of a fresh suffix scan for every nested ``](`` candidate.
    prefix_balances = [0] * (len(text) + 1)
    balance_positions: dict[int, list[int]] = {0: [0]}
    unescaped_greater_thans: list[int] = []
    backslash_run = 0
    for index, character in enumerate(text):
        escaped = backslash_run % 2 == 1
        if character == "\\":
            backslash_run += 1
        else:
            backslash_run = 0

        balance = prefix_balances[index]
        if not escaped:
            if character == "(":
                balance += 1
            elif character == ")":
                balance -= 1
            elif character == ">":
                unescaped_greater_thans.append(index)
        prefix_balances[index + 1] = balance
        balance_positions.setdefault(balance, []).append(index + 1)

    ranges: list[tuple[int, int]] = []
    range_starts: list[int] = []
    for opening in candidates:
        if _inside_ranges(opening, ranges, range_starts):
            continue

        first_content = opening + 1
        while first_content < len(text) and text[first_content] in GFM_WHITESPACE:
            first_content += 1

        if first_content < len(text) and text[first_content] == "<":
            greater_than_position = bisect_right(unescaped_greater_thans, first_content)
            if greater_than_position == len(unescaped_greater_thans):
                continue
            after_prefix = unescaped_greater_thans[greater_than_position] + 1
            target_balance = prefix_balances[after_prefix] - 1
        else:
            after_prefix = opening + 1
            target_balance = prefix_balances[opening]

        positions = balance_positions.get(target_balance, [])
        closing_position = bisect_right(positions, after_prefix)
        if closing_position == len(positions):
            continue

        ranges.append((opening, positions[closing_position] - 1))
        range_starts.append(opening)
    return ranges


def _inside_ranges(
    index: int,
    ranges: list[tuple[int, int]],
    starts: list[int],
) -> bool:
    candidate = bisect_right(starts, index) - 1
    return candidate >= 0 and index <= ranges[candidate][1]


def _is_gfm_domain_character(character: str) -> bool:
    return character.isalnum() or character in GFM_DOMAIN_PUNCTUATION


def _gfm_domain_run_bounds(text: str, start: int, maximum: int) -> tuple[int, int]:
    run_start = start
    while run_start > 0 and _is_gfm_domain_character(text[run_start - 1]):
        run_start -= 1

    run_end = start
    while run_end < maximum and _is_gfm_domain_character(text[run_end]):
        run_end += 1
    return run_start, run_end


def _gfm_domain_run_metadata(
    text: str,
    start: int,
    run_start: int,
    run_end: int,
) -> tuple[set[int], list[int], list[int], list[int]]:
    candidate_starts = {start, run_start}
    dots: list[int] = []
    double_dots: list[int] = []
    underscores: list[int] = []
    for index in range(run_start, run_end):
        character = text[index]
        if character == ".":
            dots.append(index)
            if index + 1 < run_end and text[index + 1] == ".":
                double_dots.append(index)
        elif character == "_":
            underscores.append(index)
        elif character == "w" and text.startswith("www.", index, run_end):
            candidate_starts.add(index)
    return candidate_starts, dots, double_dots, underscores


def _gfm_candidate_domain_end(
    text: str,
    candidate_start: int,
    domain_end: int,
    last_dot: int,
    second_last_dot: int,
    double_dots: list[int],
    underscores: list[int],
) -> int | None:
    if candidate_start >= domain_end or last_dot < candidate_start:
        return None
    if text[candidate_start] == ".":
        return None

    empty_segment = bisect_left(double_dots, candidate_start)
    if empty_segment < len(double_dots) and double_dots[empty_segment] < domain_end:
        return None

    last_two_start = (
        second_last_dot + 1 if second_last_dot >= candidate_start else candidate_start
    )
    underscore = bisect_left(underscores, last_two_start)
    if underscore < len(underscores) and underscores[underscore] < domain_end:
        return None
    return domain_end


def _index_gfm_domain_run(
    text: str,
    start: int,
    maximum: int,
    cache: dict[int, int | None],
) -> None:
    """Cache every possible domain start in one maximal domain-shaped run."""

    run_start, run_end = _gfm_domain_run_bounds(text, start, maximum)
    candidate_starts, dots, double_dots, underscores = _gfm_domain_run_metadata(
        text,
        start,
        run_start,
        run_end,
    )

    # A final period is path punctuation, not an empty domain segment. Scan the
    # whole domain-shaped run first so internal empty segments cannot fall back
    # to a shorter valid prefix.
    domain_end = run_end
    while domain_end > run_start and text[domain_end - 1] == ".":
        domain_end -= 1

    domain_dot_count = bisect_left(dots, domain_end)
    last_dot = dots[domain_dot_count - 1] if domain_dot_count else -1
    second_last_dot = dots[domain_dot_count - 2] if domain_dot_count > 1 else -1

    for candidate_start in candidate_starts:
        cache[candidate_start] = _gfm_candidate_domain_end(
            text,
            candidate_start,
            domain_end,
            last_dot,
            second_last_dot,
            double_dots,
            underscores,
        )


def _gfm_domain_end(
    text: str,
    start: int,
    maximum: int,
    cache: dict[int, int | None],
) -> int | None:
    """Return a complete GFM domain end, sharing each run's scan."""

    if start not in cache:
        _index_gfm_domain_run(text, start, maximum, cache)
    return cache[start]


def _gfm_bare_url_end(
    text: str,
    start: int,
    maximum: int | None = None,
    domain_cache: dict[int, int | None] | None = None,
) -> int | None:
    """Return the exclusive end of a normative GFM extended URL autolink."""

    maximum = len(text) if maximum is None else maximum
    match = GFM_BARE_URL_START_RE.match(text, start, maximum)
    if match is None:
        return None

    domain_start = start if match.group("www") else match.end()
    domain_cache = {} if domain_cache is None else domain_cache
    domain_end = _gfm_domain_end(text, domain_start, maximum, domain_cache)
    if domain_end is None:
        return None

    link_end = domain_end
    while (
        link_end < maximum
        and text[link_end] not in GFM_WHITESPACE
        and text[link_end] != "<"
    ):
        link_end += 1

    while link_end > domain_end and text[link_end - 1] in GFM_TRAILING_PUNCTUATION:
        link_end -= 1

    if link_end > domain_end and text[link_end - 1] == ")":
        unmatched_closers = text[start:link_end].count(")") - text[
            start:link_end
        ].count("(")
        while unmatched_closers > 0 and text[link_end - 1] == ")":
            link_end -= 1
            unmatched_closers -= 1

    if link_end > domain_end and text[link_end - 1] == ";":
        entity_suffix = GFM_ENTITY_SUFFIX_RE.search(text, start, link_end)
        if entity_suffix is not None:
            link_end = entity_suffix.start()
    return link_end


def _gfm_extended_autolink(state: StateInline, silent: bool) -> bool:
    """Parse exact GFM www/http(s)/ftp autolinks in inline text context."""

    # Silent calls scan a prospective link label before ``linkLevel`` is raised;
    # treating a URL there as active would hide the label's own closing bracket.
    if silent or state.linkLevel > 0:
        return False

    domain_cache = getattr(state, "_gfm_domain_cache", None)
    if domain_cache is None:
        domain_cache = {}
        state._gfm_domain_cache = domain_cache
    link_end = _gfm_bare_url_end(
        state.src,
        state.pos,
        state.posMax,
        domain_cache,
    )
    if link_end is None:
        return False

    display = state.src[state.pos : link_end]
    href = display if not display.startswith("www.") else f"http://{display}"
    href = state.md.normalizeLink(href)
    if not state.md.validateLink(href):
        return False

    token = state.push("link_open", "a", 1)
    token.attrs = {"href": href}
    token.markup = "linkify"
    token.info = "auto"

    token = state.push("text", "", 0)
    token.content = state.md.normalizeLinkText(display)

    token = state.push("link_close", "a", -1)
    token.markup = "linkify"
    token.info = "auto"

    state.pos = link_end
    return True


def _protect_inline_labels(
    text: str,
    whitespace: dict[str, str],
    long_label_marker: str,
) -> str:
    """Protect bracket-label content without ever touching URL destinations."""

    pairs = _bracket_pairs(text)
    destination_ranges = sorted(_inline_destination_ranges(text, pairs))
    destination_starts = [start for start, _ in destination_ranges]
    protected = bytearray(len(text))
    long_label_closers: set[int] = set()
    label_ranges: list[tuple[int, int]] = []

    for opener, closer in pairs:
        if _inside_ranges(opener, destination_ranges, destination_starts):
            continue
        label_ranges.append((opener + 1, closer))
        if closer - opener - 1 > MAX_REFERENCE_LABEL:
            long_label_closers.add(closer)

    protected_ranges: list[tuple[int, int]] = []
    for start, end in sorted(label_ranges):
        if not protected_ranges or start > protected_ranges[-1][1]:
            protected_ranges.append((start, end))
            continue
        previous_start, previous_end = protected_ranges[-1]
        protected_ranges[-1] = (previous_start, max(previous_end, end))
    for start, end in protected_ranges:
        protected[start:end] = b"\x01" * (end - start)

    prepared: list[str] = []
    for index, character in enumerate(text):
        if index in long_label_closers:
            prepared.append(long_label_marker)
        if protected[index]:
            prepared.append(whitespace.get(character, character))
        else:
            prepared.append(character)
    return "".join(prepared)


def _normalize_reference_label(label: str, whitespace: dict[str, str]) -> str:
    protected = "".join(whitespace.get(character, character) for character in label)
    protected = GFM_WHITESPACE_RE.sub(" ", protected.strip(GFM_WHITESPACE))
    return protected.lower().upper()


def _apply_gfm_reference_rules(state: Any) -> None:
    """Adapt public definition/inline tokens to exact GFM label rules.

    ``markdown-it-py`` follows Python's broad Unicode ``\\s`` definition when
    normalizing reference labels, while GFM only collapses six ASCII whitespace
    characters. Private-use placeholders preserve every other whitespace code
    point as an ordinary, distinct character. A marker in every overlong
    bracket span also prevents a >999-character use from matching a shorter
    normalized definition. Only inline label content is changed, so a sentinel
    can never be confused with literal, entity-derived, or encoded URL content.
    """

    whitespace = {
        character
        for character in state.src
        if character.isspace() and character not in GFM_WHITESPACE
    }
    placeholders = iter(_unused_placeholders(state.src))
    protected_whitespace: dict[str, str] = {}
    for character in sorted(whitespace, key=ord):
        protected_whitespace[character] = _next_placeholder(placeholders)
    long_label_marker = _next_placeholder(placeholders)

    references: dict[str, dict[str, object]] = {}
    for token in state.tokens:
        if token.type == "inline":
            token.content = _protect_inline_labels(
                token.content,
                protected_whitespace,
                long_label_marker,
            )
            continue
        if token.type != "definition":
            continue

        label = token.meta["label"]
        if len(label) > MAX_REFERENCE_LABEL:
            continue
        identifier = _normalize_reference_label(label, protected_whitespace)
        if not identifier:
            continue
        references.setdefault(
            identifier,
            {
                "title": token.meta["title"],
                "href": token.meta["url"],
                "map": token.map,
            },
        )
    state.env["references"] = references


def _build_parser() -> MarkdownIt:
    parser = MarkdownIt(
        "commonmark",
        options_update={"inline_definitions": True},
    )
    parser.enable("table")
    parser.use(footnote_plugin, inline=False)
    parser.inline.ruler.before(
        "text",
        "gfm_extended_autolink",
        _gfm_extended_autolink,
    )
    for character in ("F", "H", "f", "h", "w"):
        parser.inline.add_terminator_char(character)
    parser.core.ruler.before(
        "inline",
        "gfm_reference_rules",
        _apply_gfm_reference_rules,
    )
    return parser


MARKDOWN_PARSER = _build_parser()


def _token_targets(tokens: Iterable[Token]) -> list[str]:
    targets: list[str] = []
    for token in tokens:
        if token.type == "link_open" and token.markup not in {
            "autolink",
            "linkify",
        }:
            target = token.attrGet("href")
            if target is not None:
                targets.append(target)
        elif token.type == "image":
            target = token.attrGet("src")
            if target is not None:
                targets.append(target)
            continue
        if token.children:
            targets.extend(_token_targets(token.children))
    return targets


def find_link_targets(text: str) -> list[str]:
    """Return destinations for rendered CommonMark/GFM links and images."""

    return _token_targets(MARKDOWN_PARSER.parse(text))


def check_internal_links(root: Path) -> list[str]:
    failures: list[str] = []
    resolved_root = root.resolve()

    for markdown in iter_markdown_files(root):
        text = markdown.read_text(encoding="utf-8")
        for raw in find_link_targets(text):
            if _is_external_or_fragment(raw):
                continue

            raw_path = _target_path(raw)
            try:
                target = _decode_target_path(raw_path)
            except ValueError:
                failures.append(f"{markdown.relative_to(root)} -> {raw} (invalid path)")
                continue
            # GitHub renders a literal leading slash from the repository root,
            # but keeps a percent-encoded slash relative to the source file.
            # Strip decoded leading separators only after choosing that base.
            target_base = (
                resolved_root if raw_path.startswith("/") else markdown.parent
            )
            target = target.lstrip("/")
            if not target:
                continue

            resolved = (target_base / target).resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                failures.append(
                    f"{markdown.relative_to(root)} -> {raw} escapes repository"
                )
                continue

            if not resolved.exists():
                failures.append(f"{markdown.relative_to(root)} -> {raw} (missing)")

    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = check_internal_links(root)

    if failures:
        print("Broken internal Markdown links:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("Internal Markdown links: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
