from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import BoardModel, InventoryItem, Project, WiringDiagram


class WiringDiagramApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="wiring-owner",
            email="wiring-owner@example.com",
            password="test-password",
        )
        self.other = User.objects.create_user(
            username="wiring-other",
            email="wiring-other@example.com",
            password="test-password",
        )
        permissions = Permission.objects.filter(
            content_type__app_label="core",
            codename__in=[
                "add_wiringdiagram",
                "change_wiringdiagram",
                "delete_wiringdiagram",
            ],
        )
        self.owner.user_permissions.add(*permissions)
        self.other.user_permissions.add(*permissions)
        self.project = Project.objects.create(
            owner=self.owner,
            created_by=self.owner,
            name="Wiring Test Project",
        )
        self.other_project = Project.objects.create(
            owner=self.other,
            created_by=self.other,
            name="Other Wiring Project",
        )
        self.board = BoardModel.objects.create(
            name="Wiring Test Board",
            family="ESP32",
            mcu="ESP32-C3",
            pinout={"pins": [{"name": "GPIO4"}, {"name": "GND"}]},
        )
        self.inventory = InventoryItem.objects.create(
            owner=self.owner,
            inventory_id="OTH-0042",
            item_type="other",
            custom_name="Owner terminal block",
            quantity=1,
        )
        self.other_inventory = InventoryItem.objects.create(
            owner=self.other,
            inventory_id="OTH-0099",
            item_type="other",
            custom_name="Private other terminal",
            quantity=1,
        )
        self.client.force_login(self.owner)

    def test_create_and_list_project_wiring_diagram(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/wiring/",
            data={"name": "Main wiring", "description": "Control wiring"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["item"]
        self.assertEqual(item["project_id"], str(self.project.id))
        self.assertEqual(item["node_count"], 0)
        self.assertEqual(item["connection_count"], 0)

        response = self.client.get(f"/api/projects/{self.project.id}/wiring/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([row["name"] for row in response.json()["rows"]], ["Main wiring"])

    def test_project_wiring_is_owner_scoped(self):
        diagram = WiringDiagram.objects.create(
            owner=self.other,
            project=self.other_project,
            name="Private diagram",
        )
        response = self.client.get(
            f"/api/projects/{self.other_project.id}/wiring/{diagram.id}/"
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.get(f"/api/projects/{self.other_project.id}/wiring/")
        self.assertEqual(response.status_code, 404)

    def test_structured_nodes_connections_and_pin_hints_round_trip(self):
        diagram = WiringDiagram.objects.create(
            owner=self.owner,
            project=self.project,
            name="Structured",
        )
        payload = {
            "nodes": [
                {
                    "id": "node-board",
                    "type": "board",
                    "reference_id": str(self.board.id),
                    "label": "",
                    "x": 40,
                    "y": 60,
                    "notes": "",
                },
                {
                    "id": "node-power",
                    "type": "custom",
                    "reference_id": "",
                    "label": "5V supply",
                    "x": 300,
                    "y": 60,
                    "notes": "",
                },
            ],
            "connections": [
                {
                    "id": "wire-power",
                    "from_node": "node-power",
                    "from_pin": "5V",
                    "to_node": "node-board",
                    "to_pin": "VIN",
                    "label": "Power",
                    "color": "#ff0000",
                    "notes": "",
                }
            ],
            "canvas": {"show_grid": True, "zoom": 1},
        }
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["item"]
        self.assertEqual(item["revision"], 2)
        self.assertEqual(item["node_count"], 2)
        self.assertEqual(item["connection_count"], 1)
        board_node = next(node for node in item["nodes"] if node["id"] == "node-board")
        self.assertEqual(board_node["label"], "Wiring Test Board")
        self.assertIn("GPIO4", board_node["reference"]["pin_hints"])
        self.assertTrue(any(warning["code"] == "no-common-ground" for warning in item["warnings"]))

    def test_ground_to_power_is_reported_as_error(self):
        self.board.pinout = {
            "pins": [
                {"name": "GND", "role": "ground"},
                {"name": "3V3", "role": "power_output", "voltage": 3.3},
            ]
        }
        self.board.save(update_fields=["pinout", "updated_at"])
        sensor = BoardModel.objects.create(
            name="Sensor board",
            pinout={"pins": [{"name": "VCC", "role": "power_input", "min_voltage": 3.0, "max_voltage": 3.6}]},
        )
        diagram = WiringDiagram.objects.create(owner=self.owner, project=self.project, name="Bad power")
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data={
                "nodes": [
                    {"id": "controller", "type": "board", "reference_id": str(self.board.id), "label": "", "x": 0, "y": 0},
                    {"id": "sensor", "type": "board", "reference_id": str(sensor.id), "label": "", "x": 240, "y": 0},
                ],
                "connections": [
                    {"id": "bad-wire", "from_node": "controller", "from_pin": "GND", "to_node": "sensor", "to_pin": "VCC"}
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["item"]
        self.assertTrue(any(row["code"] == "ground-power-conflict" and row["severity"] == "error" for row in item["diagnostics"]))
        self.assertEqual(item["diagnostic_summary"]["connections"]["bad-wire"], "error")

    def test_power_voltage_range_is_checked(self):
        source = BoardModel.objects.create(
            name="5V source",
            pinout={"pins": [{"name": "5V", "role": "power_output", "voltage": 5.0}]},
        )
        target = BoardModel.objects.create(
            name="3V3 target",
            pinout={"pins": [{"name": "VCC", "role": "power_input", "min_voltage": 3.0, "max_voltage": 3.6}]},
        )
        diagram = WiringDiagram.objects.create(owner=self.owner, project=self.project, name="Voltage")
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data={
                "nodes": [
                    {"id": "source", "type": "board", "reference_id": str(source.id), "label": "", "x": 0, "y": 0},
                    {"id": "target", "type": "board", "reference_id": str(target.id), "label": "", "x": 240, "y": 0},
                ],
                "connections": [{"id": "power", "from_node": "source", "from_pin": "5V", "to_node": "target", "to_pin": "VCC"}],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(any(row["code"] == "overvoltage" and row["severity"] == "error" for row in response.json()["item"]["diagnostics"]))

    def test_uart_direction_mismatch_is_warning_and_tx_rx_is_valid(self):
        left = BoardModel.objects.create(name="UART left", pinout={"pins": [{"name": "TX", "role": "uart_tx"}, {"name": "RX", "role": "uart_rx"}]})
        right = BoardModel.objects.create(name="UART right", pinout={"pins": [{"name": "TX", "role": "uart_tx"}, {"name": "RX", "role": "uart_rx"}]})
        diagram = WiringDiagram.objects.create(owner=self.owner, project=self.project, name="UART")
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data={
                "nodes": [
                    {"id": "left", "type": "board", "reference_id": str(left.id), "label": "", "x": 0, "y": 0},
                    {"id": "right", "type": "board", "reference_id": str(right.id), "label": "", "x": 240, "y": 0},
                ],
                "connections": [
                    {"id": "wrong", "from_node": "left", "from_pin": "TX", "to_node": "right", "to_pin": "TX"},
                    {"id": "right-wire", "from_node": "left", "from_pin": "RX", "to_node": "right", "to_pin": "TX"},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["item"]
        self.assertEqual(item["diagnostic_summary"]["connections"]["wrong"], "warning")
        self.assertEqual(item["diagnostic_summary"]["connections"]["right-wire"], "valid")

    def test_private_inventory_cannot_be_referenced_in_another_users_wiring(self):
        diagram = WiringDiagram.objects.create(
            owner=self.owner,
            project=self.project,
            name="Isolation",
        )
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data={
                "nodes": [{
                    "id": "node-private",
                    "type": "inventory",
                    "reference_id": str(self.other_inventory.id),
                    "label": "",
                    "x": 10,
                    "y": 10,
                }],
                "connections": [],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        diagram.refresh_from_db()
        self.assertEqual(diagram.nodes, [])

    def test_duplicate_pin_to_pin_connection_is_rejected(self):
        diagram = WiringDiagram.objects.create(
            owner=self.owner,
            project=self.project,
            name="Duplicate check",
        )
        nodes = [
            {"id": "a", "type": "custom", "label": "A", "x": 0, "y": 0},
            {"id": "b", "type": "custom", "label": "B", "x": 200, "y": 0},
        ]
        duplicate_edges = [
            {"id": "one", "from_node": "a", "from_pin": "1", "to_node": "b", "to_pin": "2"},
            {"id": "two", "from_node": "b", "from_pin": "2", "to_node": "a", "to_pin": "1"},
        ]
        response = self.client.patch(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/",
            data={"nodes": nodes, "connections": duplicate_edges},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_delete_wiring_diagram(self):
        diagram = WiringDiagram.objects.create(
            owner=self.owner,
            project=self.project,
            name="Disposable",
        )
        response = self.client.delete(
            f"/api/projects/{self.project.id}/wiring/{diagram.id}/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(WiringDiagram.objects.filter(pk=diagram.id).exists())
