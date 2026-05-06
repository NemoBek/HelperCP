import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from checker import item_key, parse_decimal


class POStore:
    def __init__(self, path=".data/helpercp.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def shipped_quantity(self, po_number, key):
        if not po_number or not key:
            return Decimal("0")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT si.quantity
                FROM shipment_items si
                JOIN shipments s ON s.shipment_id = si.shipment_id
                WHERE s.po_number = ? AND si.item_key = ?
                """,
                (str(po_number), key),
            ).fetchall()

        total = Decimal("0")
        for row in rows:
            total += parse_decimal(row["quantity"]) or Decimal("0")
        return total

    def shipment_history(self, po_number):
        if not po_number:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.shipment_id, s.created_at, s.invoice_numbers,
                       si.material_code, si.description, si.quantity, si.unit
                FROM shipments s
                JOIN shipment_items si ON si.shipment_id = s.shipment_id
                WHERE s.po_number = ?
                ORDER BY s.created_at DESC, si.material_code, si.description
                """,
                (str(po_number),),
            ).fetchall()

        return [
            {
                "shipment_id": row["shipment_id"],
                "created_at": row["created_at"],
                "invoice_numbers": ", ".join(json.loads(row["invoice_numbers"] or "[]")),
                "material_code": row["material_code"] or "",
                "description": row["description"] or "",
                "quantity": row["quantity"] or "",
                "unit": row["unit"] or "",
            }
            for row in rows
        ]

    def save_shipment(self, po_number, invoice_numbers, invoice_items):
        if not po_number:
            return False, "Не найден номер PO"
        if not invoice_items:
            return False, "Нет позиций invoice для сохранения"

        shipment_id = self._shipment_id(po_number, invoice_numbers, invoice_items)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM shipments WHERE shipment_id = ?",
                (shipment_id,),
            ).fetchone()
            if exists:
                return False, "Эта отгрузка уже сохранена в истории"

            connection.execute(
                """
                INSERT INTO shipments (shipment_id, po_number, invoice_numbers, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (shipment_id, str(po_number), json.dumps(invoice_numbers, ensure_ascii=False), created_at),
            )
            connection.executemany(
                """
                INSERT INTO shipment_items (
                    shipment_id, item_key, material_code, description, quantity, unit
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        shipment_id,
                        item_key(item),
                        item.get("material_code"),
                        item.get("description"),
                        item.get("quantity"),
                        item.get("unit"),
                    )
                    for item in invoice_items
                ],
            )
            connection.commit()

        return True, "Отгрузка сохранена в истории PO"

    def _init_db(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shipments (
                    shipment_id TEXT PRIMARY KEY,
                    po_number TEXT NOT NULL,
                    invoice_numbers TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shipment_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    material_code TEXT,
                    description TEXT,
                    quantity TEXT,
                    unit TEXT,
                    FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_shipments_po ON shipments(po_number)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_items_key ON shipment_items(item_key)")
            connection.commit()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _shipment_id(po_number, invoice_numbers, invoice_items):
        payload = {
            "po_number": po_number,
            "invoice_numbers": invoice_numbers,
            "items": [
                {
                    "key": item_key(item),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                }
                for item in invoice_items
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
