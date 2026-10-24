/* Sets the colour theme before first paint (an external file, because the hub's CSP forbids inline scripts). */
(function () {
  try {
    var saved = localStorage.getItem('himaya.theme');
    var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme-pref', saved || 'auto');
  } catch {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
