# -*- coding: utf-8 -*-
"""
PlayStation Store · Поисковик цен — мобильное приложение (Android / iOS).
Фреймворк: Kivy 2.2.1 + KivyMD 1.1.1
"""

import os
import threading
import webbrowser

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex
from kivymd.app import MDApp
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from psapi import (
    REGIONS, DEFAULT_BRACKETS,
    PSStoreAPI, get_price_params, clean_price,
    load_settings, save_settings, _item_has_discount,
)

# ──────────────────────────────────────────── цвета ──────────────────────────

def _c(h):
    return get_color_from_hex(h)

BG          = _c("#0F1020")
SURFACE     = _c("#181A35")
SURFACE_2   = _c("#1F2147")
BORDER      = _c("#2A2D5C")
ACCENT      = _c("#1E88FF")
ACCENT_DIM  = _c("#1E88FF55")
TEXT        = _c("#FFFFFF")
TEXT_DIM    = _c("#9AA0C7")
TEXT_MUTED  = _c("#6E73A0")
SUCCESS     = _c("#22C55E")
DANGER      = _c("#EF4444")
PS_PLUS_CLR = _c("#B8A9FF")


# ──────────────────────────────────────── вспомогательные виджеты ────────────

def _set_bg(widget, color):
    """Рисует цветной фон на canvas.before виджета и отслеживает изменения размера."""
    with widget.canvas.before:
        clr_inst = Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda *_: setattr(rect, 'pos', widget.pos))
    widget.bind(size=lambda *_: setattr(rect, 'size', widget.size))
    return rect


class TapRow(ButtonBehavior, BoxLayout):
    """Строка списка, реагирующая на касание."""
    pass


# ──────────────────────────────────────────── основное приложение ────────────

