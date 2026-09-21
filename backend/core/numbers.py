def as_water(value):
    """水量读出口径：按库存值原样转为数值返回，不做任何掩码。

    轮灌列表序列化与仪表盘「今日轮灌升数」共用本函数，
    保证两处读出口径完全一致。库中 NULL 视为 0。
    """
    if value is None:
        return 0.0
    return float(value)
