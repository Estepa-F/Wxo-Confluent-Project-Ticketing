(function () {
  var THEME_KEY = 'theme';

  function getStoredTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      // ignore (private browsing, storage disabled, etc.)
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }

  applyTheme(getStoredTheme() === 'dark' ? 'dark' : 'light');

  function updateToggleButtons() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      btn.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
      var sun = btn.querySelector('.icon-sun');
      var moon = btn.querySelector('.icon-moon');
      if (sun) sun.hidden = isDark;
      if (moon) moon.hidden = !isDark;
    }
  }

  function toggleTheme() {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    storeTheme(next);
    updateToggleButtons();
  }

  document.addEventListener('DOMContentLoaded', function () {
    updateToggleButtons();
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', toggleTheme);
    }
  });
})();
