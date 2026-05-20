// PlayStation Store · Поисковик цен — фронтенд для pywebview
// Все вызовы Python идут через window.pywebview.api.<method>(...)
//
// Когда нет pywebview (Android-сборка с локальным HTTP-сервером, или dev-режим),
// эмулируем pywebview.api поверх fetch('/api/<method>'). Остальной код фронта
// при этом не меняется — он по-прежнему дёргает window.pywebview.api.X(args).
if (!window.pywebview && location.protocol.startsWith("http")) {
  window.pywebview = {
    api: new Proxy({}, {
      get(_t, method) {
        if (typeof method !== "string") return undefined;
        return async (...args) => {
          const r = await fetch("/api/" + method, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(args),
          });
          if (!r.ok) throw new Error("HTTP " + r.status);
          const text = await r.text();
          return text ? JSON.parse(text) : null;
        };
      },
    }),
  };
}

const SECRET_CODE = "9094549528";
const SEARCH_DEBOUNCE_MS = 400;

const $ = (id) => document.getElementById(id);

const els = {
  regionSelect:    $("regionSelect"),
  searchInput:     $("searchInput"),
  searchSpinner:   $("searchSpinner"),
  suggestions:     $("suggestions"),
  manualPrice:     $("manualPrice"),
  manualSym:       $("manualSym"),
  manualHint:      $("manualHint"),
  gameName:        $("gameName"),
  platformTag:     $("platformTag"),
  langTag:         $("langTag"),
  subTag:          $("subTag"),
  trialBadge:      $("trialBadge"),
  pricePrefix:     $("pricePrefix"),
  priceMain:       $("priceMain"),
  priceBadge:      $("priceBadge"),
  priceOld:        $("priceOld"),
  psPlusRow:       $("psPlusRow"),
  psPlusPrice:     $("psPlusPrice"),
  psPlusBadge:     $("psPlusBadge"),
  subDiscountRow:   $("subDiscountRow"),
  subDiscountLabel: $("subDiscountLabel"),
  subDiscountPrice: $("subDiscountPrice"),
  subDiscountBadge: $("subDiscountBadge"),
  // dialog
  bracketsDialog:    $("bracketsDialog"),
  bracketsRegion:    $("bracketsRegion"),
  bracketsRows:      $("bracketsRows"),
  bracketsCloseBtn:  $("bracketsCloseBtn"),
  bracketsCancelBtn: $("bracketsCancelBtn"),
  bracketsSaveBtn:   $("bracketsSaveBtn"),
};

const state = {
  regions: [],
  currentRegion: null,
  suggestions: [],
  selectedGame: null,
  selectedIdx: -1,
  detailsReqId: 0,
  searchTimer: null,
  lastQuery: "",
  bracketsDraft: {}, // {code: [[mn, mx, c, add], ...]}
};

// ─── Утилиты ──────────────────────────────────────────────────────────────

const fmtRub = (n) => (n == null ? "" : `${n.toLocaleString("ru-RU")} ₽`);

function show(el)  { el.classList.remove("hidden"); }
function hide(el)  { el.classList.add("hidden"); }

function whenApiReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
  });
}

// ─── Регион ───────────────────────────────────────────────────────────────

async function loadRegions() {
  state.regions = await window.pywebview.api.get_regions();
  els.regionSelect.innerHTML = "";
  for (const r of state.regions) {
    const opt = document.createElement("option");
    opt.value = r.code;
    opt.textContent = `${r.label}`;
    els.regionSelect.appendChild(opt);
  }
  state.currentRegion = state.regions[0];
  updateManualHint();
}

function updateManualHint() {
  const sym = state.currentRegion?.symbol || "";
  els.manualSym.textContent = sym;
  els.manualHint.textContent = `в ${sym}`;
}

async function onRegionChange() {
  const code = els.regionSelect.value;
  const reg = state.regions.find((r) => r.code === code);
  if (!reg) return;
  state.currentRegion = reg;
  await window.pywebview.api.set_region(code);
  updateManualHint();
  clearAll();
}

// ─── Поиск ────────────────────────────────────────────────────────────────

async function onSearchInput() {
  const raw = els.searchInput.value.trim();

  // Секретный код → открыть диалог настроек
  if (raw === SECRET_CODE) {
    els.searchInput.value = "";
    hideSuggestions();
    openBracketsDialog();
    return;
  }

  if (raw.length < 2) {
    hideSuggestions();
    return;
  }

  if (state.searchTimer) clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => runSearch(raw), SEARCH_DEBOUNCE_MS);
}

