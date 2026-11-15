// Runs before CSS to avoid a theme flash. This preference belongs only to the lab.
try {
  const explicit = new URLSearchParams(location.search).get('theme');
  const saved = localStorage.getItem('mm-services-lab-theme');
  const theme = [explicit,saved].find(t => ['light','dark'].includes(t)) || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.bsTheme = theme;
  document.documentElement.dataset.theme = `motionmate-${theme}`;
} catch {
  const theme = new URLSearchParams(location.search).get('theme') === 'dark' || (!new URLSearchParams(location.search).has('theme') && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  document.documentElement.dataset.bsTheme = theme;
  document.documentElement.dataset.theme = `motionmate-${theme}`;
}
