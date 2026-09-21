from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Greenhouse, IrrigationCycle, Zone
from .numbers import read_water, sum_water

User = get_user_model()


class IrrigationCycleAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pw123456")
        self.client.force_authenticate(self.user)
        self.gh = Greenhouse.objects.create(name="测试棚", area_m2=Decimal("100.00"))
        self.zone = Zone.objects.create(
            greenhouse=self.gh, zone_code="Z-1", status=Zone.STATUS_GROWING
        )
        self.today = timezone.now()
        self.url = "/api/irrigation-cycles/"

    def payload(self, **overrides):
        data = {
            "zoneId": self.zone.id,
            "startAt": self.today.isoformat(),
            "durationMin": 30,
            "waterLiters": "100.00",
            "status": "scheduled",
        }
        data.update(overrides)
        return data

    # ---------- 合法记录 ----------

    def test_valid_create_persists_and_reads_back(self):
        r = self.client.post(
            self.url, self.payload(waterLiters="0.04", status="done"), format="json"
        )
        self.assertEqual(r.status_code, 201, r.content)
        rid = r.json()["id"]
        self.assertEqual(Decimal(str(r.json()["waterLiters"])), Decimal("0.04"))
        self.assertEqual(r.json()["durationMin"], 30)
        self.assertEqual(r.json()["status"], "done")

        detail = self.client.get(f"{self.url}{rid}/").json()
        # 合法小数水量读回不得被掩码成 0
        self.assertEqual(Decimal(str(detail["waterLiters"])), Decimal("0.04"))
        self.assertEqual(detail["durationMin"], 30)
        self.assertEqual(detail["status"], "done")

    # ---------- 新建：非法组合必须 400 且中文 ----------

    def test_create_rejects_zero_and_negative_water(self):
        for bad in ("0", "0.00", "-1", "-0.01"):
            r = self.client.post(
                self.url, self.payload(waterLiters=bad), format="json"
            )
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("waterLiters", r.json())
            self.assertIn("水量必须大于 0", r.json()["waterLiters"][0])

    def test_create_rejects_bad_duration(self):
        for bad in (0, -1, 241, 300):
            r = self.client.post(
                self.url, self.payload(durationMin=bad), format="json"
            )
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("durationMin", r.json())
            self.assertIn("1 到 240", r.json()["durationMin"][0])

    def test_create_duration_must_be_integer(self):
        r = self.client.post(
            self.url, self.payload(durationMin="30.5"), format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("durationMin", r.json())

    def test_create_rejects_blank_or_wrong_case_status(self):
        for bad in ("", "  ", "Scheduled", "DONE", "Running", "finished", "null"):
            r = self.client.post(self.url, self.payload(status=bad), format="json")
            self.assertEqual(r.status_code, 400, repr(bad))
            self.assertIn("status", r.json())
            self.assertIn("状态只能是", r.json()["status"][0])

    def test_create_three_rules_hold_together(self):
        r = self.client.post(
            self.url,
            self.payload(waterLiters="0", durationMin=300, status=""),
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(set(body.keys()), {"waterLiters", "durationMin", "status"})

    # ---------- 更新：与新建完全同一套 ----------

    def _make_cycle(self, water="120.00", duration=20, status="scheduled"):
        r = self.client.post(
            self.url,
            self.payload(waterLiters=water, durationMin=duration, status=status),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def test_put_rejects_invalid_combo(self):
        rid = self._make_cycle()
        r = self.client.put(
            f"{self.url}{rid}/",
            self.payload(waterLiters="-5", durationMin=0, status="DONE"),
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            set(r.json().keys()), {"waterLiters", "durationMin", "status"}
        )
        # 拒绝后库内原值不变
        obj = IrrigationCycle.objects.get(pk=rid)
        self.assertEqual(obj.water_liters, Decimal("120.00"))
        self.assertEqual(obj.duration_min, 20)
        self.assertEqual(obj.status, "scheduled")

    def test_put_valid_updates_and_normalizes_readback(self):
        rid = self._make_cycle()
        r = self.client.put(
            f"{self.url}{rid}/",
            self.payload(waterLiters="88.50", durationMin=240, status="skipped"),
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Decimal(str(r.json()["waterLiters"])), Decimal("88.50"))
        self.assertEqual(r.json()["durationMin"], 240)
        self.assertEqual(r.json()["status"], "skipped")

    def test_patch_partial_uses_same_rules(self):
        rid = self._make_cycle()
        bad = self.client.patch(
            f"{self.url}{rid}/", {"status": ""}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("status", bad.json())

        ok = self.client.patch(
            f"{self.url}{rid}/", {"status": "running"}, format="json"
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["status"], "running")
        # 未提交的字段保持原值读回
        self.assertEqual(Decimal(str(ok.json()["waterLiters"])), Decimal("120.00"))
        self.assertEqual(ok.json()["durationMin"], 20)

    def test_boundary_duration_accepted(self):
        for d in (1, 240):
            r = self.client.post(
                self.url, self.payload(durationMin=d), format="json"
            )
            self.assertEqual(r.status_code, 201, (d, r.content))

    # ---------- 列表与仪表盘同一读出口径 ----------

    def test_list_sum_matches_dashboard_today_liters(self):
        # 今日：含一个以前会被掩码成 0 的小水量合法行
        self._make_cycle(water="0.04", duration=10, status="done")
        self._make_cycle(water="180.00", duration=25, status="scheduled")
        self._make_cycle(water="95.50", duration=30, status="running")
        # 昨日行不得计入今日
        old_start = (self.today - timedelta(days=1)).isoformat()
        r = self.client.post(
            self.url,
            self.payload(
                waterLiters="500.00", durationMin=40, status="done",
                startAt=old_start,
            ),
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

        rows = self.client.get(self.url).json()["results"]
        rows = [row for row in rows if _is_today(row["startAt"])]
        list_sum = sum(Decimal(str(row["waterLiters"])) for row in rows)

        dash = self.client.get("/api/dashboard/").json()
        self.assertEqual(
            Decimal(str(dash["irrigationTodayLiters"])), list_sum
        )
        self.assertEqual(list_sum, Decimal("275.54"))


def _is_today(iso):
    return timezone.now().date().isoformat() in iso[:10]


class NumbersTests(APITestCase):
    def test_read_water_keeps_small_legal_decimal(self):
        self.assertEqual(read_water(Decimal("0.04")), 0.04)
        self.assertEqual(read_water("180.00"), 180.0)

    def test_read_water_none_and_garbage_zero(self):
        self.assertEqual(read_water(None), 0.0)

    def test_sum_matches_repeated_reads(self):
        vals = [Decimal("0.04"), Decimal("180.00"), Decimal("95.50")]
        expected = round(sum(read_water(v) for v in vals), 2)
        self.assertEqual(round(sum_water(vals), 2), expected)
        self.assertEqual(sum_water(vals), 275.54)