async function runSearch(query) {
  state.lastQuery = query;
  els.searchSpinner.classList.add("active");
  let results = [];
  try {
    results = await window.pywebview.api.search(query);
  } catch (e) {
    console.error(e);
  }
  if (els.searchInput.value.trim() !== query) {
    els.searchSpinner.classList.remove("active");
    return;
  }
  state.suggestions = results || [];
  renderSuggestions();
  els.searchSpinner.classList.remove("active");

  // Фоновая предзагрузка деталей для верхних результатов —
  // клик по игре будет мгновенным вместо ожидания 1-2 с.
  if (state.suggestions.length > 0 && window.pywebview?.api?.prefetch_details) {
    const ids = state.suggestions
      .slice(0, 5)
      .map((it) => it.id)
      .filter(Boolean);
    if (ids.length) {
      try { window.pywebview.api.prefetch_details(ids); } catch (_) {}
    }
  }
}

function renderSuggestions() {
  els.suggestions.innerHTML = "";
  if (state.suggestions.length === 0) {
    hideSuggestions();
    return;
  }
  for (let i = 0; i < state.suggestions.length; i++) {
    const it = state.suggestions[i];
    const li = document.createElement("li");
    li.role = "option";
    li.dataset.idx = String(i);
    if (it.has_discount) li.classList.add("has-discount");

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = it.name || "";
    li.appendChild(name);

    if (it.has_discount) {
      const pill = document.createElement("span");
      pill.className = "discount-pill";
      pill.textContent = "СКИДКА";
      li.appendChild(pill);
    }

    li.addEventListener("click", () => selectSuggestion(i));
    els.suggestions.appendChild(li);
  }
  els.suggestions.classList.add("visible");
}

function hideSuggestions() {
  els.suggestions.classList.remove("visible");
  els.suggestions.innerHTML = "";
}

function markSelected(idx) {
  const items = els.suggestions.querySelectorAll("li");
  items.forEach((li, i) => {
    li.classList.toggle("selected", i === idx);
  });
}

async function selectSuggestion(idx) {
  const item = state.suggestions[idx];
  if (!item) return;
  state.selectedGame = { ...item };
  state.selectedIdx = idx;
  const reqId = ++state.detailsReqId;

  // Снимаем ручную цену
  els.manualPrice.value = "";

  markSelected(idx);
  // Сразу показываем имя + теги, но цену скрываем за плейсхолдером —
  // чтобы не мигало временное значение, которое потом меняется.
  showGameMeta(state.selectedGame);
  setPriceLoading();

  try {
    const details = await window.pywebview.api.fetch_details(item.id);
    // Если пользователь успел выбрать другую игру — игнорируем устаревший ответ
    if (reqId !== state.detailsReqId) return;
    if (details && Object.keys(details).length > 0) {
      for (const k of Object.keys(details)) {
        const v = details[k];
        if (v != null && (v !== "" || !state.selectedGame[k])) {
          state.selectedGame[k] = v;
        }
      }
    }
  } catch (e) {
    console.error(e);
  }
  // Финальная отрисовка с уже корректной ценой в ₽
  showGame(state.selectedGame);
}

// ─── Отображение игры ─────────────────────────────────────────────────────

function showGame(g) {
  showGameMeta(g);
  renderPrices(g);
}

function showGameMeta(g) {
  els.gameName.textContent = g.name || "—";

  // Платформы
  const plats = g.platforms || [];
  const ps4 = plats.some((p) => String(p).toUpperCase().includes("PS4"));
  const ps5 = plats.some((p) => String(p).toUpperCase().includes("PS5"));
  let platText = "";
  if (ps4 && ps5) platText = "PS4 · PS5";
  else if (ps5)   platText = "PS5";
  else if (ps4)   platText = "PS4";
  if (platText) {
    els.platformTag.textContent = platText;
    show(els.platformTag);
  } else hide(els.platformTag);

  // Язык
  let langText = "";
  if (g.has_ru_voice && g.has_ru_text) langText = "Звук + Текст";
  else if (g.has_ru_text)              langText = "Текст";
  else if (g.has_ru_voice)             langText = "Звук";
  if (langText) {
    els.langTag.textContent = langText;
    show(els.langTag);
  } else hide(els.langTag);

  // Подписка (EA Play / Ubisoft+ / PS+ Catalog ...)
  if (g.subscription) {
    els.subTag.textContent = g.subscription;
    show(els.subTag);
  } else hide(els.subTag);

  // Trial
  if (g.has_trial) show(els.trialBadge); else hide(els.trialBadge);
}

function setPriceLoading() {
  els.pricePrefix.textContent = "";
  els.priceMain.textContent = "…";
  els.priceMain.classList.add("loading");
  els.priceMain.classList.remove("unavailable");
  hide(els.priceBadge);
  els.priceOld.textContent = "";
  hide(els.psPlusRow);
  hide(els.subDiscountRow);
}

