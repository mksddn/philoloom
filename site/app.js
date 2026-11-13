// A URL override is for previewing themes; otherwise follow system changes.
const systemColorScheme = matchMedia('(prefers-color-scheme: light)');
const requestedTheme = new URLSearchParams(location.search).get('theme');
const themeOverride = ['light', 'dark'].includes(requestedTheme) ? requestedTheme : null;
const syncTheme = () => {
  const light = themeOverride ? themeOverride === 'light' : systemColorScheme.matches;
  document.documentElement.dataset.theme = light ? 'light' : 'dark';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', light ? '#f5f2eb' : '#111110');
};
syncTheme();
systemColorScheme.addEventListener('change', syncTheme);

const dialog = document.querySelector('#search-dialog');
const query = document.querySelector('#query');
const results = document.querySelector('#results');
const status = document.querySelector('#search-status');
let entries;
let loading;
let revision = 0;
async function search() {
  const current = ++revision;
  results.replaceChildren();
  const text = query.value.trim().toLocaleLowerCase('ru');
  if (!text) { status.textContent = 'Введи запрос для поиска по всем страницам.'; return; }
  status.textContent = 'Ищем…';
  try {
    if (!entries) {
      loading ??= fetch('search.json').then(response => {
        if (!response.ok) throw new Error('Search unavailable');
        return response.json();
      });
      entries = await loading;
    }
    if (current !== revision) return;
    const words = text.split(/\s+/);
    const found = entries.filter(entry => words.every(word => (entry.title + ' ' + entry.text).toLocaleLowerCase('ru').includes(word)));
    found.sort((a,b) => Number(b.title.toLocaleLowerCase('ru').includes(text)) - Number(a.title.toLocaleLowerCase('ru').includes(text)));
    status.textContent = found.length ? `Найдено страниц: ${found.length}` : 'Ничего не найдено.';
    for (const entry of found) {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.href = entry.url;
      link.textContent = entry.title;
      const group = document.createElement('small');
      group.textContent = entry.group || 'Главная';
      link.append(group); li.append(link); results.append(li);
    }
  } catch {
    if (current !== revision) return;
    loading = undefined;
    status.textContent = 'Не удалось загрузить поиск. Попробуй ещё раз.';
  }
}
document.querySelector('#search-open').addEventListener('click', () => { dialog.showModal(); query.focus(); search(); });
query.addEventListener('input', search);
dialog.addEventListener('close', () => { revision++; });
dialog.addEventListener('keydown', event => {
  // Chromium can consume Escape to clear a focused type=search input.
  // For an open modal, Escape must close the dialog consistently.
  if (event.key === 'Escape') { event.preventDefault(); dialog.close(); }
});
dialog.addEventListener('click', event => {
  // Native modal backdrops dispatch clicks on the dialog itself.
  if (event.target !== dialog) return;
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
});


const resourceDialog = document.querySelector('#resource-dialog');
if (resourceDialog) {
  const resourceTitle = document.querySelector('#resource-title');
  const resourceViews = [...resourceDialog.querySelectorAll('.resource-list')];
  document.querySelectorAll('[data-resource-open]').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const selected = trigger.dataset.resourceOpen;
      resourceViews.forEach(view => { view.hidden = view.id !== 'resource-' + selected; });
      resourceTitle.textContent = selected === 'watch' ? 'Что посмотреть' : 'Что почитать';
      resourceDialog.showModal();
    });
  });
  document.querySelector('#resource-close').addEventListener('click', () => resourceDialog.close());
  resourceDialog.addEventListener('click', event => {
    if (event.target !== resourceDialog) return;
    const rect = resourceDialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) resourceDialog.close();
  });
}

const panel = document.querySelector('#page-panel');
const panelContent = document.querySelector('#panel-content');
const panelPathBar = document.querySelector('#panel-path');
const panelFull = document.querySelector('#panel-full');
const panelBack = document.querySelector('#panel-back');
const panelNext = document.querySelector('#panel-next');
const pageCache = new Map();
const baseTitle = document.title;
let panelRevision = 0;
let panelOpener;
let panelPath;
let panelDepth = 0;
let requestController;
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

