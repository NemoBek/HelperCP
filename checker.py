from decimal import Decimal
from difflib import SequenceMatcher
import re

from normalizers import (
    company_similarity,
    normalize_code,
    normalize_company,
    normalize_currency,
    normalize_date,
    normalize_incoterms,
    normalize_text,
    ocr_suspect,
    parse_decimal,
    product_similarity,
    similarity,
)


OK = "OK"
OK_PARTIAL = "OK, partial shipment"
WARNING = "Warning"
CRITICAL = "Critical"
MANUAL = "Need manual review"


def build_check_report(extraction, store):
    documents = extraction.get("documents", [])
    po_docs = _documents_by_type(documents, "PO")
    invoice_docs = _documents_by_type(documents, "INVOICE")
    packing_docs = _documents_by_type(documents, "PACKING_LIST")

    rows = []
    recommendations = []

    if not po_docs:
        rows.append(_row(CRITICAL, "PO найден", "", "", "", "Не найден главный документ PO"))
        recommendations.append("Загрузите PO или проверьте, правильно ли ИИ распознал тип документа.")

    if not invoice_docs:
        rows.append(_row(WARNING, "Invoice найден", "", "", "", "Invoice не найден в загруженных файлах"))

    if not packing_docs:
        rows.append(_row(WARNING, "Packing List найден", "", "", "", "Packing List не найден в загруженных файлах"))

    po_items = _items_from(po_docs)
    invoice_items = _items_from(invoice_docs)
    packing_items = _items_from(packing_docs)
    po_number = _first_key_field(po_docs, "po_number")

    rows.extend(_check_header_fields(po_docs, invoice_docs, packing_docs))
    rows.extend(_check_document_dates(po_docs, invoice_docs, packing_docs))
    rows.extend(_check_invoice_items(po_items, invoice_items, packing_items, po_number, store))
    rows.extend(_quality_rows(documents))

    po_balance = build_po_balance(po_docs, store, invoice_items)
    can_save_shipment = bool(po_number and invoice_items and not _has_critical_item_error(rows))

    if po_number and invoice_items:
        recommendations.append(
            "Если проверка верна, сохраните отгрузку в историю PO, чтобы учитывать остатки в следующих партиях."
        )

    return {
        "check_rows": rows,
        "documents": documents,
        "extracted_items": _display_items(documents),
        "po_balance": po_balance,
        "shipment_history": store.shipment_history(po_number) if po_number else [],
        "recommendations": recommendations + extraction.get("overall_notes", []),
        "po_number": po_number,
        "invoice_numbers": [_field(doc, "invoice_number") for doc in invoice_docs if _field(doc, "invoice_number")],
        "invoice_items": invoice_items,
        "can_save_shipment": can_save_shipment,
    }


def build_po_balance(po_docs, store, current_invoice_items=None):
    rows = []
    current_invoice_items = current_invoice_items or []

    for po_doc in po_docs:
        po_number = _field(po_doc, "po_number")
        for item in po_doc.get("line_items", []):
            key = item_key(item)
            po_qty = parse_decimal(item.get("quantity"))
            shipped_qty = store.shipped_quantity(po_number, key) if po_number else Decimal("0")
            current_qty = _current_invoice_quantity(current_invoice_items, item)
            remaining_before = po_qty - shipped_qty if po_qty is not None else None
            remaining_after = remaining_before - current_qty if remaining_before is not None else None

            rows.append(
                {
                    "po_number": po_number or "",
                    "material_code": item.get("material_code") or "",
                    "description": item.get("description") or "",
                    "po_quantity": _fmt(po_qty),
                    "previously_shipped": _fmt(shipped_qty),
                    "current_invoice": _fmt(current_qty),
                    "remaining_after": _fmt(remaining_after),
                    "status": _balance_status(po_qty, shipped_qty, current_qty),
                }
            )

    return rows


def item_key(item):
    material = _clean(item.get("material_code"))
    if material:
        return f"material:{material}"
    return f"description:{_clean(item.get('description'))}"


