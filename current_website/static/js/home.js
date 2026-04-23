// Landing/home page specific interactions
(function initHomeScript() {
  function runLandingBehavior() {
    try {
      var isLanding = document.body && document.body.classList.contains('landing');
      if (!isLanding) return;

      var header = document.querySelector('.site-header');
      var landingNav = document.getElementById('site-nav');
      var heroSection = document.querySelector('.hero-landing');
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
        // Desktop: pin the header earlier than the original version, but not so early that it leaves a large empty gap.
        var heroHeight = heroSection ? (heroSection.getBoundingClientRect().height || viewportH) : viewportH;
        var desiredDistance = isMobileViewport
          ? Math.max(320, Math.round(viewportH * 0.5))
          : Math.max(420, Math.round(Math.min(viewportH * 0.62, heroHeight * 0.46)));
        scrollDistance = Math.max(1, Math.min(desiredDistance, maxScrollable || desiredDistance));

        // Mobile up-scroll release: keep header pinned at top until near page top.
        scrollReleaseDistance = isMobileViewport
          ? Math.max(180, Math.round(viewportH * 0.32))
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

        // Mobile landing: when header sits at the bottom, make the drawer open above it.
        if (landingNav) {
          var isMobileViewport = window.innerWidth <= 800;
          var nearBottom = clampedTop >= (bottomOffset - 350);
          landingNav.classList.toggle('menu-anchor-bottom', !!(isMobileViewport && nearBottom));
        }

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
    } catch (e) {
      console.error('Landing scroll behavior init failed', e);
    }
  }

  function runNewsletterBehavior() {
    var form = document.querySelector('[data-subscribe-form]');
    var messageHost = document.querySelector('[data-subscribe-messages]');
    if (!form || !messageHost) return;

    var submitButton = form.querySelector('button[type="submit"]');
    var emailInput = form.querySelector('input[name="email"]');
    var sectionId = form.getAttribute('data-section-id') || 'newsletter-signup';

    function getHeaderOffset() {
      var header = document.querySelector('.site-header');
      return header ? header.getBoundingClientRect().height : 0;
    }

    function scrollSectionIntoView(smooth) {
      var section = document.getElementById(sectionId);
      if (!section) return;

      var top = section.getBoundingClientRect().top + window.scrollY - getHeaderOffset() - 12;
      window.scrollTo({
        top: Math.max(0, top),
        behavior: smooth ? 'smooth' : 'auto'
      });

      if (typeof section.focus === 'function') {
        section.focus({ preventScroll: true });
      }
    }

    function renderMessage(level, text) {
      var message = document.createElement('p');

      message.className = 'subscribe-message subscribe-message-' + (level || 'info');
      message.textContent = text;
      messageHost.hidden = false;
      messageHost.replaceChildren(message);
    }

    if (window.location.hash === '#' + sectionId || window.location.search.indexOf('newsletter_status=') !== -1) {
      window.requestAnimationFrame(function () {
        scrollSectionIntoView(false);
      });
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();

      var formData = new FormData(form);
      if (submitButton) {
        submitButton.disabled = true;
      }

      fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        },
        credentials: 'same-origin'
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          renderMessage(result.data.level, result.data.message);
          scrollSectionIntoView(true);

          if (result.ok && emailInput) {
            emailInput.value = '';
          }
        })
        .catch(function () {
          renderMessage('error', 'Your subscription request could not be completed right now. Please try again.');
          scrollSectionIntoView(true);
        })
        .finally(function () {
          if (submitButton) {
            submitButton.disabled = false;
          }
        });
    });
  }

  function runCookieBannerBehavior() {
    var banner = document.getElementById('cookie-banner');
    var acceptButton = document.getElementById('cookie-banner-accept');
    var dismissButton = document.getElementById('cookie-banner-dismiss');
    if (!banner || !acceptButton || !dismissButton) return;

    if (banner.parentNode !== document.body) {
      document.body.appendChild(banner);
    }

    var consentKey = 'insights-home-cookie-banner-choice';

    function getChoice() {
      try {
        return window.localStorage.getItem(consentKey);
      } catch (error) {
        return null;
      }
    }

    function setChoice(value) {
      try {
        window.localStorage.setItem(consentKey, value);
      } catch (error) {
        return;
      }
    }

    function hideBanner() {
      banner.classList.remove('is-visible');
      window.setTimeout(function () {
        banner.hidden = true;
      }, 220);
    }

    if (getChoice()) {
      return;
    }

    banner.hidden = false;
    window.requestAnimationFrame(function () {
      banner.classList.add('is-visible');
    });

    acceptButton.addEventListener('click', function () {
      setChoice('accepted');
      hideBanner();
    });

    dismissButton.addEventListener('click', function () {
      setChoice('dismissed');
      hideBanner();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      runLandingBehavior();
      runNewsletterBehavior();
      runCookieBannerBehavior();
    }, { once: true });
  } else {
    runLandingBehavior();
    runNewsletterBehavior();
    runCookieBannerBehavior();
  }
})();
