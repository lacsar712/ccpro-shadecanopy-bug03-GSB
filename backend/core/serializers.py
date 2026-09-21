from decimal import Decimal

from rest_framework import serializers

from .models import ClimateLog, Greenhouse, IrrigationCycle, Zone
from .numbers import read_water


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
    VALID_STATUSES = (
        IrrigationCycle.STATUS_SCHEDULED,
        IrrigationCycle.STATUS_RUNNING,
        IrrigationCycle.STATUS_DONE,
        IrrigationCycle.STATUS_SKIPPED,
    )

    zoneId = serializers.PrimaryKeyRelatedField(
        source="zone", queryset=Zone.objects.all()
    )
    startAt = serializers.DateTimeField(source="start_at")
    durationMin = serializers.IntegerField(
        source="duration_min",
        error_messages={"invalid": "时长分钟必须是 1 到 240 的整数"},
    )
    waterLiters = serializers.DecimalField(
        source="water_liters",
        max_digits=10,
        decimal_places=2,
        error_messages={
            "invalid": "水量必须是大于 0 的数字",
            "max_digits": "水量整数位与小数位合计不得超过 10 位",
            "max_decimal_places": "水量最多保留 2 位小数",
            "max_whole_digits": "水量整数位不得超过 8 位",
        },
    )
    # 允许空串进入 validate，由显式枚举比较统一拒绝，错误口径只有一处
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
        # 新建与更新（含 PATCH 局部更新）共用同一套规则：
        # 未出现在本次提交里的字段取既有值合并后再判定。
        errors = {}

        duration = attrs.get("duration_min")
        if duration is None:
            duration = getattr(self.instance, "duration_min", None)
        # 显式数值比较：必须是整数且落在 1～240（0、负数、300 一律拒绝）
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not (1 <= duration <= 240)
        ):
            errors["durationMin"] = "时长分钟必须是 1 到 240 的整数"

        water = attrs.get("water_liters")
        if water is None:
            water = getattr(self.instance, "water_liters", None)
        # 显式数值比较：水量必须严格大于 0（0 与负数一律拒绝）
        if water is None or water <= Decimal("0"):
            errors["waterLiters"] = "水量必须大于 0"

        status = attrs.get("status")
        if status is None:
            status = getattr(self.instance, "status", None)
        # 显式枚举精确比较：空串、大小写混乱、生造词一律拒绝
        if status not in self.VALID_STATUSES:
            errors["status"] = (
                "状态只能是 scheduled(已排程)、running(进行中)、"
                "done(已完成)、skipped(已跳过) 四者之一"
            )

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["waterLiters"] = read_water(instance.water_liters)
        data["durationMin"] = instance.duration_min
        data["status"] = instance.status
        return data
