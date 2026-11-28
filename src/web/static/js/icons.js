/* ============================================================
   AUTO SERE — icons.js
   Ícones SVG inline (sem dependência de CDN externo).
   Uso: ICONS.nome("classe-opcional") retorna a string do <svg>.
   Ou use o helper icon(el, "nome") pra injetar dentro de um elemento.
   ============================================================ */

const ICONS = {
  // ---- Navegação / estrutura ----
  dashboard: (c = "") => svg(c, `<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>`),
  users: (c = "") => svg(c, `<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c0-3.6 2.5-6 5.5-6s5.5 2.4 5.5 6"/><circle cx="17.5" cy="8.5" r="2.6"/><path d="M15.8 14.2c2.6.2 4.7 2.4 4.7 5.8"/>`),
  student: (c = "") => svg(c, `<path d="M3 9.5 12 5l9 4.5-9 4.5-9-4.5Z"/><path d="M7 11.6V16c0 1.7 2.2 3 5 3s5-1.3 5-3v-4.4"/><path d="M20 9.5v5"/>`),
  clipboard: (c = "") => svg(c, `<rect x="5" y="4" width="14" height="17" rx="2"/><rect x="9" y="2.5" width="6" height="3.5" rx="1"/><path d="M8.5 11h7M8.5 14.5h7M8.5 18h4.5"/>`),
  badge: (c = "") => svg(c, `<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="10" r="2.6"/><path d="M8 17c0-2.2 1.8-3.5 4-3.5s4 1.3 4 3.5"/>`),
  ageCut: (c = "") => svg(c, `<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9h17M9 9v11M3.5 14.5h17"/><path d="M13 12h5"/>`),
  automation: (c = "") => svg(c, `<circle cx="12" cy="12" r="3"/><path d="M12 3v2.4M12 18.6V21M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M3 12h2.4M18.6 12H21M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7"/>`),
  settings: (c = "") => svg(c, `<circle cx="12" cy="12" r="3"/><path d="M19.4 13a7.6 7.6 0 0 0 0-2l2-1.5-2-3.4-2.3.9a7.4 7.4 0 0 0-1.7-1L15 3.5h-4l-.4 2.4a7.4 7.4 0 0 0-1.7 1l-2.3-.9-2 3.4L6.6 11a7.6 7.6 0 0 0 0 2l-2 1.5 2 3.4 2.3-.9c.5.4 1.1.8 1.7 1l.4 2.4h4l.4-2.4c.6-.2 1.2-.6 1.7-1l2.3.9 2-3.4-2-1.5Z"/>`),
  rocket: (c = "") => svg(c, `<path d="M12 15c3.5-3.5 5-8 4.3-11.3C12.9 3 8.5 4.5 5 8c-1 1-1.5 2-1.7 3l-1.8 1.8 3.7 3.7L7 14.7c1-.2 2-.7 3-1.7Z"/><circle cx="14.5" cy="9.5" r="1.6"/><path d="M8 16c-2.2.4-3.5 2-4 5 3-.5 4.6-1.8 5-4"/>`),
  help: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="M9.2 9.2a2.8 2.8 0 1 1 4 2.5c-.9.5-1.2 1-1.2 2"/><path d="M12 17h.01"/>`),

  // ---- Automações (uma por item do menu) ----
  folderPlus: (c = "") => svg(c, `<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2.5h8A1.5 1.5 0 0 1 20.5 10v8A1.5 1.5 0 0 1 19 19.5H4.5A1.5 1.5 0 0 1 3 18Z"/><path d="M12 12v5M9.5 14.5h5"/>`),
  fileSearch: (c = "") => svg(c, `<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M13 3v5h5"/><circle cx="11" cy="15" r="2.2"/><path d="M12.7 16.7 14.5 18.5"/>`),
  files: (c = "") => svg(c, `<path d="M8 3h6l4 4v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M6 7H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h9"/>`),
  compare: (c = "") => svg(c, `<path d="M8 4 5 7l3 3"/><path d="M5 7h9a3 3 0 0 1 3 3v1"/><path d="M16 20l3-3-3-3"/><path d="M19 17h-9a3 3 0 0 1-3-3v-1"/>`),
  mapPin: (c = "") => svg(c, `<path d="M12 21s7-6.5 7-11.5A7 7 0 0 0 5 9.5C5 14.5 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.4"/>`),
  heart: (c = "") => svg(c, `<path d="M12 20s-7-4.4-9.3-9C1.3 7.8 3 4.5 6.5 4.5c2 0 3.3 1 4 2.1.7-1.1 2-2.1 4-2.1 3.5 0 5.2 3.3 3.8 6.5C19 15.6 12 20 12 20Z"/><path d="M9 10h1.6L12 8l1.6 4L15 9.5h1"/>`),
  transfer: (c = "") => svg(c, `<path d="M4 8h13M13 4l4 4-4 4"/><path d="M20 16H7M11 20l-4-4 4-4"/>`),
  certificate: (c = "") => svg(c, `<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M7 8h10M7 11.5h6"/><path d="M9 20.5 12 18l3 2.5v-4.7H9Z"/>`),
  zip: (c = "") => svg(c, `<path d="M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M11 3v2h2V3M11 7v2h2V7M11 11v2h2v-2"/><circle cx="12" cy="16.5" r="2"/>`),
  mail: (c = "") => svg(c, `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>`),
  clock: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.5 2"/>`),
  database: (c = "") => svg(c, `<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5V12c0 1.7 3.6 3 8 3s8-1.3 8-3V5.5"/><path d="M4 12v6.5c0 1.7 3.6 3 8 3s8-1.3 8-3V12"/>`),
  send: (c = "") => svg(c, `<path d="m3 11 18-8-8 18-2.5-7.5L3 11Z"/>`),
  scale: (c = "") => svg(c, `<path d="M12 3v18M7 21h10"/><path d="m6 7 5-2 5 2"/><path d="M3 7h6M15 7h6"/><path d="M3 7l-2 5a2.6 2.6 0 0 0 4.9 0Z"/><path d="M21 7l-2 5a2.6 2.6 0 0 0 4.9 0Z"/>`),
  map: (c = "") => svg(c, `<path d="M9 4 3 6.5v13L9 17l6 2.5 6-2.5v-13L15 6.5 9 4Z"/><path d="M9 4v13M15 6.5v13"/>`),
  shieldLock: (c = "") => svg(c, `<path d="M12 3 5 6v6c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6Z"/><rect x="9.5" y="11" width="5" height="4.3" rx="1"/><path d="M10.3 11V9.5a1.7 1.7 0 0 1 3.4 0V11"/>`),
  refresh: (c = "") => svg(c, `<path d="M4 12a8 8 0 0 1 14-5.2M20 12a8 8 0 0 1-14 5.2"/><path d="M18 3v4.5h-4.5M6 21v-4.5h4.5"/>`),
  bolt: (c = "") => svg(c, `<path d="M12 2 4 14h6l-1 8 9-12h-6l1-8Z"/>`),

  // ---- Config / perfil / genero ----
  lock: (c = "") => svg(c, `<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>`),
  key: (c = "") => svg(c, `<circle cx="8" cy="15" r="4"/><path d="M11 12 19 4M16 7l2.5 2.5M13.3 9.7 15.5 12"/>`),
  unlock: (c = "") => svg(c, `<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 7.6-1.7"/>`),
  ban: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>`),
  trash: (c = "") => svg(c, `<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 12.2A1.8 1.8 0 0 0 8.8 21h6.4a1.8 1.8 0 0 0 1.8-1.8L18 7"/><path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>`),
  palette: (c = "") => svg(c, `<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-1 1.2-2-.5-.9.1-2 1.2-2H16a5 5 0 0 0 5-5c0-5-4-9-9-9Z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="9.5" cy="7.2" r="1.2"/><circle cx="14.5" cy="7.2" r="1.2"/><circle cx="16.5" cy="11" r="1.2"/>`),
  userCircle: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3"/><path d="M6.2 18.5c1-2.5 3.2-4 5.8-4s4.8 1.5 5.8 4"/>`),
  userPlain: (c = "") => svg(c, `<circle cx="12" cy="8" r="3.4"/><path d="M5.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/>`),
  info: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>`),
  book: (c = "") => svg(c, `<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H12v18H6.5A2.5 2.5 0 0 0 4 23.5Z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H12v18h5.5a2.5 2.5 0 0 1 2.5 2.5"/>`),
  headset: (c = "") => svg(c, `<path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="3" y="13" width="4" height="6" rx="1.5"/><rect x="17" y="13" width="4" height="6" rx="1.5"/><path d="M20 19v1a3 3 0 0 1-3 3h-3"/>`),
  versions: (c = "") => svg(c, `<rect x="7" y="7" width="14" height="14" rx="2"/><path d="M4 14V5a2 2 0 0 1 2-2h9"/>`),

  // ---- Ações / genéricos ----
  bell: (c = "") => svg(c, `<path d="M6 10a6 6 0 0 1 12 0c0 4.5 1.5 6 2 6.5H4C4.5 16 6 14.5 6 10Z"/><path d="M10 19.5a2.2 2.2 0 0 0 4 0"/>`),
  calendar: (c = "") => svg(c, `<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="M8 14h.01M12 14h.01M16 14h.01M8 17.2h.01M12 17.2h.01"/>`),
  chevronLeft: (c = "") => svg(c, `<path d="m15 6-6 6 6 6"/>`),
  chevronRight: (c = "") => svg(c, `<path d="m9 6 6 6-6 6"/>`),
  chevronDown: (c = "") => svg(c, `<path d="m6 9 6 6 6-6"/>`),
  arrowRight: (c = "") => svg(c, `<path d="M4 12h15M13 6l6 6-6 6"/>`),
  arrowLeft: (c = "") => svg(c, `<path d="M20 12H5M11 18l-6-6 6-6"/>`),
  refreshSmall: (c = "") => svg(c, `<path d="M3.5 10.5A6.5 6.5 0 0 1 15 6.3M17 3.5v3.8h-3.8"/><path d="M20.5 13.5A6.5 6.5 0 0 1 9 17.7M7 20.5v-3.8h3.8"/>`),
  download: (c = "") => svg(c, `<path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 19h14"/>`),
  search: (c = "") => svg(c, `<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.3-4.3"/>`),
  eye: (c = "") => svg(c, `<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="2.6"/>`),
  pencil: (c = "") => svg(c, `<path d="M4 20.5 4.7 17 16 5.7a2 2 0 0 1 2.8 0l.5.5a2 2 0 0 1 0 2.8L8 20.3l-3.5.7Z"/><path d="m14 7.5 2.5 2.5"/>`),
  folder: (c = "") => svg(c, `<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2.5h8A1.5 1.5 0 0 1 20.5 10v8A1.5 1.5 0 0 1 19 19.5H4.5A1.5 1.5 0 0 1 3 18Z"/>`),
  check: (c = "") => svg(c, `<path d="M4 12.5 9.5 18 20 6"/>`),
  circleCheck: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="m8.3 12.5 2.6 2.6L16 9.8"/>`),
  play: (c = "") => svg(c, `<path d="M7 4.5v15l13-7.5Z"/>`),
  loader: (c = "") => svg(c, `<path d="M12 3v3M12 18v3M4.2 4.2l2.2 2.2M17.6 17.6l2.2 2.2M3 12h3M18 12h3M4.2 19.8l2.2-2.2M17.6 6.4l2.2-2.2" opacity=".9"/>`),
  alertFile: (c = "") => svg(c, `<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M13 3v5h5"/><path d="M12 12v3.2M12 17.7h.01"/>`),
  mapPinOff: (c = "") => svg(c, `<path d="M12 21s7-6.5 7-11.5a6.9 6.9 0 0 0-1.1-3.8"/><path d="M8.3 5.3A7 7 0 0 0 5 9.5C5 14.5 12 21 12 21"/><path d="M3 3l18 18"/><circle cx="12" cy="9.5" r="2.4"/>`),
  man: (c = "") => svg(c, `<circle cx="12" cy="7" r="3.4"/><path d="M6.5 20.5c0-3.6 2.5-6 5.5-6s5.5 2.4 5.5 6"/>`),
  woman: (c = "") => svg(c, `<circle cx="12" cy="6.5" r="3.2"/><path d="M12 9.7v6.3M9 13.3h6M9.6 20.5 12 16l2.4 4.5"/>`),
  school: (c = "") => svg(c, `<path d="m12 3 9 4.5-9 4.5-9-4.5Z"/><path d="M6 10v5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5"/><path d="M21 8v6.5"/>`),
  moon: (c = "") => svg(c, `<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4 7 7 0 0 0 20 14.5Z"/>`),
  sun: (c = "") => svg(c, `<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M4.2 4.2l1.7 1.7M18.1 18.1l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.2 19.8l1.7-1.7M18.1 5.9l1.7-1.7"/>`),
  contrast: (c = "") => svg(c, `<circle cx="12" cy="12" r="9"/><path d="M12 3v18A9 9 0 0 0 12 3Z" fill="currentColor" stroke="none"/>`),
  whatsapp: (c = "") => svg(c, `<path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4.1A8 8 0 1 1 20 11.5z"/><path d="M9 8.8c.3 2.6 2.6 4.9 5.2 5.2l1-1.2-1.8-1-.8.6a3.6 3.6 0 0 1-1.7-1.7l.6-.8-1-1.8z"/>`),
  bars: (c = "") => svg(c, `<path d="M4 6.5h16M4 12h16M4 17.5h16"/>`),
};

