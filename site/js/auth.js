/* =========================================================================
   SecureSkillHub — auth.js
   Shared authentication helpers for browser-side features.
   ========================================================================= */

(function (root) {
  'use strict';

  var AUTH_KEY = 'secureskillhub_auth';
  var API_BASE = window.SECURESKILLHUB_API || 'https://api.secureskillhub.workers.dev/v1';

  var Auth = {
    /** Get stored auth data or null */
    getUser: function () {
      try {
        var raw = localStorage.getItem(AUTH_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    },

    /** Save auth data */
    setUser: function (data) {
      localStorage.setItem(AUTH_KEY, JSON.stringify(data));
      Auth._notify();
    },

    /** Clear auth data */
    clear: function () {
      localStorage.removeItem(AUTH_KEY);
      Auth._notify();
    },

    /** Check if logged in */
    isLoggedIn: function () {
      var user = Auth.getUser();
      return !!(user && user.token);
    },

    /** Get auth token */
    getToken: function () {
      var user = Auth.getUser();
      return user ? user.token : null;
    },

    /** Get API base URL */
    getApiBase: function () {
      return API_BASE;
    },

    /** Make authenticated API request */
    apiFetch: function (path, opts) {
      opts = opts || {};
      var headers = opts.headers || {};
      headers['Content-Type'] = 'application/json';

      var token = Auth.getToken();
      if (token) {
        headers['Authorization'] = 'Bearer ' + token;
      }

      return fetch(API_BASE + path, {
        method: opts.method || 'GET',
        headers: headers,
        body: opts.body ? JSON.stringify(opts.body) : undefined
      }).then(function (res) {
        if (!res.ok) throw new Error('API error: ' + res.status);
        if (res.status === 204) return null;
        return res.json();
      });
    },

    /** Start OAuth web flow (redirect to API which redirects to GitHub) */
    startLogin: function () {
      var returnUrl = encodeURIComponent(window.location.origin + '/profile.html');
      window.location.href = API_BASE + '/auth/web/start?return_url=' + returnUrl;
    },

    /** Handle OAuth callback (reads token from URL hash) */
    handleCallback: function () {
      var hash = window.location.hash;
      if (!hash || hash.indexOf('token=') === -1) return false;

      var params = new URLSearchParams(hash.substring(1));
      var token = params.get('token');
      var handle = params.get('handle');
      var avatar = params.get('avatar');

      if (token) {
        Auth.setUser({
          token: token,
          github_handle: handle || '',
          github_avatar: avatar || ''
        });
        // Clear hash from URL
        history.replaceState(null, '', window.location.pathname + window.location.search);
        return true;
      }
      return false;
    },

    /** Pin a skill to user's default package */
    pinSkill: function (skillId) {
      return Auth.apiFetch('/me/packages/default/pins', {
        method: 'POST',
        body: { skill_ids: [skillId] }
      });
    },

    /** Unpin a skill from user's default package */
    unpinSkill: function (skillId) {
      return Auth.apiFetch('/me/packages/default/pins/' + encodeURIComponent(skillId), {
        method: 'DELETE'
      });
    },

    /** Get user's packages */
    getPackages: function () {
      return Auth.apiFetch('/me/packages');
    },

    /** Resolve a package */
    resolvePackage: function (packageId) {
      var path = packageId === 'default'
        ? '/me/packages/default/resolve'
        : '/me/packages/' + encodeURIComponent(packageId) + '/resolve';
      return Auth.apiFetch(path);
    },

    /** Auth change listeners */
    _listeners: [],
    onAuthChange: function (fn) {
      Auth._listeners.push(fn);
    },
    _notify: function () {
      var user = Auth.getUser();
      for (var i = 0; i < Auth._listeners.length; i++) {
        try { Auth._listeners[i](user); } catch (e) { console.error(e); }
      }
    }
  };

  root.SecureSkillHubAuth = Auth;
})(window);
