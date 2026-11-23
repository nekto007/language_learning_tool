/* A page keeps the actor it was rendered for, even when another tab signs in. */
(() => {
  'use strict';
  const actor = document.querySelector('meta[name="llt-account-id"]')?.content;
  if (!actor || !window.fetch) return;
  const nativeFetch = window.fetch.bind(window);
  const nativeSubmit = HTMLFormElement.prototype.submit;
  const header = 'X-LLT-Account-ID';
  let invalid = false, checking = false;

  const local = value => {
    if (value == null) return false;
    try { return new URL(value, document.baseURI).origin === location.origin; }
    catch (_) { return false; }
  };
  const stopOldPage = (expired = false) => {
    if (invalid) return;
    invalid = true;
    const reveal = () => {
      document.body.classList.add('llt-account-invalid');
      Array.from(document.body.children).forEach(child => { child.inert = true; });
      const notice = document.createElement('main');
      notice.id = 'llt-account-notice'; notice.className = 'container py-5';
      notice.tabIndex = -1; notice.setAttribute('role', 'alert');
      const title = document.createElement('h1');
      title.textContent = expired ? 'Сессия изменилась' : 'Аккаунт изменился';
      const text = document.createElement('p');
      text.textContent = 'Открой актуальный план, чтобы продолжить. Сохранённые черновики останутся у своего аккаунта.';
      const link = document.createElement('a');
      link.href = '/dashboard'; link.className = 'btn btn-primary'; link.textContent = 'Открыть план дня';
      notice.append(title, text, link); document.body.append(notice);
      notice.focus({preventScroll: true});
      window.dispatchEvent(new CustomEvent('llt:account-changed'));
    };
    if (document.body) reveal();
    else document.addEventListener('DOMContentLoaded', reveal, {once: true});
  };
  const inspect = async response => {
    if (response.headers.get('X-LLT-Account-Changed') === '1') {
      stopOldPage(response.status === 401); return;
    }
    if (![400, 401, 403].includes(response.status) || !response.headers.get('Content-Type')?.includes('application/json')) return;
    try {
      const value = await response.clone().json();
      if (value.account_changed === true || value.csrf_expired === true) stopOldPage(value.csrf_expired === true || response.status === 401);
    } catch (_) { /* Other error bodies remain the caller's responsibility. */ }
  };
  window.fetch = (input, init) => {
    const request = input instanceof Request ? input : null;
    if (!local(request ? request.url : input) || (init?.credentials ?? request?.credentials) === 'omit') return nativeFetch(input, init);
    const method = String(init?.method ?? request?.method ?? 'GET').toUpperCase();
    if (invalid && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const error = new Error('Аккаунт изменился. Открой план заново.');
      error.code = 'access_denied'; return Promise.reject(error);
    }
    // Clone rather than mutate callers' Headers or consume a Request body.
    const headers = new Headers(init?.headers !== undefined ? init.headers : request?.headers);
    headers.set(header, actor);
    return nativeFetch(input, {...init, headers}).then(async response => {
      await inspect(response); return response;
    });
  };

  // jQuery and older modules may use XHR instead of fetch.
  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  const xhrHeader = XMLHttpRequest.prototype.setRequestHeader;
  const xhrState = new WeakMap();
  XMLHttpRequest.prototype.open = function (...args) {
    const result = xhrOpen.apply(this, args);
    if (!xhrState.has(this)) this.addEventListener('loadend', function () {
      if (!local(xhrState.get(this)?.url)) return;
      if (this.getResponseHeader('X-LLT-Account-Changed') === '1') { stopOldPage(this.status === 401); return; }
      if (![400, 401, 403].includes(this.status)) return;
      try {
        const value = this.responseType === 'json' ? this.response : JSON.parse(this.responseText);
        if (value?.account_changed === true || value?.csrf_expired === true) stopOldPage(value.csrf_expired === true || this.status === 401);
      } catch (_) {}
    });
    xhrState.set(this, {method: String(args[0]).toUpperCase(), url: String(args[1])});
    return result;
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    // Set exactly one immutable actor at send-time, even if a caller supplies
    // this header itself. Other headers retain their native append semantics.
    if (local(xhrState.get(this)?.url) && String(name).toLowerCase() === header.toLowerCase()) return;
    return xhrHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const state = xhrState.get(this);
    if (state && local(state.url)) {
      if (invalid && !['GET', 'HEAD', 'OPTIONS'].includes(state.method)) {
        const error = new Error('Аккаунт изменился. Открой план заново.'); error.code = 'access_denied'; throw error;
      }
      xhrHeader.call(this, header, actor);
    }
    return xhrSend.call(this, body);
  };

  const boundForm = form => form.method.toLowerCase() === 'post' && local(form.action || location.href);
  const stampForm = form => {
    if (!boundForm(form)) {
      form.querySelectorAll('input[data-llt-account-bound]').forEach(field => field.remove());
      return;
    }
    let field = form.querySelector('input[name="_llt_account_id"]');
    if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = '_llt_account_id'; }
    field.value = actor; field.disabled = false; field.dataset.lltAccountBound = 'true'; form.append(field);
  };
  document.addEventListener('submit', event => {
    if (!(event.target instanceof HTMLFormElement)) return;
    if (invalid && boundForm(event.target)) { event.preventDefault(); return; }
    stampForm(event.target);
  }, true);
  // Native form.submit() does not dispatch a submit event.
  HTMLFormElement.prototype.submit = function () {
    if (invalid && boundForm(this)) return;
    stampForm(this); return nativeSubmit.call(this);
  };

  const checkAccount = async () => {
    if (invalid || checking || document.visibilityState === 'hidden') return;
    checking = true;
    try {
      const response = await nativeFetch('/csrf-token', {credentials: 'same-origin', cache: 'no-store', headers: {[header]: actor}});
      await inspect(response);
      if (response.ok && !invalid) {
        const value = await response.json();
        if ('account_id' in value && String(value.account_id) !== actor) stopOldPage();
      }
    } catch (_) { /* Offline work stays usable and keeps its original actor. */ }
    finally { checking = false; }
  };
  window.addEventListener('focus', checkAccount);
  window.addEventListener('pageshow', checkAccount);
  document.addEventListener('visibilitychange', checkAccount);
})();
