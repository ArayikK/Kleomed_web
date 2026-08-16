/* КЛЕОМЕД — интерфейсная логика сайта */
(function () {
  'use strict';

  var $  = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ---------------------------------------------------------- шапка */
  var header = $('.header');
  if (header) {
    var onScroll = function () {
      header.classList.toggle('is-stuck', window.scrollY > 12);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  /* ---------------------------------------------- мобильное меню */
  var burger = $('.burger'), mobileNav = $('.mobile-nav');
  if (burger && mobileNav) {
    burger.addEventListener('click', function () {
      var open = mobileNav.classList.toggle('is-open');
      burger.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.body.classList.toggle('is-locked', open);
    });
    $$('a', mobileNav).forEach(function (a) {
      a.addEventListener('click', function () {
        mobileNav.classList.remove('is-open');
        burger.classList.remove('is-open');
        burger.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('is-locked');
      });
    });
  }

  /* ------------------------------------- подсветка пункта меню */
  var sections = $$('section[id]');
  var navLinks = $$('.nav__link[href^="#"]');
  if (sections.length && navLinks.length && 'IntersectionObserver' in window) {
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        navLinks.forEach(function (l) {
          l.classList.toggle('is-active', l.getAttribute('href') === '#' + e.target.id);
        });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    sections.forEach(function (s) { spy.observe(s); });
  }

  /* ------------------------------------------ появление блоков */
  var reveals = $$('.reveal');
  if (reveals.length) {
    if ('IntersectionObserver' in window) {
      var ro = new IntersectionObserver(function (entries, obs) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add('is-in'); obs.unobserve(e.target); }
        });
      }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
      reveals.forEach(function (el) { ro.observe(el); });
    } else {
      reveals.forEach(function (el) { el.classList.add('is-in'); });
    }
  }

  /* -------------------------------------------------- наверх */
  var toTop = $('.to-top');
  if (toTop) {
    window.addEventListener('scroll', function () {
      toTop.classList.toggle('is-visible', window.scrollY > 700);
    }, { passive: true });
    toTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ------------------------------------------ маска телефона */
  function maskPhone(input) {
    var format = function () {
      var d = input.value.replace(/\D/g, '');
      if (d[0] === '8') d = '7' + d.slice(1);
      if (d[0] !== '7') d = '7' + d;
      d = d.slice(0, 11);
      var out = '+7';
      if (d.length > 1) out += ' (' + d.slice(1, 4);
      if (d.length >= 5) out += ') ' + d.slice(4, 7);
      if (d.length >= 8) out += '-' + d.slice(7, 9);
      if (d.length >= 10) out += '-' + d.slice(9, 11);
      input.value = out;
    };
    input.addEventListener('focus', function () { if (!input.value) input.value = '+7 ('; });
    input.addEventListener('input', format);
    input.addEventListener('blur', function () { if (input.value.replace(/\D/g, '').length < 2) input.value = ''; });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Backspace' && input.value.replace(/\D/g, '').length <= 1) {
        e.preventDefault(); input.value = '';
      }
    });
  }
  $$('input[type="tel"]').forEach(maskPhone);

  /* ------------------------------------------ проверка формы */
  function validate(form) {
    var ok = true;
    $$('[required]', form).forEach(function (f) {
      var bad = false;
      if (f.type === 'tel') bad = f.value.replace(/\D/g, '').length !== 11;
      else bad = !f.value.trim();
      f.classList.toggle('is-error', bad);
      if (bad && ok) { f.focus(); }
      if (bad) ok = false;
    });
    return ok;
  }

  $$('form[data-booking]').forEach(function (form) {
    $$('input,select', form).forEach(function (f) {
      f.addEventListener('input', function () { f.classList.remove('is-error'); });
      f.addEventListener('change', function () { f.classList.remove('is-error'); });
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!validate(form)) return;
      var card = form.closest('.form-card') || form.closest('.modal__box');
      var btn = $('button[type="submit"]', form);
      if (btn) { btn.disabled = true; btn.textContent = 'Отправляем…'; }
      /* Бэкенд не подключён: заявка нигде не сохраняется.
         Подставьте здесь запрос к вашей CRM / почтовому обработчику. */
      window.setTimeout(function () {
        if (card) card.classList.add('is-sent');
        if (btn) { btn.disabled = false; btn.textContent = 'Записаться'; }
        form.reset();
      }, 550);
    });
  });

  /* ------------------------------------------------- модалка */
  var modal = $('#booking-modal');
  var lastFocus = null;

  function openModal(service) {
    if (!modal) return;
    lastFocus = document.activeElement;
    var box = $('.modal__box', modal);
    if (box) box.classList.remove('is-sent');
    var sel = $('#modal-service', modal);
    if (sel && service) {
      var match = $$('option', sel).filter(function (o) { return o.value === service; })[0];
      if (match) sel.value = service;
    }
    modal.classList.add('is-open');
    document.body.classList.add('is-locked');
    window.setTimeout(function () {
      var first = $('input,select', modal);
      if (first) first.focus();
    }, 130);
  }
  function closeModal() {
    if (!modal) return;
    modal.classList.remove('is-open');
    document.body.classList.remove('is-locked');
    if (lastFocus) lastFocus.focus();
  }

  $$('[data-open-modal]').forEach(function (b) {
    b.addEventListener('click', function (e) {
      e.preventDefault();
      openModal(b.getAttribute('data-service') || '');
    });
  });
  if (modal) {
    $$('[data-close-modal]', modal).forEach(function (b) { b.addEventListener('click', closeModal); });
    modal.addEventListener('mousedown', function (e) { if (e.target === modal) closeModal(); });
    /* фокус остаётся внутри окна */
    modal.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var f = $$('button,input,select,textarea,a[href]', modal).filter(function (el) { return !el.disabled && el.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  /* ------------------------------------------------ лайтбокс */
  var lb = $('#lightbox'), lbImg = lb && $('img', lb), lbCap = lb && $('.lightbox__cap', lb);
  var lbItems = [], lbIndex = 0;

  function collectLb() {
    lbItems = $$('[data-lb]').map(function (el) {
      var img = el.tagName === 'IMG' ? el : $('img', el);
      return { src: el.getAttribute('data-lb') || (img && img.src), cap: el.getAttribute('data-lb-cap') || (img && img.alt) || '' };
    });
  }
  function showLb(i) {
    if (!lb || !lbItems.length) return;
    lbIndex = (i + lbItems.length) % lbItems.length;
    lbImg.src = lbItems[lbIndex].src;
    lbImg.alt = lbItems[lbIndex].cap;
    if (lbCap) lbCap.textContent = lbItems[lbIndex].cap + '  ·  ' + (lbIndex + 1) + ' / ' + lbItems.length;
  }
  function openLb(i) {
    if (!lb) return;
    collectLb();
    showLb(i);
    lb.classList.add('is-open');
    document.body.classList.add('is-locked');
  }
  function closeLb() {
    if (!lb) return;
    lb.classList.remove('is-open');
    document.body.classList.remove('is-locked');
  }
  collectLb();
  $$('[data-lb]').forEach(function (el, i) {
    el.addEventListener('click', function () { openLb(i); });
  });
  if (lb) {
    $('.lightbox__close', lb).addEventListener('click', closeLb);
    $('.lightbox__btn--prev', lb).addEventListener('click', function (e) { e.stopPropagation(); showLb(lbIndex - 1); });
    $('.lightbox__btn--next', lb).addEventListener('click', function (e) { e.stopPropagation(); showLb(lbIndex + 1); });
    lb.addEventListener('click', function (e) { if (e.target === lb) closeLb(); });
  }

  /* --------------------------------------------- клавиатура */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (lb && lb.classList.contains('is-open')) closeLb();
      else if (modal && modal.classList.contains('is-open')) closeModal();
      else if (mobileNav && mobileNav.classList.contains('is-open')) burger.click();
    }
    if (lb && lb.classList.contains('is-open')) {
      if (e.key === 'ArrowLeft') showLb(lbIndex - 1);
      if (e.key === 'ArrowRight') showLb(lbIndex + 1);
    }
  });

  /* ------------------------------------------------ аккордеон */
  $$('.acc').forEach(function (acc) {
    var btn = $('.acc__btn', acc), panel = $('.acc__panel', acc);
    if (!btn || !panel) return;
    btn.addEventListener('click', function () {
      var open = acc.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      panel.style.maxHeight = open ? panel.scrollHeight + 'px' : '';
    });
  });
  window.addEventListener('resize', function () {
    $$('.acc.is-open .acc__panel').forEach(function (p) { p.style.maxHeight = p.scrollHeight + 'px'; });
  });

  /* -------------------------------------------- цены: вкладки */
  var tabs = $$('.price-tab');
  var groups = $$('.price-group');
  if (tabs.length && groups.length) {
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var key = tab.getAttribute('data-cat');
        tabs.forEach(function (t) { t.classList.toggle('is-active', t === tab); });
        groups.forEach(function (g) {
          g.hidden = !(key === 'all' || g.getAttribute('data-cat') === key);
        });
        var search = $('#price-search');
        if (search && search.value) search.dispatchEvent(new Event('input'));
      });
    });
  }

  /* -------------------------------------------- цены: поиск */
  var search = $('#price-search');
  if (search) {
    var empty = $('#price-empty');
    search.addEventListener('input', function () {
      var q = search.value.trim().toLowerCase();
      var found = 0;
      groups.forEach(function (g) {
        if (g.hidden && !q) return;
        var rows = $$('tbody tr', g), shown = 0;
        rows.forEach(function (tr) {
          var hit = !q || tr.textContent.toLowerCase().indexOf(q) !== -1;
          tr.classList.toggle('is-hidden', !hit);
          if (hit) shown++;
        });
        if (q) { g.hidden = shown === 0; }
        found += shown;
      });
      if (q) {
        tabs.forEach(function (t) { t.classList.toggle('is-active', t.getAttribute('data-cat') === 'all'); });
      } else {
        var active = tabs.filter(function (t) { return t.classList.contains('is-active'); })[0];
        var key = active ? active.getAttribute('data-cat') : 'all';
        groups.forEach(function (g) { g.hidden = !(key === 'all' || g.getAttribute('data-cat') === key); });
      }
      if (empty) empty.hidden = !(q && found === 0);
    });
  }

  /* ------------------------------------ плавный переход к якорю */
  $$('a[href^="#"]').forEach(function (a) {
    var id = a.getAttribute('href');
    if (id.length < 2) return;
    a.addEventListener('click', function (e) {
      var target = document.getElementById(id.slice(1));
      if (!target) return;
      e.preventDefault();
      var top = target.getBoundingClientRect().top + window.scrollY - (header ? header.offsetHeight + 14 : 0);
      window.scrollTo({ top: top, behavior: 'smooth' });
    });
  });

  /* ------------------------------------------- год в подвале */
  $$('[data-year]').forEach(function (el) { el.textContent = new Date().getFullYear(); });
})();
