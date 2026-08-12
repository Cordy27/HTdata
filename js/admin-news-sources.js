(function () {
  'use strict';

  var DEFAULT_API_BASE = 'https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api';
  var API_BASE = String(window.HT_NEWS_ADMIN_API || DEFAULT_API_BASE).replace(/\/+$/, '');
  var state = { token: '', expiresAt: '', current: null, versions: [] };

  var nodes = {
    loginView: byId('loginView'), adminView: byId('adminView'), loginForm: byId('loginForm'), password: byId('passwordInput'),
    passwordToggle: byId('passwordToggle'), loginButton: byId('loginButton'), loginMessage: byId('loginMessage'),
    logoutButton: byId('logoutButton'), sessionIndicator: byId('sessionIndicator'), reloadButton: byId('reloadButton'),
    formatButton: byId('formatButton'), validateButton: byId('validateButton'), editor: byId('configEditor'),
    editorStatus: byId('editorStatus'), editorCount: byId('editorCount'), changeNote: byId('changeNote'),
    publishButton: byId('publishButton'), publishMessage: byId('publishMessage'), refreshVersionsButton: byId('refreshVersionsButton'),
    versionsBody: byId('versionsBody'), currentVersion: byId('currentVersion'), currentPublishedAt: byId('currentPublishedAt'),
    rssCount: byId('rssCount'), wechatCount: byId('wechatCount'), toast: byId('toast')
  };

  init();

  function init() {
    if (window.lucide) window.lucide.createIcons();
    nodes.loginForm.addEventListener('submit', login);
    nodes.passwordToggle.addEventListener('click', togglePassword);
    nodes.logoutButton.addEventListener('click', logout);
    nodes.reloadButton.addEventListener('click', function () { loadCurrent(true); });
    nodes.formatButton.addEventListener('click', formatEditor);
    nodes.validateButton.addEventListener('click', validateEditor);
    nodes.editor.addEventListener('input', updateEditorCount);
    nodes.publishButton.addEventListener('click', publish);
    nodes.refreshVersionsButton.addEventListener('click', loadVersions);
    nodes.versionsBody.addEventListener('click', handleVersionAction);
    updateEditorCount();
  }

  async function login(event) {
    event.preventDefault();
    var password = nodes.password.value;
    if (!password) return setMessage(nodes.loginMessage, '请输入管理员密码。', true);
    setBusy(nodes.loginButton, true, '登录中');
    setMessage(nodes.loginMessage, '');
    try {
      var payload = await request('/admin/v1/login', { method: 'POST', body: { password: password }, auth: false });
      state.token = payload.data.token;
      state.expiresAt = payload.data.expiresAt;
      nodes.password.value = '';
      showAdmin();
      await Promise.all([loadCurrent(false), loadVersions()]);
      notify('管理员会话已建立。');
    } catch (error) {
      setMessage(nodes.loginMessage, error.message || '登录失败，请稍后重试。', true);
    } finally {
      setBusy(nodes.loginButton, false, '登录');
    }
  }

  function togglePassword() {
    var visible = nodes.password.type === 'text';
    nodes.password.type = visible ? 'password' : 'text';
    nodes.passwordToggle.setAttribute('title', visible ? '显示密码' : '隐藏密码');
    nodes.passwordToggle.setAttribute('aria-label', visible ? '显示密码' : '隐藏密码');
    nodes.passwordToggle.innerHTML = '<i data-lucide="' + (visible ? 'eye' : 'eye-off') + '"></i>';
    if (window.lucide) window.lucide.createIcons({ nodes: [nodes.passwordToggle] });
  }

  function showAdmin() {
    nodes.loginView.hidden = true;
    nodes.adminView.hidden = false;
    nodes.logoutButton.hidden = false;
    nodes.sessionIndicator.classList.add('is-active');
    nodes.sessionIndicator.innerHTML = '<i></i>会话有效';
  }

  function logout(message) {
    state.token = '';
    state.expiresAt = '';
    state.current = null;
    state.versions = [];
    nodes.adminView.hidden = true;
    nodes.loginView.hidden = false;
    nodes.logoutButton.hidden = true;
    nodes.sessionIndicator.classList.remove('is-active');
    nodes.sessionIndicator.innerHTML = '<i></i>未登录';
    nodes.editor.value = '';
    nodes.versionsBody.innerHTML = '<tr><td colspan="4" class="empty-table">尚未加载版本记录。</td></tr>';
    if (message) setMessage(nodes.loginMessage, message, true);
    updateEditorCount();
  }

  async function loadCurrent(showToast) {
    setBusy(nodes.reloadButton, true, '加载中');
    try {
      var payload = await request('/admin/v1/news-sources');
      var data = payload.data || {};
      state.current = data;
      if (data.config) {
        nodes.editor.value = JSON.stringify(data.config, null, 2);
        setEditorStatus('已加载当前发布版本。', false, true);
      } else {
        nodes.editor.value = '';
        setEditorStatus('尚无已发布的运行态配置，请先从默认配置创建首个版本。', true);
      }
      renderSummary(data.version, data.config);
      updateEditorCount();
      if (showToast) notify('已重新加载当前发布版本。');
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(nodes.reloadButton, false, '重新加载');
    }
  }

  async function loadVersions() {
    setBusy(nodes.refreshVersionsButton, true, '刷新中');
    try {
      var payload = await request('/admin/v1/news-sources/versions');
      state.versions = (payload.data && payload.data.versions) || [];
      renderVersions();
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(nodes.refreshVersionsButton, false, '刷新记录');
    }
  }

  function renderSummary(version, config) {
    nodes.currentVersion.textContent = version && version.id ? shortId(version.id) : '默认配置';
    nodes.currentPublishedAt.textContent = version && version.publishedAt ? localDate(version.publishedAt) : '--';
    nodes.rssCount.textContent = config ? enabledCount(config.rss) : '--';
    nodes.wechatCount.textContent = config && config.wechat ? enabledCount(config.wechat.accounts) : '--';
  }

  function renderVersions() {
    if (!state.versions.length) {
      nodes.versionsBody.innerHTML = '<tr><td colspan="4" class="empty-table">还没有已发布版本。</td></tr>';
      return;
    }
    nodes.versionsBody.innerHTML = state.versions.map(function (version) {
      return '<tr>' +
        '<td>' + escapeHtml(localDate(version.published_at || version.publishedAt)) + '</td>' +
        '<td title="' + escapeHtml(version.id) + '">' + escapeHtml(shortId(version.id)) + '</td>' +
        '<td>' + escapeHtml(version.change_note || version.changeNote || '未填写变更说明') + '</td>' +
        '<td><button class="version-action" type="button" data-version-id="' + escapeHtml(version.id) + '">载入此版本</button></td>' +
        '</tr>';
    }).join('');
  }

  async function handleVersionAction(event) {
    var button = event.target.closest('[data-version-id]');
    if (!button) return;
    var versionId = button.getAttribute('data-version-id');
    setBusy(button, true, '载入中');
    try {
      var payload = await request('/admin/v1/news-sources/versions/' + encodeURIComponent(versionId));
      nodes.editor.value = JSON.stringify(payload.data.config, null, 2);
      nodes.changeNote.value = '回滚至版本 ' + shortId(versionId);
      updateEditorCount();
      setEditorStatus('已载入历史版本。请检查后再次发布，才会在下一次抓取生效。', false, true);
      document.getElementById('editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
      notify('历史版本已载入编辑器。');
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(button, false, '载入此版本');
    }
  }

  function formatEditor() {
    var config = parseEditor();
    if (!config) return;
    nodes.editor.value = JSON.stringify(config, null, 2);
    updateEditorCount();
    setEditorStatus('JSON 格式正确，已格式化。', false, true);
  }

  function validateEditor() {
    var config = parseEditor();
    if (!config) return;
    var errors = localConfigChecks(config);
    if (errors.length) {
      setEditorStatus(errors.join(' '), true);
      return;
    }
    setEditorStatus('JSON 格式和基础结构检查通过。发布时将由服务端执行完整校验。', false, true);
  }

  function parseEditor() {
    var raw = nodes.editor.value.trim();
    if (!raw) {
      setEditorStatus('配置不能为空。', true);
      return null;
    }
    try {
      var parsed = JSON.parse(raw);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('配置根节点必须是 JSON 对象。');
      return parsed;
    } catch (error) {
      setEditorStatus('JSON 格式错误：' + (error.message || '请检查逗号和引号。'), true);
      return null;
    }
  }

  function localConfigChecks(config) {
    var errors = [];
    if (!Array.isArray(config.rss)) errors.push('rss 必须是数组。');
    if (!Array.isArray(config.hotlists)) errors.push('hotlists 必须是数组。');
    if (!config.wechat || !Array.isArray(config.wechat.accounts)) errors.push('wechat.accounts 必须是数组。');
    if (!Array.isArray(config.keywordGroups) || !config.keywordGroups.length) errors.push('keywordGroups 不能为空。');
    if (!config.settings || typeof config.settings !== 'object') errors.push('settings 必须是对象。');
    return errors;
  }

  async function publish() {
    var config = parseEditor();
    if (!config) return;
    var errors = localConfigChecks(config);
    if (errors.length) return setMessage(nodes.publishMessage, errors.join(' '), true);
    var note = nodes.changeNote.value.trim();
    if (!note) return setMessage(nodes.publishMessage, '请填写本次变更说明，便于后续回滚核对。', true);
    if (!window.confirm('确认发布此配置？下一次新闻抓取将使用新版本。')) return;
    setBusy(nodes.publishButton, true, '发布中');
    setMessage(nodes.publishMessage, '正在提交并执行服务端校验。');
    try {
      var payload = await request('/admin/v1/news-sources/publish', { method: 'POST', body: { config: config, changeNote: note } });
      var version = payload.data && payload.data.version;
      setMessage(nodes.publishMessage, '发布成功：' + (version ? shortId(version.id) : '新版本') + '。下一次抓取将自动加载。', false, true);
      nodes.changeNote.value = '';
      await Promise.all([loadCurrent(false), loadVersions()]);
      notify('新闻信源配置已发布。');
    } catch (error) {
      setMessage(nodes.publishMessage, error.message || '发布失败，请检查配置。', true);
    } finally {
      setBusy(nodes.publishButton, false, '发布并下次生效');
    }
  }

  async function request(path, options) {
    options = options || {};
    var headers = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options.auth !== false && state.token) headers.Authorization = 'Bearer ' + state.token;
    var response;
    try {
      response = await fetch(API_BASE + path, { method: options.method || 'GET', headers: headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), mode: 'cors' });
    } catch {
      throw new Error('无法连接新闻后台。请检查网络或后台服务状态。');
    }
    var payload = null;
    try { payload = await response.json(); } catch { throw new Error('后台返回了无法识别的响应。'); }
    if (!response.ok || !payload.ok) {
      var message = payload && payload.error && payload.error.message ? payload.error.message : '请求未成功。';
      var code = payload && payload.error && payload.error.code;
      if (response.status === 401 || code === 'UNAUTHORIZED') {
        if (options.auth !== false) logout('管理员会话已失效，请重新登录。');
      }
      throw new Error(message);
    }
    return payload;
  }

  function handleRequestError(error) {
    if (state.token) notify(error.message || '请求失败。', true);
  }

  function updateEditorCount() {
    nodes.editorCount.textContent = nodes.editor.value.length.toLocaleString('zh-CN') + ' 字符';
  }

  function setEditorStatus(message, error, success) {
    nodes.editorStatus.textContent = message || '';
    nodes.editorStatus.classList.toggle('is-error', Boolean(error));
    nodes.editorStatus.classList.toggle('is-success', Boolean(success));
  }

  function setMessage(node, message, error, success) {
    node.textContent = message || '';
    node.classList.toggle('is-error', Boolean(error));
    node.classList.toggle('is-success', Boolean(success));
  }

  function setBusy(button, busy, label) {
    if (!button.dataset.label) button.dataset.label = button.textContent.trim();
    button.disabled = busy;
    var span = button.querySelector('span');
    if (span) span.textContent = busy ? label : (label || button.dataset.label);
  }

  function notify(message, error) {
    nodes.toast.textContent = message;
    nodes.toast.classList.toggle('is-error', Boolean(error));
    nodes.toast.classList.add('show');
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(function () { nodes.toast.classList.remove('show'); }, 3400);
  }

  function enabledCount(items) {
    return Array.isArray(items) ? items.filter(function (item) { return item && item.enabled !== false; }).length : 0;
  }

  function shortId(value) {
    var text = String(value || '');
    return text.length > 12 ? text.slice(0, 8) + '...' : text || '--';
  }

  function localDate(value) {
    if (!value) return '--';
    var text = String(value).replace(' ', 'T');
    if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(text)) text += '+08:00';
    var date = new Date(text);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short', hour12: false, timeZone: 'Asia/Shanghai' }).format(date);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function byId(id) { return document.getElementById(id); }
})();