def _check_header_fields(po_docs, invoice_docs, packing_docs):
    rows = []
    checks = [
        ("Номер PO", "po_number", "code"),
        ("Номер контракта", "contract_number", "code"),
        ("Поставщик", "supplier", "company"),
        ("Покупатель", "buyer", "company"),
        ("Грузополучатель", "consignee", "company"),
        ("Валюта", "currency", "currency"),
        ("Incoterms", "incoterms", "incoterms"),
        ("Условия оплаты", "payment_terms", "text"),
        ("Страна происхождения", "country_of_origin", "text"),
        ("HS code", "hs_code", "code"),
        ("Маркировка", "marking", "text"),
        ("Номер контейнера", "container_number", "code"),
        ("Номер пломбы", "seal_number", "code"),
        ("BL/AWB", "bl_awb_number", "code"),
    ]

    for label, key, kind in checks:
        po_value = _first_key_field(po_docs, key)
        invoice_value = _first_key_field(invoice_docs, key)
        packing_value = _first_key_field(packing_docs, key)
        present_values = [value for value in [po_value, invoice_value, packing_value] if value]

        if not present_values:
            continue

        if len(present_values) < 2:
            status = _single_source_status(key)
            detail = "Поле найдено только в одном типе документа"
        elif _values_match(present_values, kind):
            status = OK
            detail = _match_detail(kind, present_values)
        else:
            status = WARNING
            detail = "Есть расхождение между документами"

        rows.append(_row(status, label, po_value, invoice_value, packing_value, detail))

    return rows


def _check_document_dates(po_docs, invoice_docs, packing_docs):
    rows = []
    rows.extend(
        _check_date_presence(
            [
                ("Дата PO", po_docs, "po_date"),
                ("Дата заказа", po_docs, "order_date"),
                ("Дата invoice", invoice_docs, "invoice_date"),
                ("Дата packing list", packing_docs, "packing_list_date"),
                ("Дата отгрузки", invoice_docs + packing_docs, "shipment_date"),
            ]
        )
    )

    po_date = _first_parsed_date(po_docs, "po_date") or _first_parsed_date(po_docs, "order_date")
    invoice_date = _first_parsed_date(invoice_docs, "invoice_date")
    packing_date = _first_parsed_date(packing_docs, "packing_list_date")
    shipment_date = _first_parsed_date(invoice_docs + packing_docs, "shipment_date")

    if po_date and invoice_date:
        rows.append(_chronology_row("Дата invoice не раньше PO", po_date, invoice_date, "invoice_date >= po_date"))
    if po_date and shipment_date:
        rows.append(_chronology_row("Дата отгрузки не раньше PO", po_date, shipment_date, "shipment_date >= po_date"))
    if invoice_date and packing_date:
        rows.append(_same_or_manual_date_row("Дата invoice и packing list", invoice_date, packing_date))

    return rows


def _check_invoice_items(po_items, invoice_items, packing_items, po_number, store):
    rows = []

    for invoice_item in invoice_items:
        po_item = _match_item(invoice_item, po_items)
        packing_item = _match_item(invoice_item, packing_items)
        item_label = invoice_item.get("material_code") or invoice_item.get("description") or "Позиция без названия"

        if po_item is None:
            rows.append(
                _row(
                    CRITICAL,
                    f"Позиция invoice: {item_label}",
                    "",
                    _item_value(invoice_item),
                    _item_value(packing_item),
                    "Позиция не найдена в PO",
                    invoice_item.get("evidence"),
                )
            )
            continue

        rows.extend(_compare_item_values(po_item, invoice_item, packing_item, po_number, store))

    if po_items and invoice_items and len(invoice_items) < len(po_items):
        rows.append(
            _row(
                OK_PARTIAL,
                "Частичная отгрузка",
                f"{len(po_items)} позиций в PO",
                f"{len(invoice_items)} позиций в invoice",
                "",
                "Invoice содержит только часть позиций PO, это допустимо",
            )
        )

    return rows