async function catalog() {
  if (!entries) {
    loading ??= fetch('search.json').then(response => {
      if (!response.ok) throw new Error('Catalog unavailable');
      return response.json();
    }).catch(error => { loading = undefined; throw error; });
    entries = await loading;
  }
  return entries;
}
function pagePath(url) {
  const target = new URL(url, location.href);
  const currentDirectory = new URL('.', location.href);
  if (target.origin !== location.origin || new URL('.', target).pathname !== currentDirectory.pathname) return null;
  const name = target.pathname.split('/').pop();
  return /^[a-f0-9]{32}\.html$/.test(name) && !target.hash ? name : null;
}
function panelLocation(path) {
  const url = new URL(location.href);
  if (path) url.searchParams.set('peek', path);
  else url.searchParams.delete('peek');
  return url;
}
async function displayPanel(path) {
  const current = ++panelRevision;
  requestController?.abort();
  requestController = new AbortController();
  panel.classList.remove('closing');
  panelPath = path;
  panel.removeAttribute('aria-labelledby');
  panelFull.href = path;
  panelBack.disabled = panelDepth < 2;
  panelNext.disabled = true;
  if (!panel.open) {
    panelOpener = document.activeElement;
    panel.classList.remove('closing');
    panel.showModal();
    document.documentElement.classList.add('panel-open');
  }
  panelPathBar.replaceChildren();
  panelContent.textContent = 'Загружаем страницу…';
  panelContent.setAttribute('aria-busy', 'true');
  try {
    let source = pageCache.get(path);
    if (!source) {
      const response = await fetch(path, {signal: requestController.signal});
      if (!response.ok) throw new Error('Page unavailable');
      source = await response.text();
      pageCache.set(path, source);
    }
    if (current !== panelRevision) return;
    const parsed = new DOMParser().parseFromString(source, 'text/html');
    const main = parsed.querySelector('main');
    if (!main?.querySelector('h1')) throw new Error('Invalid page');
    const breadcrumbsNode = main.querySelector('.back');
    panelPathBar.replaceChildren(...(breadcrumbsNode ? [breadcrumbsNode.cloneNode(true)] : []));
    // The panel has its own navigation. Do not copy a second, inert search button.
    main.querySelector('.detail-navigation')?.remove();
    panelContent.replaceChildren(...Array.from(main.childNodes, node => document.importNode(node, true)));
    const heading = panelContent.querySelector('h1');
    heading.id = 'panel-title';
    heading.tabIndex = -1;
    panel.setAttribute('aria-labelledby', 'panel-title');
    document.title = `${heading.textContent} · philoloom`;
    panelContent.scrollTop = 0;
    setupContent(panelContent);
    heading.focus({preventScroll:true});
    const data = await catalog();
    if (current !== panelRevision) return;
    const entry = data.find(item => item.url === path);
    const siblings = data.filter(item => item.group === entry?.group);
    const index = siblings.findIndex(item => item.url === path);
    panelNext.dataset.path = siblings[index + 1]?.url || '';
    panelNext.disabled = !panelNext.dataset.path;
  } catch (error) {
    if (current !== panelRevision || error.name === 'AbortError') return;
    panelContent.replaceChildren();
    const message = document.createElement('p');
    message.textContent = 'Не удалось загрузить страницу.';
    const retry = document.createElement('button');
    retry.textContent = 'Попробовать снова';
    retry.addEventListener('click', () => displayPanel(path));
    panelContent.append(message, retry);
    panel.removeAttribute('aria-labelledby');
  } finally {
    if (current === panelRevision) panelContent.removeAttribute('aria-busy');
  }
}
function openPanel(path) {
  if (dialog.open) dialog.close();
  panelDepth += 1;
  history.pushState({...history.state, philoDepth:panelDepth}, '', panelLocation(path));
  displayPanel(path);
}
function closePanel() {
  if (panelDepth > 0) history.go(-panelDepth);
  else {
    history.replaceState(history.state, '', panelLocation(null));
    hidePanel();
  }
}
async function hidePanel() {
  ++panelRevision;
  requestController?.abort();
  if (!panel.open) return;
  panel.classList.add('closing');
  if (!reducedMotion()) {
    await Promise.allSettled(panel.getAnimations().map(animation => animation.finished));
  }
  // A forward navigation may have reopened the panel during its exit animation.
  if (new URL(location.href).searchParams.has('peek')) { panel.classList.remove('closing'); return; }
  panel.close();
  panel.classList.remove('closing');
  document.documentElement.classList.remove('panel-open');
  document.title = baseTitle;
  panelOpener?.focus({preventScroll:true});
}
document.querySelector('#panel-close').addEventListener('click', closePanel);
panelBack.addEventListener('click', () => history.back());
panelNext.addEventListener('click', () => { if (panelNext.dataset.path) openPanel(panelNext.dataset.path); });
panel.addEventListener('cancel', event => { event.preventDefault(); closePanel(); });
panel.addEventListener('click', event => { if (event.target === panel) closePanel(); });
window.addEventListener('popstate', () => {
  panelDepth = history.state?.philoDepth || 0;
  const path = new URL(location.href).searchParams.get('peek');
  if (path && pagePath(path)) displayPanel(path);
  else hidePanel();
});
document.addEventListener('click', event => {
  const link = event.target.closest('a[href]');
  if (!link || link.hasAttribute('data-full-page') || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
  const path = pagePath(link.href);
  if (!path) return;
  event.preventDefault();
  openPanel(path);
});

const imageDialog = document.querySelector('#image-dialog');
const fullImage = document.querySelector('#image-full');
document.querySelector('#image-close').addEventListener('click', () => imageDialog.close());
imageDialog.addEventListener('click', event => { if (event.target === imageDialog) imageDialog.close(); });
function showImage(image) {
  fullImage.src = image.dataset.fullSrc || image.currentSrc || image.src;
  fullImage.alt = image.alt;
  imageDialog.showModal();
}
function setupContent(root) {
  root.querySelectorAll('img').forEach(image => {
    const failed = () => {
      if (image.closest('article') && !image.closest('a')) {
        const fallback = image.closest('article').querySelector('.bookmark-media img');
        if (fallback && fallback.src !== image.src) {
          image.addEventListener('error', () => { image.hidden = true; }, {once:true});
          image.src = fallback.src;
          return;
        }
      }
      if (image.closest('.bookmark-media')) image.closest('.bookmark-media').hidden = true;
      else if (image.classList.contains('card-cover')) image.hidden = true;
    };
    image.addEventListener('error', failed, {once:true});
    if (image.complete && !image.naturalWidth) failed();
    if (image.closest('article') && !image.closest('a')) {
      image.tabIndex = 0;
      image.setAttribute('role','button');
      image.setAttribute('aria-label','Увеличить изображение');
      image.addEventListener('click', () => showImage(image));
      image.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showImage(image); }
      });
    }
  });
  root.querySelectorAll('details').forEach(details => {
    if (details.dataset.enhanced) return;
    details.dataset.enhanced = 'true';
    const summary = details.querySelector('summary');
    const content = document.createElement('div');
    content.className = 'toggle-content';
    while (summary.nextSibling) content.append(summary.nextSibling);
    details.append(content);
    let animation;
    summary.addEventListener('click', event => {
      if (reducedMotion()) return;
      event.preventDefault();
      if (animation) return;
      const closing = details.open;
      details.open = true;
      animation = content.animate([{height:closing ? `${content.scrollHeight}px` : '0px',opacity:closing ? 1:0}, {height:closing ? '0px':`${content.scrollHeight}px`,opacity:closing ? 0:1}], {duration:160,easing:'ease-out'});
      animation.onfinish = () => { details.open = !closing; animation = null; };
    });
  });
}
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    if (!dialog.open) { dialog.showModal(); query.focus(); search(); }
  }
});
setupContent(document);
const initialPeek = new URL(location.href).searchParams.get('peek');
if (initialPeek && pagePath(initialPeek)) {
  panelDepth = 0;
  history.replaceState({...history.state, philoDepth:0}, '');
  displayPanel(initialPeek);
}

