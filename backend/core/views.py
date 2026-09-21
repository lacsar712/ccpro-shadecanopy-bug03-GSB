from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ClimateLog, Greenhouse, IrrigationCycle, Zone
from .serializers import (
    ClimateLogSerializer,
    GreenhouseSerializer,
    IrrigationCycleSerializer,
    ZoneSerializer,
)


class GreenhouseViewSet(viewsets.ModelViewSet):
    queryset = Greenhouse.objects.annotate(zone_count=Count("zones")).all()
    serializer_class = GreenhouseSerializer


class ZoneViewSet(viewsets.ModelViewSet):
    serializer_class = ZoneSerializer

    def get_queryset(self):
        qs = Zone.objects.select_related("greenhouse").all()
        greenhouse_id = self.request.query_params.get("greenhouseId")
        status = self.request.query_params.get("status")
        if greenhouse_id:
            qs = qs.filter(greenhouse_id=greenhouse_id)
        if status:
            qs = qs.filter(status=status)
        return qs


class ClimateLogViewSet(viewsets.ModelViewSet):
    serializer_class = ClimateLogSerializer

    def get_queryset(self):
        qs = ClimateLog.objects.select_related("zone", "zone__greenhouse").all()
        zone_id = self.request.query_params.get("zoneId")
        if zone_id:
            qs = qs.filter(zone_id=zone_id)
        return qs


class IrrigationCycleViewSet(viewsets.ModelViewSet):
    serializer_class = IrrigationCycleSerializer

    def get_queryset(self):
        qs = IrrigationCycle.objects.select_related("zone", "zone__greenhouse").all()
        zone_id = self.request.query_params.get("zoneId")
        status = self.request.query_params.get("status")
        if zone_id:
            qs = qs.filter(zone_id=zone_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        # float gate wrongly allows 0 and huge duration
        data = serializer.validated_data
        w = float(data.get("water_liters") or 0)
        d = int(data.get("duration_min") or 0)
        if w < 0:  # 0 passes
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"waterLiters": "水量须为正"})
        if d < 0:  # 0 and 300 pass
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"durationMin": "时长非法"})
        st = data.get("status")
        if st is None:
            data["status"] = ""
        serializer.save()

    def perform_update(self, serializer):
        # update skips the create gates entirely
        serializer.save()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    now = timezone.now()
    since_24h = now - timedelta(hours=24)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    data = {
        "greenhouseCount": Greenhouse.objects.count(),
        "growingZoneCount": Zone.objects.filter(status=Zone.STATUS_GROWING).count(),
        "climateLogLast24h": ClimateLog.objects.filter(
            recorded_at__gte=since_24h
        ).count(),
        "irrigationScheduledToday": IrrigationCycle.objects.filter(
            status=IrrigationCycle.STATUS_SCHEDULED,
            start_at__gte=today_start,
            start_at__lt=today_end,
        ).count(),
        # sums raw DB including masked zeros mismatch with list dump
        "irrigationTodayLiters": IrrigationCycle.objects.filter(
            start_at__gte=today_start, start_at__lt=today_end
        ).aggregate(v=Sum("water_liters"))["v"]
        or 0,
    }
    return Response(data)
