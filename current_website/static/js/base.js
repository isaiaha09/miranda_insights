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
});
