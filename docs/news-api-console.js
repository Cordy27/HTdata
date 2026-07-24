(function () {
  'use strict';

  function mountNewsApiConsole(container, { apiBase }) {
    const template = document.getElementById('news-api-console-template');
    const root = template.content.firstElementChild.cloneNode(true);
    container.append(root);
    const $ = (selector) => root.querySelector(selector);
    const fields = {
      apiKey: $('[data-field="api-key"]'), operation: $('[data-field="operation"]'), keywords: $('[data-field="keywords"]'), keywordMode: $('[data-field="keyword-mode"]'), sourceType: $('[data-field="source-type"]'), publishedFrom: $('[data-field="published-from"]'), publishedTo: $('[data-field="published-to"]'), view: $('[data-field="view"]'), limit: $('[data-field="limit"]'), minScore: $('[data-field="min-score"]'), includeHtml: $('[data-field="include-html"]'), incrementBatchId: $('[data-field="increment-batch-id"]'), incrementSourceType: $('[data-field="increment-source-type"]'), incrementView: $('[data-field="increment-view"]'), incrementLimit: $('[data-field="increment-limit"]'), incrementHtml: $('[data-field="increment-html"]'), articleId: $('[data-field="article-id"]'), detailHtml: $('[data-field="detail-html"]'), batchIds: $('[data-field="batch-ids"]'), includeContent: $('[data-field="include-content"]'), batchHtml: $('[data-field="batch-html"]'), runStatus: $('[data-field="run-status"]'), responseStatus: $('[data-field="response-status"]'), responseTime: $('[data-field="response-time"]'), responseCode: $('[data-field="response-code"]')
    };
    const section = { search: $('[data-section="search"]'), increments: $('[data-section="increments"]'), detail: $('[data-section="detail"]'), batch: $('[data-section="batch"]') };
    const normalizeList = (value) => String(value || '').split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
    const iso = (value) => value ? new Date(value).toISOString() : undefined;
    const quote = (value) => `'${String(value).replaceAll("'", "'\\\"'\\\"'")}'`;

    function enforceContentRules() {
      if (fields.includeHtml.checked) fields.view.value = 'full';
      if (fields.batchHtml.checked) { fields.includeContent.checked = true; fields.view.value = 'full'; }
      const fullView = fields.view.value === 'full';
      fields.limit.max = fullView ? '20' : '100';
      if (fullView && (fields.limit.value === '' || Number(fields.limit.value) > 20)) fields.limit.value = '20';
      if (fields.incrementHtml.checked) fields.incrementView.value = 'full';
      const fullIncrementView = fields.incrementView.value === 'full';
      fields.incrementLimit.max = fullIncrementView ? '20' : '100';
      if (fullIncrementView && (fields.incrementLimit.value === '' || Number(fields.incrementLimit.value) > 20)) fields.incrementLimit.value = '20';
    }

    function requestDefinition() {
      enforceContentRules();
      const operation = fields.operation.value;
      const headers = { Authorization: 'Bearer $NEWS_API_KEY' };
      const apiKey = fields.apiKey.value.trim();
      const liveHeaders = apiKey ? { Authorization: `Bearer ${apiKey}` } : {};
      const keywords = normalizeList(fields.keywords.value);
      const fallbackLimit = fields.view.value === 'full' ? 20 : 30;
      const search = { keywordMode: fields.keywordMode.value, view: fields.view.value, page: { limit: Number(fields.limit.value) || fallbackLimit } };
      if (fields.keywordMode.value === 'phrase') search.phrase = keywords.join(' '); else search.keywords = keywords;
      if (fields.sourceType.value) search.sourceTypes = [fields.sourceType.value];
      if (iso(fields.publishedFrom.value)) search.publishedFrom = iso(fields.publishedFrom.value);
      if (iso(fields.publishedTo.value)) search.publishedTo = iso(fields.publishedTo.value);
      if (fields.minScore.value !== '') search.minAiScore = Number(fields.minScore.value);
      if (fields.includeHtml.checked) search.includeHtml = true;
      if (operation === 'sources') return { method: 'GET', path: '/api/v1/sources', headers, liveHeaders };
      if (operation === 'increments') {
        const query = new URLSearchParams();
        const batchId = fields.incrementBatchId.value.trim();
        if (batchId) query.set('batchId', batchId);
        if (fields.incrementSourceType.value) query.set('sourceTypes', fields.incrementSourceType.value);
        query.set('view', fields.incrementView.value);
        query.set('limit', String(Number(fields.incrementLimit.value) || (fields.incrementView.value === 'full' ? 20 : 30)));
        if (fields.incrementHtml.checked) query.set('includeHtml', 'true');
        return { method: 'GET', path: `/api/v1/news/increments?${query}`, headers, liveHeaders };
      }
      if (operation === 'detail') return { method: 'GET', path: `/api/v1/news/${encodeURIComponent(fields.articleId.value.trim() || 'ARTICLE_ID')}${fields.detailHtml.checked ? '?includeHtml=true' : ''}`, headers, liveHeaders };
      if (operation === 'batch') {
        const body = { ids: normalizeList(fields.batchIds.value).length ? normalizeList(fields.batchIds.value) : ['ARTICLE_ID'], includeContent: fields.includeContent.checked, includeHtml: fields.batchHtml.checked, view: fields.includeContent.checked ? 'full' : 'standard' };
        return { method: 'POST', path: '/api/v1/news/batch', headers: { ...headers, 'Content-Type': 'application/json' }, liveHeaders: { ...liveHeaders, 'Content-Type': 'application/json' }, body };
      }
      if (operation === 'advanced') return { method: 'POST', path: '/api/v1/news/search', headers: { ...headers, 'Content-Type': 'application/json' }, liveHeaders: { ...liveHeaders, 'Content-Type': 'application/json' }, body: search };
      const query = new URLSearchParams();
      if (fields.keywordMode.value === 'phrase' && keywords.length) query.set('phrase', keywords.join(' '));
      else if (keywords.length === 1) query.set('q', keywords[0]);
      else keywords.forEach((value) => query.append('keywords', value));
      if (fields.keywordMode.value !== 'any') query.set('keywordMode', fields.keywordMode.value);
      if (fields.sourceType.value) query.set('sourceTypes', fields.sourceType.value);
      if (search.publishedFrom) query.set('publishedFrom', search.publishedFrom);
      if (search.publishedTo) query.set('publishedTo', search.publishedTo);
      if (search.minAiScore !== undefined) query.set('minAiScore', String(search.minAiScore));
      query.set('view', search.view); query.set('limit', String(search.page.limit));
      if (search.includeHtml) query.set('includeHtml', 'true');
      return { method: 'GET', path: `/api/v1/news?${query}`, headers, liveHeaders };
    }

    function samples(request) {
      const url = `${apiBase}${request.path}`;
      const body = request.body ? JSON.stringify(request.body, null, 2) : null;
      const compact = request.body ? JSON.stringify(request.body) : null;
      const curl = [`curl --request ${request.method}`, `  ${quote(url)}`, "  --header 'Authorization: Bearer $NEWS_API_KEY'", ...(body ? ["  --header 'Content-Type: application/json'", `  --data ${quote(compact)}`] : [])].join(' \\\n');
      const python = ['import json', 'import os', 'import requests', '', `url = ${JSON.stringify(url)}`, "headers = {'Authorization': f\"Bearer {os.environ['NEWS_API_KEY']}\"}", ...(body ? ["headers['Content-Type'] = 'application/json'", `payload = json.loads(${JSON.stringify(compact)})`, `response = requests.${request.method.toLowerCase()}(url, headers=headers, json=payload, timeout=30)`] : [`response = requests.${request.method.toLowerCase()}(url, headers=headers, timeout=30)`]), 'response.raise_for_status()', 'print(response.json())'].join('\n');
      const javascript = ['const apiKey = process.env.NEWS_API_KEY;', `const response = await fetch(${JSON.stringify(url)}, {`, `  method: ${JSON.stringify(request.method)},`, "  headers: { Authorization: `Bearer ${apiKey}`" + (body ? ", 'Content-Type': 'application/json'" : '') + ' },', ...(body ? [`  body: JSON.stringify(${body.replaceAll('\n', '\n  ')})`] : []), '});', "if (!response.ok) throw new Error(`News API request failed: ${response.status}`);", 'console.log(await response.json());'].join('\n');
      return { curl, python, javascript };
    }

    function switchTab(name) {
      root.querySelectorAll('.tab').forEach((node) => node.classList.toggle('active', node.dataset.tab === name));
      root.querySelectorAll('.pane').forEach((node) => node.classList.toggle('active', node.dataset.pane === name));
    }

    function render() {
      const request = requestDefinition();
      const output = samples(request);
      Object.entries(output).forEach(([name, value]) => { $(`[data-code="${name}"]`).textContent = value; });
      return request;
    }

    function updateSections() {
      const operation = fields.operation.value;
      section.search.hidden = !['search', 'advanced'].includes(operation);
      section.increments.hidden = operation !== 'increments';
      section.detail.hidden = operation !== 'detail';
      section.batch.hidden = operation !== 'batch';
      render();
    }

    async function copy(value) {
      try { await navigator.clipboard.writeText(value); } catch { const area = document.createElement('textarea'); area.value = value; document.body.append(area); area.select(); document.execCommand('copy'); area.remove(); }
      const toast = document.getElementById('toast'); toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 1500);
    }

    root.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => switchTab(button.dataset.tab)));
    root.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', () => copy($(`[data-code="${button.dataset.copy}"]`).textContent)));
    root.querySelectorAll('input, select, textarea').forEach((node) => node.addEventListener('input', render));
    fields.includeHtml.addEventListener('change', render);
    fields.incrementHtml.addEventListener('change', render);
    fields.batchHtml.addEventListener('change', render);
    fields.includeContent.addEventListener('change', () => { if (!fields.includeContent.checked) fields.batchHtml.checked = false; render(); });
    fields.operation.addEventListener('change', updateSections);
    root.querySelector('form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const request = render();
      if (!fields.apiKey.value.trim()) { fields.runStatus.textContent = 'Add a Bearer API Key to run this protected route.'; return; }
      const started = performance.now();
      fields.runStatus.textContent = 'Request in progress…';
      fields.responseStatus.textContent = 'PENDING';
      try {
        const response = await fetch(`${apiBase}${request.path}`, { method: request.method, headers: request.liveHeaders, ...(request.body ? { body: JSON.stringify(request.body) } : {}) });
        const text = await response.text();
        let payload; try { payload = JSON.parse(text); } catch { payload = text; }
        fields.responseStatus.textContent = `${response.status} ${response.statusText}`;
        fields.responseStatus.style.color = response.ok ? '#286a55' : '#9a431e';
        fields.responseStatus.style.background = response.ok ? 'var(--signal-soft)' : 'var(--orange-soft)';
        fields.responseTime.textContent = `${Math.round(performance.now() - started)} ms`;
        fields.responseCode.textContent = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
        fields.runStatus.textContent = response.ok ? 'Request completed.' : 'Request completed with an API error.';
      } catch (error) {
        fields.responseStatus.textContent = 'NETWORK ERROR';
        fields.responseTime.textContent = `${Math.round(performance.now() - started)} ms`;
        fields.responseCode.textContent = error instanceof Error ? error.message : String(error);
        fields.runStatus.textContent = 'Request could not be sent.';
      }
      switchTab('response');
    });
    updateSections();
    if (window.lucide) window.lucide.createIcons({ attrs: { 'aria-hidden': 'true' } });
  }

  window.HTDocsWidgets = { mountNewsApiConsole };
})();
