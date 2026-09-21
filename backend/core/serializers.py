from rest_framework import serializers

from .models import ClimateLog, Greenhouse, IrrigationCycle, Zone
from .numbers import as_water

# 状态归一化表：英文存储键（大小写不敏感）与中文标签都归一到存储键
IRRIGATION_STATUS_ALIASES = {}
for _status_key, _status_label in IrrigationCycle.STATUS_CHOICES:
    IRRIGATION_STATUS_ALIASES[_status_key] = _status_key
    IRRIGATION_STATUS_ALIASES[_status_label] = _status_key


class GreenhouseSerializer(serializers.ModelSerializer):
    areaM2 = serializers.DecimalField(
        source="area_m2", max_digits=10, decimal_places=2
    )
    zoneCount = serializers.SerializerMethodField()

    class Meta:
        model = Greenhouse
        fields = (
            "id",
            "name",
            "location",
            "areaM2",
            "notes",
            "zoneCount",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "zoneCount", "created_at", "updated_at")

    def get_zoneCount(self, obj):
        if hasattr(obj, "zone_count"):
            return obj.zone_count
        return obj.zones.count()


class ZoneSerializer(serializers.ModelSerializer):
    greenhouseId = serializers.PrimaryKeyRelatedField(
        source="greenhouse", queryset=Greenhouse.objects.all()
    )
    zoneCode = serializers.CharField(source="zone_code")
    cropName = serializers.CharField(source="crop_name", allow_blank=True, required=False)
    greenhouseName = serializers.CharField(source="greenhouse.name", read_only=True)

    class Meta:
        model = Zone
        fields = (
            "id",
            "greenhouseId",
            "greenhouseName",
            "zoneCode",
            "cropName",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "greenhouseName", "created_at", "updated_at")

    def validate(self, attrs):
        greenhouse = attrs.get("greenhouse") or getattr(self.instance, "greenhouse", None)
        zone_code = attrs.get("zone_code") or getattr(self.instance, "zone_code", None)
        if greenhouse and zone_code:
            qs = Zone.objects.filter(greenhouse=greenhouse, zone_code=zone_code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"zoneCode": "同一温室内分区编码必须唯一"}
                )
        return attrs


class ClimateLogSerializer(serializers.ModelSerializer):
    zoneId = serializers.PrimaryKeyRelatedField(
        source="zone", queryset=Zone.objects.all()
    )
    recordedAt = serializers.DateTimeField(source="recorded_at")
    tempC = serializers.DecimalField(source="temp_c", max_digits=5, decimal_places=2)
    humidityPct = serializers.DecimalField(
        source="humidity_pct", max_digits=5, decimal_places=2
    )
    parUmol = serializers.DecimalField(
        source="par_umol", max_digits=8, decimal_places=2, required=False
    )
    co2Ppm = serializers.DecimalField(
        source="co2_ppm", max_digits=8, decimal_places=2, required=False
    )
    zoneCode = serializers.CharField(source="zone.zone_code", read_only=True)
    greenhouseName = serializers.CharField(
        source="zone.greenhouse.name", read_only=True
    )

    class Meta:
        model = ClimateLog
        fields = (
            "id",
            "zoneId",
            "zoneCode",
            "greenhouseName",
            "recordedAt",
            "tempC",
            "humidityPct",
            "parUmol",
            "co2Ppm",
            "created_at",
        )
        read_only_fields = ("id", "zoneCode", "greenhouseName", "created_at")

    def validate_humidityPct(self, value):
        if value < 20 or value > 100:
            raise serializers.ValidationError("湿度须在 20～100 之间")
        return value


class IrrigationCycleSerializer(serializers.ModelSerializer):
    zoneId = serializers.PrimaryKeyRelatedField(
        source="zone", queryset=Zone.objects.all()
    )
    startAt = serializers.DateTimeField(source="start_at")
    durationMin = serializers.IntegerField(source="duration_min")
    waterLiters = serializers.DecimalField(
        source="water_liters", max_digits=10, decimal_places=2
    )
    # 显式声明以走自定义归一化：接受四个英文键（大小写不敏感）与中文标签；
    # allow_blank 让空串流入 validate() 统一按枚举拒绝（与其余两项一次返回）
    status = serializers.CharField(allow_blank=True)
    zoneCode = serializers.CharField(source="zone.zone_code", read_only=True)
    greenhouseName = serializers.CharField(
        source="zone.greenhouse.name", read_only=True
    )

    class Meta:
        model = IrrigationCycle
        fields = (
            "id",
            "zoneId",
            "zoneCode",
            "greenhouseName",
            "startAt",
            "durationMin",
            "waterLiters",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "zoneCode",
            "greenhouseName",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        # 新建与更新（含 PATCH）共用同一套校验：缺失字段回退到实例现值，
        # 对最终落库的三元组做明确数值与枚举比较，三者必须一起成立，
        # 非法项收集后一次性返回 400（中文），而不是遇错即停。
        instance = self.instance
        errors = {}

        if "water_liters" in attrs:
            water = attrs["water_liters"]
        elif instance is not None:
            water = instance.water_liters
        else:
            water = None
        if water is None or water <= 0:
            errors["waterLiters"] = "水量必须大于 0"

        if "duration_min" in attrs:
            duration = attrs["duration_min"]
        elif instance is not None:
            duration = instance.duration_min
        else:
            duration = None
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration > 240
        ):
            errors["durationMin"] = "时长分钟必须是 1 到 240 的整数"

        if "status" in attrs:
            raw_status = attrs["status"]
        elif instance is not None:
            raw_status = instance.status
        else:
            raw_status = None
        normalized_status = IRRIGATION_STATUS_ALIASES.get(
            str(raw_status or "").strip().lower()
        )
        if normalized_status is None:
            errors["status"] = "状态只能是已排程、进行中、已完成、已跳过之一"

        if errors:
            raise serializers.ValidationError(errors)
        attrs["status"] = normalized_status
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["waterLiters"] = as_water(data.get("waterLiters"))
        return data
