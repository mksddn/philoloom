// Interactive neighbourhood explorer, based solely on existing reference links.
(() => {
  const svg = document.getElementById('graph-svg');
  if (!svg) return;
  const form = document.getElementById('graph-form');
  const input = document.getElementById('graph-query');
  const datalist = document.getElementById('graph-suggestions');
  const groupFilter = document.getElementById('graph-group');
  const status = document.getElementById('graph-status');
  const list = document.getElementById('graph-list');
  const details = document.getElementById('graph-detail');
  const ns = 'http://www.w3.org/2000/svg';
  const type = {'Темы': 'topic', 'Личности': 'person', 'История философии': 'history'};
  const make = (tag, attrs = {}, text = '') => {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    el.textContent = text;
    return el;
  };
  const normalize = text => text.trim().toLocaleLowerCase('ru');
  let nodes, links, current;

  function select(id) {
    if (!nodes.has(id)) return;
    current = nodes.get(id);
    input.value = current.title;
    const url = new URL(location.href);
    url.searchParams.set('id', id);
    history.replaceState(history.state, '', url);
    draw();
  }
  function draw() {
    const connected = [...links.get(current.id)].map(id => nodes.get(id))
      .filter(node => !groupFilter.value || node.group === groupFilter.value)
      .sort((a, b) => a.title.localeCompare(b.title, 'ru'));
    const displayed = connected.slice(0, 12);
    status.textContent = current.title + ': ' + connected.length + ' связанных записей.' +
      (connected.length > 12 ? ' На схеме показаны первые 12, в списке — все.' : '');
    details.textContent = 'Выбрано: ' + current.title;
    list.replaceChildren();
    connected.forEach(node => {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.href = node.url;
      link.textContent = node.title + ' · ' + node.group;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'В центр';
      button.setAttribute('aria-label', 'Показать связи: ' + node.title);
      button.addEventListener('click', () => select(node.id));
      li.append(link, button);
      list.append(li);
    });
    if (connected.length === 0) {
      const li = document.createElement('li');
      li.textContent = 'Нет связей в выбранном разделе.';
      list.append(li);
    }
    svg.querySelectorAll('.map-generated').forEach(el => el.remove());
    const layer = make('g', {'class': 'map-generated'});
    const edgeGroup = make('g', {'class': 'graph-edges'});
    const nodeGroup = make('g', {'class': 'graph-nodes'});
    displayed.forEach((node, index) => {
      const angle = -Math.PI / 2 + 2 * Math.PI * index / displayed.length;
      const x = 500 + 355 * Math.cos(angle);
      const y = 330 + 240 * Math.sin(angle);
      edgeGroup.append(make('line', {x1: 500, y1: 330, x2: x, y2: y}));
      const item = make('g', {
        transform: 'translate(' + x + ' ' + y + ')',
        'class': 'graph-node graph-' + type[node.group],
        role: 'button', tabindex: '0',
        'aria-label': 'Показать связи: ' + node.title,
      });
      item.append(make('circle', {r: 36}));
      item.append(make('text', {y: 58, 'text-anchor': 'middle'},
        node.title.length > 26 ? node.title.slice(0, 24) + '…' : node.title));
      item.addEventListener('click', () => select(node.id));
      item.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select(node.id);
        }
      });
      nodeGroup.append(item);
    });
    const center = make('g', {'class': 'graph-center graph-' + type[current.group]});
    center.append(make('circle', {cx: 500, cy: 330, r: 70}));
    const words = current.title.split(' ');
    let rows = [], line = '';
    words.forEach(word => {
      if ((line + ' ' + word).trim().length > 16 && line) {
        rows.push(line);
        line = word;
      } else line += (line ? ' ' : '') + word;
    });
    if (line) rows.push(line);
    rows.slice(0, 3).forEach((part, i) => {
      const y = 330 + (i - Math.min(rows.length, 3) / 2 + 0.5) * 23;
      center.append(make('text', {x: 500, y, 'text-anchor': 'middle'},
        part.length > 18 ? part.slice(0, 16) + '…' : part));
    });
    layer.append(edgeGroup, nodeGroup, center);
    svg.append(layer);
  }

  fetch('graph.json').then(response => {
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }).then(graph => {
    if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw Error('Graph format');
    nodes = new Map(graph.nodes.map(node => [node.id, node]));
    links = new Map(graph.nodes.map(node => [node.id, new Set()]));
    graph.edges.forEach(edge => {
      if (!nodes.has(edge.source) || !nodes.has(edge.target)) throw Error('Unknown reference');
      links.get(edge.source).add(edge.target);
      links.get(edge.target).add(edge.source);
    });
    graph.nodes.sort((a, b) => a.title.localeCompare(b.title, 'ru'))
      .forEach(node => {
        const option = document.createElement('option');
        option.value = node.title;
        option.label = node.group;
        datalist.append(option);
      });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const q = normalize(input.value);
      const node = graph.nodes.find(item => normalize(item.title) === q) ||
                   graph.nodes.find(item => normalize(item.title).includes(q));
      if (node) select(node.id);
      else status.textContent = 'Запись не найдена. Проверьте написание.';
    });
    groupFilter.addEventListener('change', draw);
    const urlId = new URL(location.href).searchParams.get('id');
    const hub = graph.nodes.slice().sort((a, b) =>
      links.get(b.id).size - links.get(a.id).size ||
      a.title.localeCompare(b.title, 'ru'))[0];
    select(nodes.has(urlId) ? urlId : hub.id);
  }).catch(() => {
    status.textContent = 'Карта недоступна. Перейдите к материалам с главной страницы.';
  });
})();
