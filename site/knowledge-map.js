// Progressive, keyboard-accessible exploration of explicit Notion relationships.
// The original directory remains usable even when JavaScript is unavailable.
(() => {
  const svg = document.getElementById('map-visual');
  const input = document.getElementById('map-search');
  const filter = document.getElementById('map-type');
  const listing = document.getElementById('map-neighbor-list');
  const current = document.getElementById('map-current');
  const count = document.getElementById('map-count');
  const open = document.getElementById('map-open');
  const namespace = 'http://www.w3.org/2000/svg';
  const colors = {person: '#af7a53', topic: '#638b7b', history: '#8d85b7'};
  let selected = '';
  let graph = null;
  let adjacency = new Map();
  const make = (tag, attrs = {}, text = '') => {
    const node = document.createElementNS(namespace, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  };
  function choose(id, push = true) {
    const node = graph?.nodes.find(item => item.id === id);
    if (!node) return;
    selected = node.id;
    current.textContent = node.label;
    open.href = node.url;
    if (push) history.replaceState(null, '', '#node-' + node.id);
    render();
  }
  const neighborsOf = id => [...(adjacency.get(id) || new Set())]
    .map(key => graph.nodes.find(node => node.id === key))
    .filter(Boolean)
    .sort((a, b) => a.label.localeCompare(b.label, 'ru'));
  function render() {
    const node = graph.nodes.find(item => item.id === selected);
    if (!node) return;
    const neighbors = neighborsOf(selected);
    count.textContent = '(' + neighbors.length + ')';
    listing.replaceChildren();
    const visible = neighbors.slice(0, 18);
    svg.replaceChildren(make('title', {}, 'Связи: ' + node.label),
      make('desc', {}, 'Вокруг выбранного узла расположены связанные статьи. Их полный список есть справа.'));
    const centerX = 450, centerY = 275;
    visible.forEach((other, index) => {
      const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(visible.length, 1);
      const radiusX = visible.length < 5 ? 275 : 355;
      const radiusY = visible.length < 5 ? 205 : 224;
      const x = centerX + radiusX * Math.cos(angle);
      const y = centerY + radiusY * Math.sin(angle);
      svg.append(make('line', {x1: centerX, y1: centerY, x2: x, y2: y, class: 'map-edge'}));
      const group = make('g', {class: 'map-node map-node-small', tabindex: '0',
        role: 'button', 'aria-label': 'Показать связи: ' + other.label});
      group.append(make('circle', {cx: x, cy: y, r: 24, fill: colors[other.type]}),
        make('text', {x, y: y + 39, 'text-anchor': 'middle'}, other.label.length > 20 ? other.label.slice(0, 19) + '…' : other.label));
      const activate = () => choose(other.id);
      group.addEventListener('click', activate);
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
      });
      svg.append(group);
    });
    const center = make('g', {class: 'map-node map-node-center'});
    center.append(make('circle', {cx: centerX, cy: centerY, r: 49, fill: colors[node.type]}),
      make('text', {x: centerX, y: centerY + 69, 'text-anchor': 'middle'},
        node.label.length > 27 ? node.label.slice(0, 26) + '…' : node.label));
    svg.append(center);
    for (const other of neighbors) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = other.label;
      button.addEventListener('click', () => choose(other.id));
      const label = document.createElement('small');
      label.textContent = {person:'Личности',topic:'Темы',history:'История'}[other.type];
      item.append(button, label); listing.append(item);
    }
    if (!neighbors.length) {
      const item = document.createElement('li');
      item.textContent = 'В исходных материалах нет явных ссылок на другие опубликованные записи.';
      listing.append(item);
    }
    if (neighbors.length > visible.length) {
      const note = make('text', {x: 450, y: 535, 'text-anchor': 'middle', class: 'map-overflow'},
        'На схеме 18 из ' + neighbors.length + ' связей; полный список справа');
      svg.append(note);
    }
  }
  function search() {
    const query = input.value.toLocaleLowerCase('ru').trim();
    const found = graph.nodes.filter(node => (filter.value === 'all' || node.type === filter.value) &&
      (!query || node.label.toLocaleLowerCase('ru').includes(query)));
    const directory = document.querySelector('.map-directory-section');
    directory.querySelectorAll('li').forEach(item => {
      const a = item.querySelector('a');
      if (!a) return;
      const label = a.textContent.toLocaleLowerCase('ru');
      const type = a.closest('details').dataset.type;
      item.hidden = (query && !label.includes(query)) || (filter.value !== 'all' && filter.value !== type);
    });
    if (found.length) choose(found[0].id, false);
    else {
      current.textContent = 'Совпадений не найдено';
      listing.replaceChildren();
      count.textContent = '(0)';
      svg.replaceChildren(make('text', {x: 450, y: 275, 'text-anchor': 'middle'}, 'Нет результатов'));
    }
  }
  document.querySelectorAll('.map-directory').forEach((section, index) => {
    section.dataset.type = ['topic', 'history', 'person'][index];
  });
  fetch('knowledge-map.json').then(response => {
    if (!response.ok) throw new Error('Unable to load graph');
    return response.json();
  }).then(data => {
    graph = data;
    for (const n of data.nodes) adjacency.set(n.id, new Set());
    for (const e of data.edges) {
      adjacency.get(e.source)?.add(e.target);
      adjacency.get(e.target)?.add(e.source);
    }
    const hash = location.hash.match(/^#node-([a-f0-9]{32})$/);
    const preferred = hash && data.nodes.some(n => n.id === hash[1]) ? hash[1]
      : [...data.nodes].sort((a, b) => (adjacency.get(b.id)?.size || 0) - (adjacency.get(a.id)?.size || 0))[0]?.id;
    if (preferred) choose(preferred, false);
    input.addEventListener('input', search);
    filter.addEventListener('change', search);
    window.addEventListener('hashchange', () => {
      const id = location.hash.match(/^#node-([a-f0-9]{32})$/)?.[1];
      if (id) choose(id, false);
    });
  }).catch(() => {
    current.textContent = 'Не удалось загрузить интерактивную карту';
    svg.replaceChildren(make('text', {x:450,y:275,'text-anchor':'middle'}, 'Доступен каталог ссылок ниже'));
  });
})();