/** Monta a tag <svg> com o path informado. */
function svg(extraClass, inner) {
  return `<svg class="icon ${extraClass}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
}

/** Substitui o innerHTML de um elemento pelo ícone nomeado. */
function icon(name, extraClass = "") {
  return (ICONS[name] && ICONS[name](extraClass)) || "";
}

/** Aplica ícones em todo elemento [data-icon] presente no DOM (chamar após render). */
function aplicarIconesDOM(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.dataset.iconApplied) return;
    el.innerHTML = icon(el.dataset.icon, el.dataset.iconClass || "");
    el.dataset.iconApplied = "1";
  });
}

/**
 * Observa mudanças no DOM e aplica ícones automaticamente em qualquer
 * elemento [data-icon] inserido dinamicamente (cards, tabelas, wizard etc.),
 * sem precisar chamar aplicarIconesDOM() manualmente em cada função de render.
 */
function iniciarObservadorIcones(root = document.body) {
  aplicarIconesDOM(root);
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.hasAttribute && node.hasAttribute("data-icon")) {
          aplicarIconesDOM(node.parentElement || root);
        }
        if (node.querySelector && node.querySelector("[data-icon]")) {
          aplicarIconesDOM(node);
        }
      });
    }
  });
  observer.observe(root, { childList: true, subtree: true });
  return observer;
}