function renderPrices(g) {
  els.priceMain.classList.remove("loading");

  // Снято с продажи — показываем явный текст вместо прочерка
  if (g.unavailable && g.price_rub == null) {
    els.pricePrefix.textContent = "";
    els.priceMain.textContent = "Недоступно для покупки";
    els.priceMain.classList.add("unavailable");
    hide(els.priceBadge);
    els.priceOld.textContent = "";
    hide(els.psPlusRow);
    hide(els.subDiscountRow);
    return;
  }
  els.priceMain.classList.remove("unavailable");

  const reg     = g.price_rub ?? null;
  const orig    = g.original_price_rub ?? null;
  const ps      = g.ps_plus_price_rub ?? null;
  const discPct = g.discount_pct || "";
  const psDisc  = g.ps_plus_discount_pct || "";

  const hasRegDiscount = Boolean(g.original_price && discPct);
  const hasPsPlus      = Boolean(g.ps_plus_price);

  if (reg != null) {
    els.priceMain.textContent = fmtRub(reg);
    if (hasRegDiscount) {
      els.pricePrefix.textContent = "";
      els.priceBadge.textContent = `СКИДКА ${discPct}`;
      show(els.priceBadge);
      els.priceOld.textContent = fmtRub(orig);
    } else if (hasPsPlus) {
      els.pricePrefix.textContent = "Обычная ";
      hide(els.priceBadge);
      els.priceOld.textContent = "";
    } else {
      els.pricePrefix.textContent = "";
      hide(els.priceBadge);
      els.priceOld.textContent = "";
    }
  } else {
    els.pricePrefix.textContent = "";
    els.priceMain.textContent = "—";
    hide(els.priceBadge);
    els.priceOld.textContent = "";
  }

  if (hasPsPlus && ps != null) {
    els.psPlusPrice.textContent = fmtRub(ps);
    els.psPlusBadge.textContent = psDisc ? `СКИДКА ${psDisc}` : "";
    show(els.psPlusRow);
  } else {
    hide(els.psPlusRow);
  }

  // Скидка через подписку (EA Play / Ubisoft+ / ...) — отдельной строкой
  const subRub  = g.sub_discount_price_rub ?? null;
  const subPct  = g.sub_discount_pct || "";
  const subLbl  = g.sub_discount_label || "";
  if (subRub != null && subLbl) {
    els.subDiscountLabel.textContent = subLbl;
    els.subDiscountPrice.textContent = fmtRub(subRub);
    els.subDiscountBadge.textContent = subPct ? `СКИДКА ${subPct}` : "";
    show(els.subDiscountRow);
  } else {
    hide(els.subDiscountRow);
  }
}

function clearAll() {
  state.selectedGame = null;
  state.suggestions = [];
  hideSuggestions();
  els.gameName.textContent = "—";
  hide(els.platformTag);
  hide(els.langTag);
  hide(els.subTag);
  hide(els.trialBadge);
  hide(els.psPlusRow);
  els.pricePrefix.textContent = "";
  els.priceMain.textContent = "—";
  hide(els.priceBadge);
  els.priceOld.textContent = "";
}

function resetWholesale() {
  els.pricePrefix.textContent = "";
  els.priceMain.textContent = "—";
  hide(els.priceBadge);
  els.priceOld.textContent = "";
  hide(els.psPlusRow);
}

// ─── Ручная цена ──────────────────────────────────────────────────────────

async function onManualInput() {
  const v = els.manualPrice.value.trim();
  if (!v) {
    if (state.selectedGame) {
      showGame(state.selectedGame);
    } else {
      resetWholesale();
      els.gameName.textContent = "—";
    }
    return;
  }
  // Снимаем выбор игры (логика как в Tkinter-версии)
  state.selectedGame = null;
  els.searchInput.value = "";
  hideSuggestions();
  hide(els.platformTag);
  hide(els.langTag);
  hide(els.subTag);
  hide(els.trialBadge);
  els.gameName.textContent = "Ручная цена";

  try {
    const { rub } = await window.pywebview.api.calc_manual(v);
    if (rub != null) {
      els.pricePrefix.textContent = "";
      els.priceMain.textContent = fmtRub(rub);
      hide(els.priceBadge);
      els.priceOld.textContent = "";
      hide(els.psPlusRow);
    } else {
      els.priceMain.textContent = "—";
    }
  } catch (e) {
    console.error(e);
  }
}

// ─── Диалог коэффициентов ────────────────────────────────────────────────

