/* =========================================================================
   SecureSkillHub — app.js
   Pure vanilla JavaScript. No frameworks. No external dependencies.
   ========================================================================= */

(function () {
  'use strict';

  // -----------------------------------------------------------------------
  // Configuration
  // -----------------------------------------------------------------------

  var API = {
    tags:     '/api/tags.json',
    stats:    '/api/stats.json',
    skills:   '/api/skills/index.json',
    searchIndex: '/api/search-index.json',
    skill:    function (id) { return '/api/skills/' + encodeURIComponent(id) + '.json'; },
    packages: function (tagPath) { return '/api/packages/' + encodeURIComponent(tagPath) + '.json'; }
  };

  var PAGE_SIZE = 50;
  var RECENT_SKILLS_KEY = 'ssh_recent_skills';
  var RECENT_QUERIES_KEY = 'ssh_recent_queries';

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  var state = {
    skills: [],           // Full skills index
    searchIndex: [],      // Lightweight search index
    skillById: {},        // Fast skill lookup map
    tags: null,           // Tag tree data
    stats: null,          // Hub statistics
    searchTerm: '',       // Current search query
    activeTagId: null,    // Currently selected tag filter
    tagHistory: [],       // Previous tag navigation stack for back button
    packageCache: {},     // Package data cache by tag_id
    packageSkillIds: [],  // Active package skill ids
    packageOnly: false,   // Restrict current tag view to package items
    searchSuggestions: [],// Current autocomplete suggestions
    suggestionCursor: -1, // Keyboard selection index in suggestions
    recentSkillIds: [],   // Recently viewed skill ids
    recentQueries: [],    // Recently used search queries
    verifiedOnly: false,  // Show only verified skills
    scannedOrBetter: false, // Show only scanned or fully verified skills
    hideUnavailable: false, // Hide skills with repo_unavailable tag
    sortKey: 'score-desc',// Current sort key
    currentPage: 1,       // Current pagination page
    pageSize: PAGE_SIZE,  // Items shown per page
    skillCache: {},       // Cache for individual skill details
    isLoading: true,
    error: null
  };

  // -----------------------------------------------------------------------
  // DOM References (resolved once on init)
  // -----------------------------------------------------------------------

  var dom = {};
  var modalReturnFocusEl = null;
  var navActiveTicking = false;

  function resolveDom() {
    dom.statsBar       = document.getElementById('stats-bar');
    dom.statTotal      = document.getElementById('stat-total');
    dom.statVerified   = document.getElementById('stat-verified');
    dom.statFailed     = document.getElementById('stat-failed');
    dom.statPending    = document.getElementById('stat-pending');
    dom.statScans      = document.getElementById('stat-scans');
    dom.searchInput    = document.getElementById('search-input');
    dom.searchSuggest  = document.getElementById('search-suggest');
    dom.sortSelect     = document.getElementById('sort-select');
    dom.verifiedOnlyToggle = document.getElementById('verified-only-toggle');
    dom.scannedOrBetterToggle = document.getElementById('scanned-or-better-toggle');
    dom.hideUnavailableToggle = document.getElementById('hide-unavailable-toggle');
    dom.sidebarToggle  = document.getElementById('sidebar-toggle');
    dom.sidebar        = document.getElementById('sidebar');
    dom.sidebarClose   = document.getElementById('sidebar-close');
    dom.sidebarOverlay = document.getElementById('sidebar-overlay');
    dom.tagTree        = document.getElementById('tag-tree');
    dom.activeFilters  = document.getElementById('active-filters');
    dom.tagBackBtn     = document.getElementById('tag-back-btn');
    dom.contentTitle   = document.getElementById('content-title');
    dom.contentCount   = document.getElementById('content-count');
    dom.dataWarning    = document.getElementById('data-warning');
    dom.recommendPanel = document.getElementById('recommend-panel');
    dom.packagePanel   = document.getElementById('package-panel');
    dom.skillGrid      = document.getElementById('skill-grid');
    dom.pagination     = document.getElementById('pagination');
    dom.emptyState     = document.getElementById('empty-state');
    dom.errorState     = document.getElementById('error-state');
    dom.errorMessage   = document.getElementById('error-message');
    dom.clearFiltersBtn = document.getElementById('clear-filters-btn');
    dom.retryBtn       = document.getElementById('retry-btn');
    dom.modalOverlay   = document.getElementById('modal-overlay');
    dom.modalContent   = document.getElementById('modal-content');
    dom.modalClose     = document.getElementById('modal-close');
    dom.footerBuild    = document.getElementById('footer-build');
    dom.skillsAnchor   = document.getElementById('skills');

    // Hero section stats (may not exist on docs page)
    dom.heroStatTotal    = document.getElementById('hero-stat-total');
    dom.heroStatVerified = document.getElementById('hero-stat-verified');
    dom.heroStatPending  = document.getElementById('hero-stat-pending');
    dom.heroStatScans    = document.getElementById('hero-stat-scans');

    // Top navigation mobile toggle
    dom.navMobileToggle = document.getElementById('nav-mobile-toggle');
    dom.navLinks        = document.getElementById('nav-links');
  }

  // -----------------------------------------------------------------------
  // Utility Helpers
  // -----------------------------------------------------------------------

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function truncate(str, max) {
    if (!str) return '';
    if (str.length <= max) return str;
    return str.slice(0, max - 3) + '...';
  }

  function formatNumber(n) {
    if (n == null) return '--';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }

  function formatDate(iso) {
    if (!iso) return '--';
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (e) {
      return iso;
    }
  }

  function scoreClass(score) {
    if (score >= 70) return 'score-high';
    if (score >= 40) return 'score-medium';
    return 'score-low';
  }

  function normalizeStatus(status) {
    if (!status) return 'unverified';
    var value = String(status).toLowerCase();
    var map = {
      'verified': 'pass',
      'approved': 'pass',
      'failed': 'fail',
      'invalid': 'fail',
      'review': 'manual_review',
      'flagged': 'manual_review',
      'updated-unverified': 'updated_unverified'
    };
    return map[value] || value;
  }

  function getNormalizedSkillStatus(skill) {
    if (!skill) return 'unverified';
    return normalizeStatus(skill.verification_status || skill.final_status || 'unverified');
  }

  function getVerificationTier(skill) {
    if (!skill) return null;
    if (getNormalizedSkillStatus(skill) !== 'pass') return null;
    var level = String(skill.verification_level || '').toLowerCase();
    if (level === 'full_pipeline') return 'full_pipeline';
    if (level === 'scanner_only') return 'scanner_only';
    if (level === 'metadata_only') return 'metadata_only';
    // Fallback: check agents_completed
    var agents = getAgentsCompleted(skill);
    if (agents >= 5) return 'full_pipeline';
    return null;
  }

  function badgeClass(status, skill) {
    var normalized = normalizeStatus(status);
    if (!normalized) return 'badge-unverified';
    if (normalized === 'pass' && skill) {
      var tier = getVerificationTier(skill);
      if (tier === 'scanner_only') return 'badge-scanned';
      if (tier === 'metadata_only') return 'badge-assessed';
    }
    return 'badge-' + normalized.replace(/_/g, '-');
  }

  function badgeLabel(status, skill) {
    if (!status) return 'Unverified';
    var normalized = normalizeStatus(status);
    if (normalized === 'pass' && skill) {
      var tier = getVerificationTier(skill);
      if (tier === 'full_pipeline') return 'Verified';
      if (tier === 'scanner_only') return 'Scanned';
      if (tier === 'metadata_only') return 'Assessed';
    }
    var map = {
      'pass': 'Verified',
      'fail': 'Failed',
      'manual_review': 'Review',
      'unverified': 'Unverified',
      'updated_unverified': 'Updated'
    };
    return map[normalized] || normalized;
  }

  function badgeTooltip(status, skill) {
    var normalized = normalizeStatus(status);
    var passTooltip = 'Passed security verification';
    if (normalized === 'pass' && skill) {
      var tier = getVerificationTier(skill);
      if (tier === 'full_pipeline') {
        passTooltip = 'Passed full 5-agent security pipeline';
      } else if (tier === 'scanner_only') {
        passTooltip = 'Passed deterministic security scan (Agent C*)';
      } else if (tier === 'metadata_only') {
        passTooltip = 'Assessed via metadata heuristics only \u2014 no code scan';
      }
    }
    var map = {
      'pass': passTooltip,
      'fail': 'This skill failed security verification - use with caution',
      'manual_review': 'This skill requires manual security review',
      'unverified': 'This skill has not yet been verified',
      'updated_unverified': 'Skill updated since last verification'
    };
    return map[normalized] || 'Verification status unknown';
  }

  function getSkillTags(skill) {
    if (!skill || !Array.isArray(skill.tags)) return [];
    return skill.tags;
  }

  function hasSkillTag(skill, tagId) {
    var tags = getSkillTags(skill);
    return tags.indexOf(tagId) !== -1;
  }

  function isRepoUnavailableSkill(skill) {
    if (!skill) return false;
    if (hasSkillTag(skill, 'repo_unavailable')) return true;
    if (hasSkillTag(skill, 'clone_failure')) return true;
    if (hasSkillTag(skill, 'not_reachable')) return true;
    return String(skill.repo_status || '').toLowerCase() === 'unavailable';
  }

  function getAgentsCompleted(skill) {
    var agentsCompleted = Number(skill && skill.agents_completed || 0);
    if (!agentsCompleted && skill && skill.agent_audit && typeof skill.agent_audit.agents_completed === 'number') {
      agentsCompleted = Number(skill.agent_audit.agents_completed || 0);
    }
    return agentsCompleted;
  }

  function isSystemCardTag(tag) {
    if (!tag) return true;
    return tag === 'repo_unavailable' || tag === 'clone_failure' || tag === 'not_reachable' || /^status-/.test(tag);
  }

  function buildSecondaryCardBadge(skill, status) {
    if (isRepoUnavailableSkill(skill)) {
      return {
        className: 'unavailable-badge skill-badge-secondary',
        label: 'Unavailable',
        tooltip: 'Repository is unreachable, deleted, or private'
      };
    }

    var normalizedStatus = normalizeStatus(status);
    var riskLevel = String(skill && skill.risk_level || '').toLowerCase();
    if (normalizedStatus === 'pass' && (riskLevel === 'high' || riskLevel === 'critical')) {
      return {
        className: 'risk-badge risk-' + riskLevel + ' skill-badge-secondary',
        label: riskLevel,
        tooltip: 'Verified safe but high-capability: this skill uses powerful operations (file I/O, network, env access). Not a security issue \u2014 just needs care.'
      };
    }

    var agentsCompleted = getAgentsCompleted(skill);
    if ((normalizedStatus === 'manual_review' || normalizedStatus === 'updated_unverified') && agentsCompleted > 0) {
      return {
        className: 'agents-badge skill-badge-secondary',
        label: agentsCompleted + '/5 agents',
        tooltip: agentsCompleted + '/5 verification agents completed'
      };
    }

    return null;
  }

  function severityClass(sev) {
    return 'sev-' + (sev || 'info');
  }

  function isFullyVerifiedSkill(skill) {
    if (!skill) return false;
    if (getNormalizedSkillStatus(skill) !== 'pass') return false;
    var level = String(skill.verification_level || '').toLowerCase();
    var agentsCompleted = getAgentsCompleted(skill);
    return level === 'full_pipeline' || agentsCompleted >= 5;
  }

  function isScannedOrBetter(skill) {
    if (!skill) return false;
    var tier = getVerificationTier(skill);
    return tier === 'full_pipeline' || tier === 'scanner_only';
  }

  // Simple fuzzy match: check if all search terms appear somewhere in the text
  function fuzzyMatch(text, terms) {
    var lower = text.toLowerCase();
    for (var i = 0; i < terms.length; i++) {
      if (lower.indexOf(terms[i]) === -1) return false;
    }
    return true;
  }

  function computeDerivedStats() {
    var stats = {
      total_skills: state.skills.length,
      verified_skills: 0,
      failed_skills: 0,
      pending_review: 0,
      total_scans_run: 0
    };

    for (var i = 0; i < state.skills.length; i++) {
      var skill = state.skills[i];
      var status = getNormalizedSkillStatus(skill);
      if (isFullyVerifiedSkill(skill)) {
        stats.verified_skills++;
      } else if (status === 'fail') {
        stats.failed_skills++;
      } else if (status === 'manual_review' || status === 'updated_unverified' || status === 'pass') {
        stats.pending_review++;
      }
    }

    stats.total_scans_run = stats.verified_skills + stats.failed_skills + stats.pending_review;
    return stats;
  }

  function resetPagination() {
    state.currentPage = 1;
  }

  function readStorageArray(key) {
    try {
      var raw = localStorage.getItem(key);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function writeStorageArray(key, values) {
    try {
      localStorage.setItem(key, JSON.stringify(values));
    } catch (e) {
      // Ignore storage errors (private mode, quota, etc.)
    }
  }

  function prepareSkillsForFiltering() {
    state.skillById = {};
    for (var i = 0; i < state.skills.length; i++) {
      var skill = state.skills[i];
      var status = getNormalizedSkillStatus(skill);
      skill.verification_status = status;
      skill._searchBlob = [
        skill.name || '',
        skill.description || '',
        skill.owner || '',
        skill.source_hub || '',
        skill.primary_language || '',
        badgeLabel(status, skill)
      ].concat(skill.tags || []).join(' ').toLowerCase();
      state.skillById[skill.id] = skill;
    }

    if (!Array.isArray(state.searchIndex) || state.searchIndex.length === 0) {
      state.searchIndex = [];
      for (var j = 0; j < state.skills.length; j++) {
        var item = state.skills[j];
        state.searchIndex.push({
          id: item.id,
          name: item.name || '',
          description: item.description || '',
          tags: item.tags || []
        });
      }
    }

    for (var k = 0; k < state.searchIndex.length; k++) {
      var entry = state.searchIndex[k];
      entry._nameLower = (entry.name || '').toLowerCase();
      entry._descLower = (entry.description || '').toLowerCase();
      entry._tagsJoined = Array.isArray(entry.tags) ? entry.tags.join(' ').toLowerCase() : '';
    }
  }

  function loadRecentState() {
    state.recentSkillIds = readStorageArray(RECENT_SKILLS_KEY).filter(Boolean).slice(0, 8);
    state.recentQueries = readStorageArray(RECENT_QUERIES_KEY).filter(Boolean).slice(0, 8);
  }

  function rememberRecentSkill(skillId) {
    if (!skillId) return;
    var ids = [skillId];
    for (var i = 0; i < state.recentSkillIds.length; i++) {
      if (state.recentSkillIds[i] !== skillId) ids.push(state.recentSkillIds[i]);
    }
    state.recentSkillIds = ids.slice(0, 8);
    writeStorageArray(RECENT_SKILLS_KEY, state.recentSkillIds);
    renderRecommendPanel();
  }

  function rememberRecentQuery(query) {
    if (!query || query.length < 2) return;
    var value = query.trim();
    var list = [value];
    for (var i = 0; i < state.recentQueries.length; i++) {
      if (state.recentQueries[i].toLowerCase() !== value.toLowerCase()) {
        list.push(state.recentQueries[i]);
      }
    }
    state.recentQueries = list.slice(0, 8);
    writeStorageArray(RECENT_QUERIES_KEY, state.recentQueries);
  }

  // -----------------------------------------------------------------------
  // Data Fetching
  // -----------------------------------------------------------------------

  function fetchJSON(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status + ' fetching ' + url);
      return res.json();
    });
  }

  function loadAllData() {
    state.isLoading = true;
    state.error = null;
    resetPagination();
    renderLoadingState();

    var promises = [
      fetchJSON(API.tags).catch(function () { return null; }),
      fetchJSON(API.stats).catch(function () { return null; }),
      fetchJSON(API.skills).catch(function () { return []; }),
      fetchJSON(API.searchIndex).catch(function () { return []; })
    ];

    Promise.all(promises).then(function (results) {
      state.tags = results[0];
      state.stats = results[1];
      state.skills = Array.isArray(results[2]) ? results[2] : [];
      state.searchIndex = Array.isArray(results[3]) ? results[3] : [];
      state.isLoading = false;
      state.error = null;
      loadRecentState();
      prepareSkillsForFiltering();

      renderStats();
      renderTagTree();
      renderActiveFilters();
      renderRecommendPanel();
      renderPackagePanel();
      renderSkillGrid();
      renderFooterBuild();
    }).catch(function (err) {
      state.isLoading = false;
      state.error = err.message || 'Failed to load data';
      renderErrorState(state.error);
    });
  }

  function loadSkillDetail(skillId) {
    // Check cache first
    if (state.skillCache[skillId]) {
      rememberRecentSkill(skillId);
      renderSkillModal(state.skillCache[skillId]);
      return;
    }

    // Show loading in modal
    openModal();
    dom.modalContent.innerHTML = '<div class="modal-loading"><div class="spinner"></div></div>';

    fetchJSON(API.skill(skillId)).then(function (data) {
      state.skillCache[skillId] = data;
      rememberRecentSkill(skillId);
      renderSkillModal(data);
    }).catch(function () {
      // Fallback: render from index data
      var indexSkill = findSkillById(skillId);
      if (indexSkill) {
        rememberRecentSkill(skillId);
        renderSkillModal(indexSkill);
      } else {
        dom.modalContent.innerHTML =
          '<div class="error-state">' +
          '<div class="error-icon">&#x26A0;</div>' +
          '<h3>Could not load skill details</h3>' +
          '<p>The detailed data for this skill is unavailable.</p>' +
          '</div>';
      }
    });
  }

  function findSkillById(id) {
    for (var i = 0; i < state.skills.length; i++) {
      if (state.skills[i].id === id) return state.skills[i];
    }
    return null;
  }

  // -----------------------------------------------------------------------
  // Rendering: Stats
  // -----------------------------------------------------------------------

  function renderStats() {
    var s = state.stats || {};
    var derived = computeDerivedStats();
    var totalSkills = derived.total_skills;
    var verifiedSkills = derived.verified_skills;
    var failedSkills = derived.failed_skills;
    var pendingSkills = derived.pending_review;
    var totalScans = derived.total_scans_run;

    if (dom.statTotal)    dom.statTotal.textContent    = formatNumber(totalSkills);
    if (dom.statVerified) dom.statVerified.textContent = formatNumber(verifiedSkills);
    if (dom.statFailed)   dom.statFailed.textContent   = formatNumber(failedSkills);
    if (dom.statPending)  dom.statPending.textContent  = formatNumber(pendingSkills);
    if (dom.statScans)    dom.statScans.textContent    = formatNumber(totalScans);

    // Also populate hero stats if present
    if (dom.heroStatTotal)    dom.heroStatTotal.textContent    = formatNumber(totalSkills);
    if (dom.heroStatVerified) dom.heroStatVerified.textContent = formatNumber(verifiedSkills);
    if (dom.heroStatPending)  dom.heroStatPending.textContent  = formatNumber(pendingSkills);
    if (dom.heroStatScans)    dom.heroStatScans.textContent    = formatNumber(totalScans);

    if (dom.dataWarning) {
      var reportedTotal = typeof s.total_skills === 'number' ? s.total_skills : null;
      if (reportedTotal != null && reportedTotal !== totalSkills) {
        dom.dataWarning.textContent =
          'Showing ' + formatNumber(totalSkills) +
          ' skills from the live index. Upstream stats still report ' +
          formatNumber(reportedTotal) + '.';
        dom.dataWarning.classList.remove('hidden');
      } else {
        dom.dataWarning.textContent = '';
        dom.dataWarning.classList.add('hidden');
      }
    }
  }

  function renderFooterBuild() {
    var s = state.stats || {};
    if (s.last_build) {
      dom.footerBuild.textContent = 'Last build: ' + formatDate(s.last_build);
    } else {
      dom.footerBuild.textContent = 'Last build: --';
    }
  }

  // -----------------------------------------------------------------------
  // Rendering: Tag Tree
  // -----------------------------------------------------------------------

  function renderTagTree() {
    if (!state.tags || !state.tags.categories) {
      dom.tagTree.innerHTML = '<p class="tag-tree-empty">No categories available.</p>';
      return;
    }

    var html = '';
    var cats = state.tags.categories;
    for (var i = 0; i < cats.length; i++) {
      html += renderTagNode(cats[i], 0);
    }
    dom.tagTree.innerHTML = html;

    // Attach event listeners
    var headers = dom.tagTree.querySelectorAll('.tag-node-header');
    for (var j = 0; j < headers.length; j++) {
      headers[j].addEventListener('click', onTagNodeClick);
    }
  }

  function renderTagNode(node, depth) {
    var hasChildren = node.children && node.children.length > 0;
    var toggleClass = hasChildren ? '' : ' leaf';
    var count = computeTagCount(node);

    var html = '<div class="tag-node" data-tag-id="' + escapeHtml(node.id) + '">';
    html += '<div class="tag-node-header" data-tag-id="' + escapeHtml(node.id) + '" data-has-children="' + hasChildren + '" title="' + escapeHtml(node.description || '') + '">';
    html += '<span class="tag-toggle' + toggleClass + '">&#9654;</span>';
    html += '<span class="tag-node-label">' + escapeHtml(node.label) + '</span>';
    if (count > 0) {
      html += '<span class="tag-node-count">' + count + '</span>';
    }
    html += '</div>';

    if (hasChildren) {
      html += '<div class="tag-children">';
      for (var i = 0; i < node.children.length; i++) {
        html += renderTagNode(node.children[i], depth + 1);
      }
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  function computeTagCount(node) {
    if (typeof node.skill_count === 'number') {
      return node.skill_count;
    }

    // Count skills that match this tag or any child tag
    var tagIds = collectTagIds(node);
    var count = 0;
    for (var i = 0; i < state.skills.length; i++) {
      var skill = state.skills[i];
      if (skill.tags && skillMatchesAnyTag(skill, tagIds)) {
        count++;
      }
    }
    return count;
  }

  function collectTagIds(node) {
    var ids = [node.id];
    if (node.children) {
      for (var i = 0; i < node.children.length; i++) {
        ids = ids.concat(collectTagIds(node.children[i]));
      }
    }
    return ids;
  }

  function skillMatchesAnyTag(skill, tagIds) {
    if (!skill.tags) return false;
    for (var i = 0; i < skill.tags.length; i++) {
      for (var j = 0; j < tagIds.length; j++) {
        if (skill.tags[i] === tagIds[j]) return true;
      }
    }
    return false;
  }

  function skillMatchesTagLookup(skill, tagLookup) {
    if (!skill.tags) return false;
    for (var i = 0; i < skill.tags.length; i++) {
      if (tagLookup[skill.tags[i]]) return true;
    }
    return false;
  }

  function syncActiveTagHeader() {
    if (!dom.tagTree) return;
    var activeHeaders = dom.tagTree.querySelectorAll('.tag-node-header.active');
    for (var i = 0; i < activeHeaders.length; i++) {
      activeHeaders[i].classList.remove('active');
    }
    if (!state.activeTagId) return;
    var next = dom.tagTree.querySelector('.tag-node-header[data-tag-id="' + state.activeTagId + '"]');
    if (next) next.classList.add('active');
  }

  function setActiveTag(tagId, rememberHistory, shouldCloseSidebar) {
    var nextTagId = tagId || null;
    var prevTagId = state.activeTagId;
    if (nextTagId === prevTagId) return;

    state.packageOnly = false;
    state.packageSkillIds = [];

    if (rememberHistory && prevTagId !== null) {
      state.tagHistory.push(prevTagId);
      if (state.tagHistory.length > 40) {
        state.tagHistory.shift();
      }
    }

    state.activeTagId = nextTagId;
    syncActiveTagHeader();
    resetPagination();
    renderActiveFilters();
    renderRecommendPanel();
    renderPackagePanel();
    renderSkillGrid();

    if (shouldCloseSidebar !== false) {
      closeSidebar();
    }
  }

  function navigateTagBack() {
    var previous = null;
    while (state.tagHistory.length > 0) {
      previous = state.tagHistory.pop();
      if (previous !== state.activeTagId) break;
    }
    if (previous == null) previous = null;
    setActiveTag(previous, false, false);
  }

  function onTagNodeClick(e) {
    var header = e.currentTarget;
    var tagId = header.getAttribute('data-tag-id');
    var hasChildren = header.getAttribute('data-has-children') === 'true';
    var toggle = header.querySelector('.tag-toggle');
    var nodeEl = header.parentElement;
    var childrenEl = nodeEl.querySelector('.tag-children');

    // Toggle expand/collapse for nodes with children
    if (hasChildren && childrenEl) {
      var isExpanded = childrenEl.classList.contains('expanded');
      childrenEl.classList.toggle('expanded');
      toggle.classList.toggle('expanded');
    }

    // Set active tag filter
    if (state.activeTagId === tagId) {
      setActiveTag(null, true);
    } else {
      setActiveTag(tagId, true);
    }
  }

  function renderActiveFilters() {
    var chips = [];
    var title = 'All Skills';

    if (state.activeTagId) {
      var label = findTagLabel(state.activeTagId) || state.activeTagId;
      title = label;
      chips.push(
        '<span class="filter-chip">' +
        escapeHtml(label) +
        ' <span class="filter-chip-remove" data-action="clear-tag">&times;</span>' +
        '</span>'
      );
    }

    if (state.packageOnly && state.activeTagId) {
      chips.push(
        '<span class="filter-chip">' +
        'General package only' +
        ' <span class="filter-chip-remove" data-action="clear-package">&times;</span>' +
        '</span>'
      );
    }

    if (state.verifiedOnly) {
      if (!state.activeTagId) {
        title = 'Fully Verified Skills';
      }
      chips.push(
        '<span class="filter-chip">' +
        'Fully verified only' +
        ' <span class="filter-chip-remove" data-action="clear-verified">&times;</span>' +
        '</span>'
      );
    }

    if (state.scannedOrBetter && !state.verifiedOnly) {
      chips.push(
        '<span class="filter-chip">' +
        'Scanned or better' +
        ' <span class="filter-chip-remove" data-action="clear-scanned">&times;</span>' +
        '</span>'
      );
    }

    if (state.hideUnavailable) {
      chips.push(
        '<span class="filter-chip">' +
        'Hiding unavailable' +
        ' <span class="filter-chip-remove" data-action="clear-unavailable">&times;</span>' +
        '</span>'
      );
    }

    if (state.searchTerm) {
      chips.push(
        '<span class="filter-chip">' +
        '"' + escapeHtml(truncate(state.searchTerm, 24)) + '"' +
        ' <span class="filter-chip-remove" data-action="clear-search">&times;</span>' +
        '</span>'
      );
    }

    dom.contentTitle.textContent = title;
    dom.activeFilters.innerHTML = chips.join('');

    if (dom.tagBackBtn) {
      if (state.activeTagId !== null) {
        var prevTagId = state.tagHistory.length ? state.tagHistory[state.tagHistory.length - 1] : null;
        var prevLabel = prevTagId ? (findTagLabel(prevTagId) || prevTagId) : 'All Skills';
        dom.tagBackBtn.textContent = '\u2190 Back to ' + prevLabel;
        dom.tagBackBtn.classList.remove('hidden');
      } else {
        dom.tagBackBtn.classList.add('hidden');
      }
    }

    var removeBtns = dom.activeFilters.querySelectorAll('.filter-chip-remove');
    for (var i = 0; i < removeBtns.length; i++) {
      removeBtns[i].addEventListener('click', function (e) {
        var action = e.currentTarget.getAttribute('data-action');

        if (action === 'clear-tag') {
          setActiveTag(null, false, false);
          return;
        } else if (action === 'clear-package') {
          state.packageOnly = false;
        } else if (action === 'clear-verified') {
          state.verifiedOnly = false;
          if (dom.verifiedOnlyToggle) dom.verifiedOnlyToggle.checked = false;
        } else if (action === 'clear-scanned') {
          state.scannedOrBetter = false;
          if (dom.scannedOrBetterToggle) dom.scannedOrBetterToggle.checked = false;
        } else if (action === 'clear-unavailable') {
          state.hideUnavailable = false;
          if (dom.hideUnavailableToggle) dom.hideUnavailableToggle.checked = false;
        } else if (action === 'clear-search') {
          state.searchTerm = '';
          dom.searchInput.value = '';
          hideSearchSuggestions();
        }

        resetPagination();
        renderActiveFilters();
        renderPackagePanel();
        renderRecommendPanel();
        renderSkillGrid();
      });
    }
  }

  function findTagLabel(tagId) {
    if (!state.tags || !state.tags.categories) return null;
    return searchTagLabel(state.tags.categories, tagId);
  }

  function searchTagLabel(nodes, tagId) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === tagId) return nodes[i].label;
      if (nodes[i].children) {
        var found = searchTagLabel(nodes[i].children, tagId);
        if (found) return found;
      }
    }
    return null;
  }

  function applySearchTerm(term, options) {
    var opts = options || {};
    var value = (term || '').trim();
    state.searchTerm = value;
    if (dom.searchInput && dom.searchInput.value !== value) {
      dom.searchInput.value = value;
    }
    state.suggestionCursor = -1;

    if (opts.persist !== false) {
      rememberRecentQuery(value);
    }

    resetPagination();
    renderActiveFilters();
    renderRecommendPanel();
    if (opts.keepSuggestions) {
      renderSearchSuggestions(value);
    } else {
      hideSearchSuggestions();
    }
    renderSkillGrid();
  }

  function getRecentSkills(limit) {
    var rows = [];
    for (var i = 0; i < state.recentSkillIds.length; i++) {
      var skill = state.skillById[state.recentSkillIds[i]];
      if (skill) rows.push(skill);
      if (rows.length >= limit) break;
    }
    return rows;
  }

  function getTrendingSkills(limit) {
    var rows = [];
    for (var i = 0; i < state.skills.length; i++) {
      var skill = state.skills[i];
      if (getNormalizedSkillStatus(skill) !== 'pass') continue;
      rows.push(skill);
      if (rows.length >= limit) break;
    }
    return rows;
  }

  function renderRecommendPanel() {
    if (!dom.recommendPanel) return;

    var shouldShow = !state.searchTerm && !state.activeTagId && !state.error && !state.isLoading;
    if (!shouldShow) {
      dom.recommendPanel.classList.add('hidden');
      dom.recommendPanel.innerHTML = '';
      return;
    }

    var recentSkills = getRecentSkills(6);
    var trending = getTrendingSkills(8);
    var recentQueries = state.recentQueries.slice(0, 6);

    var html = '<div class="recommend-title">Quick Recommendations</div>';

    if (recentQueries.length > 0) {
      html += '<div class="recommend-row">';
      for (var i = 0; i < recentQueries.length; i++) {
        html += '<button class="recommend-btn" data-action="query" data-query="' + escapeHtml(recentQueries[i]) + '">Recent: ' + escapeHtml(truncate(recentQueries[i], 28)) + '</button>';
      }
      html += '</div>';
    }

    if (recentSkills.length > 0) {
      html += '<div class="recommend-row">';
      for (var j = 0; j < recentSkills.length; j++) {
        var rs = recentSkills[j];
        html += '<button class="recommend-btn" data-action="skill" data-skill-id="' + escapeHtml(rs.id) + '">' +
          'Resume: ' + escapeHtml(truncate(rs.name || rs.id, 30)) + '</button>';
      }
      html += '</div>';
    }

    html += '<div class="recommend-row">';
    for (var k = 0; k < trending.length; k++) {
      var ts = trending[k];
      html += '<button class="recommend-btn" data-action="skill" data-skill-id="' + escapeHtml(ts.id) + '">' +
        'Trending: ' + escapeHtml(truncate(ts.name || ts.id, 30)) + '</button>';
    }
    html += '</div>';

    dom.recommendPanel.innerHTML = html;
    dom.recommendPanel.classList.remove('hidden');
  }

  function scoreSuggestion(entry, queryLower, terms) {
    var score = 0;
    if (!entry) return -1;

    if (entry._nameLower === queryLower) score += 160;
    else if (entry._nameLower.indexOf(queryLower) === 0) score += 120;
    else if (entry._nameLower.indexOf(queryLower) !== -1) score += 90;
    else if (entry._tagsJoined.indexOf(queryLower) !== -1) score += 65;
    else if (entry._descLower.indexOf(queryLower) !== -1) score += 35;
    else score -= 20;

    for (var i = 0; i < terms.length; i++) {
      var t = terms[i];
      if (entry._nameLower.indexOf(t) !== -1) score += 15;
      else if (entry._tagsJoined.indexOf(t) !== -1) score += 10;
      else if (entry._descLower.indexOf(t) !== -1) score += 4;
      else return -1;
    }

    var skill = state.skillById[entry.id];
    if (skill) {
      if (getNormalizedSkillStatus(skill) === 'pass') score += 8;
      score += Math.min((skill.stars || 0) / 300, 25);
    }

    return score;
  }

  function renderSearchSuggestions(rawQuery) {
    if (!dom.searchSuggest) return;
    var query = (rawQuery || '').trim();

    if (!query) {
      hideSearchSuggestions();
      return;
    }

    var queryLower = query.toLowerCase();
    var terms = queryLower.split(/\s+/).filter(Boolean);
    var ranked = [];
    for (var i = 0; i < state.searchIndex.length; i++) {
      var entry = state.searchIndex[i];
      var score = scoreSuggestion(entry, queryLower, terms);
      if (score < 0) continue;
      ranked.push({ entry: entry, score: score });
    }

    ranked.sort(function (a, b) { return b.score - a.score; });
    state.searchSuggestions = ranked.slice(0, 8).map(function (row) { return row.entry; });
    state.suggestionCursor = -1;

    if (state.searchSuggestions.length === 0) {
      hideSearchSuggestions();
      return;
    }

    var html = '';
    for (var j = 0; j < state.searchSuggestions.length; j++) {
      var item = state.searchSuggestions[j];
      var skill = state.skillById[item.id];
      var statusLabel = skill ? badgeLabel(getNormalizedSkillStatus(skill), skill) : '';
      var stars = skill && skill.stars ? (' · ' + formatNumber(skill.stars) + '★') : '';
      html += '<button class="search-suggest-row" type="button" data-suggest-index="' + j + '" data-skill-id="' + escapeHtml(item.id) + '">';
      html += '<span class="search-suggest-title">' + escapeHtml(item.name || item.id) + '</span>';
      html += '<span class="search-suggest-meta">' + escapeHtml((item.tags || []).slice(0, 3).join(', ')) + (statusLabel ? (' · ' + escapeHtml(statusLabel)) : '') + stars + '</span>';
      html += '</button>';
    }

    dom.searchSuggest.innerHTML = html;
    dom.searchSuggest.classList.remove('hidden');
  }

  function hideSearchSuggestions() {
    if (!dom.searchSuggest) return;
    state.searchSuggestions = [];
    state.suggestionCursor = -1;
    dom.searchSuggest.classList.add('hidden');
    dom.searchSuggest.innerHTML = '';
  }

  function searchSuggestionsVisible() {
    return !!(dom.searchSuggest && !dom.searchSuggest.classList.contains('hidden'));
  }

  function highlightSuggestionCursor() {
    if (!dom.searchSuggest) return;
    var rows = dom.searchSuggest.querySelectorAll('.search-suggest-row');
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.toggle('active', i === state.suggestionCursor);
    }
  }

  function chooseSuggestion(index) {
    if (index < 0 || index >= state.searchSuggestions.length) return;
    var selected = state.searchSuggestions[index];
    if (!selected) return;
    rememberRecentQuery(selected.name || '');
    if (dom.searchInput) dom.searchInput.value = selected.name || '';
    hideSearchSuggestions();
    loadSkillDetail(selected.id);
  }

  function renderPackagePanel() {
    if (!dom.packagePanel) return;
    if (!state.activeTagId) {
      state.packageOnly = false;
      state.packageSkillIds = [];
      dom.packagePanel.classList.add('hidden');
      dom.packagePanel.innerHTML = '';
      return;
    }

    var tagId = state.activeTagId;
    var pkg = state.packageCache[tagId];
    if (pkg === '__loading__') {
      dom.packagePanel.classList.remove('hidden');
      dom.packagePanel.innerHTML = '<div class="package-title">General Package</div><div class="package-desc">Loading package recommendations...</div>';
      return;
    }

    if (!pkg) {
      dom.packagePanel.classList.remove('hidden');
      dom.packagePanel.innerHTML = '<div class="package-title">General Package</div><div class="package-desc">Loading package recommendations...</div>';
      state.packageCache[tagId] = '__loading__';
      fetchJSON(API.packages(tagId)).then(function (data) {
        state.packageCache[tagId] = data;
        if (state.activeTagId === tagId) {
          renderPackagePanel();
        }
      }).catch(function () {
        state.packageCache[tagId] = null;
        if (state.activeTagId === tagId) {
          renderPackagePanel();
        }
      });
      return;
    }

    if (pkg === null) {
      dom.packagePanel.classList.remove('hidden');
      dom.packagePanel.innerHTML = '<div class="package-title">General Package</div><div class="package-desc">No package is available for this tag yet.</div>';
      return;
    }

    var skills = Array.isArray(pkg.skills) ? pkg.skills.slice(0, 8) : [];
    state.packageSkillIds = Array.isArray(pkg.skill_ids) ? pkg.skill_ids : [];

    var html = '<div class="package-title">General Package</div>';
    html += '<div class="package-header">';
    html += '<span class="package-name">' + escapeHtml(pkg.label || ('General ' + tagId + ' Package')) + '</span>';
    html += '<button class="package-btn ' + (state.packageOnly ? 'is-active' : '') + '" type="button" data-action="package-toggle">' +
      (state.packageOnly ? 'Showing package only' : 'View package only') +
      '</button>';
    html += '</div>';
    html += '<p class="package-desc">' + escapeHtml(pkg.description || '') + '</p>';
    html += '<div class="package-meta">skills: ' + (pkg.total_skills || skills.length) +
      ' · candidates: ' + (pkg.total_candidates || 0) +
      ' · mode: ' + escapeHtml((pkg.selection_mode || 'verified_only').replace(/_/g, ' ')) +
      '</div>';

    if (skills.length > 0) {
      html += '<div class="recommend-row recommend-row--spaced">';
      for (var i = 0; i < skills.length; i++) {
        var s = skills[i];
        html += '<button class="package-btn" type="button" data-action="package-skill" data-skill-id="' + escapeHtml(s.id) + '">' +
          escapeHtml(truncate(s.name || s.id, 28)) +
          '</button>';
      }
      html += '</div>';
    }

    dom.packagePanel.innerHTML = html;
    dom.packagePanel.classList.remove('hidden');
  }

  // -----------------------------------------------------------------------
  // Rendering: Skill Grid
  // -----------------------------------------------------------------------

  function getFilteredSkills() {
    var skills = state.skills.slice();

    // Filter by verification status
    if (state.verifiedOnly) {
      skills = skills.filter(function (s) {
        return isFullyVerifiedSkill(s);
      });
    }

    // Filter by scanned or better (full_pipeline or scanner_only)
    if (state.scannedOrBetter && !state.verifiedOnly) {
      skills = skills.filter(function (s) {
        return isScannedOrBetter(s);
      });
    }

    // Filter out unavailable repos
    if (state.hideUnavailable) {
      skills = skills.filter(function (s) {
        return !isRepoUnavailableSkill(s);
      });
    }

    // Filter by tag
    if (state.activeTagId) {
      var tagNode = findTagNode(state.activeTagId);
      var tagIds = tagNode ? collectTagIds(tagNode) : [state.activeTagId];
      var tagLookup = {};
      for (var t = 0; t < tagIds.length; t++) {
        tagLookup[tagIds[t]] = true;
      }
      skills = skills.filter(function (s) {
        return skillMatchesTagLookup(s, tagLookup);
      });
    }

    // Filter by search
    if (state.searchTerm) {
      var terms = state.searchTerm.toLowerCase().split(/\s+/).filter(Boolean);
      skills = skills.filter(function (s) {
        return fuzzyMatch(s._searchBlob || '', terms);
      });
    }

    if (state.packageOnly && state.packageSkillIds.length > 0) {
      var packageLookup = {};
      for (var p = 0; p < state.packageSkillIds.length; p++) {
        packageLookup[state.packageSkillIds[p]] = true;
      }
      skills = skills.filter(function (s) { return !!packageLookup[s.id]; });
    }

    // Sort
    skills = sortSkills(skills, state.sortKey);

    return skills;
  }

  function findTagNode(tagId) {
    if (!state.tags || !state.tags.categories) return null;
    return searchTagNode(state.tags.categories, tagId);
  }

  function searchTagNode(nodes, tagId) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === tagId) return nodes[i];
      if (nodes[i].children) {
        var found = searchTagNode(nodes[i].children, tagId);
        if (found) return found;
      }
    }
    return null;
  }

  function sortSkills(skills, key) {
    var parts = key.split('-');
    var field = parts[0];
    var dir = parts[1];

    skills.sort(function (a, b) {
      var va, vb;
      if (field === 'score') {
        va = a.overall_score != null ? a.overall_score : -1;
        vb = b.overall_score != null ? b.overall_score : -1;
      } else if (field === 'stars') {
        va = a.stars || 0;
        vb = b.stars || 0;
      } else if (field === 'name') {
        va = (a.name || '').toLowerCase();
        vb = (b.name || '').toLowerCase();
        if (dir === 'asc') return va < vb ? -1 : va > vb ? 1 : 0;
        return va > vb ? -1 : va < vb ? 1 : 0;
      }

      if (dir === 'desc') return vb - va;
      return va - vb;
    });

    return skills;
  }

  function renderSkillGrid() {
    var skills = getFilteredSkills();
    var total = skills.length;
    renderRecommendPanel();
    renderPackagePanel();
    var pageCount = Math.max(1, Math.ceil(total / state.pageSize));
    if (state.currentPage > pageCount) {
      state.currentPage = pageCount;
    }
    var start = (state.currentPage - 1) * state.pageSize;
    var end = Math.min(start + state.pageSize, total);
    var pageSkills = skills.slice(start, end);

    // Update count
    if (total > 0) {
      dom.contentCount.textContent =
        total + ' skill' + (total !== 1 ? 's' : '') +
        ' | Showing ' + (start + 1) + '-' + end;
    } else {
      dom.contentCount.textContent = '0 skills';
    }

    // Show/hide states
    if (total === 0 && !state.isLoading && !state.error) {
      dom.skillGrid.classList.add('hidden');
      dom.emptyState.classList.remove('hidden');
      dom.errorState.classList.add('hidden');
      if (dom.pagination) {
        dom.pagination.innerHTML = '';
        dom.pagination.classList.add('hidden');
      }
      return;
    }

    dom.emptyState.classList.add('hidden');
    dom.errorState.classList.add('hidden');
    dom.skillGrid.classList.remove('hidden');

    var html = '';
    for (var i = 0; i < pageSkills.length; i++) {
      html += renderSkillCard(pageSkills[i]);
    }
    dom.skillGrid.innerHTML = html;
    renderPagination(pageCount, total);

    // Attach click listeners to cards
    var cards = dom.skillGrid.querySelectorAll('.skill-card');
    for (var j = 0; j < cards.length; j++) {
      cards[j].addEventListener('click', onSkillCardClick);
    }
  }

  function renderPagination(pageCount, totalItems) {
    if (!dom.pagination) return;
    if (pageCount <= 1 || totalItems <= state.pageSize) {
      dom.pagination.classList.add('hidden');
      dom.pagination.innerHTML = '';
      return;
    }

    var current = state.currentPage;
    var html = '';
    var startPage = Math.max(1, current - 2);
    var endPage = Math.min(pageCount, current + 2);

    html += '<button class="page-btn" data-page-action="prev" ' +
      (current === 1 ? 'disabled' : '') +
      '>Prev</button>';

    if (startPage > 1) {
      html += '<button class="page-btn" data-page="1">1</button>';
      if (startPage > 2) html += '<span class="page-ellipsis">&#8230;</span>';
    }

    for (var i = startPage; i <= endPage; i++) {
      html += '<button class="page-btn ' + (i === current ? 'active' : '') + '" data-page="' + i + '">' + i + '</button>';
    }

    if (endPage < pageCount) {
      if (endPage < pageCount - 1) html += '<span class="page-ellipsis">&#8230;</span>';
      html += '<button class="page-btn" data-page="' + pageCount + '">' + pageCount + '</button>';
    }

    html += '<button class="page-btn" data-page-action="next" ' +
      (current === pageCount ? 'disabled' : '') +
      '>Next</button>';

    html += '<span class="page-summary">Page ' + current + ' of ' + pageCount + '</span>';

    dom.pagination.innerHTML = html;
    dom.pagination.classList.remove('hidden');
  }

  function renderSkillCard(skill) {
    var status = getNormalizedSkillStatus(skill);
    var score = skill.overall_score != null ? skill.overall_score : null;
    var sClass = score != null ? scoreClass(score) : '';

    var isUnavailable = isRepoUnavailableSkill(skill);
    var html = '<div class="skill-card' + (isUnavailable ? ' skill-card-unreachable' : '') + '" data-skill-id="' + escapeHtml(skill.id) + '">';

    // Top row: name + badge
    html += '<div class="skill-card-top">';
    html += '<span class="skill-name">' + escapeHtml(skill.name) + '</span>';
    html += '<span class="skill-card-badges">';
    html += '<span class="skill-badge ' + badgeClass(status, skill) + '" data-tooltip="' + escapeHtml(badgeTooltip(status, skill)) + '">';
    html += badgeLabel(status, skill);
    html += '</span>';
    var secondaryBadge = buildSecondaryCardBadge(skill, status);
    if (secondaryBadge) {
      html += '<span class="' + secondaryBadge.className + '" data-tooltip="' + escapeHtml(secondaryBadge.tooltip || '') + '">' + escapeHtml(secondaryBadge.label) + '</span>';
    }
    html += '</span>';
    html += '</div>';

    // Description
    html += '<p class="skill-description">' + escapeHtml(skill.description || 'No description available.') + '</p>';

    // Meta row
    html += '<div class="skill-meta">';
    if (score != null) {
      html += '<span class="skill-meta-item"><span class="meta-icon">&#x2605;</span> <span class="skill-score ' + sClass + '">' + score + '/100</span></span>';
    }
    if (skill.stars != null && skill.stars > 0) {
      html += '<span class="skill-meta-item"><span class="meta-icon">&#x2606;</span> ' + formatNumber(skill.stars) + '</span>';
    }
    if (skill.source_hub) {
      html += '<span class="skill-meta-item"><span class="meta-icon">&#x2302;</span> ' + escapeHtml(formatSourceHub(skill.source_hub)) + '</span>';
    }
    if (skill.primary_language && skill.primary_language !== 'unknown') {
      html += '<span class="skill-meta-item"><span class="meta-icon">&#x2022;</span> ' + escapeHtml(skill.primary_language) + '</span>';
    }
    html += '</div>';

    // Tags
    var skillTags = getSkillTags(skill);
    var taxonomyTags = [];
    for (var ti = 0; ti < skillTags.length; ti++) {
      if (!isSystemCardTag(skillTags[ti])) taxonomyTags.push(skillTags[ti]);
    }
    if (taxonomyTags.length > 0) {
      html += '<div class="skill-tags">';
      var displayTags = taxonomyTags.slice(0, 3);
      for (var i = 0; i < displayTags.length; i++) {
        html += '<span class="skill-tag">' + escapeHtml(displayTags[i]) + '</span>';
      }
      if (taxonomyTags.length > 3) {
        html += '<span class="skill-tag skill-tag-overflow">+' + (taxonomyTags.length - 3) + '</span>';
      }
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  function formatSourceHub(hub) {
    var map = {
      'skillsmp': 'SkillsMP',
      'skills_sh': 'skills.sh',
      'claude_plugins': 'Claude Plugins',
      'mcp_so': 'mcp.so',
      'smithery': 'Smithery',
      'pulsemcp': 'PulseMCP',
      'awesome_list': 'Awesome List',
      'github_search': 'GitHub'
    };
    return map[hub] || hub;
  }

  function onSkillCardClick(e) {
    var card = e.currentTarget;
    var skillId = card.getAttribute('data-skill-id');
    if (skillId) {
      loadSkillDetail(skillId);
    }
  }

  // -----------------------------------------------------------------------
  // Rendering: Loading & Error States
  // -----------------------------------------------------------------------

  function renderLoadingState() {
    dom.skillGrid.classList.remove('hidden');
    dom.emptyState.classList.add('hidden');
    dom.errorState.classList.add('hidden');

    var html = '';
    for (var i = 0; i < 6; i++) {
      html += '<div class="skill-card skeleton-card">' +
        '<div class="skeleton-block"></div>' +
        '<div class="skeleton-block short"></div>' +
        '<div class="skeleton-block"></div>' +
        '</div>';
    }
    dom.skillGrid.innerHTML = html;
    if (dom.pagination) {
      dom.pagination.innerHTML = '';
      dom.pagination.classList.add('hidden');
    }
  }

  function renderErrorState(message) {
    dom.skillGrid.classList.add('hidden');
    dom.emptyState.classList.add('hidden');
    dom.errorState.classList.remove('hidden');
    dom.errorMessage.textContent = message || 'An error occurred while fetching data.';
    if (dom.pagination) {
      dom.pagination.innerHTML = '';
      dom.pagination.classList.add('hidden');
    }
  }

  // -----------------------------------------------------------------------
  // Rendering: Skill Detail Modal
  // -----------------------------------------------------------------------

  function renderSkillModal(skill) {
    var status = getNormalizedSkillStatus(skill);
    var score = skill.overall_score != null ? skill.overall_score : null;
    var sClass = score != null ? scoreClass(score) : '';
    var html = '';

    // -- Header --
    html += '<div class="detail-header">';
    html += '<div class="detail-title-row">';
    html += '<h2 class="detail-name" id="modal-title">' + escapeHtml(skill.name) + '</h2>';
    html += '<span class="skill-badge ' + badgeClass(status, skill) + '" data-tooltip="' + escapeHtml(badgeTooltip(status, skill)) + '">' + badgeLabel(status, skill) + '</span>';
    html += '</div>';

    html += '<p class="detail-description">' + escapeHtml(skill.description || 'No description available.') + '</p>';

    // Meta
    html += '<div class="detail-meta">';
    if (skill.owner) {
      html += '<span class="detail-meta-item">Owner: <strong>' + escapeHtml(skill.owner) + '</strong></span>';
    }
    if (skill.repo_url) {
      html += '<span class="detail-meta-item">Repo: <a href="' + escapeHtml(skill.repo_url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(truncate(skill.repo_url, 50)) + '</a></span>';
    }
    if (skill.source_hub) {
      html += '<span class="detail-meta-item">Source: ' + escapeHtml(formatSourceHub(skill.source_hub)) + '</span>';
    }
    if (skill.stars != null) {
      html += '<span class="detail-meta-item">Stars: ' + formatNumber(skill.stars) + '</span>';
    }
    if (skill.primary_language && skill.primary_language !== 'unknown') {
      html += '<span class="detail-meta-item">Language: ' + escapeHtml(skill.primary_language) + '</span>';
    }
    if (skill.trust_level) {
      html += '<span class="detail-meta-item">Trust: ' + escapeHtml(skill.trust_level) + '</span>';
    }
    if (skill.scan_date) {
      html += '<span class="detail-meta-item">Scanned: ' + formatDate(skill.scan_date) + '</span>';
    }
    if (skill.verified_commit) {
      html += '<span class="detail-meta-item detail-meta-item--mono">Commit: ' + escapeHtml(skill.verified_commit.slice(0, 8)) + '</span>';
    }
    if (skill.verification_level) {
      var tierBadgeClass = badgeClass(status, skill);
      var tierBadgeLabel = skill.verification_level === 'full_pipeline' ? '5-Agent Pipeline' :
                           skill.verification_level === 'scanner_only' ? 'Scanner Only' :
                           skill.verification_level === 'metadata_only' ? 'Metadata Only' : skill.verification_level;
      html += '<span class="detail-meta-item">Verification: <span class="skill-badge ' + tierBadgeClass + '" style="font-size:0.75rem;padding:2px 8px;">' + escapeHtml(tierBadgeLabel) + '</span></span>';
    }
    if (skill.agents_completed > 0) {
      html += '<span class="detail-meta-item">Agents: <strong>' + skill.agents_completed + '/5 completed</strong></span>';
    }
    html += '</div>';

    // Tags
    if (skill.tags && skill.tags.length > 0) {
      html += '<div class="detail-tags">';
      for (var i = 0; i < skill.tags.length; i++) {
        if (!isSystemCardTag(skill.tags[i])) {
          html += '<span class="skill-tag">' + escapeHtml(skill.tags[i]) + '</span>';
        }
      }
      html += '</div>';
    }

    // Score bar
    if (score != null) {
      html += '<div class="detail-score-bar">';
      html += '<span class="score-label">Security Score</span>';
      html += '<div class="score-track"><div class="score-fill ' + sClass + '" style="width:' + score + '%"></div></div>';
      html += '<span class="score-number ' + sClass + '">' + score + '</span>';
      html += '</div>';
    }

    html += '</div>'; // end detail-header

    // -- Pin to My Stack button (only if auth.js is loaded and user is logged in) --
    if (window.SecureSkillHubAuth && window.SecureSkillHubAuth.isLoggedIn()) {
      html += '<div class="pin-to-stack">';
      html += '<button class="btn-pin-stack" data-pin-skill="' + escapeHtml(skill.id) + '" onclick="window.__pinSkill(this)">&#x1F4CC; Pin to My Stack</button>';
      html += '</div>';
    }

    // -- Install command --
    html += renderInstallSection(skill, status);

    // -- Security Report --
    html += renderSecurityReport(skill);

    dom.modalContent.innerHTML = html;
    openModal();
  }

  function normalizeLanguage(language) {
    if (!language) return '';
    return String(language).toLowerCase();
  }

  function parseGitHubSlug(url) {
    if (!url) return null;
    var match = String(url).match(/github\.com\/([^/]+\/[^/#?]+)/i);
    if (!match) return null;
    return match[1].replace(/\.git$/i, '');
  }

  function repoDirName(url) {
    var slug = parseGitHubSlug(url);
    if (slug) {
      var parts = slug.split('/');
      return parts[1];
    }
    var cleaned = String(url || '').replace(/\/+$/, '');
    var sections = cleaned.split('/');
    return sections.length ? sections[sections.length - 1].replace(/\.git$/i, '') : 'skill-repo';
  }

  function ensureGitUrl(url) {
    if (!url) return '';
    var cleaned = String(url).replace(/\/+$/, '');
    if (/\.git$/i.test(cleaned)) return cleaned;
    return cleaned + '.git';
  }

  function buildInstallCommand(skill, status) {
    var sourceUrl = (skill.install_url || skill.repo_url || '').trim();
    if (!sourceUrl) return null;

    var commit = (skill.verified_commit || '').trim();
    var language = normalizeLanguage(skill.primary_language || '');
    var slug = parseGitHubSlug(sourceUrl);
    var command = '';
    var commandType = 'git clone';

    if (language.indexOf('python') !== -1) {
      commandType = 'pip';
      command = commit
        ? 'pip install "git+' + ensureGitUrl(sourceUrl) + '@' + commit + '"'
        : 'pip install "git+' + ensureGitUrl(sourceUrl) + '"';
    } else if (
      language.indexOf('typescript') !== -1 ||
      language.indexOf('javascript') !== -1 ||
      language.indexOf('node') !== -1
    ) {
      commandType = 'npx';
      if (slug) {
        command = commit ? 'npx -y github:' + slug + '#' + commit : 'npx -y github:' + slug;
      } else {
        commandType = 'git clone';
      }
    }

    if (!command) {
      if (commit) {
        command = 'git clone ' + sourceUrl + ' && cd ' + repoDirName(sourceUrl) + ' && git checkout ' + commit;
      } else {
        command = 'git clone ' + sourceUrl;
      }
    }

    return {
      command: command,
      command_type: commandType,
      commit: commit,
      pinned: status === 'pass' && !!commit
    };
  }

  function renderInstallSection(skill, status) {
    var install = buildInstallCommand(skill, status);
    var html = '';

    html += '<div class="report-section install-section">';
    html += '<div class="report-section-title">Install Command</div>';

    if (!install) {
      html += '<p class="install-note">No install command available for this skill yet.</p>';
      html += '</div>';
      return html;
    }

    html += '<p class="install-note">Suggested ' + escapeHtml(install.command_type) + ' command based on detected language.</p>';
    html += '<div class="install-command-row">';
    html += '<code class="install-command">' + escapeHtml(install.command) + '</code>';
    html += '<button class="btn btn-outline install-copy-btn" data-copy-command="' + escapeHtml(install.command) + '">Copy</button>';
    html += '</div>';

    if (install.pinned) {
      html += '<p class="install-status install-status-good">Pinned to verified commit ' + escapeHtml(install.commit.slice(0, 12)) + '.</p>';
    } else if (status === 'pass') {
      html += '<p class="install-status install-status-warn">Verified skill, but commit pin is unavailable in the current record.</p>';
    } else {
      html += '<p class="install-status install-status-neutral">Skill is not currently verified. Review report before installing.</p>';
    }

    html += '</div>';
    return html;
  }

  function renderAgentAuditTrail(audit) {
    if (!audit || !audit.agents_completed) return '';
    var html = '<div class="report-section">';
    html += '<div class="report-section-title">Agent Audit Trail</div>';
    html += '<div class="report-body-text">';
    html += '<strong>' + audit.agents_completed + '/' + (audit.agents_required || 5) + ' agents completed</strong>';
    if (audit.pipeline_run_at) {
      html += ' &mdash; <span class="text-muted">' + new Date(audit.pipeline_run_at).toLocaleString() + '</span>';
    }
    html += '</div>';

    var agents = [
      { key: 'agent_a', label: 'A &mdash; Docs Reader' },
      { key: 'agent_b', label: 'B &mdash; Code Parser' },
      { key: 'agent_c_star', label: 'C* &mdash; Static Scanner' },
      { key: 'agent_d', label: 'D &mdash; Scorer' },
      { key: 'agent_e', label: 'E &mdash; Supervisor' }
    ];

    html += '<table class="audit-trail-table" style="width:100%;border-collapse:collapse;margin-top:8px;font-size:0.85em">';
    html += '<tr style="border-bottom:1px solid var(--border-subtle,#333)"><th style="text-align:left;padding:4px 8px">Agent</th><th style="text-align:left;padding:4px 8px">Status</th><th style="text-align:left;padding:4px 8px">Comment</th></tr>';
    for (var i = 0; i < agents.length; i++) {
      var a = audit[agents[i].key];
      var signed = a && a.signed;
      var icon = signed ? '<span style="color:#4caf50">&#x2713;</span>' : '<span style="color:#666">&#x2717;</span>';
      var comment = (a && a.comment) ? escapeHtml(a.comment) : '<span class="text-muted">Not run</span>';
      html += '<tr style="border-bottom:1px solid var(--border-subtle,#222)">';
      html += '<td style="padding:4px 8px;white-space:nowrap">' + agents[i].label + '</td>';
      html += '<td style="padding:4px 8px">' + icon + '</td>';
      html += '<td style="padding:4px 8px;word-break:break-word">' + comment + '</td>';
      html += '</tr>';
    }
    html += '</table>';

    if (audit.manager_summary) {
      html += '<div style="margin-top:8px;padding:8px 12px;background:var(--bg-card-alt,#1a1a2e);border-radius:6px;font-size:0.85em">';
      html += '<strong>Manager Summary:</strong> ' + escapeHtml(audit.manager_summary);
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  function renderSecurityReport(skill) {
    var html = '';

    if (isRepoUnavailableSkill(skill)) {
      html += '<div class="report-section">';
      html += '<div class="report-section-title">Repository Availability</div>';
      html += '<p class="report-body-text"><strong>Status:</strong> Not reachable</p>';
      if (skill.repo_check_date) {
        html += '<p class="report-body-text"><strong>Last Check:</strong> ' + escapeHtml(formatDate(skill.repo_check_date)) + '</p>';
      }
      if (skill.repo_check_error) {
        html += '<p class="report-body-text"><strong>Error:</strong> ' + escapeHtml(String(skill.repo_check_error)) + '</p>';
      }
      html += '<p class="report-body-text--muted">This skill is tagged <code>not_reachable</code> and <code>repo_unavailable</code>. Recheck reachability before trusting install guidance.</p>';
      html += '</div>';
    }

    // Show agent audit trail if available (from verification_level + agent_audit fields)
    if (skill.agent_audit && skill.agent_audit.agents_completed > 0) {
      html += renderAgentAuditTrail(skill.agent_audit);
    } else if (skill.agents_completed > 0 && skill.verification_level === 'full_pipeline') {
      // Fallback: index-only data, show simplified audit summary
      html += '<div class="report-section">';
      html += '<div class="report-section-title">Agent Audit Trail</div>';
      html += '<div class="report-body-text"><strong>' + skill.agents_completed + '/5 verification agents completed</strong> (Full Pipeline)</div>';
      html += '<p class="report-body-text--muted">Open this skill from a served site to see detailed per-agent comments.</p>';
      html += '</div>';
    }

    // Show PM final decision (if present in findings_summary.pm_review)
    if (skill.findings_summary && skill.findings_summary.pm_review) {
      html += renderPMReview(skill.findings_summary.pm_review, skill);
    }

    // If the detailed report data is not available, show a minimal view
    var hasReport = skill.agent_a || skill.agent_b || skill.scanner || skill.scorer || skill.supervisor;
    if (!hasReport && skill.findings_summary) {
      // Render findings summary from index
      html += renderFindingsSummary(skill.findings_summary);
      return html;
    }

    if (!hasReport) {
      if (!html) {
        html += '<div class="report-section">';
        html += '<div class="report-section-title">Security Report</div>';
        html += '<p class="report-body-text--muted">Detailed security report is not yet available for this skill.</p>';
        html += '</div>';
      }
      return html;
    }

    // Supervisor verdict (shown first, at the top)
    if (skill.supervisor) {
      html += renderSupervisorVerdict(skill.supervisor);
    }

    // Agent A: Documentation Reader
    if (skill.agent_a) {
      html += renderAgentASection(skill.agent_a);
    }

    // Agent B: Code Parser
    if (skill.agent_b) {
      html += renderAgentBSection(skill.agent_b);
    }

    // Agent C*: Scanner
    if (skill.scanner) {
      html += renderScannerSection(skill.scanner);
    }

    // Agent D: Scorer
    if (skill.scorer) {
      html += renderScorerSection(skill.scorer);
    }

    return html;
  }

  // -- Supervisor Verdict --
  function renderSupervisorVerdict(sup) {
    var verdictClass, icon, title;

    if (sup.approved) {
      verdictClass = 'verdict-approved';
      icon = '&#x2714;';
      title = 'Approved';
    } else if (sup.final_status === 'manual_review') {
      verdictClass = 'verdict-review';
      icon = '&#x26A0;';
      title = 'Manual Review Required';
    } else {
      verdictClass = 'verdict-rejected';
      icon = '&#x2718;';
      title = 'Rejected';
    }

    var html = '<div class="verdict-banner ' + verdictClass + '">';
    html += '<span class="verdict-icon">' + icon + '</span>';
    html += '<div class="verdict-text">';
    html += '<h4>' + title + '</h4>';
    if (sup.summary) {
      html += '<p>' + escapeHtml(sup.summary) + '</p>';
    }
    html += '<div class="verdict-confidence">';
    html += '<span class="report-agent-label agent-e">Agent E: Supervisor</span>';
    html += ' Confidence: ' + (sup.confidence != null ? sup.confidence + '%' : '--');
    if (sup.agent_consistency_check === false) {
      html += ' | <span class="report-consistency-fail">Agent consistency check FAILED</span>';
    }
    html += '</div>';
    if (sup.compromised_agent_suspicion) {
      html += '<p class="report-warn-text">Suspected compromise: ' + escapeHtml(sup.compromised_agent_suspicion) + '</p>';
    }
    if (sup.override_reason) {
      html += '<p class="report-override-text">Override: ' + escapeHtml(sup.override_reason) + '</p>';
    }
    if (sup.recommendations && sup.recommendations.length > 0) {
      html += '<ul class="report-list report-list--spaced">';
      for (var i = 0; i < sup.recommendations.length; i++) {
        html += '<li>' + escapeHtml(sup.recommendations[i]) + '</li>';
      }
      html += '</ul>';
    }
    html += '</div>';
    html += '</div>';
    return html;
  }

  // -- Agent A: Documentation Reader --
  function renderAgentASection(a) {
    var html = '<div class="report-section">';
    html += '<div class="report-section-title"><span class="report-agent-label agent-a">Agent A</span> Documentation Reader &mdash; Claimed Features</div>';

    if (a.claimed_description) {
      html += '<p class="report-body-text">' + escapeHtml(a.claimed_description) + '</p>';
    }

    if (a.claimed_features && a.claimed_features.length > 0) {
      html += '<ul class="report-list">';
      for (var i = 0; i < a.claimed_features.length; i++) {
        html += '<li>' + escapeHtml(a.claimed_features[i]) + '</li>';
      }
      html += '</ul>';
    }

    // Additional detail
    var details = [];
    if (a.claimed_permissions && a.claimed_permissions.length > 0) {
      details.push('Permissions: ' + a.claimed_permissions.join(', '));
    }
    if (a.claimed_dependencies && a.claimed_dependencies.length > 0) {
      details.push('Dependencies: ' + a.claimed_dependencies.join(', '));
    }
    if (a.doc_quality_score != null) {
      details.push('Documentation quality: ' + a.doc_quality_score + '/10');
    }
    details.push('Has skill.md: ' + (a.has_skill_md ? 'Yes' : 'No'));
    details.push('Has README: ' + (a.has_readme ? 'Yes' : 'No'));

    if (details.length > 0) {
      html += '<div class="report-ops-row">';
      html += details.join(' &middot; ');
      html += '</div>';
    }

    if (a.warnings && a.warnings.length > 0) {
      html += '<ul class="report-list report-list--spaced">';
      for (var j = 0; j < a.warnings.length; j++) {
        html += '<li class="severity-medium">' + escapeHtml(a.warnings[j]) + '</li>';
      }
      html += '</ul>';
    }

    html += '</div>';
    return html;
  }

  // -- Agent B: Code Parser --
  function renderAgentBSection(b) {
    var html = '<div class="report-section">';
    html += '<div class="report-section-title"><span class="report-agent-label agent-b">Agent B</span> Code Parser &mdash; Actual Behavior</div>';

    if (b.actual_capabilities && b.actual_capabilities.length > 0) {
      html += '<p class="report-sub-label">Capabilities found in code:</p>';
      html += '<ul class="report-list">';
      for (var i = 0; i < b.actual_capabilities.length; i++) {
        html += '<li>' + escapeHtml(b.actual_capabilities[i]) + '</li>';
      }
      html += '</ul>';
    }

    // Operations summary
    var ops = [];
    if (b.system_calls && b.system_calls.length > 0) ops.push('System calls: ' + b.system_calls.length);
    if (b.network_calls && b.network_calls.length > 0) ops.push('Network calls: ' + b.network_calls.length);
    if (b.file_operations && b.file_operations.length > 0) ops.push('File operations: ' + b.file_operations.length);
    if (b.env_access && b.env_access.length > 0) ops.push('Env access: ' + b.env_access.length);
    if (b.total_files_analyzed) ops.push('Files analyzed: ' + b.total_files_analyzed);
    if (b.primary_language && b.primary_language !== 'unknown') ops.push('Language: ' + b.primary_language);

    if (ops.length > 0) {
      html += '<div class="report-ops-row">' + ops.join(' &middot; ') + '</div>';
    }

    // Findings
    if (b.findings && b.findings.length > 0) {
      html += '<p class="report-sub-label--spaced">Findings:</p>';
      html += '<ul class="report-list">';
      for (var j = 0; j < b.findings.length; j++) {
        var f = b.findings[j];
        html += '<li class="severity-' + (f.severity || 'info') + '">';
        html += '<strong>' + escapeHtml(f.category) + ':</strong> ' + escapeHtml(f.detail);
        if (f.file_path) {
          html += '<div class="finding-detail">' + escapeHtml(f.file_path);
          if (f.line_number) html += ':' + f.line_number;
          html += '</div>';
        }
        html += '</li>';
      }
      html += '</ul>';
    }

    html += '</div>';
    return html;
  }

  // -- Agent C*: Scanner --
  function renderScannerSection(scanner) {
    var html = '<div class="report-section">';
    html += '<div class="report-section-title"><span class="report-agent-label agent-c">Agent C*</span> Static Scanner &mdash; Deterministic Analysis</div>';

    // Counters
    var counters = [];
    if (scanner.dangerous_calls_count) counters.push('<span class="counter-critical">Dangerous calls: ' + scanner.dangerous_calls_count + '</span>');
    if (scanner.network_ops_count) counters.push('Network ops: ' + scanner.network_ops_count);
    if (scanner.file_ops_count) counters.push('File ops: ' + scanner.file_ops_count);
    if (scanner.env_access_count) counters.push('Env access: ' + scanner.env_access_count);
    if (scanner.obfuscation_count) counters.push('<span class="counter-high">Obfuscation: ' + scanner.obfuscation_count + '</span>');
    if (scanner.injection_patterns_count) counters.push('<span class="counter-critical">Injection patterns: ' + scanner.injection_patterns_count + '</span>');
    if (scanner.total_files_scanned) counters.push('Files scanned: ' + scanner.total_files_scanned);

    if (counters.length > 0) {
      html += '<div class="report-counter-row">' + counters.join(' &middot; ') + '</div>';
    }

    // Findings
    if (scanner.findings && scanner.findings.length > 0) {
      html += '<ul class="report-list">';
      for (var i = 0; i < scanner.findings.length; i++) {
        var f = scanner.findings[i];
        html += '<li class="severity-' + (f.severity || 'info') + '">';
        html += '<span class="severity-badge ' + severityClass(f.severity) + '">' + escapeHtml(f.severity || 'info') + '</span> ';
        html += '<strong>' + escapeHtml(f.rule_id) + '</strong>: ' + escapeHtml(f.message);
        if (f.file_path) {
          html += '<div class="finding-detail">' + escapeHtml(f.file_path);
          if (f.line_number) html += ':' + f.line_number;
          if (f.matched_pattern) html += ' — pattern: ' + escapeHtml(f.matched_pattern);
          html += '</div>';
        }
        html += '</li>';
      }
      html += '</ul>';
    } else {
      html += '<p class="report-body-text--muted">No findings from static scanner.</p>';
    }

    html += '</div>';
    return html;
  }

  // -- Agent D: Scorer --
  function renderScorerSection(scorer) {
    var html = '<div class="report-section">';
    html += '<div class="report-section-title"><span class="report-agent-label agent-d">Agent D</span> Scorer &mdash; Mismatch Analysis</div>';

    if (scorer.summary) {
      html += '<p class="report-body-text">' + escapeHtml(scorer.summary) + '</p>';
    }

    var meta = [];
    if (scorer.overall_score != null) meta.push('Score: ' + scorer.overall_score + '/100');
    if (scorer.risk_level) meta.push('Risk: <span class="severity-badge ' + severityClass(scorer.risk_level) + '">' + escapeHtml(scorer.risk_level) + '</span>');
    if (scorer.status) meta.push('Status: ' + escapeHtml(scorer.status));

    if (meta.length > 0) {
      html += '<div class="report-meta-row">' + meta.join(' &middot; ') + '</div>';
    }

    // Mismatches table
    if (scorer.mismatches && scorer.mismatches.length > 0) {
      html += '<table class="mismatch-table">';
      html += '<thead><tr><th>Category</th><th>Claimed</th><th>Actual</th><th>Severity</th></tr></thead>';
      html += '<tbody>';
      for (var i = 0; i < scorer.mismatches.length; i++) {
        var m = scorer.mismatches[i];
        html += '<tr>';
        html += '<td><strong>' + escapeHtml(m.category) + '</strong>';
        if (m.explanation) html += '<br><span class="mismatch-explanation">' + escapeHtml(m.explanation) + '</span>';
        html += '</td>';
        html += '<td>' + escapeHtml(m.claimed) + '</td>';
        html += '<td>' + escapeHtml(m.actual) + '</td>';
        html += '<td><span class="severity-badge ' + severityClass(m.severity) + '">' + escapeHtml(m.severity || 'info') + '</span></td>';
        html += '</tr>';
      }
      html += '</tbody></table>';
    }

    // Undocumented capabilities
    if (scorer.undocumented_capabilities && scorer.undocumented_capabilities.length > 0) {
      html += '<p class="report-sub-label--yellow">Undocumented capabilities found:</p>';
      html += '<ul class="report-list">';
      for (var j = 0; j < scorer.undocumented_capabilities.length; j++) {
        html += '<li class="severity-high">' + escapeHtml(scorer.undocumented_capabilities[j]) + '</li>';
      }
      html += '</ul>';
    }

    html += '</div>';
    return html;
  }

  function renderPMReview(pmReview, skill) {
    if (!pmReview || typeof pmReview !== 'object') return '';
    var decision = normalizeStatus(pmReview.decision);
    var reason = String(pmReview.reason || '').trim();
    var reviewer = String(pmReview.reviewer || 'pm');
    var reviewedAt = pmReview.reviewed_at ? formatDate(pmReview.reviewed_at) : '';
    var evidence = pmReview.evidence && typeof pmReview.evidence === 'object' ? pmReview.evidence : null;

    var html = '<div class="report-section">';
    html += '<div class="report-section-title">Project Manager Review</div>';
    html += '<div class="report-body-text">';
    html += '<span class="skill-badge ' + badgeClass(decision, skill) + '">' + badgeLabel(decision, skill) + '</span>';
    html += ' &mdash; Final Decision';
    html += '</div>';
    html += '<div class="report-body-text">';
    html += '<strong>Reviewer:</strong> ' + escapeHtml(reviewer);
    if (reviewedAt) {
      html += ' &middot; <strong>Reviewed:</strong> ' + escapeHtml(reviewedAt);
    }
    html += '</div>';
    if (reason) {
      html += '<p class="report-body-text"><strong>Reason:</strong> ' + escapeHtml(reason) + '</p>';
    }
    if (evidence) {
      var bits = [];
      if (evidence.score != null) bits.push('Score: ' + escapeHtml(String(evidence.score)));
      if (evidence.risk_level) bits.push('Risk: ' + escapeHtml(String(evidence.risk_level)));
      if (evidence.high_findings != null) bits.push('High findings: ' + escapeHtml(String(evidence.high_findings)));
      if (evidence.critical_findings != null) bits.push('Critical findings: ' + escapeHtml(String(evidence.critical_findings)));
      if (evidence.obfuscation_high_risk_count != null) bits.push('Obfuscation high-risk: ' + escapeHtml(String(evidence.obfuscation_high_risk_count)));
      if (evidence.injection_patterns_count != null) bits.push('Injection patterns: ' + escapeHtml(String(evidence.injection_patterns_count)));
      if (evidence.repo_unavailable != null) bits.push('Repo unavailable: ' + (evidence.repo_unavailable ? 'yes' : 'no'));
      if (bits.length > 0) {
        html += '<p class="report-body-text"><strong>Evidence:</strong> ' + bits.join(' &middot; ') + '</p>';
      }
    }
    html += '</div>';
    return html;
  }

  // -- Findings Summary (from index) --
  function renderFindingsSummary(summary) {
    if (!summary || Object.keys(summary).length === 0) return '';

    var html = '<div class="report-section">';
    html += '<div class="report-section-title">Findings Summary</div>';
    html += '<ul class="report-list">';

    var keys = Object.keys(summary);
    for (var i = 0; i < keys.length; i++) {
      html += '<li><strong>' + escapeHtml(keys[i]) + ':</strong> ' + escapeHtml(String(summary[keys[i]])) + '</li>';
    }

    html += '</ul></div>';
    return html;
  }

  // -----------------------------------------------------------------------
  // Modal Management
  // -----------------------------------------------------------------------

  function openModal() {
    var wasHidden = dom.modalOverlay.classList.contains('hidden');
    if (wasHidden) {
      var active = document.activeElement;
      modalReturnFocusEl = (active && active !== document.body) ? active : null;
    }
    dom.modalOverlay.classList.remove('hidden');
    syncBodyScrollLock();
    if (wasHidden && dom.modalClose && typeof dom.modalClose.focus === 'function') {
      setTimeout(function () {
        dom.modalClose.focus();
      }, 0);
    }
  }

  function closeModal() {
    var returnFocusEl = modalReturnFocusEl;
    dom.modalOverlay.classList.add('hidden');
    syncBodyScrollLock();
    modalReturnFocusEl = null;
    if (returnFocusEl && document.contains(returnFocusEl) && typeof returnFocusEl.focus === 'function') {
      setTimeout(function () {
        returnFocusEl.focus();
      }, 0);
    }
  }

  // -----------------------------------------------------------------------
  // Sidebar Management
  // -----------------------------------------------------------------------

  function openSidebar() {
    dom.sidebar.classList.add('open');
    syncBodyScrollLock();
  }

  function closeSidebar() {
    dom.sidebar.classList.remove('open');
    syncBodyScrollLock();
  }

  function syncBodyScrollLock() {
    var modalOpen = dom.modalOverlay && !dom.modalOverlay.classList.contains('hidden');
    var mobileSidebarOpen = dom.sidebar && dom.sidebar.classList.contains('open') && window.innerWidth <= 767;
    document.body.style.overflow = (modalOpen || mobileSidebarOpen) ? 'hidden' : '';
  }

  function findTopNavLinks() {
    if (!dom.navLinks) return { home: null, browse: null };

    var home = null;
    var browse = null;
    var anchors = dom.navLinks.querySelectorAll('a');

    for (var i = 0; i < anchors.length; i++) {
      var href = (anchors[i].getAttribute('href') || '').trim();
      if (!home && (href === '/' || href === './' || href === 'index.html')) {
        home = anchors[i];
      }
      if (!browse && (href === '#skills' || href === '/#skills' || href === './#skills' || href === 'index.html#skills')) {
        browse = anchors[i];
      }
      if (home && browse) break;
    }

    return { home: home, browse: browse };
  }

  function setTopNavActive(activeLink) {
    if (!dom.navLinks) return;
    var anchors = dom.navLinks.querySelectorAll('a');
    for (var i = 0; i < anchors.length; i++) {
      anchors[i].classList.remove('active');
    }
    if (activeLink) {
      activeLink.classList.add('active');
    }
  }

  function updateIndexNavActiveState() {
    var links = findTopNavLinks();
    if (!links.home && !links.browse) return;

    var skillsAnchor = dom.skillsAnchor || document.getElementById('skills');
    var hash = (window.location.hash || '').toLowerCase();
    var browseByHash = hash === '#skills';
    var browseByScroll = false;

    if (skillsAnchor) {
      var anchorTop = skillsAnchor.getBoundingClientRect().top + window.pageYOffset;
      var threshold = Math.max(0, anchorTop - 140);
      browseByScroll = window.pageYOffset >= threshold;
    }

    if (browseByHash || browseByScroll) {
      setTopNavActive(links.browse || links.home);
    } else {
      setTopNavActive(links.home || links.browse);
    }
  }

  function scheduleIndexNavActiveState() {
    if (navActiveTicking) return;
    navActiveTicking = true;
    window.requestAnimationFrame(function () {
      navActiveTicking = false;
      updateIndexNavActiveState();
    });
  }

  // -----------------------------------------------------------------------
  // Event Binding
  // -----------------------------------------------------------------------

  function bindEvents() {
    // Search input
    var searchTimer = null;
    dom.searchInput.addEventListener('input', function () {
      var value = dom.searchInput.value.trim();
      renderSearchSuggestions(value);
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        applySearchTerm(value, { persist: false, keepSuggestions: true });
      }, 120);
    });

    dom.searchInput.addEventListener('focus', function () {
      renderSearchSuggestions(dom.searchInput.value.trim());
    });

    dom.searchInput.addEventListener('keydown', function (e) {
      var suggestionsVisible = searchSuggestionsVisible();

      if (e.key === 'Enter') {
        e.preventDefault();
        if (suggestionsVisible && state.suggestionCursor >= 0) {
          chooseSuggestion(state.suggestionCursor);
        } else {
          applySearchTerm(dom.searchInput.value.trim(), { persist: true });
        }
        return;
      }

      if (!suggestionsVisible) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        state.suggestionCursor = Math.min(
          state.searchSuggestions.length - 1,
          state.suggestionCursor + 1
        );
        highlightSuggestionCursor();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        state.suggestionCursor = Math.max(-1, state.suggestionCursor - 1);
        highlightSuggestionCursor();
      } else if (e.key === 'Escape') {
        hideSearchSuggestions();
      }
    });

    dom.searchInput.addEventListener('blur', function () {
      setTimeout(function () {
        hideSearchSuggestions();
      }, 120);
    });

    // Sort select
    dom.sortSelect.addEventListener('change', function () {
      state.sortKey = dom.sortSelect.value;
      resetPagination();
      renderSkillGrid();
    });

    if (dom.verifiedOnlyToggle) {
      dom.verifiedOnlyToggle.addEventListener('change', function () {
        state.verifiedOnly = !!dom.verifiedOnlyToggle.checked;
        resetPagination();
        renderActiveFilters();
        renderRecommendPanel();
        renderSkillGrid();
      });
    }

    if (dom.scannedOrBetterToggle) {
      dom.scannedOrBetterToggle.addEventListener('change', function () {
        state.scannedOrBetter = !!dom.scannedOrBetterToggle.checked;
        resetPagination();
        renderActiveFilters();
        renderRecommendPanel();
        renderSkillGrid();
      });
    }

    if (dom.hideUnavailableToggle) {
      dom.hideUnavailableToggle.addEventListener('change', function () {
        state.hideUnavailable = !!dom.hideUnavailableToggle.checked;
        resetPagination();
        renderActiveFilters();
        renderSkillGrid();
      });
    }

    if (dom.tagBackBtn) {
      dom.tagBackBtn.addEventListener('click', function () {
        navigateTagBack();
      });
    }

    // Sidebar toggle (mobile)
    dom.sidebarToggle.addEventListener('click', function () {
      if (dom.sidebar.classList.contains('open')) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });

    dom.sidebarClose.addEventListener('click', closeSidebar);
    dom.sidebarOverlay.addEventListener('click', closeSidebar);

    // Modal close
    dom.modalClose.addEventListener('click', closeModal);
    dom.modalOverlay.addEventListener('click', function (e) {
      if (e.target === dom.modalOverlay) {
        closeModal();
      }
    });

    dom.modalContent.addEventListener('click', function (e) {
      var target = e.target;
      while (target && target !== dom.modalContent && !target.getAttribute('data-copy-command')) {
        target = target.parentElement;
      }
      if (!target || target === dom.modalContent) return;

      var command = target.getAttribute('data-copy-command');
      if (!command) return;

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(command).then(function () {
          target.textContent = 'Copied';
          setTimeout(function () { target.textContent = 'Copy'; }, 1200);
        }).catch(function () {
          target.textContent = 'Copy failed';
          setTimeout(function () { target.textContent = 'Copy'; }, 1200);
        });
      } else {
        var helper = document.createElement('textarea');
        helper.value = command;
        helper.style.position = 'fixed';
        helper.style.left = '-9999px';
        document.body.appendChild(helper);
        helper.focus();
        helper.select();
        try {
          document.execCommand('copy');
          target.textContent = 'Copied';
        } catch (err) {
          target.textContent = 'Copy failed';
        }
        document.body.removeChild(helper);
        setTimeout(function () { target.textContent = 'Copy'; }, 1200);
      }
    });

    // Keyboard: Escape closes modal/sidebar
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (!dom.modalOverlay.classList.contains('hidden')) {
          closeModal();
        } else if (dom.sidebar.classList.contains('open')) {
          closeSidebar();
        }
      }
    });

    // Clear filters button (empty state)
    dom.clearFiltersBtn.addEventListener('click', function () {
      state.searchTerm = '';
      state.verifiedOnly = false;
      state.scannedOrBetter = false;
      state.hideUnavailable = false;
      dom.searchInput.value = '';
      hideSearchSuggestions();
      if (dom.verifiedOnlyToggle) dom.verifiedOnlyToggle.checked = false;
      if (dom.scannedOrBetterToggle) dom.scannedOrBetterToggle.checked = false;
      if (dom.hideUnavailableToggle) dom.hideUnavailableToggle.checked = false;
      state.tagHistory = [];
      setActiveTag(null, false, false);
      renderActiveFilters();
      renderPackagePanel();
      renderRecommendPanel();
      renderSkillGrid();
    });

    if (dom.searchSuggest) {
      dom.searchSuggest.addEventListener('click', function (e) {
        var target = e.target;
        while (target && target !== dom.searchSuggest && !target.getAttribute('data-suggest-index')) {
          target = target.parentElement;
        }
        if (!target || target === dom.searchSuggest) return;
        var idx = parseInt(target.getAttribute('data-suggest-index'), 10);
        if (!isNaN(idx)) chooseSuggestion(idx);
      });
    }

    if (dom.recommendPanel) {
      dom.recommendPanel.addEventListener('click', function (e) {
        var target = e.target;
        while (target && target !== dom.recommendPanel && !target.getAttribute('data-action')) {
          target = target.parentElement;
        }
        if (!target || target === dom.recommendPanel) return;
        var action = target.getAttribute('data-action');
        if (action === 'skill') {
          var skillId = target.getAttribute('data-skill-id');
          if (skillId) loadSkillDetail(skillId);
        } else if (action === 'query') {
          var query = target.getAttribute('data-query') || '';
          applySearchTerm(query);
        }
      });
    }

    if (dom.packagePanel) {
      dom.packagePanel.addEventListener('click', function (e) {
        var target = e.target;
        while (target && target !== dom.packagePanel && !target.getAttribute('data-action')) {
          target = target.parentElement;
        }
        if (!target || target === dom.packagePanel) return;
        var action = target.getAttribute('data-action');
        if (action === 'package-toggle') {
          state.packageOnly = !state.packageOnly;
          resetPagination();
          renderActiveFilters();
          renderPackagePanel();
          renderSkillGrid();
        } else if (action === 'package-skill') {
          var packageSkillId = target.getAttribute('data-skill-id');
          if (packageSkillId) loadSkillDetail(packageSkillId);
        }
      });
    }

    if (dom.pagination) {
      dom.pagination.addEventListener('click', function (e) {
        var target = e.target;
        if (!target || target.tagName !== 'BUTTON') return;

        var action = target.getAttribute('data-page-action');
        var page = parseInt(target.getAttribute('data-page'), 10);
        var nextPage = state.currentPage;
        var pageCount = Math.max(1, Math.ceil(getFilteredSkills().length / state.pageSize));

        if (action === 'prev') nextPage = Math.max(1, state.currentPage - 1);
        if (action === 'next') nextPage = Math.min(pageCount, state.currentPage + 1);
        if (!isNaN(page)) nextPage = Math.min(pageCount, Math.max(1, page));

        if (nextPage !== state.currentPage) {
          state.currentPage = nextPage;
          renderSkillGrid();
          var top = dom.contentTitle ? dom.contentTitle.getBoundingClientRect().top + window.pageYOffset - 90 : 0;
          window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
        }
      });
    }

    // Retry button (error state)
    dom.retryBtn.addEventListener('click', function () {
      loadAllData();
    });

    // Top navigation mobile toggle
    if (dom.navMobileToggle && dom.navLinks) {
      dom.navMobileToggle.addEventListener('click', function () {
        dom.navLinks.classList.toggle('nav-open');
      });

      var navAnchors = dom.navLinks.querySelectorAll('a');
      for (var n = 0; n < navAnchors.length; n++) {
        navAnchors[n].addEventListener('click', function () {
          dom.navLinks.classList.remove('nav-open');
        });
      }

      document.addEventListener('click', function (e) {
        if (window.innerWidth > 767) return;
        if (e.target === dom.navMobileToggle || dom.navMobileToggle.contains(e.target)) return;
        if (e.target === dom.navLinks || dom.navLinks.contains(e.target)) return;
        dom.navLinks.classList.remove('nav-open');
      });

      window.addEventListener('scroll', scheduleIndexNavActiveState, { passive: true });
      window.addEventListener('hashchange', scheduleIndexNavActiveState);
      window.addEventListener('resize', scheduleIndexNavActiveState);
      scheduleIndexNavActiveState();
    }
  }

  // -----------------------------------------------------------------------
  // Initialize
  // -----------------------------------------------------------------------

  function init() {
    resolveDom();
    bindEvents();
    loadAllData();
  }

  // -----------------------------------------------------------------------
  // Pin to My Stack (global handler for inline onclick)
  // -----------------------------------------------------------------------

  window.__pinSkill = function (btn) {
    var skillId = btn.getAttribute('data-pin-skill');
    if (!skillId || !window.SecureSkillHubAuth) return;

    btn.textContent = 'Pinning...';
    btn.disabled = true;

    window.SecureSkillHubAuth.pinSkill(skillId)
      .then(function () {
        btn.textContent = '\u2705 Pinned!';
        btn.classList.add('pinned');
      })
      .catch(function (err) {
        btn.textContent = 'Failed — ' + err.message;
        btn.disabled = false;
      });
  };

  // Run on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
