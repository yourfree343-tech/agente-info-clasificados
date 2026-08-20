/* Sistema de iconos en línea (sustituye a los emojis como "chrome" de interfaz).
   Trazo simple, monocromo (hereda currentColor), 24x24. Los emojis que forman
   parte del contenido generado (dossiers del detective, etc.) no se tocan aquí. */

const ICONS = {
  folder: '<path d="M3 7a1 1 0 0 1 1-1h4.6l1.6 1.8H20a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><line x1="20" y1="20" x2="15.5" y2="15.5"/>',
  refresh: '<path d="M4 12a8 8 0 0 1 13.66-5.66L20 8.5"/><polyline points="20 4 20 8.5 15.5 8.5"/>'
    + '<path d="M20 12a8 8 0 0 1-13.66 5.66L4 15.5"/><polyline points="4 20 4 15.5 8.5 15.5"/>',
  download: '<line x1="12" y1="3" x2="12" y2="14"/><polyline points="7.5 10 12 14.5 16.5 10"/><line x1="5" y1="19" x2="19" y2="19"/>',
  sparkles: '<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3Z"/>'
    + '<path d="M19 14.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6Z"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><line x1="3.5" y1="12" x2="20.5" y2="12"/>'
    + '<path d="M12 3.5c2.6 2.3 4 5.4 4 8.5s-1.4 6.2-4 8.5c-2.6-2.3-4-5.4-4-8.5s1.4-6.2 4-8.5Z"/>',
  "check-circle": '<circle cx="12" cy="12" r="8.5"/><polyline points="8 12.3 10.7 15 16 9.3"/>',
  "alert-triangle": '<path d="M12 4L21 19H3Z"/><line x1="12" y1="10" x2="12" y2="14"/>'
    + '<circle cx="12" cy="16.7" r="0.6" fill="currentColor" stroke="none"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><line x1="3.5" y1="9.5" x2="20.5" y2="9.5"/>'
    + '<line x1="8" y1="3" x2="8" y2="6.5"/><line x1="16" y1="3" x2="16" y2="6.5"/>',
  "file-text": '<path d="M6 3.5h7l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/>'
    + '<polyline points="13 3.5 13 7.5 17 7.5"/><line x1="8.5" y1="13" x2="15.5" y2="13"/><line x1="8.5" y1="16.5" x2="15.5" y2="16.5"/>',
  "bar-chart": '<line x1="5" y1="20" x2="5" y2="11"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="19" y1="20" x2="19" y2="13"/>',
  radio: '<circle cx="6" cy="18" r="1.6" fill="currentColor" stroke="none"/>'
    + '<path d="M6 12.8a5.2 5.2 0 0 1 5.2 5.2"/><path d="M6 8a10 10 0 0 1 10 10"/>',
  link: '<path d="M10 14l4-4"/><path d="M11.5 6.2l1.1-1.1a3.8 3.8 0 0 1 5.4 5.4l-2 2"/>'
    + '<path d="M12.5 17.8l-1.1 1.1a3.8 3.8 0 0 1-5.4-5.4l2-2"/>',
  eye: '<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
  activity: '<polyline points="3 12 7 12 9.5 18 13.5 6 16 12 21 12"/>',
  box: '<path d="M3.5 8L12 4l8.5 4-8.5 4-8.5-4Z"/><path d="M3.5 8v8L12 20l8.5-4V8"/><line x1="12" y1="12" x2="12" y2="20"/>',
  tag: '<path d="M3.5 12.3V5a1.5 1.5 0 0 1 1.5-1.5h7.3L20.5 11.7l-8.2 8.2L3.5 12.3Z"/><circle cx="8" cy="8.5" r="1.1" fill="currentColor" stroke="none"/>',
  x: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  "plus-circle": '<circle cx="12" cy="12" r="8.5"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>',
};

function iconSvg(name, opts) {
  opts = opts || {};
  const size = opts.size || 16;
  const cls = opts.cls ? ' ' + opts.cls : '';
  const body = ICONS[name];
  if (!body) return '';
  return `<svg class="icon${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" `
    + `stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" `
    + `aria-hidden="true" focusable="false">${body}</svg>`;
}

/* Monta iconos declarados de forma estática en el HTML: <span data-icon="search"></span> */
function mountIcons(root) {
  (root || document).querySelectorAll('[data-icon]').forEach(el => {
    if (el.dataset.iconMounted) return;
    const size = el.dataset.iconSize ? parseInt(el.dataset.iconSize, 10) : 16;
    el.insertAdjacentHTML('afterbegin', iconSvg(el.dataset.icon, { size }));
    el.dataset.iconMounted = '1';
  });
}
