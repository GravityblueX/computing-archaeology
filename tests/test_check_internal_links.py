from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.check_internal_links as link_checker
from tools.check_internal_links import (
    MARKDOWN_PARSER,
    _bracket_pairs,
    _gfm_bare_url_end,
    _inline_destination_ranges,
    check_internal_links,
    find_link_targets,
    normalize_target,
)


class InternalLinkCheckerTests(unittest.TestCase):
    def check_text(self, markdown: str, existing: tuple[str, ...] = ()) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(markdown, encoding="utf-8")
            for relative in existing:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            return check_internal_links(root)

    def test_finds_full_collapsed_shortcut_and_image_references(self) -> None:
        markdown = """
[full text][full]
[collapsed][]
[shortcut]
![image alt][image]

[full]: full.md
[collapsed]: collapsed.md
[shortcut]: shortcut.md
[image]: image.png
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["full.md", "collapsed.md", "shortcut.md", "image.png"],
        )

    def test_normalizes_reference_label_case_and_whitespace(self) -> None:
        markdown = """
[first][  mixed
 LABEL ]
[MiXeD\tLabel][]

[ mixed\t label ]: target.md
"""
        self.assertEqual(find_link_targets(markdown), ["target.md", "target.md"])

    def test_unescapes_reference_labels_and_destinations(self) -> None:
        markdown = r"""
[escaped][A\]B]
\[not a link]

[a\]b]: docs/escaped\(target\).md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/escaped(target).md"],
        )
        self.assertEqual(
            self.check_text(markdown, ("docs/escaped(target).md",)),
            [],
        )

    def test_first_duplicate_definition_wins_and_undefined_labels_are_text(
        self,
    ) -> None:
        markdown = """
[use][duplicate]
[full][undefined]
[undefined][]
[undefined]

[duplicate]: first.md
[DUPLICATE]: missing.md
"""
        self.assertEqual(find_link_targets(markdown), ["first.md"])

    def test_reference_definitions_support_destination_and_title_continuations(
        self,
    ) -> None:
        markdown = """
[next-line][next]
[titled][title]

[next]:
  docs/next.md
[title]: docs/title.md
  "optional title"
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/next.md", "docs/title.md"],
        )

    def test_ignores_references_in_fenced_and_inline_code(self) -> None:
        markdown = """
```markdown
[fenced][live]
[hidden]: missing-fenced.md
```

~~~
![also fenced][live]
~~~

