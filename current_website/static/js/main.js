// Minimal JS placeholder for site interactions
document.addEventListener('DOMContentLoaded', function(){
  // Example: simple console message
  console.debug('Insights site JS loaded');
  // Update footer year dynamically so it stays current
  try {
    var yearEl = document.getElementById('site-year');
    if (yearEl) {
      yearEl.textContent = new Date().getFullYear();
    }
  } catch (e) {
    console.error('Error setting site year', e);
  }
  
  // Theme toggle: persistent light/dark mode
  try {
    var rootBody = document.body;
    var toggle = document.getElementById('theme-toggle');

    function applyTheme(theme) {
      if (theme === 'dark') {
        rootBody.classList.add('dark-mode');
        if (toggle) toggle.textContent = '☀️';
      } else {
        rootBody.classList.remove('dark-mode');
        if (toggle) toggle.textContent = '🌙';
      }
    }

    // initialize from localStorage, or system preference if not set
    var stored = localStorage.getItem('insights-theme');
    if (stored === 'dark' || stored === 'light') {
      applyTheme(stored);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      applyTheme('dark');
    }

    if (toggle) {
      toggle.addEventListener('click', function () {
        var isDark = rootBody.classList.contains('dark-mode');
        var next = isDark ? 'light' : 'dark';
        applyTheme(next);
        try { localStorage.setItem('insights-theme', next); } catch (e) { /* ignore */ }
      });
    }
  } catch (e) {
    console.error('Theme toggle init failed', e);
  }

  // Mobile nav menu toggle
  try {
    var nav = document.getElementById('site-nav');
    var hamburger = document.getElementById('nav-hamburger');
    var menu = document.getElementById('nav-menu');
    var overlay = document.getElementById('nav-overlay');
    var MOBILE_BREAKPOINT = 800;

    function setMenuOpen(isOpen) {
      if (!nav || !hamburger || !menu) return;
      nav.classList.toggle('menu-open', isOpen);
      document.body.classList.toggle('nav-open', isOpen);
      hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');

      if (overlay) {
        overlay.hidden = !isOpen;
      }
    }

    if (hamburger && nav && menu) {
      hamburger.addEventListener('click', function () {
        var isOpen = nav.classList.contains('menu-open');
        setMenuOpen(!isOpen);
      });

      if (overlay) {
        overlay.addEventListener('click', function () {
          setMenuOpen(false);
        });
      }

      document.addEventListener('click', function (evt) {
        if (!nav.classList.contains('menu-open')) return;
        var target = evt.target;
        if (target && (nav.contains(target))) return;
        setMenuOpen(false);
      });

      document.addEventListener('keydown', function (evt) {
        if (evt.key === 'Escape') setMenuOpen(false);
      });

      // Close menu when a link is clicked
      menu.addEventListener('click', function (evt) {
        var el = evt.target;
        if (el && el.tagName === 'A') setMenuOpen(false);
      });

      // Ensure menu doesn't stay open when resizing to desktop
      window.addEventListener('resize', function () {
        if (window.innerWidth > MOBILE_BREAKPOINT) {
          setMenuOpen(false);
        }
      });
    }
  } catch (e) {
    console.error('Nav menu init failed', e);
  }

  // Landing page scroll behavior:
  // - Nav starts at bottom and slides to top as you scroll down
  // - "Welcome to Insights" hero content fades out as you scroll
  try {
    var isLanding = document.body && document.body.classList.contains('landing');
    if (isLanding) {
      var header = document.querySelector('.site-header');
      var heroLeft = document.querySelector('.hero-left');
      var ticking = false;

      function clamp01(n) {
        if (n < 0) return 0;
        if (n > 1) return 1;
        return n;
      }

      function updateLandingScroll() {
        ticking = false;
        if (!header) return;

        var scrollY = window.scrollY || window.pageYOffset || 0;
        // Transition distance is capped to available scroll so the nav can always reach the top.
        var docEl = document.documentElement;
        var maxScrollable = 0;
        if (docEl) {
          maxScrollable = Math.max(0, (docEl.scrollHeight || 0) - (window.innerHeight || 0));
        }
        // Complete the bottom->top transition within a moderate scroll.
        // If the page is short, cap to the available scroll so it still reaches the top.
        var desiredDistance = 500; // px
        var scrollDistance = Math.max(1, Math.min(desiredDistance, maxScrollable || desiredDistance));
        var progress = clamp01(scrollY / scrollDistance);
        var headerHeight = header.getBoundingClientRect().height || 0;
        var bottomOffset = Math.max(0, window.innerHeight - headerHeight);
        var topPx = progress >= 1 ? 0 : Math.round(bottomOffset * (1 - progress));

        // Keep the hero from intersecting the moving navbar by shifting it up in sync
        // with the navbar's travel from bottom -> top.
        var heroShift = Math.max(0, bottomOffset - topPx);
        document.documentElement.style.setProperty('--landing-hero-shift', Math.round(heroShift) + 'px');

        // Move header between bottom -> top without using transforms (keeps fixed-position children working).
        header.style.top = topPx + 'px';

        // Make room for the header without changing document flow (avoids scrollHeight changes while scrolling).
        var mainShift = Math.max(0, Math.round(headerHeight * (1 - progress)));
        document.documentElement.style.setProperty('--landing-main-shift', mainShift + 'px');

        // Fade out the hero content as you scroll.
        if (heroLeft) {
          if (progress <= 0) {
            // Preserve the initial CSS fade-in.
            heroLeft.style.opacity = '';
            heroLeft.style.transform = '';
            heroLeft.style.pointerEvents = '';
          } else {
            heroLeft.style.opacity = String(1 - progress);
            // Avoid adding another translateY here since the whole hero section
            // is already moving upward with the navbar.
            heroLeft.style.transform = '';
            heroLeft.style.pointerEvents = progress > 0.95 ? 'none' : '';
          }
        }
      }

      function onLandingScroll() {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(updateLandingScroll);
      }

      window.addEventListener('scroll', onLandingScroll, { passive: true });
      window.addEventListener('resize', onLandingScroll);
      updateLandingScroll();
    }
  } catch (e) {
    console.error('Landing scroll behavior init failed', e);
  }
});
