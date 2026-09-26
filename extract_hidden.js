// Run this in the DevTools console while the Godic listening page is open.
(() => {
  const article = document.querySelector('#article');
  if (article) {
    article.style.height = 'auto';
    article.style.maxHeight = 'none';
    article.style.overflow = 'visible';
  }

  const rows = [...document.querySelectorAll('.sentence')].map((node, index) => ({
    order: index + 1,
    start: node.dataset.starttime || '',
    end: node.dataset.endtime || '',
    german: node.innerText.replace(/\s+/g, ' ').trim(),
    translation: node.closest('.paragraph')?.querySelector('.trans')?.innerText
      .replace(/\s+/g, ' ').trim() || ''
  }));

  const result = {
    url: location.href,
    sentenceCount: rows.length,
    articleClientHeight: article?.clientHeight ?? null,
    articleScrollHeight: article?.scrollHeight ?? null,
    rows
  };
  console.log(JSON.stringify(result, null, 2));
  copy(rows.map(x => `${x.start}\t${x.german}\t${x.translation}`).join('\n'));
  return result;
})();
