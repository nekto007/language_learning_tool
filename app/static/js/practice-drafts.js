/* Browser-local drafts. A Web Lock prevents two tabs from editing one lesson. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LLTPracticeDrafts = api;
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';
  class Store {
    constructor(view, account, lesson) {
      this.view = view; this.account = String(account); this.lesson = String(lesson);
      if (!/^[1-9][0-9]*$/.test(this.account) || !/^[a-zA-Z0-9:_-]{1,200}$/.test(this.lesson)) throw new Error('Invalid draft scope');
      this.prefix = `llt:practice:${this.account}:${this.lesson}:`;
      this.durable = false; this.release = null; this.writable = false; this.generation = 0;
    }
    async acquire() {
      if (this.release) return true;
      const generation = ++this.generation;
      this.durable = false; this.storage = null; this.writable = false;
      const tabOnly = () => {
        if (generation !== this.generation) return false;
        this.writable = true; return true;
      };
      let locks;
      try { locks = this.view.navigator?.locks; } catch (_) { return tabOnly(); }
      if (!locks?.request) return tabOnly();
      return new Promise(resolve => {
        const edit = async lock => {
          if (!lock || generation !== this.generation) { resolve(false); return; }
          try { this.storage = this.view.localStorage; this.storage.getItem(this.prefix + 'active'); this.durable = true; } catch (_) {}
          let releaseLock;
          const held = new Promise(release => { releaseLock = release; this.release = release; });
          this.writable = true;
          resolve(true);
          await held;
          if (this.release === releaseLock) this.release = null;
        };
        try { locks.request(this.prefix + 'editor', {ifAvailable: true}, edit).catch(() => resolve(tabOnly())); }
        catch (_) { resolve(tabOnly()); } // Unsupported/denied locks retain tab-only storage.
      });
    }
    readPersistent(key) {
      const raw = (this.storage || this.view.localStorage).getItem(key);
      if (raw == null) return null;
      try {
        const record = JSON.parse(raw);
        return record?.schema === 1 && record.account === this.account && record.lesson === this.lesson
          && typeof record.value === 'string' ? record.value : null;
      } catch (_) { return null; }
    }
    getItem(key) {
      if (!key || !key.startsWith(this.prefix)) return null;
      if (this.durable) {
        const value = this.readPersistent(key);
        if (value != null) return value;
      }
      try { return this.view.sessionStorage.getItem(key); } // Migrate this tab's pre-upgrade draft on its next save.
      catch (error) { if (!this.durable) throw error; return null; }
    }
    setItem(key, value) {
      if (!this.writable) throw new Error('Draft ownership released');
      if (!key.startsWith(this.prefix)) throw new Error('Draft scope mismatch');
      if (this.durable) {
        this.storage.setItem(key, JSON.stringify({schema: 1, account: this.account, lesson: this.lesson, value}));
        try { this.view.sessionStorage.removeItem(key); } catch (_) {}
      } else this.view.sessionStorage.setItem(key, value);
    }
    removeItem(key) {
      if (!this.writable) throw new Error('Draft ownership released');
      if (!key || !key.startsWith(this.prefix)) return;
      if (this.durable) this.storage.removeItem(key);
      try { this.view.sessionStorage.removeItem(key); } catch (error) { if (!this.durable) throw error; }
    }
    close() {
      this.generation += 1;
      this.writable = false; this.durable = false; this.storage = null;
      const release = this.release; this.release = null; if (release) release();
    }
  }
  function savedDraft(view, account, lesson, lessonType) {
    try {
      const store = new Store(view, account, lesson);
      // The dashboard only reads. It never takes over the editor's lock.
      const key = store.readPersistent(store.prefix + 'active');
      if (!key || !key.startsWith(store.prefix)) return null;
      const state = JSON.parse(store.readPersistent(key));
      return state && !state.result && state.lessonType === lessonType
        && (!state.intro || Object.keys(state.answers || {}).length) ? state : null;
    } catch (_) { return null; }
  }
  return {Store, savedDraft};
});