async function openBracketsDialog() {
  const brackets = await window.pywebview.api.get_brackets();
  state.bracketsDraft = {};
  for (const code of Object.keys(brackets)) {
    state.bracketsDraft[code] = brackets[code].map((r) => [...r]);
  }

  els.bracketsRegion.innerHTML = "";
  for (const r of state.regions) {
    const opt = document.createElement("option");
    opt.value = r.code;
    opt.textContent = r.label;
    els.bracketsRegion.appendChild(opt);
  }
  els.bracketsRegion.value = state.currentRegion?.code || state.regions[0].code;
  renderBracketRows(els.bracketsRegion.value);

  show(els.bracketsDialog);
}

function closeBracketsDialog() {
  hide(els.bracketsDialog);
}

function renderBracketRows(code) {
  const rows = state.bracketsDraft[code] || [];
  els.bracketsRows.innerHTML = "";
  rows.forEach((row, i) => {
    const div = document.createElement("div");
    div.className = "bracket-row";

    const mn = document.createElement("span");
    mn.className = "bracket-cell";
    mn.textContent = Math.trunc(row[0]);
    div.appendChild(mn);

    const mx = document.createElement("span");
    mx.className = "bracket-cell";
    mx.textContent = Math.trunc(row[1]);
    div.appendChild(mx);

    const cIn = document.createElement("input");
    cIn.type = "text";
    cIn.className = "bracket-input";
    cIn.value = row[2];
    cIn.addEventListener("input", () => {
      state.bracketsDraft[code][i][2] = cIn.value;
    });
    div.appendChild(cIn);

    const aIn = document.createElement("input");
    aIn.type = "text";
    aIn.className = "bracket-input add";
    aIn.value = Number.isInteger(+row[3]) ? Math.trunc(+row[3]) : row[3];
    aIn.addEventListener("input", () => {
      state.bracketsDraft[code][i][3] = aIn.value;
    });
    div.appendChild(aIn);

    els.bracketsRows.appendChild(div);
  });
}

async function saveBrackets() {
  // Преобразуем строки в числа перед отправкой
  const payload = {};
  for (const code of Object.keys(state.bracketsDraft)) {
    payload[code] = state.bracketsDraft[code].map((r) => [r[0], r[1], r[2], r[3]]);
  }
  try {
    await window.pywebview.api.save_brackets(payload);
  } catch (e) {
    console.error(e);
  }
  closeBracketsDialog();
  // Пересчитываем текущее отображение
  if (state.selectedGame) {
    const details = await window.pywebview.api.fetch_details(state.selectedGame.id);
    if (details) state.selectedGame = { ...state.selectedGame, ...details };
    showGame(state.selectedGame);
  } else if (els.manualPrice.value.trim()) {
    onManualInput();
  }
}

// ─── Авто-подгонка высоты окна под содержимое ────────────────────────────

function setupAutoResize() {
  const app = document.querySelector(".app");
  if (!app) return;
  let pending = false;
  let lastH = 0;
  const send = () => {
    pending = false;
    // getBoundingClientRect возвращает значения уже после применения zoom,
    // т.е. реальный размер в окне.
    const rect = app.getBoundingClientRect();
    const h = Math.ceil(rect.bottom + 12);
    if (Math.abs(h - lastH) < 4) return;
    lastH = h;
    if (window.pywebview?.api?.resize_window) {
      try { window.pywebview.api.resize_window(h); } catch (_) {}
    }
  };
  const schedule = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(send);
  };
  new ResizeObserver(schedule).observe(app);
  setTimeout(schedule, 120);
}

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
  await whenApiReady();
  await loadRegions();
  setupAutoResize();

  els.regionSelect.addEventListener("change", onRegionChange);
  els.searchInput.addEventListener("input", onSearchInput);
  els.manualPrice.addEventListener("input", onManualInput);
  els.bracketsCloseBtn.addEventListener("click", closeBracketsDialog);
  els.bracketsCancelBtn.addEventListener("click", closeBracketsDialog);
  els.bracketsSaveBtn.addEventListener("click", saveBrackets);
  els.bracketsRegion.addEventListener("change", () => {
    renderBracketRows(els.bracketsRegion.value);
  });
  els.bracketsDialog.addEventListener("click", (e) => {
    if (e.target === els.bracketsDialog) closeBracketsDialog();
  });

  document.addEventListener("keydown", (e) => {
    // Esc закрывает диалог
    if (e.key === "Escape" && !els.bracketsDialog.classList.contains("hidden")) {
      closeBracketsDialog();
      return;
    }
    // "=" открывает выбранную игру в браузере (не мешая вводу в полях)
    if (e.key === "=") {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const g = state.selectedGame;
      if (g && g.url) {
        window.pywebview.api.open_url(g.url);
        e.preventDefault();
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
