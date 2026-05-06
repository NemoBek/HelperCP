KEY_FIELD_NAMES = [
    "po_number",
    "po_date",
    "order_date",
    "invoice_number",
    "invoice_date",
    "packing_list_number",
    "packing_list_date",
    "contract_number",
    "proforma_invoice_number",
    "supplier",
    "buyer",
    "consignee",
    "notify_party",
    "ship_to",
    "bill_to",
    "currency",
    "incoterms",
    "payment_terms",
    "shipment_date",
    "delivery_date",
    "total_amount",
    "gross_weight",
    "net_weight",
    "packages",
    "country_of_origin",
    "hs_code",
    "marking",
    "container_number",
    "seal_number",
    "bl_awb_number",
    "vessel_flight",
]

LINE_ITEM_FIELD_NAMES = [
    "line_no",
    "material_code",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "total_amount",
    "currency",
    "gross_weight",
    "net_weight",
    "packages",
    "country_of_origin",
    "hs_code",
    "evidence",
    "confidence",
]

DOCUMENT_TYPES = {
    "PO",
    "INVOICE",
    "PACKING_LIST",
    "CERTIFICATE",
    "DRAWING",
    "SPECIFICATION",
    "TRANSPORT",
    "OTHER",
}


def sanitize_extraction(data):
    documents = data.get("documents", [])
    if not isinstance(documents, list):
        documents = []

    sanitized = {
        "documents": [_sanitize_document(doc, index) for index, doc in enumerate(documents, start=1)],
        "overall_notes": _string_list(data.get("overall_notes")),
    }

    return sanitized


def _sanitize_document(doc, index):
    if not isinstance(doc, dict):
        doc = {}

    document_type = str(doc.get("document_type") or "OTHER").upper().strip()
    if document_type not in DOCUMENT_TYPES:
        document_type = "OTHER"

    key_fields = doc.get("key_fields") if isinstance(doc.get("key_fields"), dict) else {}
    line_items = doc.get("line_items") if isinstance(doc.get("line_items"), list) else []

    return {
        "document_id": _value(doc.get("document_id")) or f"D{index}",
        "file_name": _value(doc.get("file_name")),
        "document_type": document_type,
        "pages": _value(doc.get("pages")) or "unknown",
        "language": _value(doc.get("language")) or "unknown",
        "quality": _quality(doc.get("quality")),
        "confidence": _confidence(doc.get("confidence")),
        "key_fields": {name: _value(key_fields.get(name)) for name in KEY_FIELD_NAMES},
        "line_items": [_sanitize_line_item(item) for item in line_items if isinstance(item, dict)],
        "extraction_notes": _string_list(doc.get("extraction_notes")),
    }


def _sanitize_line_item(item):
    cleaned = {name: _value(item.get(name)) for name in LINE_ITEM_FIELD_NAMES}
    cleaned["confidence"] = _confidence(item.get("confidence"))
    return cleaned


def _value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value).strip()


def _confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _quality(value):
    text = str(value or "medium").lower().strip()
    return text if text in {"good", "medium", "poor"} else "medium"


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [_value(item) for item in value if _value(item)]
