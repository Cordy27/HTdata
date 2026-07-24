"""Build static HTML pages from the Markdown documents in docs/content."""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import markdown


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
CONTENT_DIR = DOCS_DIR / "content"

DOCUMENT_METADATA = {
    "news-api": {
        "kicker": "RSS + WECHAT / READ-ONLY API",
        "summary": "面向外部 Agent 的 RSS 与微信公众号新闻聚合查询接口，支持来源发现、关键词检索、正文读取与按批次取数。",
    },
}


def document_title(source: str, slug: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", source, flags=re.MULTILINE)
    return match.group(1).strip() if match else slug.replace("-", " ").title()


def document_summary(source: str, slug: str) -> str:
    configured = DOCUMENT_METADATA.get(slug, {}).get("summary")
    if configured:
        return configured
    for line in source.splitlines():
        value = line.strip()
        if value and not value.startswith("#") and not value.startswith("-"):
            return value
    return ""


def metadata(slug: str, source: str) -> dict[str, str]:
    configured = DOCUMENT_METADATA.get(slug, {})
    return {
        "slug": slug,
        "title": document_title(source, slug),
        "kicker": configured.get("kicker", "REFERENCE"),
        "summary": document_summary(source, slug),
    }


def convert_markdown(source: str) -> str:
    body = re.sub(r"^#\s+.+?\n+", "", source, count=1)
    converter = markdown.Markdown(
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )
    return converter.convert(body)


def navigation(
    documents: list[dict[str, str]],
    active_slug: str | None = None,
    href_prefix: str = "",
) -> str:
    links = []
    for document in documents:
        active = " active" if document["slug"] == active_slug else ""
        links.append(
            f'<a class="document-link{active}" href="{html.escape(href_prefix + document["slug"] + "/")}">'
            f'<strong>{html.escape(document["title"])}</strong>'
            f'<span>{html.escape(document["kicker"])}</span></a>'
        )
    return "\n".join(links)


def page_shell(document: dict[str, str], documents: list[dict[str, str]], body: str) -> str:
    slug = document["slug"]
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(document["summary"])}">
  <meta name="robots" content="index,follow">
  <title>{html.escape(document["title"])} | 华泰互联网技术文档</title>
  <link rel="stylesheet" href="../../css/styles.css">
  <link rel="stylesheet" href="../styles.css">
</head>
<body>
  <div class="docs-shell">
    <aside class="document-library" aria-label="技术文档目录">
      <a class="portal-link" href="../../" aria-label="返回研究数据门户">
        <span class="portal-mark brand-mark">HT</span>
        <span class="portal-copy"><strong>华泰互联网组</strong><small>技术文档中心</small></span>
      </a>
      <div class="library-body">
        <div class="library-heading"><span class="mono">DOCUMENTS</span><strong>技术文档</strong></div>
        <nav class="document-nav" aria-label="文档列表">
          <a class="document-link" href="../">文档目录</a>
          {navigation(documents, slug, "../")}
        </nav>
        <div class="library-foot">正文由仓库中的 Markdown 构建，页面无需运行脚本即可阅读。</div>
      </div>
    </aside>
    <div class="docs-workspace">
      <header class="docs-topbar">
        <div class="docs-topbar-title"><span class="eyebrow">INTERNET RESEARCH WORKSPACE</span><strong>技术文档</strong></div>
        <span class="docs-status"><i></i>Static reference</span>
      </header>
      <main class="document-main">
        <header class="document-hero">
          <p class="eyebrow">{html.escape(document["kicker"])}</p>
          <h1>{html.escape(document["title"])}</h1>
          <p class="document-summary">{html.escape(document["summary"])}</p>
          <div class="document-meta"><span>STATIC HTML</span><span>MARKDOWN SOURCE</span></div>
        </header>
        <article class="document-article">{body}</article>
      </main>
    </div>
  </div>
</body>
</html>
'''


def index_page(documents: list[dict[str, str]]) -> str:
    cards = []
    for document in documents:
        cards.append(
            f'''<a class="document-card" href="{html.escape(document["slug"] + "/")}">
  <span class="eyebrow">{html.escape(document["kicker"])}</span>
  <h2>{html.escape(document["title"])}</h2>
  <p>{html.escape(document["summary"])}</p>
  <span class="document-card-link">阅读文档 <span aria-hidden="true">-&gt;</span></span>
</a>'''
        )
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="华泰互联网研究数据门户技术文档中心。">
  <meta name="robots" content="index,follow">
  <title>技术文档 | 华泰互联网</title>
  <link rel="stylesheet" href="../css/styles.css">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="docs-shell">
    <aside class="document-library" aria-label="技术文档目录">
      <a class="portal-link" href="../" aria-label="返回研究数据门户">
        <span class="portal-mark brand-mark">HT</span>
        <span class="portal-copy"><strong>华泰互联网组</strong><small>技术文档中心</small></span>
      </a>
      <div class="library-body">
        <div class="library-heading"><span class="mono">DOCUMENTS</span><strong>技术文档</strong></div>
        <nav class="document-nav" aria-label="文档列表">
          {navigation(documents)}
        </nav>
        <div class="library-foot">正文由仓库中的 Markdown 构建，页面无需运行脚本即可阅读。</div>
      </div>
    </aside>
    <div class="docs-workspace">
      <header class="docs-topbar">
        <div class="docs-topbar-title"><span class="eyebrow">INTERNET RESEARCH WORKSPACE</span><strong>技术文档</strong></div>
        <span class="docs-status"><i></i>Static reference</span>
      </header>
      <main class="document-main">
        <header class="document-hero">
          <p class="eyebrow">REFERENCE LIBRARY</p>
          <h1>技术文档</h1>
          <p class="document-summary">接口契约、数据边界与接入说明。每份文档都可以通过独立 URL 直接读取。</p>
          <div class="document-meta"><span>{len(documents)} DOCUMENTS</span><span>STATIC HTML</span></div>
        </header>
        <section class="document-cards" aria-label="文档列表">
          {''.join(cards)}
        </section>
      </main>
    </div>
  </div>
</body>
</html>
'''


def main() -> None:
    sources = sorted(CONTENT_DIR.glob("*.md"))
    documents = []
    rendered = []
    for source_path in sources:
        slug = source_path.stem
        source = source_path.read_text(encoding="utf-8")
        document = metadata(slug, source)
        documents.append(document)
        rendered.append((document, convert_markdown(source)))

    for child in DOCS_DIR.iterdir():
        if child.is_dir() and child.name != "content" and (child / "index.html").exists():
            shutil.rmtree(child)

    for document, body in rendered:
        target = DOCS_DIR / document["slug"]
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.html").write_text(page_shell(document, documents, body), encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(index_page(documents), encoding="utf-8")


if __name__ == "__main__":
    main()
