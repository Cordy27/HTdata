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
    if (!password) return setMessage(nodes.loginMessage, '璇疯緭鍏ョ鐞嗗憳瀵嗙爜銆?, true);
    setBusy(nodes.loginButton, true, '鐧诲綍涓?);
    setMessage(nodes.loginMessage, '');
    try {
      var payload = await request('/admin/v1/login', { method: 'POST', body: { password: password }, auth: false });
      state.token = payload.data.token;
      state.expiresAt = payload.data.expiresAt;
      nodes.password.value = '';
      showAdmin();
      await Promise.all([loadCurrent(false), loadVersions()]);
      notify('绠＄悊鍛樹細璇濆凡寤虹珛銆?);
    } catch (error) {
      setMessage(nodes.loginMessage, error.message || '鐧诲綍澶辫触锛岃绋嶅悗閲嶈瘯銆?, true);
    } finally {
      setBusy(nodes.loginButton, false, '鐧诲綍');
    }
  }

  function togglePassword() {
    var visible = nodes.password.type === 'text';
    nodes.password.type = visible ? 'password' : 'text';
    nodes.passwordToggle.setAttribute('title', visible ? '鏄剧ず瀵嗙爜' : '闅愯棌瀵嗙爜');
    nodes.passwordToggle.setAttribute('aria-label', visible ? '鏄剧ず瀵嗙爜' : '闅愯棌瀵嗙爜');
    nodes.passwordToggle.innerHTML = '<i data-lucide="' + (visible ? 'eye' : 'eye-off') + '"></i>';
    if (window.lucide) window.lucide.createIcons({ nodes: [nodes.passwordToggle] });
  }

  function showAdmin() {
    nodes.loginView.hidden = true;
    nodes.adminView.hidden = false;
    nodes.logoutButton.hidden = false;
    nodes.sessionIndicator.classList.add('is-active');
    nodes.sessionIndicator.innerHTML = '<i></i>浼氳瘽鏈夋晥';
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
    nodes.sessionIndicator.innerHTML = '<i></i>鏈櫥褰?;
    nodes.editor.value = '';
    nodes.versionsBody.innerHTML = '<tr><td colspan="4" class="empty-table">灏氭湭鍔犺浇鐗堟湰璁板綍銆?/td></tr>';
    if (message) setMessage(nodes.loginMessage, message, true);
    updateEditorCount();
  }

  async function loadCurrent(showToast) {
    setBusy(nodes.reloadButton, true, '鍔犺浇涓?);
    try {
      var payload = await request('/admin/v1/news-sources');
      var data = payload.data || {};
      state.current = data;
      if (data.config) {
        nodes.editor.value = JSON.stringify(data.config, null, 2);
        setEditorStatus('宸插姞杞藉綋鍓嶅彂甯冪増鏈€?, false, true);
      } else {
        nodes.editor.value = '';
        setEditorStatus('灏氭棤宸插彂甯冪殑杩愯鎬侀厤缃紝璇峰厛浠庨粯璁ら厤缃垱寤洪涓増鏈€?, true);
      }
      renderSummary(data.version, data.config);
      updateEditorCount();
      if (showToast) notify('宸查噸鏂板姞杞藉綋鍓嶅彂甯冪増鏈€?);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(nodes.reloadButton, false, '閲嶆柊鍔犺浇');
    }
  }

  async function loadVersions() {
    setBusy(nodes.refreshVersionsButton, true, '鍒锋柊涓?);
    try {
      var payload = await request('/admin/v1/news-sources/versions');
      state.versions = (payload.data && payload.data.versions) || [];
      renderVersions();
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(nodes.refreshVersionsButton, false, '鍒锋柊璁板綍');
    }
  }

  function renderSummary(version, config) {
    nodes.currentVersion.textContent = version && version.id ? shortId(version.id) : '榛樿閰嶇疆';
    nodes.currentPublishedAt.textContent = version && version.publishedAt ? localDate(version.publishedAt) : '--';
    nodes.rssCount.textContent = config ? enabledCount(config.rss) : '--';
    nodes.wechatCount.textContent = config && config.wechat ? enabledCount(config.wechat.accounts) : '--';
  }

  function renderVersions() {
    if (!state.versions.length) {
      nodes.versionsBody.innerHTML = '<tr><td colspan="4" class="empty-table">杩樻病鏈夊凡鍙戝竷鐗堟湰銆?/td></tr>';
      return;
    }
    nodes.versionsBody.innerHTML = state.versions.map(function (version) {
      return '<tr>' +
        '<td>' + escapeHtml(localDate(version.published_at || version.publishedAt)) + '</td>' +
        '<td title="' + escapeHtml(version.id) + '">' + escapeHtml(shortId(version.id)) + '</td>' +
        '<td>' + escapeHtml(version.change_note || version.changeNote || '鏈～鍐欏彉鏇磋鏄?) + '</td>' +
        '<td><button class="version-action" type="button" data-version-id="' + escapeHtml(version.id) + '">杞藉叆姝ょ増鏈?/button></td>' +
        '</tr>';
    }).join('');
  }

  async function handleVersionAction(event) {
    var button = event.target.closest('[data-version-id]');
    if (!button) return;
    var versionId = button.getAttribute('data-version-id');
    setBusy(button, true, '杞藉叆涓?);
    try {
      var payload = await request('/admin/v1/news-sources/versions/' + encodeURIComponent(versionId));
      nodes.editor.value = JSON.stringify(payload.data.config, null, 2);
      nodes.changeNote.value = '鍥炴粴鑷崇増鏈?' + shortId(versionId);
      updateEditorCount();
      setEditorStatus('宸茶浇鍏ュ巻鍙茬増鏈€傝妫€鏌ュ悗鍐嶆鍙戝竷锛屾墠浼氬湪涓嬩竴娆℃姄鍙栫敓鏁堛€?, false, true);
      document.getElementById('editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
      notify('鍘嗗彶鐗堟湰宸茶浇鍏ョ紪杈戝櫒銆?);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setBusy(button, false, '杞藉叆姝ょ増鏈?);
    }
  }

  function formatEditor() {
    var config = parseEditor();
    if (!config) return;
    nodes.editor.value = JSON.stringify(config, null, 2);
    updateEditorCount();
    setEditorStatus('JSON 鏍煎紡姝ｇ‘锛屽凡鏍煎紡鍖栥€?, false, true);
  }

  function validateEditor() {
    var config = parseEditor();
    if (!config) return;
    var errors = localConfigChecks(config);
    if (errors.length) {
      setEditorStatus(errors.join(' '), true);
      return;
    }
    setEditorStatus('JSON 鏍煎紡鍜屽熀纭€缁撴瀯妫€鏌ラ€氳繃銆傚彂甯冩椂灏嗙敱鏈嶅姟绔墽琛屽畬鏁存牎楠屻€?, false, true);
  }

  function parseEditor() {
    var raw = nodes.editor.value.trim();
    if (!raw) {
      setEditorStatus('閰嶇疆涓嶈兘涓虹┖銆?, true);
      return null;
    }
    try {
      var parsed = JSON.parse(raw);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('閰嶇疆鏍硅妭鐐瑰繀椤绘槸 JSON 瀵硅薄銆?);
      return parsed;
    } catch (error) {
      setEditorStatus('JSON 鏍煎紡閿欒锛? + (error.message || '璇锋鏌ラ€楀彿鍜屽紩鍙枫€?), true);
      return null;
    }
  }

  function localConfigChecks(config) {
    var errors = [];
    if (!Array.isArray(config.rss)) errors.push('rss 蹇呴』鏄暟缁勩€?);
    if (!Array.isArray(config.hotlists)) errors.push('hotlists 蹇呴』鏄暟缁勩€?);
    if (!config.wechat || !Array.isArray(config.wechat.accounts)) errors.push('wechat.accounts 蹇呴』鏄暟缁勩€?);
    if (!Array.isArray(config.keywordGroups) || !config.keywordGroups.length) errors.push('keywordGroups 涓嶈兘涓虹┖銆?);
    if (!config.settings || typeof config.settings !== 'object') errors.push('settings 蹇呴』鏄璞°€?);
    return errors;
  }

  async function publish() {
    var config = parseEditor();
    if (!config) return;
    var errors = localConfigChecks(config);
    if (errors.length) return setMessage(nodes.publishMessage, errors.join(' '), true);
    var note = nodes.changeNote.value.trim();
    if (!note) return setMessage(nodes.publishMessage, '璇峰～鍐欐湰娆″彉鏇磋鏄庯紝渚夸簬鍚庣画鍥炴粴鏍稿銆?, true);
    if (!window.confirm('纭鍙戝竷姝ら厤缃紵涓嬩竴娆℃柊闂绘姄鍙栧皢浣跨敤鏂扮増鏈€?)) return;
    setBusy(nodes.publishButton, true, '鍙戝竷涓?);
    setMessage(nodes.publishMessage, '姝ｅ湪鎻愪氦骞舵墽琛屾湇鍔＄鏍￠獙銆?);
    try {
      var payload = await request('/admin/v1/news-sources/publish', { method: 'POST', body: { config: config, changeNote: note } });
      var version = payload.data && payload.data.version;
      setMessage(nodes.publishMessage, '鍙戝竷鎴愬姛锛? + (version ? shortId(version.id) : '鏂扮増鏈?) + '銆備笅涓€娆℃姄鍙栧皢鑷姩鍔犺浇銆?, false, true);
      nodes.changeNote.value = '';
      await Promise.all([loadCurrent(false), loadVersions()]);
      notify('鏂伴椈淇℃簮閰嶇疆宸插彂甯冦€?);
    } catch (error) {
      setMessage(nodes.publishMessage, error.message || '鍙戝竷澶辫触锛岃妫€鏌ラ厤缃€?, true);
    } finally {
      setBusy(nodes.publishButton, false, '鍙戝竷骞朵笅娆＄敓鏁?);
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
      throw new Error('鏃犳硶杩炴帴鏂伴椈鍚庡彴銆傝妫€鏌ョ綉缁滄垨鍚庡彴鏈嶅姟鐘舵€併€?);
    }
    var payload = null;
    try { payload = await response.json(); } catch { throw new Error('鍚庡彴杩斿洖浜嗘棤娉曡瘑鍒殑鍝嶅簲銆?); }
    if (!response.ok || !payload.ok) {
      var message = payload && payload.error && payload.error.message ? payload.error.message : '璇锋眰鏈垚鍔熴€?;
      var code = payload && payload.error && payload.error.code;
      if (response.status === 401 || code === 'UNAUTHORIZED') {
        if (options.auth !== false) logout('绠＄悊鍛樹細璇濆凡澶辨晥锛岃閲嶆柊鐧诲綍銆?);
      }
      throw new Error(message);
    }
    return payload;
  }

  function handleRequestError(error) {
    if (state.token) notify(error.message || '璇锋眰澶辫触銆?, true);
  }

  function updateEditorCount() {
    nodes.editorCount.textContent = nodes.editor.value.length.toLocaleString('zh-CN') + ' 瀛楃';
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