`[inline][live]` and ``[other ` code][live]``

[live]: missing-live.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_escaped_reference_openers_are_not_links(self) -> None:
        markdown = """
\\[full]\\[live]
\\[shortcut]

[live]: missing.md
[shortcut]: also-missing.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_external_and_fragment_reference_targets_are_ignored(self) -> None:
        markdown = """
[web][web] [mail][mail] [fragment][fragment] [network][network]

[web]: HTTPS://example.com/path
[mail]: mailto:history@example.com
[fragment]: #section
[network]: //example.com/path
"""
        self.assertEqual(self.check_text(markdown), [])

    def test_commonmark_autolinks_are_not_repository_paths(self) -> None:
        markdown = "<https://example.com/path> <person@example.com>"
        self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_extended_autolinks_consume_reference_syntax(self) -> None:
        cases = (
            "https://example.com/[id]",
            "www.example.com/foo[id]bar",
            "https://example.com/![id]",
            "HTTPS://EXAMPLE.COM/foo[id].",
        )
        for source in cases:
            with self.subTest(source=source):
                markdown = f"{source}\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_extended_autolinks_require_their_left_boundary(self) -> None:
        valid_prefixes = ("", " ", "\t", "\n", "*", "_", "~", "(")
        invalid_prefixes = ("a", "0", "-", ".", "@", "+", "/", ":", "=", "%")
        autolinks = (
            "www.example.com/",
            "http://example.com/",
            "https://example.com/",
            "HTTP://example.com/",
            "HTTPS://example.com/",
        )
        for scheme in autolinks:
            for prefix in valid_prefixes:
                with self.subTest(scheme=scheme, prefix=prefix, valid=True):
                    markdown = f"{prefix}{scheme}[id]\n\n[id]: missing.md\n"
                    self.assertEqual(find_link_targets(markdown), [])
            for prefix in invalid_prefixes:
                with self.subTest(scheme=scheme, prefix=prefix, valid=False):
                    markdown = f"{prefix}{scheme}[id]\n\n[id]: missing.md\n"
                    self.assertEqual(find_link_targets(markdown), ["missing.md"])

    def test_gfm_extended_autolinks_use_only_ascii_gfm_whitespace(self) -> None:
        non_gfm_whitespace = (
            "\x1c",
            "\x1d",
            "\x1e",
            "\x1f",
            "\x85",
            "\xa0",
            "\u1680",
            "\u2000",
            "\u2001",
            "\u2002",
            "\u2003",
            "\u2004",
            "\u2005",
            "\u2006",
            "\u2007",
            "\u2008",
            "\u2009",
            "\u200a",
            "\u2028",
            "\u2029",
            "\u202f",
            "\u205f",
            "\u3000",
        )
        for character in non_gfm_whitespace:
            with self.subTest(codepoint=f"U+{ord(character):04X}", position="prefix"):
                markdown = f"x{character}www.example.com/[id]\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), ["missing.md"])
            with self.subTest(codepoint=f"U+{ord(character):04X}", position="path"):
                markdown = f"www.example.com{character}[id]\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_extended_autolinks_require_a_complete_valid_domain(self) -> None:
        valid = (
            "www.example.com/[id]",
            "www.foo-bar.example.com/[id]",
            "www.foo_bar.example.com/[id]",
            "www.example.com-foo/[id]",
            "www.example.com.[id]",
            "http://example.com/[id]",
            "https://foo-bar.example.com/[id]",
            "HTTP://foo_bar.example.com/[id]",
            "HTTPS://EXAMPLE.COM/[id]",
            "ftp://example.com/[id]",
            "www.é.com/[id]",
            "http://中.com/[id]",
            "HTTPS://π.com/[id]",
            "http://١.com/[id]",
        )
        invalid = (
            "WWW.EXAMPLE.COM/[id]",
            "http://localhost/[id]",
            "www.example_com/[id]",
            "www.example_.com/[id]",
            "www.exa_mple.com/[id]",
            "www.example.c_m/[id]",
            "www.example.com_foo/[id]",
            "http://example_com/[id]",
            "http://example_.com/[id]",
            "http://exa_mple.com/[id]",
            "http://example.c_m/[id]",
            "http://example.com_foo/[id]",
            "www..example.com/[id]",
            "www.example..com/[id]",
            "http://.example.com/[id]",
            "http://example..com/[id]",
            "www.😀.com/[id]",
            "https://\ue000.com/[id]",
        )
        for source in valid:
            with self.subTest(source=source, valid=True):
                markdown = f"{source}\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), [])
        for source in invalid:
            with self.subTest(source=source, valid=False):
                markdown = f"{source}\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), ["missing.md"])

    def test_gfm_extended_autolink_scanner_skips_nested_starts(self) -> None:
        source = "www.a.com/" + "_www.a.com/" * 2000 + "[id]"
        self.assertEqual(_gfm_bare_url_end(source, 0), len(source))
        markdown = f"{source}\n\n[id]: missing.md\n"
        self.assertEqual(find_link_targets(markdown), [])

    def test_invalid_nested_autolink_starts_share_one_domain_index(self) -> None:
        source = "www." + "_www." * 2000 + "x"
        with patch.object(
            link_checker,
            "_index_gfm_domain_run",
            wraps=link_checker._index_gfm_domain_run,
        ) as index_run:
            self.assertEqual(find_link_targets(source), [])
        self.assertEqual(index_run.call_count, 1)

        nested_valid = "www.._www.example.com/[id]\n\n[id]: missing.md\n"
        self.assertEqual(find_link_targets(nested_valid), [])

    def test_gfm_entity_suffix_uses_absolute_match_offsets(self) -> None:
        source = "x www.example.com/&amp;"
        self.assertEqual(_gfm_bare_url_end(source, 2), source.index("&"))
        self.assertEqual(
            MARKDOWN_PARSER.render(source),
            '<p>x <a href="http://www.example.com/">www.example.com/</a>' "&amp;</p>\n",
        )

    def test_gfm_ftp_autolinks_trigger_after_plain_text(self) -> None:
        for source in (
            "ftp://example.com/[id]",
            "FTP://example.com/[id]",
            "x ftp://example.com/[id]",
            "x FTP://example.com/[id]",
        ):
            with self.subTest(source=source):
                markdown = f"{source}\n\n[id]: missing.md\n"
                self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_autolink_scan_resumes_after_an_inline_destination(self) -> None:
        for separator in ("_", "*", "<_"):
            with self.subTest(separator=separator):
                markdown = (
                    f"[local](www.example.com/foo){separator}"
                    "www.example.com/[id]\n\n[id]: missing.md\n"
                )
                self.assertEqual(
                    find_link_targets(markdown),
                    ["www.example.com/foo"],
                )

    def test_gfm_autolinks_do_not_start_inside_link_text(self) -> None:
        markdown = """
[_www.example.com/![inline-image]](outer.md)
[text _www.example.com/![reference-image]][outer]

[inline-image]: inline.png
[reference-image]: reference.png
[outer]: reference-link.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["outer.md", "inline.png", "reference-link.md", "reference.png"],
        )

    def test_gfm_autolinks_do_not_start_inside_code_spans(self) -> None:
        markdown = """
`_www.example.com/foo`![single]
``(www.example.com/foo``[double]

[single]: single.png
[double]: double.md
"""
        self.assertEqual(find_link_targets(markdown), ["single.png", "double.md"])

    def test_gfm_autolinks_do_not_start_inside_html_tags(self) -> None:
        markdown = (
            '<span data-x="_www.example.com/foo">[id]</span>\n\n' "[id]: missing.md\n"
        )
        self.assertEqual(find_link_targets(markdown), ["missing.md"])

    def test_inline_destination_scan_coalesces_deeply_nested_ranges(self) -> None:
        source = "[x](" * 2000 + "target" + ")" * 2000
        self.assertEqual(
            _inline_destination_ranges(source, _bracket_pairs(source)),
            [(3, len(source) - 1)],
        )

    def test_inline_destination_scan_preserves_angle_and_escape_rules(self) -> None:
        cases = (
            "[x](<foo(bar>)",
            "[x](foo\\)bar)",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    _inline_destination_ranges(source, _bracket_pairs(source)),
                    [(3, len(source) - 1)],
                )

    def test_bracketed_bare_email_matches_github_rendering(self) -> None:
        markdown = "person+tag[id]@example.com\n\n[id]: missing.md\n"
        self.assertEqual(find_link_targets(markdown), ["missing.md"])

    def test_explicit_local_destination_is_not_extended_autolink_text(self) -> None:
        markdown = "[local](www.example.com/foo[id])\n\n[id]: ignored.md\n"
        targets = find_link_targets(markdown)
        self.assertEqual(
            [normalize_target(target) for target in targets],
            ["www.example.com/foo[id]"],
        )

    def test_reference_target_is_checked_only_when_definition_is_used(self) -> None:
        markdown = """
[used][missing]
[literal][undefined]

[missing]: missing.md
[unused]: also-missing.md
"""
        self.assertEqual(
            self.check_text(markdown),
            ["README.md -> missing.md (missing)"],
        )

    def test_preserves_inline_link_and_image_checks(self) -> None:
        markdown = """
[existing](docs/existing.md)
[nested](docs/a_(b).md)
[spaced](<docs/with space.md> "title")
![missing image](images/missing.png)
[external](https://example.com/a_(b))
[fragment](#local)
"""
        self.assertEqual(
            self.check_text(
                markdown,
                ("docs/existing.md", "docs/a_(b).md", "docs/with space.md"),
            ),
            ["README.md -> images/missing.png (missing)"],
        )

    def test_literal_leading_slash_resolves_from_repository_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "docs"
            nested.mkdir()
            (root / "README.md").write_text("# Root\n", encoding="utf-8")
            (nested / "source.md").write_text(
                "[Repository root](/README.md)\n",
                encoding="utf-8",
            )

            self.assertEqual(check_internal_links(root), [])

    def test_encoded_leading_slash_stays_source_relative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "docs"
            nested.mkdir()
            (root / "README.md").write_text("# Root\n", encoding="utf-8")
            (nested / "target.md").write_text("# Target\n", encoding="utf-8")
            (nested / "source.md").write_text(
                "[Same directory](%2Ftarget.md)\n"
                "[Parent directory](%2F..%2FREADME.md)\n",
                encoding="utf-8",
            )

            self.assertEqual(check_internal_links(root), [])

    def test_root_and_encoded_paths_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "repository"
            nested = root / "docs"
            nested.mkdir(parents=True)
            (parent / "outside.md").write_text("# Outside\n", encoding="utf-8")
            (nested / "source.md").write_text(
                "[Root traversal](/../outside.md)\n"
                "[Encoded traversal](%2F..%2F..%2Foutside.md)\n",
                encoding="utf-8",
            )

            errors = check_internal_links(root)

            self.assertEqual(len(errors), 2)
            self.assertTrue(all("escapes repository" in error for error in errors))

    def test_invalid_percent_encoded_paths_are_reported_deterministically(
        self,
    ) -> None:
        markdown = (
            "[invalid UTF-8](replacement-%FF.md)\n"
            "[embedded NUL](embedded%00nul.md)\n"
        )

        self.assertEqual(
            self.check_text(markdown, ("replacement-\ufffd.md",)),
            [
                "README.md -> replacement-%FF.md (invalid path)",
                "README.md -> embedded%00nul.md (invalid path)",
            ],
        )

    def test_inline_code_and_escaped_inline_links_are_not_checked(self) -> None:
        markdown = """
`[code](missing-code.md)`
``[code with `](missing-code-2.md)``
\\[escaped](missing-escaped.md)
"""
        self.assertEqual(self.check_text(markdown), [])

    def test_definition_like_text_in_code_or_four_space_indent_is_not_active(
        self,
    ) -> None:
        markdown = """
