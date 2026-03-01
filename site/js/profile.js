/* =========================================================================
   SecureSkillHub — profile.js
   Profile page logic: package management, tag picker, skill pinning.
   Depends on auth.js (SecureSkillHubAuth global).
   ========================================================================= */

(function () {
  'use strict';

  var Auth = window.SecureSkillHubAuth;
  var loginView = document.getElementById('login-view');
  var profileView = document.getElementById('profile-view');
  var packagesList = document.getElementById('packages-list');
  var profileAvatar = document.getElementById('profile-avatar');
  var profileHandle = document.getElementById('profile-handle');
  var newPackageBtn = document.getElementById('new-package-btn');
  var logoutBtn = document.getElementById('logout-btn');

  // -----------------------------------------------------------------------
  // Init
  // -----------------------------------------------------------------------

  function init() {
    // Handle OAuth callback
    Auth.handleCallback();

    // Show correct view
    updateView();

    // Listen for auth changes
    Auth.onAuthChange(updateView);

    // Button handlers
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        Auth.clear();
        updateView();
      });
    }

    if (newPackageBtn) {
      newPackageBtn.addEventListener('click', createNewPackage);
    }
  }

  function updateView() {
    if (Auth.isLoggedIn()) {
      loginView.classList.add('hidden');
      profileView.classList.remove('hidden');
      var user = Auth.getUser();
      profileHandle.textContent = '@' + (user.github_handle || 'user');
      profileAvatar.src = user.github_avatar || 'https://avatars.githubusercontent.com/u/0?v=4';
      loadPackages();
    } else {
      loginView.classList.remove('hidden');
      profileView.classList.add('hidden');
    }
  }

  // -----------------------------------------------------------------------
  // Package Management
  // -----------------------------------------------------------------------

  function loadPackages() {
    packagesList.innerHTML = '<div class="empty-packages"><p>Loading packages...</p></div>';

    Auth.getPackages()
      .then(function (data) {
        renderPackages(data.packages || data || []);
      })
      .catch(function (err) {
        packagesList.innerHTML =
          '<div class="empty-packages">' +
          '<p>Could not load packages. The API may not be deployed yet.</p>' +
          '<p class="report-ops-row">' + escapeHtml(err.message) + '</p>' +
          '<p class="report-sub-label--spaced">Use the CLI to manage packages:</p>' +
          '<div class="cli-command">' +
          '<code>npx secureskillhub login<br>npx secureskillhub add security<br>npx secureskillhub install</code>' +
          '</div></div>';
      });
  }

  function renderPackages(packages) {
    if (!packages || packages.length === 0) {
      packagesList.innerHTML =
        '<div class="empty-packages">' +
        '<p>No packages yet. Create your first custom package!</p>' +
        '<p class="report-ops-row">Or use the CLI: <code>npx secureskillhub add dev-web-frontend-react</code></p>' +
        '</div>';
      return;
    }

    var html = '';
    for (var i = 0; i < packages.length; i++) {
      html += renderPackageCard(packages[i]);
    }
    packagesList.innerHTML = html;

    // Attach event listeners
    var resolveBtns = packagesList.querySelectorAll('[data-action="resolve"]');
    for (var j = 0; j < resolveBtns.length; j++) {
      resolveBtns[j].addEventListener('click', onResolveClick);
    }
    var deleteBtns = packagesList.querySelectorAll('[data-action="delete"]');
    for (var k = 0; k < deleteBtns.length; k++) {
      deleteBtns[k].addEventListener('click', onDeleteClick);
    }
  }

  function renderPackageCard(pkg) {
    var html = '<div class="package-card" data-package-id="' + escapeHtml(pkg.id) + '">';

    html += '<div class="package-top">';
    html += '<span class="package-name">' + escapeHtml(pkg.name) + '</span>';
    if (pkg.is_default) {
      html += '<span class="package-default-badge">DEFAULT</span>';
    }
    if (pkg.is_public) {
      html += '<span class="package-public-badge">PUBLIC</span>';
    }
    html += '</div>';

    if (pkg.description) {
      html += '<p class="report-body-text">' + escapeHtml(pkg.description) + '</p>';
    }

    var tagCount = (pkg.tags || []).length;
    var pinCount = (pkg.pinned_skills || []).length;

    html += '<div class="package-stats">';
    html += '<span><strong>' + tagCount + '</strong> tags</span>';
    html += '<span><strong>' + pinCount + '</strong> pinned skills</span>';
    html += '</div>';

    if (pkg.tags && pkg.tags.length > 0) {
      html += '<div class="package-tags">';
      for (var i = 0; i < pkg.tags.length; i++) {
        var tag = typeof pkg.tags[i] === 'string' ? pkg.tags[i] : pkg.tags[i].tag_path;
        html += '<span class="package-tag">' + escapeHtml(tag) + '</span>';
      }
      html += '</div>';
    }

    html += '<div class="package-actions">';
    html += '<button class="btn-sm" data-action="resolve" data-id="' + escapeHtml(pkg.id) + '">Preview Install</button>';
    html += '<button class="btn-sm danger" data-action="delete" data-id="' + escapeHtml(pkg.id) + '">Delete</button>';
    html += '</div>';

    html += '</div>';
    return html;
  }

  function createNewPackage() {
    var name = prompt('Package name:');
    if (!name || !name.trim()) return;

    Auth.apiFetch('/me/packages', {
      method: 'POST',
      body: { name: name.trim() }
    })
      .then(function () { loadPackages(); })
      .catch(function (err) { alert('Failed to create package: ' + err.message); });
  }

  function onResolveClick(e) {
    var pkgId = e.target.getAttribute('data-id');
    e.target.textContent = 'Resolving...';
    e.target.disabled = true;

    Auth.resolvePackage(pkgId)
      .then(function (result) {
        var skills = result.skills || [];
        var msg = 'Resolved ' + skills.length + ' skills:\n\n';
        for (var i = 0; i < Math.min(skills.length, 20); i++) {
          msg += '- ' + skills[i].name + ' (' + (skills[i].install_command || 'no install cmd') + ')\n';
        }
        if (skills.length > 20) {
          msg += '\n... and ' + (skills.length - 20) + ' more';
        }
        alert(msg);
      })
      .catch(function (err) { alert('Resolve failed: ' + err.message); })
      .finally(function () {
        e.target.textContent = 'Preview Install';
        e.target.disabled = false;
      });
  }

  function onDeleteClick(e) {
    var pkgId = e.target.getAttribute('data-id');
    if (!confirm('Delete this package?')) return;

    Auth.apiFetch('/me/packages/' + encodeURIComponent(pkgId), { method: 'DELETE' })
      .then(function () { loadPackages(); })
      .catch(function (err) { alert('Delete failed: ' + err.message); });
  }

  // -----------------------------------------------------------------------
  // Utilities
  // -----------------------------------------------------------------------

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // -----------------------------------------------------------------------
  // Start
  // -----------------------------------------------------------------------

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
