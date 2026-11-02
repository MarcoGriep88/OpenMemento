// The search index is served by this website; no external search service is used.
const search = document.querySelector('[data-help-search]');
const topics = document.querySelector('.help-topics');
if (topics && window.matchMedia('(max-width: 800px)').matches) topics.open = false;
if (search) {
  const input = search.querySelector('input');
  const results = search.querySelector('ul');
  const status = search.querySelector('[role="status"]');
  const normalize = (text) => text.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ß/g, 'ss');
  let indexPromise;
  let revision = 0;
  let timer;
  const getIndex = () => {
    if (!indexPromise) {
      indexPromise = fetch(search.dataset.index).then((response) => {
        if (!response.ok) throw new Error('Search index unavailable');
        return response.json();
      }).then((pages) => pages.map((page) => ({...page, normalized: normalize(`${page.title} ${page.summary} ${page.text}`)}))).catch((error) => {
        indexPromise = undefined;
        throw error;
      });
    }
    return indexPromise;
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const current = ++revision;
    const tokens = normalize(input.value.trim()).split(/\s+/).filter(Boolean);
    results.replaceChildren();
    results.hidden = true;
    status.textContent = '';
    if (!tokens.length) return;
    timer = setTimeout(async () => {
      try {
        const pages = await getIndex();
        if (current !== revision) return;
        const matches = pages.filter((page) => tokens.every((token) => page.normalized.includes(token)));
        status.textContent = matches.length ? `${matches.length} ${search.dataset.count}` : search.dataset.empty;
        matches.forEach((page) => {
          const item = document.createElement('li');
          const link = document.createElement('a');
          link.href = page.url;
          link.textContent = page.title;
          item.append(link);
          results.append(item);
        });
        results.hidden = !matches.length;
      } catch {
        if (current === revision) status.textContent = search.dataset.error;
      }
    }, 120);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      input.value = '';
      input.dispatchEvent(new Event('input'));
    }
  });
}
