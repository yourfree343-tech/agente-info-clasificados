/* Utilidades compartidas por las tres páginas: escapado, peticiones a la API, avisos,
   fechas, paginación, tooltip de gráficas, tema claro/oscuro y atajos de teclado.
   Antes cada plantilla llevaba su propia copia de escHtml/showToast/paginación. */

/* ---------- Escapado ---------- */
function escHtml(s) {
  return s == null ? '' : String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
/* URL segura para href/src: solo http(s); cualquier otra cosa (javascript:, data:...) -> '#'. */
function escUrl(s) {
  if (!s || !/^https?:\/\//i.test(String(s))) return '#';
  return escHtml(s);
}

/* Texto plano con sus URLs convertidas en enlaces cortos ("nytimes.com ↗"): el modelo cita
   las fuentes entre paréntesis con la URL completa, que desborda columnas y no se lee. */
function textoConEnlaces(s) {
  if (s == null) return '';
  const str = String(s);
  const re = /https?:\/\/[^\s<>"'()[\]]+[^\s<>"'()[\].,;:!?]/g;
  let out = '', ultimo = 0, m;
  while ((m = re.exec(str))) {
    out += escHtml(str.slice(ultimo, m.index));
    let dom;
    try { dom = new URL(m[0]).hostname.replace(/^www\./, ''); } catch (_) { dom = m[0]; }
    out += `<a class="cita-url" href="${escUrl(m[0])}" target="_blank" rel="noopener noreferrer" title="${escHtml(m[0])}">${escHtml(dom)} ↗</a>`;
    ultimo = m.index + m[0].length;
  }
  return out + escHtml(str.slice(ultimo));
}

/* ---------- API ---------- */
/* fetch + JSON con errores normalizados: nunca lanza; devuelve {ok:false, error} si falla. */
async function api(url, opts) {
  try {
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (_) { data = null; }
    if (data === null) return { ok: false, error: `Respuesta no válida del servidor (HTTP ${r.status}).`, status: r.status };
    if (!r.ok && data && typeof data === 'object' && !Array.isArray(data) && data.ok === undefined) data.ok = false;
    if (data && typeof data === 'object' && !Array.isArray(data)) data.status = r.status;
    return data;
  } catch (e) {
    return { ok: false, error: 'Sin conexión con el servidor.', status: 0 };
  }
}

/* ---------- Avisos (toasts apilables) ---------- */
function showToast(msg, tipo) {
  let stack = document.getElementById('toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toast-stack'; stack.className = 'toast-stack';
    stack.setAttribute('role', 'status'); stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
  }
  const t = document.createElement('div');
  t.className = 'toast ' + (tipo || 'info');
  t.textContent = msg;
  stack.appendChild(t);
  while (stack.children.length > 3) stack.firstChild.remove();
  const dur = tipo === 'error' ? 7000 : 4500;
  setTimeout(() => { t.classList.add('saliendo'); setTimeout(() => t.remove(), 300); }, dur);
}

/* ---------- Fechas ---------- */
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic'];

/* '2025-03-18' -> '18 mar 2025' · '1977' -> '1977' · '' -> '—' */
function fmtFechaDoc(s) {
  if (!s) return '—';
  const m = String(s).match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/);
  if (!m) return String(s);
  if (!m[2]) return m[1];
  if (!m[3]) return `${MESES[+m[2] - 1]} ${m[1]}`;
  return `${+m[3]} ${MESES[+m[2] - 1]} ${m[1]}`;
}

/* ISO con hora -> '21 ago 2026, 07:20' */
function fmtFechaHora(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return `${d.getDate()} ${MESES[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/* ISO -> 'hace 5 min', 'hace 3 h', 'ayer', 'hace 4 días' */
function fmtRelativo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'hace un momento';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  const dias = Math.round(s / 86400);
  return dias === 1 ? 'ayer' : `hace ${dias} días`;
}

/* segundos -> '2 min 05 s' */
function fmtDuracion(seg) {
  seg = Math.max(0, Math.round(seg));
  const m = Math.floor(seg / 60), s = seg % 60;
  return m ? `${m} min ${String(s).padStart(2, '0')} s` : `${s} s`;
}

function plural(n, uno, varios) { return `${n} ${n === 1 ? uno : (varios || uno + 's')}`; }
function fmtNum(n) { return (n == null ? 0 : n).toLocaleString('es-ES'); }

/* ---------- Paginación ---------- */
/* Pinta la paginación en `el` y llama a onGo(página). Sin onclick en línea. */
function renderPagination(el, actual, totalPaginas, onGo) {
  if (totalPaginas <= 1) { el.innerHTML = ''; return; }
  const b = (p, txt, dis, label) =>
    `<button class="btn btn-sm" data-page="${p}" ${dis ? 'disabled' : ''} aria-label="${label}">${txt}</button>`;
  el.innerHTML =
    b(1, '« Primera', actual === 1, 'Primera página') +
    b(actual - 1, '‹ Anterior', actual === 1, 'Página anterior') +
    `<span class="page-info">${actual} / ${totalPaginas}</span>` +
    b(actual + 1, 'Siguiente ›', actual === totalPaginas, 'Página siguiente') +
    b(totalPaginas, 'Última »', actual === totalPaginas, 'Última página');
  el.onclick = e => {
    const btn = e.target.closest('button[data-page]');
    if (btn && !btn.disabled) onGo(parseInt(btn.dataset.page, 10));
  };
}

/* ---------- Tooltip de gráficas ---------- */
/* Un solo tooltip para toda la página. El texto entra con textContent (los nombres de
   categorías/fuentes vienen de datos externos). Valor primero, etiqueta después. */
const Tip = (() => {
  let el = null;
  function asegurar() {
    if (!el) {
      el = document.createElement('div');
      el.className = 'viz-tip'; el.setAttribute('role', 'tooltip');
      document.body.appendChild(el);
    }
    return el;
  }
  function show(x, y, valor, etiqueta) {
    const t = asegurar();
    t.textContent = '';
    const v = document.createElement('span'); v.className = 'tip-val'; v.textContent = valor;
    t.appendChild(v);
    if (etiqueta) t.appendChild(document.createTextNode(etiqueta));
    const w = t.offsetWidth || 200, h = t.offsetHeight || 40;
    let left = x + 14, top = y - h - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 16;
    t.style.left = left + 'px'; t.style.top = top + 'px';
    t.classList.add('show');
  }
  function hide() { if (el) el.classList.remove('show'); }
  /* Engancha el tooltip a los elementos [data-tip-val] dentro de root (hover y foco). */
  function bind(root) {
    root.querySelectorAll('[data-tip-val]').forEach(n => {
      const mostrar = e => {
        const r = n.getBoundingClientRect();
        const x = e && e.clientX != null && e.type !== 'focus' ? e.clientX : r.left + r.width / 2;
        const y = e && e.clientY != null && e.type !== 'focus' ? e.clientY : r.top;
        show(x, y, n.dataset.tipVal, n.dataset.tipLbl || '');
      };
      n.addEventListener('pointermove', mostrar);
      n.addEventListener('focus', mostrar);
      n.addEventListener('pointerleave', hide);
      n.addEventListener('blur', hide);
    });
  }
  return { show, hide, bind };
})();

/* ---------- Gráficas de barras (una serie, un color) ---------- */
/* items: [{label, n, value?}] · opts: {total, clase, onClick(value), vacio} */
function renderBarList(el, items, opts) {
  opts = opts || {};
  if (!items || !items.length) {
    el.innerHTML = `<div class="chart-empty">${escHtml(opts.vacio || 'Sin datos todavía.')}</div>`;
    return;
  }
  const max = Math.max(...items.map(i => i.n), 1);
  const tag = opts.onClick ? 'button' : 'div';
  el.className = 'bar-list' + (opts.clase ? ' ' + opts.clase : '');
  el.innerHTML = items.map(i => {
    const pct = opts.total ? ` · ${Math.round(i.n / opts.total * 100)} % del total` : '';
    const attrs = opts.onClick ? `type="button" data-value="${escHtml(i.value ?? i.label)}" aria-label="${escHtml(i.label)}: ${i.n}. Filtrar"` : '';
    return `<${tag} class="bar-row" ${attrs} data-tip-val="${escHtml(fmtNum(i.n))}" data-tip-lbl="${escHtml(i.label + pct)}">
        <span class="bar-label">${escHtml(i.label)}</span>
        <span class="bar-cell"><span class="bar-fill" style="width:${Math.max(1, Math.round(i.n / max * 88))}%"></span><span class="bar-val">${fmtNum(i.n)}</span></span>
      </${tag}>`;
  }).join('');
  if (opts.onClick) el.onclick = e => { const b = e.target.closest('.bar-row'); if (b) opts.onClick(b.dataset.value); };
  Tip.bind(el);
}

/* ---------- Tema claro / oscuro ---------- */
function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('tema', t); } catch (_) { /* navegación privada */ }
  const b = document.getElementById('theme-toggle');
  if (b) b.setAttribute('aria-label', t === 'light' ? 'Cambiar a tema oscuro' : 'Cambiar a tema claro');
}
function toggleTheme() {
  setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
}

/* ---------- Parámetros de la URL (estado compartible de filtros) ---------- */
function leerParams() { return new URLSearchParams(window.location.search); }
function escribirParams(params) {
  const q = params.toString();
  history.replaceState(null, '', window.location.pathname + (q ? '?' + q : ''));
}

/* ---------- Arranque común ---------- */
document.addEventListener('DOMContentLoaded', () => {
  mountIcons();
  const tt = document.getElementById('theme-toggle');
  if (tt) {
    tt.addEventListener('click', toggleTheme);
    setTheme(document.documentElement.getAttribute('data-theme') || 'dark');
  }
  // "/" enfoca el buscador de la página (como en GitHub o Gmail).
  document.addEventListener('keydown', e => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
    const s = document.querySelector('[data-search]');
    if (s) { e.preventDefault(); s.focus(); s.select(); }
  });
});
