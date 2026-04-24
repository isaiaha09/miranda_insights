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

function isPwaDisplayMode() {
  var displayModes = ['standalone', 'window-controls-overlay', 'minimal-ui', 'fullscreen'];
  var hasMatchingDisplayMode = displayModes.some(function (mode) {
    return window.matchMedia('(display-mode: ' + mode + ')').matches;
  });

  return hasMatchingDisplayMode || window.navigator.standalone === true || document.referrer.indexOf('android-app://') === 0;
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
  var isStandalone = isPwaDisplayMode();
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

function syncPwaModeInputs() {
  var isStandalone = isPwaDisplayMode();

  document.querySelectorAll('[data-pwa-mode-input]').forEach(function (input) {
    input.value = isStandalone ? '1' : '0';
  });
}

function setupLoginSubmitLoading() {
  var form = document.querySelector('[data-login-submit-form]');
  if (!form) {
    return;
  }

  var submitButton = form.querySelector('[data-login-submit-button]');
  if (!submitButton) {
    return;
  }

  form.addEventListener('submit', function (event) {
    if (form.dataset.submitting === 'true') {
      return;
    }

    event.preventDefault();
    form.dataset.submitting = 'true';
    submitButton.disabled = true;
    submitButton.classList.add('is-loading');
    var label = submitButton.querySelector('.auth-submit__label');
    if (label) {
      label.textContent = 'Logging in...';
    }

    window.requestAnimationFrame(function () {
      window.setTimeout(function () {
        form.submit();
      }, 120);
    });
  });
}

function setupSiteAnalyticsBackground() {
  var layer = document.querySelector('.site-analytics-bg');
  if (!layer) {
    return;
  }

  var canvas = layer.querySelector('.site-analytics-bg__canvas');
  if (!canvas || !canvas.getContext) {
    return;
  }

  var context = canvas.getContext('2d');
  if (!context) {
    return;
  }

  var mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  var width = 0;
  var height = 0;
  var route = [];
  var routeLength = 0;
  var headDistance = 0;
  var speed = 220;
  var tailLength = 420;
  var barFadeDistance = 920;
  var arrowClearance = 28;
  var loopResetDistance = 0;
  var frameId = 0;
  var lastTime = 0;
  var resizeTimer = 0;
  var viewportResizeTolerance = 2;
  var pendingCanvasMetrics = null;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function randomBetween(min, max) {
    return min + (Math.random() * (max - min));
  }

  function buildRoutePoints() {
    var pointCount = width < 700 ? 8 : 9;
    var startX = -Math.round(width * 0.16);
    var endX = Math.round(width * 1.08);
    var spanX = endX - startX;
    var centerY = height * (width < 700 ? 0.54 : 0.48);
    var range = height * (width < 700 ? 0.18 : 0.23);
    var currentY = centerY + randomBetween(-range * 0.2, range * 0.2);
    var points = [{ x: startX, y: currentY }];

    for (var index = 1; index < pointCount; index += 1) {
      var slopeMode = Math.random();
      var offset;

      if (slopeMode < 0.18) {
        offset = 0;
      } else if (slopeMode < 0.5) {
        offset = randomBetween(-range * 0.38, range * 0.38);
      } else {
        offset = randomBetween(-range * 0.82, range * 0.82);
      }

      currentY = clamp(currentY + offset, centerY - range, centerY + range);
      var currentX = startX + ((spanX * index) / (pointCount - 1));

      points.push({
        x: index === pointCount - 1 ? endX : currentX,
        y: currentY
      });
    }

    return points;
  }

  function rebuildRoute(resetHeadDistance) {
    var points = buildRoutePoints();
    route = [];
    routeLength = 0;

    for (var index = 0; index < points.length; index += 1) {
      route.push({
        x: points[index].x,
        y: points[index].y,
        distance: routeLength
      });

      if (index < points.length - 1) {
        var dx = points[index + 1].x - points[index].x;
        var dy = points[index + 1].y - points[index].y;
        routeLength += Math.sqrt((dx * dx) + (dy * dy));
      }
    }

    tailLength = clamp(width * 0.39, 260, 620);
    if (resetHeadDistance !== false) {
      headDistance = 0;
    }
  }

  function applyCanvasMetrics(nextWidth, nextHeight, devicePixelRatio) {
    width = nextWidth;
    height = nextHeight;
    speed = clamp(width * 0.17, 150, 290);
    barFadeDistance = clamp(width * 0.98, 620, 1280);
    arrowClearance = clamp(width * 0.028, 20, 34);

    layer.style.bottom = 'auto';
    layer.style.height = height + 'px';

    canvas.width = Math.round(width * devicePixelRatio);
    canvas.height = Math.round(height * devicePixelRatio);
    context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  }

  function pointAtDistance(distance) {
    if (!route.length) {
      return null;
    }

    if (distance <= 0) {
      var firstSegment = route[1];
      var firstSegmentLength = Math.max(1, firstSegment.distance - route[0].distance);
      var firstProgress = distance / firstSegmentLength;
      return {
        x: route[0].x + ((firstSegment.x - route[0].x) * firstProgress),
        y: route[0].y + ((firstSegment.y - route[0].y) * firstProgress),
        angle: Math.atan2(firstSegment.y - route[0].y, firstSegment.x - route[0].x)
      };
    }

    if (distance >= routeLength) {
      var lastIndex = route.length - 1;
      var lastStart = route[lastIndex - 1];
      var lastEnd = route[lastIndex];
      var lastSegmentLength = Math.max(1, lastEnd.distance - lastStart.distance);
      var lastProgress = (distance - lastStart.distance) / lastSegmentLength;
      return {
        x: lastStart.x + ((lastEnd.x - lastStart.x) * lastProgress),
        y: lastStart.y + ((lastEnd.y - lastStart.y) * lastProgress),
        angle: Math.atan2(lastEnd.y - lastStart.y, lastEnd.x - lastStart.x)
      };
    }

    for (var index = 0; index < route.length - 1; index += 1) {
      var start = route[index];
      var end = route[index + 1];
      var segmentLength = end.distance - start.distance;

      if (distance <= end.distance) {
        var progress = segmentLength === 0 ? 0 : (distance - start.distance) / segmentLength;
        return {
          x: start.x + ((end.x - start.x) * progress),
          y: start.y + ((end.y - start.y) * progress),
          angle: Math.atan2(end.y - start.y, end.x - start.x)
        };
      }
    }

    return null;
  }

  function extractTrail(startDistance, endDistance) {
    var trail = [];
    var startPoint = pointAtDistance(startDistance);
    var endPoint = pointAtDistance(endDistance);

    if (!startPoint || !endPoint) {
      return trail;
    }

    trail.push({ x: startPoint.x, y: startPoint.y, distance: startDistance });

    for (var index = 1; index < route.length - 1; index += 1) {
      if (route[index].distance > startDistance && route[index].distance < endDistance) {
        trail.push({ x: route[index].x, y: route[index].y, distance: route[index].distance });
      }
    }

    trail.push({ x: endPoint.x, y: endPoint.y, angle: endPoint.angle, distance: endDistance });
    return trail;
  }

  function drawBars() {
    var floorY = height * 0.9;

    for (var index = 1; index < route.length - 1; index += 1) {
      var point = route[index];
      var elapsed = headDistance - point.distance;

      if (elapsed < arrowClearance || elapsed > barFadeDistance) {
        continue;
      }

      if (point.x < -24 || point.x > width + 24) {
        continue;
      }

      var progress = 1 - clamp((elapsed - arrowClearance) / Math.max(1, barFadeDistance - arrowClearance), 0, 1);
      var alpha = progress * progress * (3 - (2 * progress));
      if (alpha <= 0.002) {
        continue;
      }

      var barWidth = width < 700 ? 50 : 68;
      var barTop = point.y + (width < 700 ? 8 : 10);
      var barHeight = Math.max(12, floorY - barTop);
      var barGradient = context.createLinearGradient(point.x, floorY, point.x, barTop);

      barGradient.addColorStop(0, 'rgba(88, 166, 255, 0)');
      barGradient.addColorStop(0.06, 'rgba(88, 166, 255, 0)');
      barGradient.addColorStop(0.22, 'rgba(88, 166, 255, ' + (alpha * 0.06).toFixed(3) + ')');
      barGradient.addColorStop(1, 'rgba(255, 255, 255, ' + (alpha * 0.48).toFixed(3) + ')');

      context.fillStyle = barGradient;
      context.shadowBlur = 12;
      context.shadowColor = 'rgba(88, 166, 255, ' + (alpha * 0.16).toFixed(3) + ')';
      context.fillRect(point.x - (barWidth / 2), barTop, barWidth, barHeight);
    }
  }

  function drawArrow(point) {
    if (!point) {
      return;
    }

    var arrowLength = width < 700 ? 16 : 20;
    var arrowWidth = width < 700 ? 7 : 9;
    var tipX = point.x + (Math.cos(point.angle) * arrowLength);
    var tipY = point.y + (Math.sin(point.angle) * arrowLength);
    var leftX = point.x + (Math.cos(point.angle + (Math.PI * 0.64)) * arrowWidth);
    var leftY = point.y + (Math.sin(point.angle + (Math.PI * 0.64)) * arrowWidth);
    var rightX = point.x + (Math.cos(point.angle - (Math.PI * 0.64)) * arrowWidth);
    var rightY = point.y + (Math.sin(point.angle - (Math.PI * 0.64)) * arrowWidth);

    context.beginPath();
    context.moveTo(tipX, tipY);
    context.lineTo(leftX, leftY);
    context.lineTo(rightX, rightY);
    context.closePath();
    context.fill();
  }

  function draw(now) {
    if (!width || !height || !routeLength) {
      return;
    }

    if (!lastTime) {
      lastTime = now;
    }

    var deltaSeconds = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;

    if (!mediaQuery.matches) {
      headDistance += speed * deltaSeconds;
      if (headDistance > loopResetDistance) {
        if (pendingCanvasMetrics) {
          applyCanvasMetrics(
            pendingCanvasMetrics.width,
            pendingCanvasMetrics.height,
            pendingCanvasMetrics.devicePixelRatio
          );
          pendingCanvasMetrics = null;
        }
        rebuildRoute();
      }
    } else if (headDistance === 0) {
      headDistance = Math.min(routeLength * 0.72, tailLength + 120);
    }

    var visibleEnd = headDistance;
    var visibleStart = Math.max(0, visibleEnd - tailLength);
    var trail = extractTrail(visibleStart, visibleEnd);
    var headPoint = pointAtDistance(visibleEnd);

    context.clearRect(0, 0, width, height);

    drawBars();

    if (trail.length >= 2) {
      var gradient = context.createLinearGradient(trail[0].x, trail[0].y, trail[trail.length - 1].x, trail[trail.length - 1].y);
      var glowGradient = context.createLinearGradient(trail[0].x, trail[0].y, trail[trail.length - 1].x, trail[trail.length - 1].y);
      gradient.addColorStop(0, 'rgba(88, 166, 255, 0)');
      gradient.addColorStop(0.24, 'rgba(88, 166, 255, 0.004)');
      gradient.addColorStop(0.4, 'rgba(88, 166, 255, 0.07)');
      gradient.addColorStop(0.72, 'rgba(88, 166, 255, 0.72)');
      gradient.addColorStop(1, 'rgba(255, 255, 255, 0.96)');

      glowGradient.addColorStop(0, 'rgba(88, 166, 255, 0)');
      glowGradient.addColorStop(0.28, 'rgba(88, 166, 255, 0.002)');
      glowGradient.addColorStop(0.45, 'rgba(88, 166, 255, 0.035)');
      glowGradient.addColorStop(0.78, 'rgba(88, 166, 255, 0.16)');
      glowGradient.addColorStop(1, 'rgba(167, 139, 250, 0.22)');

      context.beginPath();
      context.moveTo(trail[0].x, trail[0].y);
      for (var index = 1; index < trail.length; index += 1) {
        context.lineTo(trail[index].x, trail[index].y);
      }

      context.lineWidth = width < 700 ? 10 : 12;
      context.lineJoin = 'miter';
      context.lineCap = 'butt';
      context.strokeStyle = glowGradient;
      context.shadowBlur = 10;
      context.shadowColor = 'rgba(88, 166, 255, 0.08)';
      context.stroke();

      context.beginPath();
      context.moveTo(trail[0].x, trail[0].y);
      for (var index2 = 1; index2 < trail.length; index2 += 1) {
        context.lineTo(trail[index2].x, trail[index2].y);
      }

      context.lineWidth = width < 700 ? 3 : 4;
      context.strokeStyle = gradient;
      context.shadowBlur = 14;
      context.shadowColor = 'rgba(167, 139, 250, 0.34)';
      context.stroke();

      if (headPoint) {
        var glow = context.createRadialGradient(headPoint.x, headPoint.y, 0, headPoint.x, headPoint.y, width < 700 ? 18 : 24);
        glow.addColorStop(0, 'rgba(255, 255, 255, 0.9)');
        glow.addColorStop(0.4, 'rgba(88, 166, 255, 0.34)');
        glow.addColorStop(1, 'rgba(88, 166, 255, 0)');
        context.fillStyle = glow;
        context.beginPath();
        context.arc(headPoint.x, headPoint.y, width < 700 ? 18 : 24, 0, Math.PI * 2);
        context.fill();

        context.fillStyle = 'rgba(255, 255, 255, 0.96)';
        context.shadowBlur = 10;
        context.shadowColor = 'rgba(88, 166, 255, 0.42)';
        drawArrow(headPoint);
      }
    }

    if (!mediaQuery.matches) {
      frameId = window.requestAnimationFrame(draw);
    }
  }

  function resizeCanvas() {
    var rect = layer.getBoundingClientRect();
    var devicePixelRatio = window.devicePixelRatio || 1;
    var nextWidth = Math.max(1, rect.width);
    var nextHeight = Math.max(1, rect.height);
    var widthChanged = Math.abs(nextWidth - width) > viewportResizeTolerance;
    var heightChanged = Math.abs(nextHeight - height) > viewportResizeTolerance;
    var isHeightOnlyResize = !widthChanged && heightChanged;
    var shouldPreserveAnimation = (widthChanged || heightChanged) && width > 0 && routeLength > 0 && loopResetDistance > 0;
    var loopProgress = shouldPreserveAnimation ? clamp(headDistance / loopResetDistance, 0, 1) : 0;

    if (!widthChanged && !heightChanged && width > 0 && height > 0) {
      return;
    }

    if (isHeightOnlyResize && shouldPreserveAnimation) {
      pendingCanvasMetrics = {
        width: nextWidth,
        height: nextHeight,
        devicePixelRatio: devicePixelRatio,
      };
      return;
    }

    applyCanvasMetrics(nextWidth, nextHeight, devicePixelRatio);

    rebuildRoute(!shouldPreserveAnimation);
    loopResetDistance = routeLength + Math.max(tailLength, barFadeDistance) + Math.max(72, width * 0.12);

    if (shouldPreserveAnimation) {
      headDistance = loopProgress * loopResetDistance;
    }

    if (frameId) {
      window.cancelAnimationFrame(frameId);
      frameId = 0;
    }

    lastTime = 0;
    draw(window.performance.now());
  }

  function handleResize() {
    if (resizeTimer) {
      window.clearTimeout(resizeTimer);
    }

    resizeTimer = window.setTimeout(resizeCanvas, 90);
  }

  function handleMotionChange() {
    resizeCanvas();
  }

  window.addEventListener('resize', handleResize);

  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', handleMotionChange);
  } else if (typeof mediaQuery.addListener === 'function') {
    mediaQuery.addListener(handleMotionChange);
  }

  resizeCanvas();
}

syncBrowserChromeColor();
registerServiceWorker();

// Minimal JS placeholder for site interactions
document.addEventListener('DOMContentLoaded', function(){
  syncBrowserChromeColor();
  setupSiteAnalyticsBackground();
  setupPwaInstallExperience();
  syncPwaModeInputs();
  setupLoginSubmitLoading();
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
