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
  trash: '<line x1="4" y1="7" x2="20" y2="7"/><path d="M9 7V4.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V7"/>'
    + '<path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  network: '<circle cx="6" cy="6.5" r="2"/><circle cx="18" cy="6.5" r="2"/><circle cx="12" cy="18" r="2"/>'
    + '<line x1="7.7" y1="7.6" x2="10.7" y2="16.2"/><line x1="16.3" y1="7.6" x2="13.3" y2="16.2"/><line x1="8" y1="6.5" x2="16" y2="6.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><line x1="12" y1="7" x2="12" y2="12.5"/><line x1="12" y1="12.5" x2="15.5" y2="14.5"/>',
  inbox: '<path d="M4 12.5l2.6-7a1 1 0 0 1 .9-.6h9a1 1 0 0 1 .9.6l2.6 7"/>'
    + '<path d="M4 12.5v5.5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5.5"/>'
    + '<path d="M4 12.5h4.3l1.2 2h4.9l1.2-2H20"/>',
  "help-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M9.4 9.3a2.7 2.7 0 0 1 5.1 1c0 1.7-2.4 2-2.4 3.6"/>'
    + '<circle cx="12" cy="16.9" r="0.6" fill="currentColor" stroke="none"/>',
  "external-link": '<path d="M13.5 4.5H19.5V10.5"/><line x1="19.5" y1="4.5" x2="11" y2="13"/>'
    + '<path d="M17 13.5V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h5.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><line x1="12" y1="2.5" x2="12" y2="4.5"/><line x1="12" y1="19.5" x2="12" y2="21.5"/>'
    + '<line x1="2.5" y1="12" x2="4.5" y2="12"/><line x1="19.5" y1="12" x2="21.5" y2="12"/>'
    + '<line x1="5.3" y1="5.3" x2="6.7" y2="6.7"/><line x1="17.3" y1="17.3" x2="18.7" y2="18.7"/>'
    + '<line x1="5.3" y1="18.7" x2="6.7" y2="17.3"/><line x1="17.3" y1="6.7" x2="18.7" y2="5.3"/>',
  moon: '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10Z"/>',
  "chevron-right": '<polyline points="9.5 6 15.5 12 9.5 18"/>',
  "book-open": '<path d="M3.5 5.5h5a3.5 3.5 0 0 1 3.5 3.5v10.5a2.5 2.5 0 0 0-2.5-2.5h-6Z"/>'
    + '<path d="M20.5 5.5h-5A3.5 3.5 0 0 0 12 9v10.5a2.5 2.5 0 0 1 2.5-2.5h6Z"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8"/><path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8"/>'
    + '<path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16"/><path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><line x1="7" y1="12" x2="17" y2="12"/>',
  layers: '<path d="M12 3.5 21 8l-9 4.5L3 8Z"/><path d="M3 12.5 12 17l9-4.5"/><path d="M3 16.5 12 21l9-4.5"/>',
  database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.5"/><path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13"/>'
    + '<path d="M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/>',
  shield: '<path d="M12 3.5 19.5 6v5.5c0 4.4-3.1 8-7.5 9.5-4.4-1.5-7.5-5.1-7.5-9.5V6Z"/><polyline points="8.8 12 11 14.2 15.4 9.8"/>',
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