def _compare_item_values(po_item, invoice_item, packing_item, po_number, store):
    label = invoice_item.get("material_code") or invoice_item.get("description") or "Позиция"
    rows = []

    rows.extend(_compare_item_identity(po_item, invoice_item, packing_item, label))

    po_qty = parse_decimal(po_item.get("quantity"))
    invoice_qty = parse_decimal(invoice_item.get("quantity"))
    shipped_qty = store.shipped_quantity(po_number, item_key(po_item)) if po_number else Decimal("0")
    remaining_qty = po_qty - shipped_qty if po_qty is not None else None

    if po_qty is None or invoice_qty is None:
        rows.append(_row(MANUAL, f"Количество: {label}", po_item.get("quantity"), invoice_item.get("quantity"), "", "Количество распознано не полностью"))
    elif remaining_qty is not None and invoice_qty > remaining_qty:
        rows.append(
            _row(
                CRITICAL,
                f"Количество: {label}",
                _fmt(remaining_qty),
                _fmt(invoice_qty),
                _field_value(packing_item, "quantity"),
                "Invoice превышает доступный остаток по PO",
                invoice_item.get("evidence"),
            )
        )
    elif invoice_qty < po_qty:
        status = MANUAL if ocr_suspect(po_item.get("quantity"), invoice_item.get("quantity")) else OK_PARTIAL
        detail = "Частичная отгрузка по позиции"
        if status == MANUAL:
            detail += ". Число содержит OCR-подозрительные символы, нужна ручная проверка."
        rows.append(_row(status, f"Количество: {label}", _fmt(po_qty), _fmt(invoice_qty), _field_value(packing_item, "quantity"), detail))
    else:
        status = MANUAL if ocr_suspect(po_item.get("quantity"), invoice_item.get("quantity")) else OK
        detail = "Количество не превышает PO"
        if status == MANUAL:
            detail += ". Совпало после OCR-нормализации, проверьте оригинал."
        rows.append(_row(status, f"Количество: {label}", _fmt(po_qty), _fmt(invoice_qty), _field_value(packing_item, "quantity"), detail))

    rows.append(_compare_decimal("Цена за единицу", "unit_price", po_item, invoice_item, packing_item, label, invoice_item.get("evidence")))
    rows.append(_check_invoice_line_total(po_item, invoice_item, packing_item, label, invoice_item.get("evidence")))

    if packing_item:
        rows.append(_compare_decimal("Вес брутто", "gross_weight", invoice_item, packing_item, None, label, packing_item.get("evidence"), left_name="invoice", right_name="packing_list"))
        rows.append(_compare_decimal("Вес нетто", "net_weight", invoice_item, packing_item, None, label, packing_item.get("evidence"), left_name="invoice", right_name="packing_list"))
    else:
        rows.append(_row(MANUAL, f"Packing List: {label}", "", _item_value(invoice_item), "", "Соответствующая позиция в Packing List не найдена"))

    return rows


def _compare_item_identity(po_item, invoice_item, packing_item, item_label):
    rows = []
    rows.append(
        _compare_item_code(
            po_item.get("material_code"),
            invoice_item.get("material_code"),
            _field_value(packing_item, "material_code"),
            item_label,
            invoice_item.get("evidence"),
        )
    )
    rows.append(
        _compare_item_description(
            po_item.get("description"),
            invoice_item.get("description"),
            _field_value(packing_item, "description"),
            item_label,
            invoice_item.get("evidence"),
        )
    )
    return rows


def _compare_item_code(po_value, invoice_value, packing_value, item_label, evidence=None):
    values = [value for value in [po_value, invoice_value, packing_value] if value]
    if len(values) < 2:
        return _row(MANUAL, f"Код товара: {item_label}", po_value, invoice_value, packing_value, "Недостаточно данных для сверки кода товара", evidence)

    if len({normalize_code(value) for value in values}) == 1:
        return _row(OK, f"Код товара: {item_label}", po_value, invoice_value, packing_value, "Код товара совпадает", evidence)

    return _row(WARNING, f"Код товара: {item_label}", po_value, invoice_value, packing_value, "Код товара отличается между документами", evidence)


def _compare_item_description(po_value, invoice_value, packing_value, item_label, evidence=None):
    values = [value for value in [po_value, invoice_value, packing_value] if value]
    if len(values) < 2:
        return _row(MANUAL, f"Наименование товара: {item_label}", po_value, invoice_value, packing_value, "Недостаточно данных для сверки наименования", evidence)

    normalized = [normalize_text(value) for value in values]
    if len(set(normalized)) == 1:
        return _row(OK, f"Наименование товара: {item_label}", po_value, invoice_value, packing_value, "Наименование совпадает", evidence)

    scores = [product_similarity(normalized[0], value) for value in normalized[1:]]
    if scores and min(scores) >= 0.78:
        return _row(OK, f"Наименование товара: {item_label}", po_value, invoice_value, packing_value, "Наименование совпадает с учетом сокращений/форматирования", evidence)

    return _row(WARNING, f"Наименование товара: {item_label}", po_value, invoice_value, packing_value, "Наименование товара отличается между документами", evidence)