// Preserve real links and all section content in static HTML; enhance navigation in the browser.
const sectionNav = document.querySelector('.section-nav');
const sectionTabs = sectionNav ? [...sectionNav.querySelectorAll('a')] : [];
const sections = [...document.querySelectorAll('.reference-section')];
function activateSection(id, focus = false) {
  const selected = sections.find(section => section.id === id) || sections[0];
  if (!selected) return;
  sections.forEach(section => { section.hidden = section !== selected; });
  sectionTabs.forEach(tab => {
    const active = tab.getAttribute('aria-controls') === selected.id;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  });
}
if (sectionNav) {
  sectionNav.setAttribute('role', 'tablist');
  sectionTabs.forEach((tab, index) => {
    const id = new URL(tab.href).hash.slice(1);
    tab.id = `section-tab-${index}`;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', id);
    const section = document.getElementById(id);
    section.setAttribute('role', 'tabpanel');
    section.setAttribute('aria-labelledby', tab.id);
    // Panels contain keyboard-focusable cards; do not add a giant focus ring to the panel.
    section.tabIndex = -1;
    tab.addEventListener('click', event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      const url = new URL(location.href);
      url.hash = id;
      history.replaceState(history.state, '', url);
      activateSection(id);
    });
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index+1) % sectionTabs.length;
      if (event.key === 'ArrowLeft') next = (index-1+sectionTabs.length) % sectionTabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = sectionTabs.length-1;
      if (next !== undefined) { event.preventDefault(); sectionTabs[next].click(); sectionTabs[next].focus(); }
    });
  });
  document.documentElement.classList.add('tabs-ready');
  activateSection(location.hash.slice(1));
  window.addEventListener('hashchange', () => activateSection(location.hash.slice(1)));
  window.addEventListener('popstate', () => activateSection(location.hash.slice(1)));
}
function selectView(section, view, remember = false) {
  const target = section.querySelector(`[data-view-content="${view}"]`);
  if (!target) return;
  section.querySelectorAll('[data-view]').forEach(control => control.setAttribute('aria-pressed', String(control.dataset.view === view)));
  section.querySelectorAll('[data-view-content]').forEach(content => { content.hidden = content !== target; });
  if (remember) {
    try { localStorage.setItem(`philoloom:view:${section.id}`, view); } catch { /* Storage may be disabled. */ }
  }
}
sections.forEach(section => {
  let saved;
  try { saved = localStorage.getItem(`philoloom:view:${section.id}`); } catch { /* Default views still work. */ }
  if (['gallery', 'list', 'table'].includes(saved)) selectView(section, saved);
});
document.querySelectorAll('.view-controls button').forEach(button => {
  button.addEventListener('click', () => selectView(button.closest('section'), button.dataset.view, true));
});
document.querySelectorAll('.column-sort').forEach(button => {
  button.addEventListener('click', () => {
    const table = button.closest('table');
    const heading = button.closest('th');
    const ascending = heading.getAttribute('aria-sort') !== 'ascending';
    const index = Number(button.dataset.column);
    const rows = [...table.tBodies[0].rows];
    rows.sort((a,b) => {
      const left = a.cells[index].textContent.trim();
      const right = b.cells[index].textContent.trim();
      const numeric = /^-?\d+$/.test(left) && /^-?\d+$/.test(right);
      const isDate = value => /^\d{2}\/\d{2}\/\d{4}$/.test(value);
      const timestamp = value => value.split('/').reverse().join('');
      const comparison = numeric ? Number(left)-Number(right) :
        isDate(left) && isDate(right) ? timestamp(left).localeCompare(timestamp(right)) :
        left.localeCompare(right,'ru',{numeric:true});
      return comparison * (ascending ? 1:-1);
    });
    table.querySelectorAll('th[aria-sort]').forEach(th => th.removeAttribute('aria-sort'));
    heading.setAttribute('aria-sort',ascending ? 'ascending':'descending');
    table.tBodies[0].append(...rows);
  });
});
