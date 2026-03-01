/* =========================================================================
   SecureSkillHub — nav.js
   Shared top navigation behavior for docs/profile/static pages.
   ========================================================================= */

(function () {
  'use strict';

  function isMobileViewport() {
    return window.innerWidth <= 767;
  }

  function initSharedNav() {
    var toggle = document.getElementById('nav-mobile-toggle');
    var links = document.getElementById('nav-links');
    if (!toggle || !links) return;
    if (links.getAttribute('data-shh-nav-init') === '1') return;
    links.setAttribute('data-shh-nav-init', '1');

    function closeNav() {
      links.classList.remove('nav-open');
      toggle.setAttribute('aria-expanded', 'false');
    }

    function openNav() {
      links.classList.add('nav-open');
      toggle.setAttribute('aria-expanded', 'true');
    }

    function toggleNav() {
      if (links.classList.contains('nav-open')) {
        closeNav();
      } else {
        openNav();
      }
    }

    toggle.setAttribute('aria-expanded', links.classList.contains('nav-open') ? 'true' : 'false');
    toggle.addEventListener('click', toggleNav);

    links.addEventListener('click', function (e) {
      var target = e.target;
      while (target && target !== links && target.tagName !== 'A') {
        target = target.parentElement;
      }
      if (!target || target === links) return;
      closeNav();
    });

    document.addEventListener('click', function (e) {
      if (!isMobileViewport()) return;
      if (e.target === toggle || toggle.contains(e.target)) return;
      if (e.target === links || links.contains(e.target)) return;
      closeNav();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeNav();
      }
    });

    window.addEventListener('resize', function () {
      if (!isMobileViewport()) {
        closeNav();
      }
    });
  }

  window.SecureSkillHubNav = window.SecureSkillHubNav || {};
  window.SecureSkillHubNav.init = initSharedNav;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSharedNav);
  } else {
    initSharedNav();
  }
})();
