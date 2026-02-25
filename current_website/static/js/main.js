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
});