def _compare_decimal(label, field, left_item, right_item, packing_item, item_label, evidence=None, left_name="po", right_name="invoice"):
    left = parse_decimal(left_item.get(field)) if left_item else None
    right = parse_decimal(right_item.get(field)) if right_item else None

    if left is None or right is None:
        return _row(MANUAL, f"{label}: {item_label}", _field_value(left_item, field), _field_value(right_item, field), _field_value(packing_item, field), "Недостаточно данных для автоматической сверки", evidence)

    if left == right:
        status = MANUAL if ocr_suspect(_field_value(left_item, field), _field_value(right_item, field)) else OK
        detail = f"{left_name} и {right_name} совпадают"
        if status == MANUAL:
            detail += " после OCR-нормализации, нужна ручная проверка оригинала"
        return _row(status, f"{label}: {item_label}", _fmt(left), _fmt(right), _field_value(packing_item, field), detail)

    return _row(WARNING, f"{label}: {item_label}", _fmt(left), _fmt(right), _field_value(packing_item, field), f"{left_name} и {right_name} расходятся", evidence)


def _check_invoice_line_total(po_item, invoice_item, packing_item, item_label, evidence=None):
    invoice_qty = parse_decimal(invoice_item.get("quantity"))
    invoice_price = parse_decimal(invoice_item.get("unit_price")) or parse_decimal(po_item.get("unit_price"))
    invoice_total = parse_decimal(invoice_item.get("total_amount"))

    if invoice_qty is None or invoice_price is None or invoice_total is None:
        return _row(
            MANUAL,
            f"Сумма invoice: {item_label}",
            "qty * unit price",
            invoice_item.get("total_amount"),
            _field_value(packing_item, "total_amount"),
            "Недостаточно данных, чтобы пересчитать сумму invoice",
            evidence,
        )

    expected = invoice_qty * invoice_price
    if expected == invoice_total:
        status = MANUAL if ocr_suspect(invoice_item.get("quantity"), invoice_item.get("unit_price"), invoice_item.get("total_amount")) else OK
        detail = "Сумма invoice корректно пересчитана по количеству и цене"
        if status == MANUAL:
            detail += " после OCR-нормализации, проверьте оригинал"
        return _row(status, f"Сумма invoice: {item_label}", _fmt(expected), _fmt(invoice_total), _field_value(packing_item, "total_amount"), detail, evidence)

    return _row(
        WARNING,
        f"Сумма invoice: {item_label}",
        _fmt(expected),
        _fmt(invoice_total),
        _field_value(packing_item, "total_amount"),
        "Сумма invoice не равна quantity * unit price",
        evidence,
    )


def _quality_rows(documents):
    rows = []
    for doc in documents:
        quality = doc.get("quality") or "unknown"
        confidence = doc.get("confidence")
        if quality == "poor" or (isinstance(confidence, (int, float)) and confidence < 0.65):
            rows.append(
                _row(
                    MANUAL,
                    f"Качество документа: {doc.get('file_name', '')}",
                    doc.get("document_type", ""),
                    quality,
                    "",
                    "Низкое качество или уверенность распознавания. Нужна ручная проверка.",
                )
            )
    return rows


def _values_match(values, kind):
    normalized = [_normalize_for_kind(value, kind) for value in values if value not in (None, "")]
    normalized = [value for value in normalized if value]
    if len(normalized) < 2:
        return False

    if kind in {"code", "date", "currency", "incoterms"}:
        return len(set(normalized)) == 1

    if len(set(normalized)) == 1:
        return True

    if kind == "company":
        return all(company_similarity(normalized[0], value) >= 0.78 for value in normalized[1:])

    return all(similarity(normalized[0], value) >= 0.86 for value in normalized[1:])


def _normalize_for_kind(value, kind):
    if kind == "code":
        return normalize_code(value)
    if kind == "date":
        return normalize_date(value)
    if kind == "currency":
        return normalize_currency(value)
    if kind == "incoterms":
        return normalize_incoterms(value)
    if kind == "company":
        return normalize_company(value)
    return normalize_text(value)


def _match_detail(kind, values):
    if kind == "currency":
        return "Валюта совпадает после нормализации"
    if kind == "incoterms":
        return "Код Incoterms совпадает; место может быть уточнено в одном документе"
    if kind == "company":
        return "Название компании совпадает с учетом регистра, сокращений и юр. формы"
    return "Значения совпадают"


def _single_source_status(key):
    reference_only_fields = {
        "consignee",
        "notify_party",
        "ship_to",
        "bill_to",
        "country_of_origin",
        "hs_code",
        "marking",
        "container_number",
        "seal_number",
        "bl_awb_number",
        "payment_terms",
    }
    return OK if key in reference_only_fields else MANUAL