class PSApp(MDApp):
    _SECRET = "9094549528"

    # ── инициализация ────────────────────────────────────────────────────────

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        self.title = "PS Store Поисковик"

        # Для десктопной разработки — фиксированный размер окна, как телефон
        if os.environ.get("KIVY_DESKTOP_TEST"):
            Window.size = (400, 720)

        self._init_state()
        return self._build_root()

    def on_start(self):
        self._settings_file = os.path.join(self.user_data_dir, "settings.json")
        cfg = load_settings(self._settings_file)
        if not cfg:
            bundled = os.path.join(self.directory, "settings.json")
            cfg = load_settings(bundled)
        regions_cfg = cfg.get("regions", {})
        for code, *_ in REGIONS:
            r = regions_cfg.get(code, {})
            raw = r.get("brackets")
            if raw and isinstance(raw, list) and raw:
                rows = []
                for b in raw:
                    row = list(b)
                    if len(row) == 3:
                        row.append(0)
                    rows.append(row)
                self.region_brackets[code] = rows

    def _init_state(self):
        self._region    = REGIONS[0][0]
        self._api       = PSStoreAPI(self._region)
        self._sugg      = []           # текущий список подсказок
        self._lock      = threading.Lock()
        self._search_ev = None         # Clock event для debounce
        self._pf_gen    = 0            # счётчик prefetch
        self._selected  = None         # выбранная игра
        self._settings_file = None
        self._params_dlg    = None
        self._muting        = False    # защита от рекурсии
        self.region_brackets = {
            code: [list(b) for b in DEFAULT_BRACKETS]
            for code, *_ in REGIONS
        }

    # ── построение UI ────────────────────────────────────────────────────────

    def _build_root(self):
        screen = MDScreen()
        _set_bg(screen, BG)

        root = BoxLayout(orientation="vertical")
        screen.add_widget(root)

        root.add_widget(self._build_header())

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        content = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=[dp(10), dp(6), dp(10), dp(8)],
            spacing=dp(8),
        )
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        root.add_widget(scroll)

        content.add_widget(self._build_region_section())
        content.add_widget(self._build_search_section())
        content.add_widget(self._build_free_price_section())

        root.add_widget(self._build_result_section())

        return screen

    # ── шапка ────────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(52),
            padding=[dp(12), dp(4), dp(12), dp(4)],
        )
        _set_bg(hdr, SURFACE)

        hdr.add_widget(MDLabel(
            text="PlayStation Store by Slava",
            theme_text_color="Custom", text_color=TEXT,
            font_style="H6", bold=True,
            size_hint=(1, None), height=dp(28),
        ))
        hdr.add_widget(MDLabel(
            text="Поиск игр · расчёт цены в рублях",
            theme_text_color="Custom", text_color=TEXT_DIM,
            font_style="Caption",
            size_hint=(1, None), height=dp(18),
        ))
        return hdr

    # ── карточка-обёртка ─────────────────────────────────────────────────────

    def _make_card(self, title, icon=""):
        card = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            padding=[dp(12), dp(8), dp(12), dp(10)],
            spacing=dp(6),
        )
        card.bind(minimum_height=card.setter("height"))
        _set_bg(card, SURFACE)

        title_row = BoxLayout(size_hint=(1, None), height=dp(26), spacing=dp(6))
        if icon:
            title_row.add_widget(MDLabel(
                text=icon, theme_text_color="Custom", text_color=ACCENT,
                size_hint=(None, 1), width=dp(26), font_size=sp(15),
            ))
        title_row.add_widget(MDLabel(
            text=title, theme_text_color="Custom", text_color=TEXT,
            font_style="Subtitle1", bold=True,
        ))
        card.add_widget(title_row)

        # тонкий разделитель
        sep = Widget(size_hint=(1, None), height=dp(1))
        _set_bg(sep, BORDER)
        card.add_widget(sep)

        body = BoxLayout(orientation="vertical", size_hint=(1, None), spacing=dp(6))
        body.bind(minimum_height=body.setter("height"))
        card.add_widget(body)
        return card, body

    # ── раздел: регион ───────────────────────────────────────────────────────

    def _build_region_section(self):
        card, body = self._make_card("Регион магазина")

        btn_row = BoxLayout(size_hint=(1, None), height=dp(40), spacing=dp(6))
        self._region_btns = {}
        for code, label, *_ in REGIONS:
            btn = MDFlatButton(
                text=label,
                size_hint=(1, 1),
                font_size=sp(13),
            )
            btn.bind(on_release=lambda b, c=code: self._select_region(c))
            self._region_btns[code] = btn
            btn_row.add_widget(btn)

        body.add_widget(btn_row)
        self._refresh_region_btns()
        return card

    def _refresh_region_btns(self):
        for code, btn in self._region_btns.items():
            if code == self._region:
                btn.theme_text_color = "Custom"
                btn.text_color = TEXT
                btn.md_bg_color = ACCENT_DIM
            else:
                btn.theme_text_color = "Custom"
                btn.text_color = TEXT_DIM
                btn.md_bg_color = (0, 0, 0, 0)

    def _select_region(self, code):
        self._region = code
        self._api = PSStoreAPI(code)
        self._clear_results()
        self._refresh_region_btns()
        self._free_sym_lbl.text = f"Цена в {self._current_sym()} (вместо поиска):"

    def _current_sym(self):
        for c, _, _, sym in REGIONS:
            if c == self._region:
                return sym
        return ""

    # ── раздел: поиск ────────────────────────────────────────────────────────

    def _build_search_section(self):
        card, body = self._make_card("Название игры")
        self._search_card = card

        body.add_widget(MDLabel(
            text="Введите название (от 2 символов):",
            theme_text_color="Custom", text_color=TEXT_MUTED,
            font_style="Caption", size_hint=(1, None), height=dp(18),
        ))

        self._search_tf = MDTextField(
            hint_text="Название игры...",
            mode="rectangle",
            size_hint=(1, None),
            height=dp(44),
        )
        self._search_tf.bind(text=self._on_search_text)
        self._search_tf.bind(on_text_validate=self._on_search_submit)
        body.add_widget(self._search_tf)

        self._sugg_box = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=0,
        )
        _set_bg(self._sugg_box, SURFACE_2)
        body.add_widget(self._sugg_box)

        return card

    def _on_search_text(self, instance, value):
        if self._muting:
            return
        query = value.strip()
        if len(query) < 2:
            self._clear_sugg()
            return
        if self._search_ev:
            self._search_ev.cancel()
        self._search_ev = Clock.schedule_once(
            lambda dt: threading.Thread(
                target=self._fetch_sugg, args=(query,), daemon=True
            ).start(),
            0.4,
        )

    def _on_search_submit(self, instance):
        if instance.text.strip() == self._SECRET:
            instance.text = ""
            self._clear_sugg()
            Clock.schedule_once(lambda dt: self._open_params_dialog(), 0.1)

    def _fetch_sugg(self, query):
        try:
            results = self._api.search(query, limit=12)
        except Exception:
            results = []
        if self._search_tf.text.strip() != query:
            return
        with self._lock:
            self._sugg = results
        Clock.schedule_once(lambda dt: self._render_sugg(), 0)

    def _render_sugg(self):
        self._sugg_box.clear_widgets()
        with self._lock:
            items = list(self._sugg)

        if not items:
            self._sugg_box.height = 0
            return

        row_h  = dp(48)
        max_h  = dp(240)
        total  = min(len(items) * row_h, max_h)

        scroll = ScrollView(size_hint=(1, None), height=total, do_scroll_x=False)
        col = BoxLayout(orientation="vertical", size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        scroll.add_widget(col)

        for i, game in enumerate(items):
            has_disc = _item_has_discount(game)
            name     = game.get("name", "")
            color    = SUCCESS if has_disc else TEXT
            suffix   = "  [color=#22C55E]Скидка![/color]" if has_disc else ""

            row = TapRow(size_hint=(1, None), height=row_h, padding=[dp(12), 0])
            _set_bg(row, SURFACE if i % 2 == 0 else SURFACE_2)

            row.add_widget(MDLabel(
                text=name + suffix,
                markup=True,
                theme_text_color="Custom",
                text_color=color,
                font_size=sp(13),
                shorten=True,
                shorten_from="right",
            ))
            row.bind(on_release=lambda _, g=game: self._on_sugg_tap(g))
            col.add_widget(row)

        self._sugg_box.add_widget(scroll)
        self._sugg_box.height = total
        Clock.schedule_once(lambda dt: self._force_search_card_update(), 0)

        # фоновая предзагрузка скидок
        self._pf_gen += 1
        gen = self._pf_gen
        with self._lock:
            snap = list(self._sugg)
        threading.Thread(
            target=self._prefetch, args=(snap, gen), daemon=True
        ).start()

    def _on_sugg_tap(self, game):
        self._selected = dict(game)
        self._muting = True
        self._search_tf.text = game.get("name", "")
        self._free_tf.text   = ""
        self._muting = False
        self._clear_sugg()
        self._show_price()
        threading.Thread(target=self._refresh_details, daemon=True).start()

    def _force_search_card_update(self):
        if hasattr(self, '_search_card'):
            self._search_card.height = self._search_card.minimum_height

    def _clear_sugg(self):
        self._sugg_box.clear_widgets()
        self._sugg_box.height = 0
        Clock.schedule_once(lambda dt: self._force_search_card_update(), 0)
        with self._lock:
            self._sugg = []

    def _prefetch(self, items, gen):
        for i, item in enumerate(items):
            if gen != self._pf_gen:
                return
            details = self._api.fetch_product_details(item.get("id", ""))
            if not details:
                continue
            changed = False
            with self._lock:
                if i < len(self._sugg):
                    si = self._sugg[i]
                    for f in ("discount_pct", "original_price",
                              "ps_plus_price", "ps_plus_discount_pct"):
                        nv = details.get(f)
                        if nv is not None and nv != si.get(f):
                            si[f] = nv
                            changed = True
            if changed:
                Clock.schedule_once(lambda dt: self._render_sugg(), 0)

    # ── раздел: ручная цена ──────────────────────────────────────────────────

    def _build_free_price_section(self):
        card, body = self._make_card("Ручная цена")

        self._free_sym_lbl = MDLabel(
            text=f"Цена в {self._current_sym()} (вместо поиска):",
            theme_text_color="Custom", text_color=TEXT_MUTED,
            font_style="Caption", size_hint=(1, None), height=dp(20),
        )
        body.add_widget(self._free_sym_lbl)

        self._free_tf = MDTextField(
            hint_text="Введите цену вручную...",
            mode="rectangle",
            size_hint=(1, None),
            height=dp(44),
        )
        self._free_tf.bind(text=self._on_free_price_text)
        body.add_widget(self._free_tf)
        return card

    def _on_free_price_text(self, instance, value):
        if self._muting:
            return
        if value.strip():
            self._selected = None
            self._muting = True
            self._search_tf.text = ""
            self._muting = False
            self._clear_sugg()
            self._result_name.text = "Ручная цена"
            self._plat_lbl.text   = ""
            self._lang_lbl.text   = ""
            self._trial_lbl.height  = 0
            self._trial_lbl.opacity = 0
            self._recalc()
        else:
            self._reset_display()

    # ── раздел: результат ────────────────────────────────────────────────────

    def _build_result_section(self):
        outer = BoxLayout(orientation="vertical", size_hint=(1, None), height=dp(160))
        _set_bg(outer, SURFACE)
        sep = Widget(size_hint=(1, None), height=dp(1))
        _set_bg(sep, BORDER)
        outer.add_widget(sep)
        inner = BoxLayout(
            orientation="vertical", size_hint=(1, 1),
            padding=[dp(12), dp(6), dp(12), dp(4)], spacing=dp(3),
        )
        outer.add_widget(inner)

        name_row = BoxLayout(size_hint=(1, None), height=dp(24), spacing=dp(4))
        self._result_name = MDLabel(
            text="—", theme_text_color="Custom", text_color=TEXT,
            font_style="Subtitle2", bold=True,
            size_hint=(1, 1), shorten=True, shorten_from="right",
        )
        self._plat_lbl = MDLabel(
            text="", theme_text_color="Custom", text_color=ACCENT,
            font_style="Caption", halign="right",
            size_hint=(None, 1), width=dp(80),
        )
        self._lang_lbl = MDLabel(
            text="", theme_text_color="Custom", text_color=SUCCESS,
            font_style="Caption", halign="right",
            size_hint=(None, 1), width=dp(80),
        )
        name_row.add_widget(self._result_name)
        name_row.add_widget(self._plat_lbl)
        name_row.add_widget(self._lang_lbl)
        inner.add_widget(name_row)

        self._trial_lbl = MDLabel(
            text="ДОСТУПНА ПРОБНАЯ ВЕРСИЯ",
            theme_text_color="Custom", text_color=get_color_from_hex("#f0a500"),
            font_style="Caption", bold=True,
            size_hint=(1, None), height=0, opacity=0,
        )
        inner.add_widget(self._trial_lbl)

        reg_row = BoxLayout(size_hint=(1, None), height=dp(46), spacing=dp(4))
        self._price_prefix = MDLabel(
            text="", theme_text_color="Custom", text_color=TEXT_MUTED,
            font_style="Caption", size_hint=(None, 1), width=dp(60),
            valign="bottom", halign="right",
        )
        self._price_lbl = MDLabel(
            text="—", theme_text_color="Custom", text_color=SUCCESS,
            font_size=sp(28), bold=True, halign="center", size_hint=(1, 1),
        )
        self._disc_badge = MDLabel(
            text="", theme_text_color="Custom", text_color=DANGER,
            font_style="Caption", size_hint=(None, 1), width=dp(80),
            valign="bottom",
        )
        reg_row.add_widget(self._price_prefix)
        reg_row.add_widget(self._price_lbl)
        reg_row.add_widget(self._disc_badge)
        inner.add_widget(reg_row)

        self._old_price_lbl = MDLabel(
            text="", markup=True,
            theme_text_color="Custom", text_color=TEXT_MUTED,
            font_style="Caption", halign="center",
            size_hint=(1, None), height=dp(16),
        )
        inner.add_widget(self._old_price_lbl)

        ps_row = BoxLayout(size_hint=(1, None), height=dp(26), spacing=dp(4))
        self._ps_prefix = MDLabel(
            text="", theme_text_color="Custom", text_color=TEXT_DIM,
            font_style="Caption", bold=True,
            size_hint=(None, 1), width=dp(36),
        )
        self._ps_price_lbl = MDLabel(
            text="", theme_text_color="Custom", text_color=PS_PLUS_CLR,
            font_size=sp(20), bold=True, halign="center", size_hint=(1, 1),
        )
        self._ps_badge = MDLabel(
            text="", theme_text_color="Custom", text_color=PS_PLUS_CLR,
            font_style="Caption", size_hint=(None, 1), width=dp(80),
            valign="bottom",
        )
        ps_row.add_widget(self._ps_prefix)
        ps_row.add_widget(self._ps_price_lbl)
        ps_row.add_widget(self._ps_badge)
        inner.add_widget(ps_row)

        open_btn = MDFlatButton(
            text="Открыть в браузере",
            theme_text_color="Custom", text_color=ACCENT,
            size_hint=(1, None), height=dp(32),
            font_size=sp(12),
        )
        open_btn.bind(on_release=lambda *_: self._open_browser())
        inner.add_widget(open_btn)

        return outer

    # ── логика цен ───────────────────────────────────────────────────────────

    def _refresh_details(self):
        if not self._selected:
            return
        details = self._api.fetch_product_details(self._selected["id"])
        if not details:
            return
        for f in ("price", "original_price", "discount_pct",
                  "ps_plus_price", "ps_plus_discount_pct", "name"):
            v = details.get(f)
            if v is not None and (v != "" or not self._selected.get(f)):
                self._selected[f] = v
        if details.get("has_trial"):
            self._selected["has_trial"] = True
        for f in ("platforms", "has_ru_voice", "has_ru_text"):
            if details.get(f) is not None:
                self._selected[f] = details[f]
        Clock.schedule_once(lambda dt: self._show_price(), 0)

    def _show_price(self):
        if not self._selected:
            return
        g = self._selected
        self._result_name.text = g.get("name", "")

        platforms = g.get("platforms") or []
        ps4 = any("PS4" in p.upper() for p in platforms)
        ps5 = any("PS5" in p.upper() for p in platforms)
        self._plat_lbl.text = (
            "[PS4+PS5]" if (ps4 and ps5) else
            "[PS5]"     if ps5 else
            "[PS4]"     if ps4 else ""
        )
        has_voice = g.get("has_ru_voice", False)
        has_text  = g.get("has_ru_text",  False)
        self._lang_lbl.text = (
            "[Звук+Текст]" if (has_voice and has_text) else
            "[Текст]"      if has_text  else
            "[Звук]"       if has_voice else ""
        )
        if g.get("has_trial"):
            self._trial_lbl.height  = dp(22)
            self._trial_lbl.opacity = 1
        else:
            self._trial_lbl.height  = 0
            self._trial_lbl.opacity = 0

        self._recalc()

    def _recalc(self):
        free = self._free_tf.text.strip()
        if free:
            price_str = free
            orig_str = disc_pct = ps_str = ps_disc_pct = ""
        elif self._selected:
            g = self._selected
            price_str   = g.get("price") or ""
            orig_str    = g.get("original_price") or ""
            disc_pct    = g.get("discount_pct") or ""
            ps_str      = g.get("ps_plus_price") or ""
            ps_disc_pct = g.get("ps_plus_discount_pct") or ""
        else:
            return

        brackets = self.region_brackets[self._region]

        def to_rub(s):
            v = clean_price(s)
            if v == 0:
                return None
            coeff, add = get_price_params(v, brackets)
            return round(round(v * coeff + add) / 10) * 10

        def fmt(amt):
            return f"{amt} ₽" if amt is not None else ""

        reg  = to_rub(price_str)
        orig = to_rub(orig_str)
        ps   = to_rub(ps_str)

        has_disc = bool(orig_str and disc_pct)
        has_ps   = bool(ps_str)

        if reg is not None:
            self._price_lbl.text = fmt(reg)
            if has_disc:
                self._price_prefix.text = ""
                self._disc_badge.text   = f"СКИДКА {disc_pct}"
                self._old_price_lbl.text = f"[s]{fmt(orig)}[/s]"
            elif has_ps:
                self._price_prefix.text  = "Обычная"
                self._disc_badge.text    = ""
                self._old_price_lbl.text = ""
            else:
                self._price_prefix.text  = ""
                self._disc_badge.text    = ""
                self._old_price_lbl.text = ""
        else:
            self._price_lbl.text     = "—"
            self._price_prefix.text  = ""
            self._disc_badge.text    = ""
            self._old_price_lbl.text = ""

        if has_ps and ps is not None:
            self._ps_prefix.text    = "PS+"
            self._ps_price_lbl.text = fmt(ps)
            self._ps_badge.text     = f"СКИДКА {ps_disc_pct}" if ps_disc_pct else ""
        else:
            self._ps_prefix.text    = ""
            self._ps_price_lbl.text = ""
            self._ps_badge.text     = ""

    def _reset_display(self):
        self._price_lbl.text     = "—"
        self._price_prefix.text  = ""
        self._disc_badge.text    = ""
        self._old_price_lbl.text = ""
        self._ps_prefix.text     = ""
        self._ps_price_lbl.text  = ""
        self._ps_badge.text      = ""
        self._result_name.text   = "—"
        self._plat_lbl.text      = ""
        self._lang_lbl.text      = ""
        self._trial_lbl.height   = 0
        self._trial_lbl.opacity  = 0

    def _clear_results(self):
        self._selected = None
        self._clear_sugg()
        self._reset_display()

    def _open_browser(self):
        if self._selected and self._selected.get("url"):
            webbrowser.open(self._selected["url"])

    # ── диалог параметров ────────────────────────────────────────────────────

    def _open_params_dialog(self):
        self._dlg_region = REGIONS[0][0]

        # Поля ввода для каждого региона
        self._dlg_coeff = {}
        self._dlg_add   = {}
        for code, *_ in REGIONS:
            self._dlg_coeff[code] = []
            self._dlg_add[code]   = []
            for row in self.region_brackets[code]:
                v_add = row[3]
                s_add = str(int(v_add) if float(v_add) == int(float(v_add)) else v_add)
                self._dlg_coeff[code].append(
                    MDTextField(text=str(row[2]), mode="rectangle",
                                size_hint=(None, None), width=dp(72), height=dp(40),
                                font_size=sp(12))
                )
                self._dlg_add[code].append(
                    MDTextField(text=s_add, mode="rectangle",
                                size_hint=(None, None), width=dp(72), height=dp(40),
                                font_size=sp(12))
                )

        modal = ModalView(size_hint=(1, 1), background_color=[0, 0, 0, 0.9])
        self._params_dlg = modal

        wrap = BoxLayout(
            orientation="vertical",
            size_hint=(0.97, 0.92),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            padding=[dp(10), dp(10)],
            spacing=dp(6),
        )
        _set_bg(wrap, SURFACE)
        modal.add_widget(wrap)

        wrap.add_widget(MDLabel(
            text="Коэффициенты расчёта",
            theme_text_color="Custom", text_color=TEXT,
            font_style="H6", bold=True,
            size_hint=(1, None), height=dp(36),
        ))

        content = self._build_params_content()
        wrap.add_widget(content)

        btn_row = BoxLayout(size_hint=(1, None), height=dp(48), spacing=dp(8))
        btn_row.add_widget(MDFlatButton(
            text="Закрыть",
            theme_text_color="Custom", text_color=TEXT_DIM,
            size_hint=(1, 1),
            on_release=lambda *_: modal.dismiss(),
        ))
        btn_row.add_widget(MDRaisedButton(
            text="Сохранить",
            size_hint=(1, 1),
            on_release=lambda *_: self._params_save(),
        ))
        wrap.add_widget(btn_row)

        modal.open()

    def _build_params_content(self):
        content = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(380),
            spacing=dp(6),
        )

        # Переключатель регионов
        reg_row = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))
        self._dlg_reg_btns = {}
        for code, label, *_ in REGIONS:
            btn = MDFlatButton(
                text=label, size_hint=(1, 1), font_size=sp(12),
            )
            btn.bind(on_release=lambda b, c=code: self._dlg_switch(c))
            self._dlg_reg_btns[code] = btn
            reg_row.add_widget(btn)
        content.add_widget(reg_row)
        self._dlg_refresh_btns()

        # Заголовок таблицы
        hdr = BoxLayout(size_hint=(1, None), height=dp(26))
        for txt, w in [("Мин", 50), ("Макс", 50), ("Коэф.", 72), ("Добавка", 72)]:
            hdr.add_widget(MDLabel(
                text=txt, theme_text_color="Custom", text_color=TEXT_DIM,
                font_style="Caption", halign="center",
                size_hint=(None, 1), width=dp(w),
            ))
        content.add_widget(hdr)

        # Таблица со скроллом
        self._dlg_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self._dlg_col = BoxLayout(orientation="vertical", size_hint_y=None)
        self._dlg_col.bind(minimum_height=self._dlg_col.setter("height"))
        self._dlg_scroll.add_widget(self._dlg_col)
        content.add_widget(self._dlg_scroll)

        self._dlg_draw(REGIONS[0][0])
        return content

    def _dlg_switch(self, code):
        self._dlg_region = code
        self._dlg_refresh_btns()
        self._dlg_draw(code)

    def _dlg_refresh_btns(self):
        for code, btn in self._dlg_reg_btns.items():
            if code == self._dlg_region:
                btn.theme_text_color = "Custom"
                btn.text_color = TEXT
                btn.md_bg_color = ACCENT_DIM
            else:
                btn.theme_text_color = "Custom"
                btn.text_color = TEXT_DIM
                btn.md_bg_color = (0, 0, 0, 0)

    def _dlg_draw(self, code):
        self._dlg_col.clear_widgets()
        brackets = self.region_brackets[code]
        for i, bkt in enumerate(brackets):
            row = BoxLayout(size_hint=(1, None), height=dp(46), spacing=dp(4),
                            padding=[dp(4), dp(3)])
            _set_bg(row, SURFACE if i % 2 == 0 else SURFACE_2)
            row.add_widget(MDLabel(
                text=str(int(bkt[0])), theme_text_color="Custom", text_color=TEXT_DIM,
                font_style="Caption", halign="center",
                size_hint=(None, 1), width=dp(50),
            ))
            row.add_widget(MDLabel(
                text=str(int(bkt[1])), theme_text_color="Custom", text_color=TEXT_DIM,
                font_style="Caption", halign="center",
                size_hint=(None, 1), width=dp(50),
            ))
            row.add_widget(self._dlg_coeff[code][i])
            row.add_widget(self._dlg_add[code][i])
            self._dlg_col.add_widget(row)

    def _params_save(self):
        for code, *_ in REGIONS:
            brackets = self.region_brackets[code]
            for i, (cf, af) in enumerate(zip(self._dlg_coeff[code], self._dlg_add[code])):
                try:
                    brackets[i][2] = float(cf.text.replace(",", "."))
                except ValueError:
                    pass
                try:
                    brackets[i][3] = float(af.text.replace(",", "."))
                except ValueError:
                    pass
        data = {code: {"brackets": self.region_brackets[code]} for code, *_ in REGIONS}
        if self._settings_file:
            save_settings(self._settings_file, data)
        self._recalc()
        self._params_dlg.dismiss()


# ──────────────────────────────────────────────────── точка входа ────────────

if __name__ == "__main__":
    PSApp().run()
