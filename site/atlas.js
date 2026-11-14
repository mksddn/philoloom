/* Public knowledge atlas: only explicit source-backed relationships are drawn. */
(() => {
  const root = document.querySelector('#atlas-graph');
  if (!root) return;
  const ns = 'http://www.w3.org/2000/svg';
  const focus = document.querySelector('#atlas-focus');
  const query = document.querySelector('#atlas-query');
  const list = document.querySelector('#atlas-list');
  const status = document.querySelector('#atlas-status');
  const groups = [...document.querySelectorAll('.atlas-filters input[type=checkbox]')];
  const maxVisible = 24;
  let data;
  let nodeMap;
  let neighbors;

  function el(tag, attributes, text) {
    const element = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function buildIndex(graph) {
    const ids = new Set(graph.nodes.map(node => node.id));
    if (ids.size !== graph.nodes.length) throw new Error('Duplicate atlas nodes');
    const map = new Map(graph.nodes.map(node => [node.id, node]));
    const adjacency = new Map(graph.nodes.map(node => [node.id, []]));
    for (const edge of graph.edges) {
      if (!ids.has(edge.source) || !ids.has(edge.target) ||
          edge.source === edge.target || edge.type !== 'explicit_relation' ||
          !Array.isArray(edge.evidence) || !edge.evidence.length) {
        throw new Error('Invalid atlas link');
      }
      adjacency.get(edge.source).push({node: map.get(edge.target), edge});
      adjacency.get(edge.target).push({node: map.get(edge.source), edge});
    }
    for (const relation of graph.semantic_edges || []) {
      if (!ids.has(relation.source) || !ids.has(relation.target) ||
          relation.source === relation.target ||
          !['responds_to', 'develops', 'criticizes'].includes(relation.type) ||
          !relation.evidence?.url?.startsWith('https://') ||
          !relation.evidence?.work || !relation.evidence?.locator || !relation.statement) {
        throw new Error('Invalid sourced philosophical relationship');
      }
      let joined = adjacency.get(relation.source)
        .find(value => value.node.id === relation.target)?.edge;
      if (!joined) {
        joined = {source:relation.source,target:relation.target,
          type:'semantic', evidence:[], interpretations:[]};
        adjacency.get(relation.source).push({node:map.get(relation.target),edge:joined});
        adjacency.get(relation.target).push({node:map.get(relation.source),edge:joined});
      }
      joined.interpretations ??= [];
      joined.interpretations.push(relation);
    }
    for (const values of adjacency.values()) {
      values.sort((a, b) => a.node.title.localeCompare(b.node.title, 'ru'));
    }
    nodeMap = map;
    neighbors = adjacency;
  }

  function centerId() {
    return focus.value && nodeMap.has(focus.value) ? focus.value : data.nodes[0]?.id;
  }

  function refreshChoices() {
    const current = centerId();
    const term = query.value.trim().toLocaleLowerCase('ru');
    const matches = data.nodes.filter(node =>
      node.title.toLocaleLowerCase('ru').includes(term));
    focus.replaceChildren();
    for (const node of matches) {
      const option = document.createElement('option');
      option.value = node.id;
      option.textContent = node.title + ' · ' + node.group;
      focus.append(option);
    }
    const chosen = matches.some(node => node.id === current) ? current : matches[0]?.id;
    focus.value = chosen || '';
    focus.disabled = !matches.length;
    if (!matches.length) {
      status.textContent = 'Ничего не найдено. Измени поисковый запрос.';
      root.replaceChildren();
      list.replaceChildren();
    } else render();
  }

  function setFocus(id) {
    if (!nodeMap.has(id)) return;
    query.value = '';
    focus.value = id;
    refreshChoices();
  }

  function drawNode(node, x, y, centered) {
    const group = el('g', {'class': 'atlas-node atlas-node--' +
      (node.group === 'Личности' ? 'people' : node.group === 'Темы' ? 'topics' : 'history')});
    const link = el('a', {href: node.url, 'aria-label': node.title + ', ' + node.group});
    const label = el('text', {
      x, y: y + (centered ? 46 : 34), 'text-anchor': 'middle',
      'class': 'atlas-label',
    }, node.title.length > 24 ? node.title.slice(0, 22) + '…' : node.title);
    const title = el('title', {}, node.title + ' — ' + node.group);
    const circle = el('circle', {cx:x, cy:y, r:centered ? 31 : 18,
      'class': centered ? 'atlas-center-circle' : 'atlas-neighbor-circle'});
    link.append(title, circle, label);
    link.addEventListener('click', event => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey ||
          event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      setFocus(node.id);
    });
    group.append(link);
    return group;
  }

  function render() {
    const selected = nodeMap.get(centerId());
    if (!selected) return;
    const allowed = new Set(groups.filter(input => input.checked).map(input => input.value));
    const linked = neighbors.get(selected.id).filter(item => allowed.has(item.node.group));
    const visible = linked.slice(0, maxVisible);
    const extra = linked.length - visible.length;
    const total = neighbors.get(selected.id).length;
    status.textContent = 'Найдено прямых связей: ' + linked.length +
      (linked.length !== total ? ' из ' + total : '') +
      (extra ? '. На схеме показано ' + visible.length + '; полный список ниже.' : '.');
    const url = new URL(location.href);
    url.searchParams.set('focus', selected.id);
    history.replaceState(history.state, '', url);

    root.replaceChildren();
    list.replaceChildren();
    const centerX = 460, centerY = 290;
    const coordinates = visible.map((item, index) => {
      const angle = (index / Math.max(1, visible.length)) * 2 * Math.PI - Math.PI / 2;
      return {item, x:centerX + 355 * Math.cos(angle), y:centerY + 218 * Math.sin(angle)};
    });
    for (const point of coordinates) {
      root.append(el('line', {x1:centerX,y1:centerY,x2:point.x,y2:point.y,
        'class':point.item.edge.interpretations?.length ? 'atlas-edge atlas-edge--semantic' : 'atlas-edge'}));
    }
    for (const point of coordinates) {
      root.append(drawNode(point.item.node, point.x, point.y, false));
    }
    root.append(drawNode(selected,centerX,centerY,true));

    for (const {node, edge} of linked) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = node.url;
      a.textContent = node.title;
      const small = document.createElement('small');
      const sourceFields = edge.evidence.map(item =>
        nodeMap.get(item.from).title + ' · ' + item.field);
      small.textContent = node.group +
        (sourceFields.length ? ' · связь из данных: ' + sourceFields.join('; ') :
          ' · редакционно подтверждённая связь');
      li.append(a, small);
      for (const relation of edge.interpretations || []) {
        const claim = document.createElement('p');
        claim.className = 'atlas-semantic-claim';
        const verbs = {
          responds_to: ['Отвечает на проблему', 'На его проблему отвечает'],
          develops: ['Развивает идеи', 'Его идеи развивает'],
          criticizes: ['Критикует', 'Его идеи критикует'],
        };
        const direction = selected.id === relation.source ? 0 : 1;
        const lead = document.createElement('strong');
        lead.textContent = verbs[relation.type][direction] + ': ';
        claim.append(lead, document.createTextNode(relation.statement));
        li.append(claim);
        const source = document.createElement('a');
        source.href = relation.evidence.url;
        source.target = '_blank';
        source.rel = 'noopener noreferrer';
        source.className = 'atlas-claim-source';
        source.textContent = 'Источник: ' + relation.evidence.work +
          ' (' + relation.evidence.locator + ')';
        li.append(source);
      }
      list.append(li);
    }
    if (!linked.length) {
      const li = document.createElement('li');
      li.textContent = 'Для выбранных разделов связанных материалов нет.';
      list.append(li);
    }
  }

  async function start() {
    try {
      const response = await fetch(new URL('graph.json', document.baseURI));
      if (!response.ok) throw new Error('Atlas data unavailable');
      data = await response.json();
      if (data.version !== 1 || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
        throw new Error('Unknown atlas format');
      }
      buildIndex(data);
      const requested = new URLSearchParams(location.search).get('focus');
      for (const node of data.nodes) {
        const option = document.createElement('option');
        option.value = node.id;
        option.textContent = node.title + ' · ' + node.group;
        focus.append(option);
      }
      const fallback = data.nodes.find(node => node.title === 'Онтология')?.id || data.nodes[0]?.id;
      focus.value = requested && nodeMap.has(requested) ? requested : fallback;
      focus.addEventListener('change', render);
      query.addEventListener('input', refreshChoices);
      groups.forEach(input => input.addEventListener('change', render));
      render();
    } catch (error) {
      status.textContent = 'Не удалось загрузить атлас. Попробуй обновить страницу.';
      root.replaceChildren();
      list.replaceChildren();
      console.error('Atlas:', error);
    }
  }
  start();
})();