def _check_date_presence(date_checks):
    rows = []
    for label, documents, key in date_checks:
        value = _first_key_field(documents, key)
        if not value:
            continue

        parsed = normalize_date(value)
        if not parsed:
            rows.append(_row(MANUAL, label, value, "", "", "Дата есть, но формат не удалось надежно распознать"))
        else:
            rows.append(_row(OK, label, value, parsed, "", "Дата распознана и нормализована"))
    return rows


def _first_parsed_date(documents, key):
    for doc in documents:
        value = _field(doc, key)
        parsed = normalize_date(value)
        if parsed:
            return parsed
    return ""


def _chronology_row(label, earlier_date, later_date, detail):
    if later_date >= earlier_date:
        return _row(OK, label, earlier_date, later_date, "", detail)
    return _row(WARNING, label, earlier_date, later_date, "", "Хронология дат выглядит подозрительно")


def _same_or_manual_date_row(label, left_date, right_date):
    if left_date == right_date:
        return _row(OK, label, left_date, right_date, "", "Даты совпадают")
    return _row(MANUAL, label, left_date, right_date, "", "Даты отличаются. Это может быть нормально, нужна проверка контекста.")


def _documents_by_type(documents, document_type):
    return [doc for doc in documents if _clean(doc.get("document_type")) == _clean(document_type)]


def _items_from(documents):
    items = []
    for doc in documents:
        for item in doc.get("line_items", []) or []:
            item = dict(item)
            item["_document_id"] = doc.get("document_id")
            item["_file_name"] = doc.get("file_name")
            items.append(item)
    return items


def _match_item(target, candidates):
    if not target or not candidates:
        return None

    target_key = item_key(target)
    for candidate in candidates:
        if item_key(candidate) == target_key and target_key != "description:":
            return candidate

    target_text = _clean(target.get("description"))
    best = None
    best_score = 0
    for candidate in candidates:
        score = SequenceMatcher(None, target_text, _clean(candidate.get("description"))).ratio()
        if score > best_score:
            best = candidate
            best_score = score

    return best if best_score >= 0.72 else None


def _current_invoice_quantity(invoice_items, po_item):
    total = Decimal("0")
    for invoice_item in invoice_items:
        if _match_item(invoice_item, [po_item]):
            total += parse_decimal(invoice_item.get("quantity")) or Decimal("0")
    return total


def _balance_status(po_qty, shipped_qty, current_qty):
    if po_qty is None:
        return MANUAL
    if shipped_qty + current_qty > po_qty:
        return CRITICAL
    if shipped_qty + current_qty == po_qty:
        return OK
    return OK_PARTIAL


def _has_critical_item_error(rows):
    return any(row.get("status") == CRITICAL for row in rows)


def _display_items(documents):
    rows = []
    for doc in documents:
        for item in doc.get("line_items", []) or []:
            rows.append(
                {
                    "document": doc.get("document_type", ""),
                    "file": doc.get("file_name", ""),
                    "line_no": item.get("line_no", ""),
                    "material_code": item.get("material_code", ""),
                    "description": item.get("description", ""),
                    "quantity": item.get("quantity", ""),
                    "unit": item.get("unit", ""),
                    "unit_price": item.get("unit_price", ""),
                    "total_amount": item.get("total_amount", ""),
                    "currency": item.get("currency", ""),
                    "confidence": item.get("confidence", ""),
                    "evidence": item.get("evidence", ""),
                }
            )
    return rows


def _first_key_field(documents, key):
    for doc in documents:
        value = _field(doc, key)
        if value:
            return value
    return ""


def _field(doc, key):
    return (doc.get("key_fields") or {}).get(key)


def _field_value(item, key):
    if not item:
        return ""
    return item.get(key) or ""


def _item_value(item):
    if not item:
        return ""
    parts = [item.get("material_code"), item.get("description"), item.get("quantity")]
    return " | ".join(str(part) for part in parts if part)


def _row(status, check, po, invoice, packing_list, detail, evidence=""):
    return {
        "status": status,
        "check": check,
        "po": _display_value(po),
        "invoice": _display_value(invoice),
        "packing_list": _display_value(packing_list),
        "detail": detail,
        "evidence": _display_value(evidence),
    }


def _display_value(value):
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text else "N/A"


def _clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)
