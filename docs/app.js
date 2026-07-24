(function () {
  'use strict';

  const base = document.querySelector('base').href;
  const manifestUrl = new URL('docs/documents.json', base);
  const article = document.getElementById('document-article');
  const nav = document.getElementById('document-nav');
  const title = document.getElementById('document-title');
  const kicker = document.getElementById('document-kicker');
  const summary = document.getElementById('document-summary');
  const meta = document.getElementById('document-meta');
  const apiBase = document.body.dataset.apiBase;
  let documents = [];

  function selectedSlug() {
    return decodeURIComponent(window.location.hash.slice(1) || 'news-api');
  }

  function safeSlug(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-').replace(/^-+|-+$/g, '') || 'section';
  }

  function documentUrl(source) {
    return new URL(`docs/${source}`, base);
  }

  function renderNavigation(activeSlug) {
    nav.replaceChildren();
    for (const doc of documents) {
      const button = document.createElement('button');
      button.type = 'button';
      button.classList.toggle('active', doc.slug === activeSlug);
      const name = document.createElement('strong');
      name.textContent = doc.title;
      const detail = document.createElement('span');
      detail.textContent = doc.kicker || 'REFERENCE';
      button.append(name, detail);
      button.addEventListener('click', () => { window.location.hash = encodeURIComponent(doc.slug); });
      nav.append(button);
    }
  }

  function sanitizeArticle(root) {
    root.querySelectorAll('script, style, iframe, object, embed, link, meta').forEach((node) => node.remove());
    root.querySelectorAll('*').forEach((node) => {
      for (const attribute of [...node.attributes]) {
        const name = attribute.name.toLowerCase();
        const value = attribute.value.trim().toLowerCase();
        if (name.startsWith('on') || ((name === 'href' || name === 'src') && value.startsWith('javascript:'))) node.removeAttribute(attribute.name);
      }
    });
  }

  function decorateHeadings(root) {
    const used = new Set();
    root.querySelectorAll('h2, h3').forEach((heading) => {
      const baseId = safeSlug(heading.textContent);
      let id = baseId;
      let suffix = 2;
      while (used.has(id)) id = `${baseId}-${suffix++}`;
      used.add(id);
      heading.id = id;
    });
  }

  function renderMeta(doc) {
    meta.replaceChildren();
    const item = document.createElement('span');
    item.textContent = `UPDATED ${doc.updated || '—'}`;
    meta.append(item);
    if (doc.widgets && doc.widgets.includes('news-api-console')) {
      const api = document.createElement('span');
      api.textContent = 'INTERACTIVE API CONSOLE';
      meta.append(api);
    }
  }

  async function renderDocument() {
    const slug = selectedSlug();
    const doc = documents.find((item) => item.slug === slug) || documents[0];
    if (!doc) return;
    if (doc.slug !== slug) history.replaceState(null, '', `#${encodeURIComponent(doc.slug)}`);
    renderNavigation(doc.slug);
    kicker.textContent = doc.kicker || 'REFERENCE';
    title.textContent = doc.title;
    summary.textContent = doc.summary || '';
    renderMeta(doc);
    article.innerHTML = '<p class="mono">Loading document…</p>';
    try {
      const response = await fetch(documentUrl(doc.source), { cache: 'no-store' });
      if (!response.ok) throw new Error(`Document source returned ${response.status}`);
      const markdown = await response.text();
      article.innerHTML = window.marked.parse(markdown, { gfm: true, breaks: false, mangle: false, headerIds: false });
      sanitizeArticle(article);
      decorateHeadings(article);
      for (const widget of doc.widgets || []) {
        if (widget === 'news-api-console') window.HTDocsWidgets.mountNewsApiConsole(article, { apiBase });
      }
      if (window.lucide) window.lucide.createIcons();
    } catch (error) {
      article.replaceChildren();
      const errorNode = document.createElement('p');
      errorNode.className = 'document-error';
      errorNode.textContent = `无法加载文档：${error instanceof Error ? error.message : String(error)}`;
      article.append(errorNode);
    }
  }

  async function init() {
    try {
      const response = await fetch(manifestUrl, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Document manifest returned ${response.status}`);
      const manifest = await response.json();
      documents = Array.isArray(manifest.documents) ? manifest.documents.filter((item) => item && item.slug && item.title && item.source) : [];
      if (!documents.length) throw new Error('No technical documents are configured.');
      await renderDocument();
      window.addEventListener('hashchange', renderDocument);
    } catch (error) {
      article.innerHTML = `<p class="document-error">无法初始化文档中心：${error instanceof Error ? error.message : String(error)}</p>`;
    }
  }

  init();
})();
