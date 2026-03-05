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
      var rafId = 0;
      var targetTop = null;
      var currentTop = null;
      var currentProgress = 0;
      var headerHeight = 0;
      var scrollDistance = 500;
      var scrollReleaseDistance = 500;
      var EASE_FAST = 0.35;
      var SNAP_THRESHOLD = 0.8;
      var JUMP_SMOOTH_THRESHOLD = 56;
      var lastWheelAt = 0;
      var scrollIdleTimer = 0;
      var lastScrollY = window.scrollY || window.pageYOffset || 0;

      function clamp01(n) {
        if (n < 0) return 0;
        if (n > 1) return 1;
        return n;
      }

      function recomputeMetrics() {
        if (!header) return;
        var docEl = document.documentElement;
        var viewportH = window.innerHeight || 800;
        var isMobileViewport = window.innerWidth <= 800;
        headerHeight = header.getBoundingClientRect().height || 0;
        var maxScrollable = 0;
        if (docEl) {
          maxScrollable = Math.max(0, (docEl.scrollHeight || 0) - (window.innerHeight || 0));
        }

        // Mobile: move header out of the way quickly on scroll-down.
        // Desktop: keep the longer cinematic travel.
        var desiredDistance = isMobileViewport
          ? Math.max(420, Math.round(viewportH * 0.65))
          : Math.max(900, Math.round(viewportH * 1.2));
        scrollDistance = Math.max(1, Math.min(desiredDistance, maxScrollable || desiredDistance));

        // Mobile up-scroll release: keep header pinned at top until near page top.
        scrollReleaseDistance = isMobileViewport
          ? Math.max(220, Math.round(viewportH * 0.48))
          : scrollDistance;
      }

      function computeTargetTop(scrollY, scrollingUp) {
        if (!header) return 0;
        var isMobileViewport = window.innerWidth <= 800;
        var progress;

        if (isMobileViewport && scrollingUp) {
          if (scrollY > scrollReleaseDistance) {
            progress = 1;
          } else {
            progress = clamp01(scrollY / Math.max(1, scrollReleaseDistance));
          }
        } else {
          progress = clamp01(scrollY / scrollDistance);
        }

        var bottomOffset = Math.max(0, window.innerHeight - headerHeight);
        var topPx = progress >= 1 ? 0 : (bottomOffset * (1 - progress));
        currentProgress = progress;
        return topPx;
      }

      function applyLandingState(topPx, progress) {
        if (!header) return;
        var clampedTop = Math.max(0, topPx);
        var bottomOffset = Math.max(0, window.innerHeight - headerHeight);

        // Keep the hero from intersecting with the traveling nav.
        var heroShift = Math.max(0, bottomOffset - clampedTop);
        document.documentElement.style.setProperty('--landing-hero-shift', heroShift.toFixed(3) + 'px');

        // Move header bottom->top with subpixel precision for smoother scrollbar drag.
        header.style.top = clampedTop.toFixed(3) + 'px';

        // Keep layout stable while header transitions.
        var mainShift = Math.max(0, headerHeight * (1 - progress));
        document.documentElement.style.setProperty('--landing-main-shift', mainShift.toFixed(3) + 'px');

        if (heroLeft) {
          if (progress <= 0) {
            heroLeft.style.opacity = '';
            heroLeft.style.transform = '';
            heroLeft.style.pointerEvents = '';
          } else {
            heroLeft.style.opacity = String(1 - progress);
            heroLeft.style.transform = '';
            heroLeft.style.pointerEvents = progress > 0.95 ? 'none' : '';
          }
        }
      }

      function animateLanding() {
        rafId = 0;
        if (targetTop === null || currentTop === null) return;

        var delta = targetTop - currentTop;
        currentTop += delta * EASE_FAST;

        // Smooth progress based on the animated position, not the raw scroll sample.
        var bottomOffset = Math.max(0, window.innerHeight - headerHeight);
        var progressFromTop = 1 - clamp01(currentTop / Math.max(1, bottomOffset));
        currentProgress = progressFromTop;
        applyLandingState(currentTop, currentProgress);

        if (Math.abs(delta) > SNAP_THRESHOLD) {
          rafId = window.requestAnimationFrame(animateLanding);
        } else {
          currentTop = targetTop;
          var bottomOffset2 = Math.max(0, window.innerHeight - headerHeight);
          currentProgress = 1 - clamp01(currentTop / Math.max(1, bottomOffset2));
          applyLandingState(currentTop, currentProgress);
        }
      }

      function scheduleLandingAnimation() {
        var scrollYNow = window.scrollY || window.pageYOffset || 0;
        var scrollingDown = scrollYNow > lastScrollY;
        var scrollingUp = scrollYNow < lastScrollY;
        lastScrollY = scrollYNow;

        targetTop = computeTargetTop(scrollYNow, scrollingUp);
        if (currentTop === null) {
          currentTop = targetTop;
          applyLandingState(currentTop, currentProgress);
          return;
        }

        var bottomOffset = Math.max(0, window.innerHeight - headerHeight);
        var atTopEdge = currentTop <= 0.6;
        var atBottomEdge = currentTop >= (bottomOffset - 0.6);

        var now = Date.now();
        var isWheelDriven = (now - lastWheelAt <= 120);
        var isLikelyScrollbarDrag = (now - lastWheelAt > 120) && (Math.abs(targetTop - currentTop) > 40);
        var leavingBoundary = (atTopEdge && scrollingUp) || (atBottomEdge && scrollingDown);

        // Browser scrollbar dragging should map directly with no catch-up animation.
        if (!isWheelDriven) {
          if (rafId) {
            window.cancelAnimationFrame(rafId);
            rafId = 0;
          }
          currentTop = targetTop;
          applyLandingState(currentTop, currentProgress);
          return;
        }

        // Scrollbar thumb dragging often emits sparse large jumps. Map directly to avoid catch-up lag.
        if (isLikelyScrollbarDrag || leavingBoundary) {
          if (rafId) {
            window.cancelAnimationFrame(rafId);
            rafId = 0;
          }
          currentTop = targetTop;
          applyLandingState(currentTop, currentProgress);
          return;
        }

        // For normal wheel/trackpad scrolling, apply immediately to avoid perceived lag.
        if (Math.abs(targetTop - currentTop) <= JUMP_SMOOTH_THRESHOLD) {
          if (rafId) {
            window.cancelAnimationFrame(rafId);
            rafId = 0;
          }
          currentTop = targetTop;
          applyLandingState(currentTop, currentProgress);
          return;
        }

        if (!rafId) {
          rafId = window.requestAnimationFrame(animateLanding);
        }
      }

      function onLandingScroll() {
        if (scrollIdleTimer) {
          window.clearTimeout(scrollIdleTimer);
        }
        document.body.classList.add('is-scrolling');
        scrollIdleTimer = window.setTimeout(function () {
          document.body.classList.remove('is-scrolling');
        }, 120);

        scheduleLandingAnimation();
      }

      function onLandingResize() {
        recomputeMetrics();
        scheduleLandingAnimation();
      }

      recomputeMetrics();
      window.addEventListener('wheel', function () {
        lastWheelAt = Date.now();
      }, { passive: true });
      window.addEventListener('scroll', onLandingScroll, { passive: true });
      window.addEventListener('resize', onLandingResize);
      // Initialize immediately at the correct visual position.
      targetTop = computeTargetTop(window.scrollY || window.pageYOffset || 0, false);
      currentTop = targetTop;
      applyLandingState(currentTop, currentProgress);
    }
  } catch (e) {
    console.error('Landing scroll behavior init failed', e);
  }
});
