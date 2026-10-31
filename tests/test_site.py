import unittest
from html.parser import HTMLParser
from inspect import getdoc
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from grugdb import Column, RowId
from tools.site import Page, Site, highlight_block


class Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: list[str] = []
        self.anchors: list[dict[str, str | None]] = []
        self.tasks: list[dict[str, str | None]] = []
        self.anchor_depth = 0
        self.nested_anchors = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "input" and dict(attrs).get("type") == "checkbox":
            self.tasks.append(dict(attrs))
        if tag == "a":
            self.anchor_depth += 1
            self.nested_anchors |= self.anchor_depth > 1
            self.anchors.append(dict(attrs))
        for name, value in attrs:
            if value is not None:
                if name == "id":
                    self.ids.append(value)
                if (tag == "a" and name == "href") or (tag == "script" and name == "src"):
                    self.links.append(value)
                if tag == "link" and name == "href":
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.anchor_depth -= 1


class TestSite(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "output"
        (self.root / "README.md").write_text(
            "# Course\n\n[Start](chapters/01-rows.md)\n", encoding="utf-8"
        )
        (self.root / "chapters").mkdir()
        (self.root / "chapters/01-rows.md").write_text(
            "# 1. Rows\n\n[Home](../README.md)\n\n[Next](02-query.md)\n"
            "\n## A heading\n\nSome `int | None`.\n\n"
            "| Name | Value |\n| --- | --- |\n| ann | 1 |\n"
            "\n```python\nvalue = None\n```\n",
            encoding="utf-8",
        )
        (self.root / "chapters/02-query.md").write_text(
            "# 2. Query\n\n[Rows](01-rows.md#a-heading)\n", encoding="utf-8"
        )
        self.site = Site(self.root, self.output)

    def test_builds_pages_navigation_and_local_assets(self) -> None:
        self.site.build()
        index = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="01-rows.html"', index)
        self.assertTrue((self.output / "02-query.html").is_file())
        self.assertTrue((self.output / "style.css").is_file())
        self.assertTrue((self.output / "theme.js").is_file())
        self.assertNotIn("Print / PDF", index)
        self.assertNotIn("Course home", index)
        self.assertIn('<button id="theme"', index.split("</aside>")[0])
        self.assertIn('href="#content"', index)

    def test_rebuild_removes_obsolete_generated_pages(self) -> None:
        self.site.build()
        obsolete = self.output / "removed-lesson.html"
        obsolete.write_text("old output", encoding="utf-8")

        Site(self.root, self.output).build()

        self.assertFalse(obsolete.exists())
        self.assertTrue((self.output / "index.html").is_file())
        self.assertFalse((self.output / "book.html").exists())

    def test_site_publishes_learner_material_not_maintainer_instructions(self) -> None:
        """Publish tutoring guidance and course tests, not authoring or tooling pages."""
        files = {
            "AGENTS.md": "# Maintainers\n\nAUTHORING_ONLY\n",
            ".agents/skills/prose/SKILL.md": "# Prose\n\nAUTHORING_ONLY\n",
            ".agents/skills/tutor/SKILL.md": "# Tutor\n\nLEARNER_TUTOR\n",
            ".agents/skills/tutor/references/teaching.md": "# Teaching\n\nReferences.\n",
            "tests/test_course.py": '"""DEVELOPER_TESTS"""\n',
            "tests/test_site.py": '"""DEVELOPER_TESTS"""\n',
            "tests/test_table.py": '"""LEARNER_TESTS"""\n',
        }
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.output.mkdir()
        hidden = ("agents", "prose", "test-course", "test-site")
        for slug in hidden:
            (self.output / f"{slug}.html").write_text("old output", encoding="utf-8")

        Site(self.root, self.output).build()

        self.assertIn("LEARNER_TUTOR", (self.output / "tutor.html").read_text())
        self.assertTrue((self.output / "teaching.html").is_file())
        self.assertTrue((self.output / "test-table.html").is_file())
        for slug in hidden:
            self.assertFalse((self.output / f"{slug}.html").exists())
        for page in self.output.glob("*.html"):
            html = page.read_text(encoding="utf-8")
            self.assertNotIn("AUTHORING_ONLY", html)
            self.assertNotIn("DEVELOPER_TESTS", html)

    def test_tables_blocks_and_inline_code_are_rendered(self) -> None:
        rendered = self.site.render(self.site.chapters[0])
        self.assertIn("<table>", rendered)
        self.assertIn('<pre class="highlight"><code>', rendered)
        self.assertNotIn("<pre><code><pre", rendered)
        self.assertIn('class="inline-code"', rendered)
        self.assertIn('class="hl-constant-builtin">None', rendered)

    def test_chapter_links_point_to_chapter_pages(self) -> None:
        rendered = self.site.render(self.site.chapters[1])
        self.assertIn('href="01-rows.html#01-rows-a-heading"', rendered)

    def test_unknown_languages_and_raw_html_are_escaped(self) -> None:
        rendered = highlight_block("<script>alert(1)</script>", "unknown-language-name", "")
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        page = Page(
            self.root / "example.md",
            "example",
            "Example",
            "# Example\n\n<script>alert(1)</script>\n\n`<img src=x onerror=alert(1)>`\n",
        )
        body = self.site.render(page)
        self.assertNotIn("<script>", body)
        self.assertNotIn("<img ", body)

    def test_frontmatter_is_hidden_without_changing_source(self) -> None:
        source = self.root / "skill.md"
        original = "---\nname: tutor\ndescription: Teach\n---\n\n# Tutor\n\nHelp.\n"
        source.write_text(original, encoding="utf-8")
        page = Page.read(source, "tutor")
        self.assertNotIn("name: tutor", page.markdown)
        self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_unclosed_frontmatter_fails(self) -> None:
        source = self.root / "skill.md"
        source.write_text("---\nname: tutor\n# Tutor\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unclosed frontmatter"):
            Page.read(source, "tutor")

    def test_missing_local_links_fail_the_build(self) -> None:
        (self.root / "README.md").write_text(
            "# Course\n\n[Missing](missing.md)\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Unknown local link"):
            Site(self.root, self.output).build()

    def test_introduction_is_homepage_and_precedes_database_lessons(self) -> None:
        (self.root / "chapters/00-intro.md").write_text(
            "# Introduction\n\nCourse setup.\n\n[Start](01-rows.md)\n", encoding="utf-8"
        )
        site = Site(self.root, self.output)
        site.build()
        self.assertEqual(site.course[0].slug, "index")
        self.assertEqual(site.chapters[0].slug, "01-rows")
        home = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn("Course setup.", home)
        self.assertIn('href="01-rows.html">Next', home)
        self.assertNotIn("Preface", home)
        self.assertNotIn(">Previous<span>", site.page_links(site.course[0]))
        self.assertIn('class="number">01</span>', site.navigation("index"))
        self.assertIn('href="index.html"', site.page_links(site.chapters[0]))

    def test_navigation_groups_chapters_into_parts(self) -> None:
        site = Site(Path(__file__).resolve().parents[1], self.output)
        navigation = site.navigation("index")
        for label in ("Part 1", "Part 2", "Part 3", "Appendix"):
            self.assertIn(label, navigation)
        self.assertIn(">Next<span>", site.page_links(site.chapters[6]))

    def test_external_links_are_unchanged(self) -> None:
        page = self.site.chapters[0]
        href = "https://example.com/guide?x=1#section"
        self.assertEqual(self.site.link(href, page), href)

    def test_heading_ids_are_unique_and_stable(self) -> None:
        page = Page(
            self.root / "example.md",
            "example",
            "Example",
            "# Example\n\n## Test\n\n## Test\n",
        )
        rendered = self.site.render(page)
        self.assertIn('id="example-test"', rendered)
        self.assertIn('id="example-test-2"', rendered)
        self.assertEqual(rendered, self.site.render(page))

    def render_code(self, markdown: str) -> Document:
        document = Document()
        document.feed(
            self.site.render(Page(self.root / "example.md", "example", "Example", markdown))
        )
        return document

    def test_reference_links_in_inline_code_and_python_fences(self) -> None:
        sample = "Row Column[str] Unique[str] Table(User) Database() Query"
        for language in ("python", "py", "pycon"):
            with self.subTest(language=language):
                prompt = ">>> " if language == "pycon" else ""
                document = self.render_code(f"`{sample}`\n\n```{language}\n{prompt}{sample}\n```\n")
                for name in ("Row", "Column", "Unique", "Table", "Database", "Query"):
                    self.assertEqual(
                        document.links.count(f"reference.html#reference-{name.lower()}"), 2
                    )
                self.assertFalse(document.nested_anchors)

    def test_lowercase_terms_link_only_in_their_api_context(self) -> None:
        document = self.render_code(
            "```python\ncolumn(default=1); table.lookup(); table.scan()\n"
            "column = 2; lookup = 1; scan(); row = user\n"
            "def column(): pass\ndef scan(): pass\n```\n"
        )
        self.assertEqual(document.links.count("reference.html#reference-column-2"), 1)
        self.assertEqual(document.links.count("reference.html#reference-lookup"), 1)
        self.assertEqual(document.links.count("reference.html#reference-scan"), 1)
        self.assertEqual(len(document.links), 3)

    def test_strings_comments_raw_html_and_unknown_fences_are_not_linked(self) -> None:
        document = self.render_code(
            '```python\n"Column Row"\n# Column Row\nunknown = 1\n```\n\n'
            "```unknown-language-name\nColumn Row\n```\n\n"
            "```text\nColumn Row\n```\n\n<a>Column Row</a>\n\n`'Column Row'`\n"
        )
        self.assertEqual(document.links, [])

    def test_markdown_link_labels_do_not_contain_nested_links(self) -> None:
        document = self.render_code(
            "[`Column` and `column()`](REFERENCE.md#column)\n\n"
            "[**`Row`**](https://example.com)\n\n`Row`\n"
        )
        self.assertFalse(document.nested_anchors)
        self.assertEqual(
            document.links,
            [
                "reference.html#reference-column",
                "https://example.com",
                "reference.html#reference-row",
            ],
        )
        self.assertEqual(sum(anchor.get("class") == "api-term" for anchor in document.anchors), 1)

    def test_docstrings_supply_reference_and_hover_without_markdown_copy(self) -> None:
        self.assertFalse((self.root / "REFERENCE.md").exists())
        term = self.site.terms["Column"]
        self.assertEqual(term.documentation, getdoc(Column))
        self.assertIn("class Column[K]:", term.source)
        self.assertIn("def __get__", term.source)
        self.assertNotIn('"""', term.source)
        self.assertNotIn("class User", term.source)
        self.assertEqual(self.site.terms["RowId"].documentation, getdoc(RowId))
        self.assertEqual(self.site.terms["RowId"].source, 'RowId = NewType("RowId", int)')
        self.site.build()
        self.assertTrue((self.output / "reference.html").is_file())
        self.assertIn('href="reference.html">API reference', self.site.navigation("index"))

    def test_preview_escapes_docstrings_and_highlights_each_view_once(self) -> None:
        summary = 'A Column with <tags> & "quotes".'
        example = 'Column[str] = column(default="<script>")'
        documentation = f"{summary}\n\nAnother paragraph.\n\n```python\n{example}\n```"
        with patch.object(Column, "__doc__", documentation):
            site = Site(self.root, self.output)
        self.assertEqual(site.terms["Column"].documentation, documentation)
        body = site.render(Page(self.root / "example.md", "example", "Example", "`Column`"))
        document = Document()
        document.feed(body)
        term = document.anchors[0]
        self.assertEqual(term["data-summary"], summary)
        self.assertEqual(term["title"], f"{summary}\n\n{example}")
        html = site.document("Example", body, "example")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<tags>", html)
        self.assertEqual(html.count('id="api-preview-Column"'), 1)
        self.assertIn('<section data-view="source"><pre class="highlight">', html)
        self.assertIn('<span class="hl-keyword">class</span>', html)
        self.assertIn('class="hl-string"', html)
        self.assertNotIn("data-example=", html)

    def test_factory_imports_are_linked_as_well_as_calls(self) -> None:
        document = self.render_code("```python\nfrom grugdb import Column, column\n```")
        self.assertEqual(
            document.links,
            ["reference.html#reference-column", "reference.html#reference-column-2"],
        )

    def test_task_keys_are_rendered_for_each_checklist_item(self) -> None:
        page = Page(
            self.root / "tasks.md",
            "tasks",
            "Tasks",
            "# Tasks\n\n- [ ] Implement `Table.get`.\n- [x] Write a test.\n",
        )
        standalone = Document()
        standalone.feed(self.site.render(page))
        self.assertEqual(len(standalone.tasks), 2)
        self.assertNotIn("checked", standalone.tasks[0])
        self.assertIn("checked", standalone.tasks[1])
        reordered = Document()
        reordered.feed(
            self.site.render(
                Page(
                    page.source,
                    page.slug,
                    page.title,
                    "# Tasks\n\n- [x] Write a test.\n- [ ] Implement\n  `Table.get`.\n",
                )
            )
        )
        self.assertEqual(standalone.tasks, list(reversed(reordered.tasks)))

    def test_test_links_use_code_docstrings_and_validate_exact_method(self) -> None:
        (self.root / "tests").mkdir()
        (self.root / "tests/test_example.py").write_text(
            "class TestExample:\n    def test_value(self):\n"
            '        """A stored value is returned unchanged."""\n        assert 1 == 1\n',
            encoding="utf-8",
        )
        site = Site(self.root, self.output)
        page = Page(
            self.root / "chapters/example.md",
            "example",
            "Example",
            "# Example\n\n- [ ] [TestExample.test_value]"
            "(../tests/test_example.py#TestExample.test_value)\n",
        )
        document = Document()
        rendered = site.render(page)
        document.feed(rendered)
        self.assertIn("A stored value is returned unchanged.", rendered)
        self.assertNotIn(">TestExample.test_value<", rendered)
        self.assertEqual(document.links, ["test-example.html#test-example-testexample-test-value"])
        site.build()
        code = (self.output / "test-example.html").read_text(encoding="utf-8")
        self.assertIn("A stored value is returned unchanged.", code)
        self.assertIn("tests.test_example.TestExample.test_value", code)
        with self.assertRaisesRegex(ValueError, "Unknown test"):
            site.link("../tests/test_example.py#TestExample.test_missing", page)

    def test_gruvbox_material_styles_both_modes_and_syntax(self) -> None:
        self.site.build()
        css = (self.output / "style.css").read_text(encoding="utf-8")
        self.assertIn("--paper: #fbf1c7", css)
        self.assertIn("--paper: #282828", css)
        self.assertIn(':root[data-theme="dark"] code .hl-type', css)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertNotIn("@media print", css)
        self.assertNotIn("toolbar", css)
        self.assertNotIn(".kc,", css)

    def test_file_paths_are_plain_code_without_python_scopes(self) -> None:
        page = Page(
            self.root / "paths.md",
            "paths",
            "Paths",
            "# Paths\n\n`src/grugdb/table.py` `pyproject.toml` "
            "`src/grugdb` `../my-grugdb` `RowId`\n",
        )
        rendered = self.site.render(page)
        self.assertIn('<code class="inline-code">src/grugdb/table.py</code>', rendered)
        self.assertIn('<code class="inline-code">pyproject.toml</code>', rendered)
        self.assertIn('<code class="inline-code">src/grugdb</code>', rendered)
        self.assertIn('<code class="inline-code">../my-grugdb</code>', rendered)
        self.assertIn('data-term="RowId"', rendered)

    def test_learner_pages_omit_machine_specific_workspace_paths(self) -> None:
        """Learner pages contain no workspace banner or local absolute path."""
        (self.root / ".course.json").write_text("{}", encoding="utf-8")
        html = self.site.document("Example", "Body", "example")
        self.assertNotIn('class="workspace-note"', html)
        self.assertNotIn(str(self.root.resolve()), html)
        self.assertNotIn("Work in ", html)

    def test_real_course_links_back_to_github_and_shares_well(self) -> None:
        """Pages link to their GitHub source, carry preview metadata, and a 404 exists."""
        root = Path(__file__).resolve().parents[1]
        Site(root, self.output).build()
        chapter = (self.output / "01-rows-and-tables.html").read_text(encoding="utf-8")
        repo = "https://github.com/h0rv/grugdb"
        self.assertIn(f'href="{repo}">Source on GitHub', chapter)
        self.assertIn(f"{repo}/blob/main/chapters/01-rows-and-tables.md", chapter)
        self.assertIn(f'class="file-link" href="{repo}/blob/main/src/grugdb/table.py"', chapter)
        self.assertIn(
            '<link rel="canonical" href="https://grugdb.horv.co/01-rows-and-tables.html">', chapter
        )
        self.assertIn('<meta property="og:title"', chapter)
        self.assertIn('<meta name="description" content="A row is one record', chapter)
        home = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="canonical" href="https://grugdb.horv.co/">', home)
        missing = (self.output / "404.html").read_text(encoding="utf-8")
        self.assertIn('<base href="/">', missing)
        self.assertIn("Page not found", missing)

    def test_real_course_has_valid_local_links_and_anchors(self) -> None:
        root = Path(__file__).resolve().parents[1]
        Site(root, self.output).build()
        documents: dict[str, Document] = {}
        for path in self.output.glob("*.html"):
            document = Document()
            document.feed(path.read_text(encoding="utf-8"))
            self.assertEqual(len(document.ids), len(set(document.ids)), path.name)
            self.assertFalse(document.nested_anchors, path.name)
            documents[path.name] = document
        self.assertIn("reference.html", documents)
        self.assertIn("reference-column", documents["reference.html"].ids)
        self.assertTrue(
            any(
                "reference.html#reference-column" in document.links
                for document in documents.values()
            )
        )
        for filename, document in documents.items():
            for href in document.links:
                url = urlsplit(href)
                if url.scheme or url.netloc:
                    continue
                destination = unquote(url.path) or filename
                with self.subTest(source=filename, href=href):
                    self.assertTrue((self.output / destination).is_file())
                    if url.fragment:
                        self.assertIn(unquote(url.fragment), documents[destination].ids)


if __name__ == "__main__":
    unittest.main()
