function syncBrowserChromeColor() {
  var rootStyles = window.getComputedStyle(document.documentElement);
  var chromeColor = (rootStyles.getPropertyValue('--chrome-bg') || '').trim() || '#0c111b';
  var metaNames = ['theme-color', 'msapplication-navbutton-color'];

  metaNames.forEach(function (name) {
    var meta = document.querySelector('meta[name="' + name + '"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.setAttribute('name', name);
      document.head.appendChild(meta);
    }
    meta.setAttribute('content', chromeColor);
  });
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) {
    return;
  }

  var config = window.insightsPwaConfig || {};
  var serviceWorkerUrl = config.serviceWorkerUrl || '/service-worker.js';

  window.addEventListener('load', function () {
    navigator.serviceWorker.register(serviceWorkerUrl).catch(function (error) {
      console.warn('Service worker registration failed', error);
    });
  });
}

function setupPwaInstallExperience() {
  var banner = document.getElementById('pwa-install-banner');
  var title = document.getElementById('pwa-install-title');
  var copy = document.getElementById('pwa-install-copy');
  var steps = document.getElementById('pwa-install-steps');
  var action = document.getElementById('pwa-install-action');
  var dismiss = document.getElementById('pwa-install-dismiss');

  if (!banner || !title || !copy || !steps || !action || !dismiss) {
    return;
  }

  var deferredPrompt = null;
  var dismissKey = 'insights-pwa-install-dismissed-at';
  var dismissDurationMs = 7 * 24 * 60 * 60 * 1000;
  var userAgent = window.navigator.userAgent || '';
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  var isTouchDevice = window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(max-width: 820px)').matches;
  var isIOS = /iPad|iPhone|iPod/.test(userAgent) || (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  var isAndroid = /Android/i.test(userAgent);

  function isDismissed() {
    try {
      var value = window.localStorage.getItem(dismissKey);
      if (!value) {
        return false;
      }
      return Date.now() - Number(value) < dismissDurationMs;
    } catch (error) {
      return false;
    }
  }

  function setDismissed() {
    try {
      window.localStorage.setItem(dismissKey, String(Date.now()));
    } catch (error) {
      return;
    }
  }

  function hideBanner() {
    banner.hidden = true;
    banner.classList.remove('is-visible');
  }

  function showBanner() {
    if (isStandalone || !isTouchDevice || isDismissed()) {
      return;
    }
    banner.hidden = false;
    window.requestAnimationFrame(function () {
      banner.classList.add('is-visible');
    });
  }

  function setManualMode(titleText, copyText, actionText, stepsText) {
    title.textContent = titleText;
    copy.textContent = copyText;
    action.textContent = actionText;
    steps.textContent = stepsText;
    steps.hidden = true;
    action.hidden = false;
    action.onclick = function () {
      var expanded = !steps.hidden;
      steps.hidden = expanded;
      action.textContent = expanded ? actionText : 'Hide steps';
    };
    showBanner();
  }

  dismiss.addEventListener('click', function () {
    setDismissed();
    hideBanner();
  });

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    title.textContent = 'Install Insights on this device.';
    copy.textContent = 'Get faster launch access and a full-screen app experience right from your home screen.';
    steps.hidden = true;
    action.hidden = false;
    action.textContent = 'Install app';
    action.onclick = function () {
      if (!deferredPrompt) {
        return;
      }
      deferredPrompt.prompt();
      deferredPrompt.userChoice.finally(function () {
        deferredPrompt = null;
        hideBanner();
      });
    };
    showBanner();
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    hideBanner();
  });

  if (isIOS) {
    setManualMode(
      'Add Insights to your home screen.',
      'On iPhone and iPad, installation happens from the browser share sheet rather than a browser popup.',
      'Show install steps',
      'Tap Share in your browser, then choose Add to Home Screen.'
    );
    return;
  }

  if (isAndroid) {
    window.setTimeout(function () {
      if (!deferredPrompt) {
        setManualMode(
          'Install Insights on Android.',
          'If your browser does not show the native install prompt, you can still install the app from the browser menu.',
          'Show install steps',
          'Open the browser menu, then choose Install app or Add to Home screen.'
        );
      }
    }, 1500);
    return;
  }

  setManualMode(
    'Save Insights for quick access.',
    'This browser may not offer a native install popup, but you can usually save the site from the browser menu.',
    'Show install steps',
    'Open your browser menu and look for Install app, Add to Home screen, or a similar save-to-device option.'
  );
}

syncBrowserChromeColor();
registerServiceWorker();

// Minimal JS placeholder for site interactions
document.addEventListener('DOMContentLoaded', function(){
  syncBrowserChromeColor();
  setupPwaInstallExperience();
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
});
