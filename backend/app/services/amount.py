"""金额处理：人民币大写转换与格式化，用于借款单、报销单等单据。"""

from __future__ import annotations

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_UNITS = ["", "拾", "佰", "仟"]
_BIG_UNITS = ["", "万", "亿", "兆"]


def amount_to_chinese(amount: float) -> str:
    """把金额转换为财务票据要求的中文大写形式，如 1234.56 → 壹仟贰佰叁拾肆元伍角陆分。"""
    try:
        value = round(float(amount or 0), 2)
    except (TypeError, ValueError):
        return ""

    if value == 0:
        return "零元整"

    negative = value < 0
    value = abs(value)

    integer = int(value)
    decimal = int(round((value - integer) * 100))

    if integer >= 10 ** 12:
        return f"{value:.2f}"

    parts: list[str] = []
    group_index = 0
    remaining = integer
    zero_pending = False

    while remaining > 0:
        group = remaining % 10000
        if group == 0:
            zero_pending = bool(parts)
        else:
            group_str = _four_digit(group, zero_pending)
            parts.insert(0, group_str + _BIG_UNITS[group_index])
            zero_pending = group < 1000
        remaining //= 10000
        group_index += 1

    integer_str = "".join(parts) or "零"
    result = f"{integer_str}元"

    if decimal == 0:
        return ("负" if negative else "") + result + "整"

    jiao, fen = divmod(decimal, 10)
    if jiao:
        result += f"{_DIGITS[jiao]}角"
    if fen:
        if not jiao:
            result += "零"
        result += f"{_DIGITS[fen]}分"
    return ("负" if negative else "") + result


def _four_digit(num: int, zero_pending: bool) -> str:
    out = ""
    unit_pos = 0
    zero_flag = False
    while num > 0:
        digit = num % 10
        if digit == 0:
            if out and not zero_flag:
                out = "零" + out
                zero_flag = True
        else:
            out = _DIGITS[digit] + _UNITS[unit_pos] + out
            zero_flag = False
        num //= 10
        unit_pos += 1
    if zero_pending and out and not out.startswith("零"):
        out = "零" + out
    return out


def money(amount: float | None, currency: str = "CNY") -> str:
    symbol = {"CNY": "¥", "RMB": "¥", "USD": "$"}.get((currency or "CNY").upper(), "")
    return f"{symbol}{float(amount or 0):,.2f}"