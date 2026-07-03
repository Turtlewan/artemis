from __future__ import annotations

from artemis.reachout.render_script import extract_text


def test_extract_text_strips_script_style_and_collapses_whitespace() -> None:
    html = "<div>A</div><script>bad()</script><style>x</style><p>B</p>"

    assert extract_text(html) == "A B"


def test_extract_text_skips_noscript_and_template_content() -> None:
    html = "<p>keep</p><noscript>no1</noscript><template>tpl</template><p>me</p>"

    assert extract_text(html) == "keep me"
