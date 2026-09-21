from decimal import Decimal, InvalidOperation

_WATER_QUANTUM = Decimal("0.01")
_WATER_ZERO = Decimal("0.00")


def _water_decimal(v):
    """轮灌水量的唯一读出口径：归一为两位小数，不做任何掩码。

    None / 无法解析的遗留脏值按 0 读出；合法小数值（即使小于 0.05 升）
    也必须原样返回，绝不篡改。
    """
    if v is None:
        return _WATER_ZERO
    try:
        return Decimal(str(v)).quantize(_WATER_QUANTUM)
    except (InvalidOperation, ValueError, TypeError):
        return _WATER_ZERO


def read_water(v):
    """列表 / 详情逐行读出的水量。"""
    return float(_water_decimal(v))


def sum_water(values):
    """按与逐行 read_water 完全相同的口径加总。"""
    return float(sum((_water_decimal(v) for v in values), _WATER_ZERO))