```text
[fenced]: missing-fenced.md
```
    [indented]: missing-indented.md
    [indented usage][live]
    [indented inline](missing-inline.md)

[fenced] [indented]

[live]: missing-live.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_paragraph_text_cannot_be_interrupted_by_a_definition(self) -> None:
        markdown = """A paragraph continues here
[not-a-definition]: missing.md

[not-a-definition]
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_footnotes_are_not_reference_links(self) -> None:
        markdown = """
Footnote usage.[^source]

[^source]: docs/not-a-link.md and [rendered link](docs/rendered.md)
"""
        self.assertEqual(find_link_targets(markdown), ["docs/rendered.md"])

    def test_reference_links_render_inside_gfm_table_cells(self) -> None:
        markdown = """
| resource |
| --- |
| [full][guide] |
| [guide] |

[guide]: docs/guide.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/guide.md", "docs/guide.md"],
        )

    def test_definitions_inside_list_and_block_quote_containers_are_global(
        self,
    ) -> None:
        markdown = """
[inline list][list-inline]
[continued list][list-continued]
[quoted][quote]

- [list-inline]: docs/list-inline.md

- [list-continued]:
    docs/list-continued.md

> [quote]:
>   docs/quote.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            [
                "docs/list-inline.md",
                "docs/list-continued.md",
                "docs/quote.md",
            ],
        )

    def test_container_blocks_respect_paragraph_interruption_rules(self) -> None:
        markdown = """
