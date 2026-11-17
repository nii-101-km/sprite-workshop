/* Translate only fixed interface elements; collection and project data are never modified. */
(function () {
  'use strict';
  const i18n = window.WorkshopI18n;
  if (!i18n) return;
  const entries = [
    ['#queue-open', 'Очередь', 'Queue'],
    ['#batch-open', 'Загрузить пакет', 'Load batch'],
    ['#new-open', '＋ Новый предмет', '＋ New object'],
    ['#collection-tab', 'Коллекция', 'Collection'],
    ['.animation-nav', '✦ Анимации персонажей', '✦ Character animations'],
    ['#new-category', '＋ Создать категорию', '＋ Create category'],
    ['#semantic-sidebar', 'Поиск по смыслу', 'Semantic search'],
    ['#tiled-export', 'Обновить для Tiled', 'Update for Tiled'],
    ['#export-settings', 'Выгрузить настройки', 'Export settings'],
    ['#import-settings', 'Загрузить настройки', 'Import settings'],
    ['#semantic-open', 'По смыслу', 'Semantic search'],
    ['#semantic-submit', 'Найти', 'Search'],
    ['#semantic-reset', 'Сбросить поиск', 'Clear search'],
    ['#semantic-build', 'Обновить индекс', 'Update index'],
    ['#raw-mode', 'Исходники', 'Sources'],
    ['#output-mode', 'Готовые', 'Finished'],
    ['#back-collection', 'К предметам', 'Back to objects'],
    ['#pause', 'Ⅱ Пауза после текущего', 'Ⅱ Pause after current job'],
    ['#new-project', '＋ Персонаж', '＋ Character'],
    ['#export', 'Собрать и скачать', 'Build and download'],
    ['#project-save', 'Сохранить описание', 'Save description'],
    ['#view-game', 'Камера игры', 'Game camera'],
    ['#view-front', 'Посмотреть спереди', 'Front view'],
    ['#view-top', 'Посмотреть сверху', 'Top view'],
    ['#manual-title', '1. Положение предмета', '1. Object position'],
    ['#reset', 'Сбросить положение', 'Reset position'],
    ['#reset-scale', 'Сбросить масштаб 100/100/100%', 'Reset scale to 100/100/100%'],
    ['#preview', 'Показать четыре пробных вида', 'Show four preview views'],
    ['#confirm', 'Зафиксировать положение', 'Confirm position'],
  ];
  const textNodes = [];
  for (const [selector, ru, en] of entries) {
    const element = document.querySelector(selector);
    if (element && element.textContent.trim() === ru) textNodes.push({element, ru, en});
  }
  const staticText = [];
  const staticAttributes = [];
  const translations = window.WorkshopStaticTranslations || {};
  const originalTitle = document.title;
  if (document.createTreeWalker) {
    const walker = document.createTreeWalker(document.body, 4);
    while (walker.nextNode()) {
      const node = walker.currentNode, parent = node.parentElement;
      if (!parent || parent.closest('script,style,textarea,#grid,#groups,#projects,#jobs,#previews,#project-title,#project-count,#folder,#toast,#notice')) continue;
      const original = node.nodeValue, text = original.trim();
      if (Object.prototype.hasOwnProperty.call(translations, text)) staticText.push({node, original, text});
    }
    for (const element of document.querySelectorAll('[aria-label],[placeholder],[title],[alt]')) {
      if (element.closest('#grid,#groups,#projects,#jobs,#previews')) continue;
      for (const attribute of ['aria-label','placeholder','title','alt']) {
        const original = element.getAttribute(attribute);
        if (original && Object.prototype.hasOwnProperty.call(translations, original)) staticAttributes.push({element, attribute, original});
      }
    }
  }
  const header = document.querySelector('header');
  if (!header) return;
  const selector = document.createElement('select');
  selector.id = 'language-selector';
  selector.setAttribute('aria-label', 'Language / Язык');
  for (const [value, label] of [['ru', 'Русский'], ['en', 'English']]) {
    const option = document.createElement('option');option.value = value;option.textContent = label;selector.append(option);
  }
  selector.style.cssText = 'margin:0 8px;padding:6px;border:1px solid #7d8c6e;border-radius:6px;background:#202b24;color:#eef3da';
  (header.querySelector('.actions') || header).append(selector);
  function apply(language) {
    document.documentElement.lang = language;
    if (originalTitle && translations[originalTitle]) document.title = language === 'en' ? translations[originalTitle] : originalTitle;
    selector.value = language;
    for (const item of textNodes) item.element.textContent = item[language];
    for (const item of staticText) {
      if (item.node.isConnected) item.node.nodeValue = language === 'en' ? item.original.replace(item.text, translations[item.text]) : item.original;
    }
    for (const item of staticAttributes) item.element.setAttribute(item.attribute, language === 'en' ? translations[item.original] : item.original);
  }
  function changed(language) {
    apply(language);
    if (window.dispatchEvent && typeof Event === 'function') window.dispatchEvent(new Event('workshop-language-change'));
  }
  selector.addEventListener('change', () => changed(i18n.setLanguage(window.localStorage, selector.value)));
  window.addEventListener('storage', event => { if (event.key === i18n.storageKey) changed(i18n.getLanguage(window.localStorage)); });
  apply(i18n.getLanguage(window.localStorage));
})();
