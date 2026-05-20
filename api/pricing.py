# -*- coding: utf-8 -*-
"""Парсинг цены из строки и расчёт оптовой цены в рублях."""

import re


def clean_price(s) -> float:
    if s is None:
        return 0.0
    s = str(s)
    cleaned = re.sub(r'[^\d,.\s]', '', s).strip()
    if not cleaned:
        return 0.0
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        parts = cleaned.split(',')
        if len(parts[-1]) <= 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    cleaned = cleaned.replace(' ', '')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def get_price_params(price: float, brackets: list) -> tuple[float, float]:
    """Возвращает (коэффициент, добавка_₽) для заданной цены."""
    for row in brackets:
        mn, mx, c = float(row[0]), float(row[1]), float(row[2])
        add = float(row[3]) if len(row) > 3 else 0.0
        if mn <= price <= mx:
            return c, add
    last = brackets[-1] if brackets else [0, 0, 2.4, 0]
    return float(last[2]), float(last[3]) if len(last) > 3 else 0.0


def calc_rub(price_str: str, brackets: list):
    """Из строки локальной цены → итоговая цена в рублях (округлённая до 10).
    Возвращает int или None если цена нулевая/нераспознана."""
    val = clean_price(price_str)
    if val == 0:
        return None
    coeff, add = get_price_params(val, brackets)
    return round(round(val * coeff + add) / 10) * 10


def item_has_discount(item: dict) -> bool:
    """True только при реальной скидке (не 'включено в подписку')."""
    disc_pct  = item.get("discount_pct") or ""
    orig      = item.get("original_price") or ""
    ps_price  = item.get("ps_plus_price") or ""
    reg_price = item.get("price") or ""
    real_disc = "%" in disc_pct and disc_pct not in ("0%", "-0%")
    ps_val  = clean_price(ps_price) if ps_price else 0.0
    reg_val = clean_price(reg_price) if reg_price else 0.0
    real_ps = ps_val > 0 and (reg_val <= 0 or ps_val < reg_val)
    return bool(real_disc or orig or real_ps)