outer paragraph
- [list]: docs/list.md

outer paragraph
2. [not-a-list]: docs/not-a-list.md

> quoted paragraph
> [not-a-definition]: docs/not-a-definition.md

> quoted paragraph
> - [nested-list]: docs/nested-list.md

[list use][list]
[literal][not-a-list]
[literal][not-a-definition]
[nested use][nested-list]
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/list.md", "docs/nested-list.md"],
        )

    def test_list_marker_padding_controls_indented_code(self) -> None:
        markdown = """
[four][four]
[five][five]

-    [four]: docs/four.md
-     [five]: docs/five.md
"""
        self.assertEqual(find_link_targets(markdown), ["docs/four.md"])

    def test_quoted_fences_and_indented_code_mask_link_syntax(self) -> None:
        markdown = """
> ~~~markdown
> [fenced][live]
> ~~~

>     [indented][live]

[live]: docs/live.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_definition_after_quoted_fence_starts_a_new_block(self) -> None:
        markdown = """
> ~~~text
> code
> ~~~
[after]: docs/after.md

[use][after]
"""
        self.assertEqual(find_link_targets(markdown), ["docs/after.md"])

    def test_quoted_fence_ends_with_its_container(self) -> None:
        markdown = """
> ```markdown
> code
[outside][live]

[live]: docs/live.md
"""
        self.assertEqual(find_link_targets(markdown), ["docs/live.md"])

    def test_raw_html_blocks_mask_markdown_and_close_cleanly(self) -> None:
        markdown = """
<script>
[script][script-id]
</script>
[script-id]: docs/script.md

[script use][script-id]

<!--
[comment][comment-id]
-->
[comment-id]: docs/comment.md

[comment use][comment-id]

<div>
[hidden][hidden-id]

</div>

[hidden-id]: docs/hidden.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/script.md", "docs/comment.md"],
        )

    def test_html_declaration_closer_precedes_container_parsing(self) -> None:
        markdown = """
<!DOCUMENT
[hidden][visible]
>
[visible]: docs/visible.md

[use][visible]
"""
        self.assertEqual(find_link_targets(markdown), ["docs/visible.md"])

    def test_invalid_angle_construct_does_not_hide_reference_usage(self) -> None:
        markdown = """
<foo [id]>

[id]: docs/visible.md
"""
        self.assertEqual(find_link_targets(markdown), ["docs/visible.md"])

    def test_nested_links_and_images_follow_rendered_commonmark_structure(self) -> None:
        markdown = """
[outer [inner](inner.md)](not-rendered.md)
[outer ![image](image.png)](outer.md)
![alt [hidden](hidden.md)](outer.png)
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["inner.md", "outer.md", "image.png", "outer.png"],
        )

    def test_multiline_definition_labels_destinations_and_titles(self) -> None:
        markdown = """
[use][multi line]

[multi
 line]:
      docs/multiline.md
        "a title
        on two lines"
"""
        self.assertEqual(find_link_targets(markdown), ["docs/multiline.md"])

    def test_invalid_definition_and_blank_inline_link_stay_literal(self) -> None:
        markdown = """
[bad definition][bad]
[blank inline](missing.md

)

[bad]: <missing.md>(title-without-separator)
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_gfm_label_whitespace_does_not_collapse_nbsp(self) -> None:
        markdown = """
[vertical-tab][a\v b]
[form-feed][a\f b]
[no-break-space][a\u00a0b]

[a b]: gfm-whitespace.md
[a\u00a0b]: nbsp.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["gfm-whitespace.md", "gfm-whitespace.md", "nbsp.md"],
        )

    def test_reference_label_escapes_must_match_exactly(self) -> None:
        markdown = """
[bar][foo\\!]

[foo!]: missing.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_reference_links_accept_crlf_line_endings(self) -> None:
        markdown = "[use][two lines]\r\n\r\n[two\r\n lines]: docs/crlf.md\r\n"
        self.assertEqual(find_link_targets(markdown), ["docs/crlf.md"])

    def test_definition_titles_and_angle_destinations_do_not_become_paths(self) -> None:
        markdown = """
[angle][angle]
[single][single]
[parenthesized][parenthesized]

[angle]: <docs/with space.md> "double title"
[single]: docs/single.md 'single title'
[parenthesized]: docs/parenthesized.md (parenthesized title)
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["docs/with%20space.md", "docs/single.md", "docs/parenthesized.md"],
        )

    def test_labels_longer_than_commonmark_limit_remain_literal(self) -> None:
        label = "x" * 1000
        markdown = f"[text][{label}]\n\n[{label}]: missing.md\n"
        self.assertEqual(find_link_targets(markdown), [])

    def test_label_limit_counts_normalized_crlf_as_one_character(self) -> None:
        allowed = "x" * 997 + "\r\n" + "y"
        rejected = "x" * 998 + "\r\n" + "y"
        allowed_markdown = f"[use][{allowed}]\r\n\r\n[{allowed}]: allowed.md\r\n"
        rejected_markdown = f"[use][{rejected}]\r\n\r\n[{rejected}]: rejected.md\r\n"
        self.assertEqual(find_link_targets(allowed_markdown), ["allowed.md"])
        self.assertEqual(find_link_targets(rejected_markdown), [])

    def test_overlong_uses_cannot_match_a_short_normalized_label(self) -> None:
        label = "a" + " " * 999 + "b"
        markdown = f"""
[full][{label}]
![image][{label}]
[{label}][]
[{label}]

[a b]: missing.md
"""
        self.assertEqual(find_link_targets(markdown), [])

    def test_invalid_overlong_definition_does_not_shadow_valid_definition(
        self,
    ) -> None:
        label = "a" + " " * 999 + "b"
        markdown = f"""
[use][a b]

[{label}]: invalid.md
[a b]: valid.md
"""
        self.assertEqual(find_link_targets(markdown), ["valid.md"])

    def test_long_inline_link_text_keeps_its_destination(self) -> None:
        label = "x" * 1000
        self.assertEqual(find_link_targets(f"[{label}](inline.md)"), ["inline.md"])

    def test_long_link_text_can_use_a_short_full_reference_label(self) -> None:
        text = "x" * 1000
        markdown = f"[{text}][id]\n\n[id]: full.md\n"
        self.assertEqual(find_link_targets(markdown), ["full.md"])

    def test_long_brackets_outside_labels_do_not_change_targets(self) -> None:
        bracketed = "[" + "x" * 1000 + "]"
        markdown = f"""
[destination](<docs/{bracketed}.md>)
`{bracketed}`
<span data-value="{bracketed}">text</span>
"""
        targets = find_link_targets(markdown)
        self.assertEqual(
            [normalize_target(target) for target in targets],
            [f"docs/{bracketed}.md"],
        )

    def test_all_non_gfm_unicode_whitespace_stays_label_content(self) -> None:
        codepoints = [
            *range(0x1C, 0x20),
            0x85,
            0xA0,
            0x1680,
            *range(0x2000, 0x200B),
            0x2028,
            0x2029,
            0x202F,
            0x205F,
            0x3000,
        ]
        for codepoint in codepoints:
            with self.subTest(codepoint=f"U+{codepoint:04X}"):
                whitespace = chr(codepoint)
                markdown = (
                    f"[use][a{whitespace}b]\n\n"
                    "[a b]: ascii.md\n"
                    f"[a{whitespace}b]: unicode.md\n"
                )
                self.assertEqual(find_link_targets(markdown), ["unicode.md"])

    def test_placeholder_allocation_extends_beyond_the_bmp_private_use_area(
        self,
    ) -> None:
        occupied_bmp_private_use = "".join(
            chr(codepoint) for codepoint in range(0xE000, 0xF900)
        )
        markdown = (
            f"{occupied_bmp_private_use}\n\n"
            "[use][a\u00a0b]\n\n"
            "[a\u00a0b]: unicode.md\n"
        )
        self.assertEqual(find_link_targets(markdown), ["unicode.md"])

    def test_entity_and_literal_whitespace_labels_remain_distinct(self) -> None:
        markdown = """
[entity][a&nbsp;b]
[literal][a\u00a0b]
[ascii][a b]

[a&nbsp;b]: entity.md
[a\u00a0b]: literal.md
[a b]: ascii.md
"""
        self.assertEqual(
            find_link_targets(markdown),
            ["entity.md", "literal.md", "ascii.md"],
        )

    def test_entity_label_does_not_match_literal_nbsp_definition(self) -> None:
        markdown = "[use][a&#xA0;b]\n\n[a\u00a0b]: missing.md\n"
        self.assertEqual(find_link_targets(markdown), [])

    def test_unicode_whitespace_in_destination_is_restored(self) -> None:
        targets = find_link_targets("[use](docs/a\u00a0b.md)")
        self.assertEqual(
            [normalize_target(target) for target in targets],
            ["docs/a\u00a0b.md"],
        )

    def test_placeholders_avoid_entity_and_percent_encoded_targets(self) -> None:
        markdown = """
[literal][a\u00a0b]
[entity target](docs/a&#xE000;b.md)
[percent target](docs/a%EE%80%80b.md)
[lowercase percent target](docs/a%ee%80%80b.md)
[literal target](docs/a\ue000b.md)
[entity percent target](docs/a&#37;EE&#37;80&#37;80b.md)
[escaped percent target](docs/a\\%EE\\%80\\%80b.md)
[mixed percent target](docs/a&#37;EE\\%80&#37;80b.md)

[a\u00a0b]: literal.md
"""
        targets = find_link_targets(markdown)
        self.assertEqual(
            [normalize_target(target) for target in targets],
            [
                "literal.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
                "docs/a\ue000b.md",
            ],
        )


if __name__ == "__main__":
    unittest.main()
