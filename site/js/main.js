/* КЛЕОМЕД — интерфейсная логика сайта */
(function () {
  'use strict';

  var $  = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ------------------------------------------------- переключатель темы */
  /* Выбор темы уже применён инлайн-скриптом в <head> — там же он читается
     из localStorage, иначе страница успевала моргнуть тёмным. Здесь только
     переключение и запись выбора. */
  var THEME_KEY = 'kleomed-theme';
  function applyTheme(name) {
    var root = document.documentElement;
    var changed = root.getAttribute('data-theme') !== name;
    root.setAttribute('data-theme', name);
    var meta = $('meta[name="theme-color"]');
    /* Цвет строки состояния мобильного браузера — держим его равным фону
       страницы (--lav), иначе над сайтом висит полоса чужого оттенка. */
    if (meta) meta.setAttribute('content', name === 'light' ? '#D5E8C1' : '#02120F');
    $$('.theme-toggle').forEach(function (b) {
      b.setAttribute('aria-label', name === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему');
    });
    /* Смена только CSS-переменных не инвалидирует слои с backdrop-filter:
       шапка, нижняя панель и стеклянные плашки остаются перекрашенными
       по-старому, пока страница под ними уже сменила тему. Один
       принудительный пересчёт макета перерисовывает их все разом. */
    if (changed) { root.style.display = 'none'; void root.offsetHeight; root.style.display = ''; }
  }
  applyTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
  $$('.theme-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    });
  });

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

  /* ------------------------------ нижняя панель на телефоне */
  /* На первом экране её нет: там уже стоят «Записаться на приём» и телефон,
     а панель вдобавок съедала высоту, из-за которой следующая секция
     заглядывала под сгиб. Появляется, когда герой ушёл вверх больше чем
     наполовину. Порог считаем от самого героя, а не от окна: на подстраницах
     его нет, и там панель нужна почти сразу. */
  var mobileBar = $('.mobile-bar');
  if (mobileBar) {
    var hero = $('.hero');
    var toggleBar = function () {
      var edge = hero ? hero.offsetHeight * 0.6 : window.innerHeight * 0.3;
      mobileBar.classList.toggle('is-on', window.scrollY > edge);
    };
    toggleBar();
    window.addEventListener('scroll', toggleBar, { passive: true });
    window.addEventListener('resize', toggleBar);
  }

  /* ---------------------------------------- узел связи */
  /* Кнопка со списком каналов вместо родной кнопки amoCRM: в её панели
     нет списка каналов, MAX туда добавить нечем. Виджет amo загружается
     скрытым (inline + hidden в коде вставки), а «Написать в чат» открывает
     его командой runChatShow — имя команды взято из самого button.js. */
  var dock = $('[data-chatdock]');
  if (dock) {
    var dockBtn = dock.querySelector('.chatdock__toggle');
    var dockList = dock.querySelector('.chatdock__list');
    var setDock = function (open) {
      dock.classList.toggle('is-open', open);
      dockBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      /* hidden снимаем сразу, а ставим обратно после анимации — иначе
         пункты исчезают мгновенно, не успев уехать вниз. */
      if (open) { dockList.hidden = false; }
      else { setTimeout(function () { if (!dock.classList.contains('is-open')) dockList.hidden = true; }, 240); }
    };
    dockBtn.addEventListener('click', function () {
      setDock(!dock.classList.contains('is-open'));
    });
    document.addEventListener('click', function (e) {
      if (!dock.contains(e.target)) setDock(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setDock(false);
    });
    var amoBtn = dock.querySelector('[data-amo-chat]');
    if (amoBtn) {
      amoBtn.addEventListener('click', function () {
        setDock(false);
        /* Сначала штатная команда виджета. Если она не сработала (виджет
           отвечает не всегда), жмём его собственную кнопку — она спрятана
           стилями, но в отрисовке осталась, и клик по ней открывает чат
           тем же путём, что и обычно. */
        /* Настоящий клик по кнопке виджета — единственный надёжный способ:
           команда runChatShow из его же кода выполняется без ошибки, но окно
           не открывает (проверено на боевой странице).
           Вызов отложен: иначе наш собственный клик всплывает до документа,
           виджет считает его кликом «мимо себя» и тут же закрывает только
           что открытое окно. */
        setTimeout(function () {
          var own = document.getElementById('amobutton');
          if (own) own.click();
          else if (typeof window.amoSocialButton === 'function') {
            try { window.amoSocialButton('runChatShow'); } catch (e) {}
          }
        }, 250);
      });
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
  /* Галочка согласия — тоже [required], но у неё подсвечивается не сам
     input (он визуально скрыт), а обёртка .consent: иначе ошибку не видно. */
  function errHost(f) { return (f.closest && f.closest('.consent')) || f; }

  function validate(form) {
    var ok = true;
    $$('[required]', form).forEach(function (f) {
      var bad = false;
      if (f.type === 'tel') bad = f.value.replace(/\D/g, '').length !== 11;
      else if (f.type === 'checkbox') bad = !f.checked;
      else bad = !f.value.trim();
      errHost(f).classList.toggle('is-error', bad);
      if (bad && ok) { f.focus(); }
      if (bad) ok = false;
    });
    return ok;
  }

  /* Адрес приёмника заявок. Тот же домен — значит без CORS и без
     стороннего сервиса в цепочке. nginx проксирует /api/ на сервис. */
  var LEAD_URL = '/api/lead';
  var CALL_US = 'Не удалось отправить заявку. Позвоните нам: +7 (911) 937-77-27';

  /* Метки рекламы живут в первой ссылке, по которой пришёл человек, а форму
     он заполняет уже на третьей странице. Поэтому запоминаем на сессию. */
  var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];
  var UTM_STORE = 'kleomed-utm';

  function readUtm() {
    var out = {};
    try {
      var q = new URLSearchParams(location.search);
      var fresh = false;
      UTM_KEYS.forEach(function (k) {
        var v = q.get(k);
        if (v) { out[k] = v.slice(0, 120); fresh = true; }
      });
      if (fresh) { sessionStorage.setItem(UTM_STORE, JSON.stringify(out)); return out; }
      var saved = sessionStorage.getItem(UTM_STORE);
      return saved ? JSON.parse(saved) : {};
    } catch (e) { return out; }
  }

  /* Место для сообщения об ошибке отправки — создаём при первой надобности,
     чтобы не плодить пустые узлы в разметке всех шестнадцати страниц. */
  function formError(form) {
    var el = $('.form-err', form);
    if (!el) {
      el = document.createElement('p');
      el.className = 'form-err';
      el.setAttribute('role', 'alert');
      form.appendChild(el);
    }
    return el;
  }

  $$('form[data-booking]').forEach(function (form) {
    $$('input,select', form).forEach(function (f) {
      var clear = function () { errHost(f).classList.remove('is-error'); };
      f.addEventListener('input', clear);
      f.addEventListener('change', clear);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!validate(form)) return;

      var card = form.closest('.form-card') || form.closest('.modal__box');
      var btn = $('button[type="submit"]', form);
      var err = formError(form);
      err.textContent = '';
      err.classList.remove('is-on');
      if (btn) { btn.disabled = true; btn.textContent = 'Отправляем…'; }

      var val = function (n) { var f = $('[name="' + n + '"]', form); return f ? f.value : ''; };
      var payload = {
        name:    val('name'),
        phone:   val('phone'),
        service: val('service'),
        time:    val('time'),
        consent: true,
        form:    form.closest('.modal__box') ? 'Модальное окно записи' : 'Блок записи на странице',
        page:    location.pathname,
        referer: document.referrer
      };
      var utm = readUtm();
      for (var k in utm) { if (utm.hasOwnProperty(k)) payload[k] = utm[k]; }

      var done = function (ok, message) {
        if (btn) { btn.disabled = false; btn.textContent = 'Записаться'; }
        if (ok) {
          if (card) card.classList.add('is-sent');
          form.reset();
          document.dispatchEvent(new CustomEvent('kleomed:lead'));
        } else {
          err.textContent = message;
          err.classList.add('is-on');
        }
      };

      fetch(LEAD_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          return { ok: r.ok, data: data };
        });
      }).then(function (res) {
        if (res.ok && res.data.ok) done(true);
        else done(false, res.data.error || CALL_US);
      }).catch(function () {
        /* Сеть отвалилась или сервис лежит. Молча «спасибо» показывать нельзя:
           человек будет ждать звонка, которого никто не сделает. */
        done(false, CALL_US);
      });
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


  /* ------------------------------------------- калькулятор скидки */
  var calcForm = $('#calc-form');
  if (calcForm) {
    var veil    = $('#calc-veil'),
        load    = $('#calc-load'),
        res     = $('#calc-res'),
        resNum  = $('#calc-res-num'),
        resCat  = $('#calc-res-cat'),
        errBox  = $('#calc-err'),
        btnClose= $('#calc-close'),
        btnBook = $('#calc-book'),
        timers  = [];

    var slow = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function clearTimers() { timers.forEach(function (t) { clearTimeout(t); clearInterval(t); }); timers = []; }

    function closeVeil() {
      clearTimers();
      veil.classList.remove('is-on');
      document.body.classList.remove('is-locked');
      setTimeout(function () { veil.hidden = true; }, 450);
    }

    /* Счёт от нуля до целевого значения. Кегль и свечение растут вместе
       со счётчиком — за это отвечает --k, её же читает css. */
    function countTo(target) {
      var dur = 1100, t0 = Date.now(), box = resNum.parentNode;
      box.style.setProperty('--k', 0);
      resNum.textContent = '0';
      var id = setInterval(function () {
        var p = Math.min((Date.now() - t0) / dur, 1);
        var e = 1 - Math.pow(1 - p, 3);           /* быстро в начале, мягко в конце */
        resNum.textContent = Math.round(target * e);
        box.style.setProperty('--k', e.toFixed(3));
        if (p >= 1) {
          clearInterval(id);
          resNum.textContent = target;            /* добиваем точное значение */
          box.style.setProperty('--k', 1);
        }
      }, 16);
      timers.push(id);
    }

    calcForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var picked = calcForm.querySelector('input[name="cat"]:checked');
      if (!picked) {
        errBox.hidden = false;
        calcForm.querySelector('.calc__opt').scrollIntoView({ block: 'center', behavior: 'smooth' });
        return;
      }
      errBox.hidden = true;

      var off = parseInt(picked.getAttribute('data-off'), 10) || 0;
      resCat.textContent = picked.value;

      /* показываем шторку и крутим загрузку 3–4 секунды */
      veil.hidden = false;
      load.hidden = false;
      res.hidden = true;
      document.body.classList.add('is-locked');
      requestAnimationFrame(function () { veil.classList.add('is-on'); });

      var wait = slow ? 400 : 3000 + Math.random() * 1000;
      timers.push(setTimeout(function () {
        load.hidden = true;
        res.hidden = false;
        if (slow) { resNum.textContent = off; resNum.parentNode.style.setProperty('--k', 1); }
        else countTo(off);
      }, wait));
    });

    if (btnClose) btnClose.addEventListener('click', closeVeil);
    if (btnBook)  btnBook.addEventListener('click', closeVeil);
    veil.addEventListener('click', function (e) { if (e.target === veil) closeVeil(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !veil.hidden) closeVeil();
    });
  }

  /* ------------------------------------------ плашка про cookie */
  /* Плашка уведомительная: счётчик работает сразу, кнопка лишь убирает
     сообщение и запоминает это в localStorage. Отдельного «отказа» нет —
     без аналитики сайт вести нельзя, а факт сбора мы честно раскрываем
     в политике конфиденциальности. */
  var COOKIE_KEY = 'kleomed-cookie-ok';

  function cookieSeen() {
    try { return localStorage.getItem(COOKIE_KEY) === '1'; } catch (e) { return true; }
  }

  if (!cookieSeen()) {
    var bar = document.createElement('div');
    bar.className = 'cookie';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Уведомление об использовании cookie');
    bar.innerHTML =
      '<p class="cookie__txt">Мы используем cookie и сервисы статистики, чтобы сайт работал ' +
      'корректно и мы понимали, что вам интересно. Подробнее — в ' +
      '<a href="/privacy-policy">политике конфиденциальности</a>.</p>' +
      '<button class="btn cookie__ok" type="button">Хорошо</button>';
    document.body.appendChild(bar);
    /* следующий кадр — иначе перехода не видно */
    requestAnimationFrame(function () { bar.classList.add('is-in'); });
    $('.cookie__ok', bar).addEventListener('click', function () {
      try { localStorage.setItem(COOKIE_KEY, '1'); } catch (e) {}
      bar.classList.remove('is-in');
      setTimeout(function () { bar.remove(); }, 320);
    });
  }

  /* ------------------------------------------- Яндекс.Метрика */
  /* Номер счётчика берётся в кабинете Метрики (metrika.yandex.ru).
     Пока строка пустая — ничего не грузится и запросов наружу нет.
     Чтобы включить аналитику, впишите сюда номер, например '12345678'. */
  var METRIKA_ID = '110119162';

  /* Вебвизор пока выключен намеренно. Он записывает действия на странице,
     включая то, что человек печатает в форме записи, — то есть ФИО и телефон
     пациента уехали бы в Яндекс. Яндекс маскирует сам только пароли и карты,
     а имя в поле «Ваше имя» — нет; его же условия прямо запрещают собирать
     через Вебвизор данные, идентифицирующие человека.
     Включим (webvisor:true), когда в настройках счётчика будет поднято
     «Маскировать персональные данные» с селекторами полей формы. */
  var METRIKA_WEBVISOR = false;

  if (METRIKA_ID) {
    window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
    window.ym.l = +new Date();
    var ms = document.createElement('script');
    ms.async = true;
    ms.src = 'https://mc.yandex.ru/metrika/tag.js';
    document.head.appendChild(ms);
    window.ym(METRIKA_ID, 'init', {
      clickmap: true,
      trackLinks: true,
      accurateTrackBounce: true,
      webvisor: METRIKA_WEBVISOR
    });

    /* Цели: отправленная заявка и клик по телефону — то, ради чего сайт есть. */
    document.addEventListener('kleomed:lead', function () { window.ym(METRIKA_ID, 'reachGoal', 'lead'); });
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href^="tel:"]');
      if (a) window.ym(METRIKA_ID, 'reachGoal', 'call');
    });
  }

  /* ------------------------------------------- год в подвале */
  $$('[data-year]').forEach(function (el) { el.textContent = new Date().getFullYear(); });
})();
