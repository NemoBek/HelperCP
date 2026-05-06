from io import BytesIO

import pandas as pd


def build_excel_report(report, extraction):
    output = BytesIO()

    sheets = {
        "Check": report.get("check_rows", []),
        "Documents": _document_rows(report.get("documents", [])),
        "Items": report.get("extracted_items", []),
        "PO Balance": report.get("po_balance", []),
        "PO History": report.get("shipment_history", []),
        "Recommendations": [{"recommendation": item} for item in report.get("recommendations", [])],
        "Local Extraction": _local_extraction_rows(extraction.get("local_extractions", [])),
    }

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            dataframe = pd.DataFrame(rows or [{"info": "N/A"}]).fillna("N/A")
            dataframe = dataframe.replace("", "N/A")
            dataframe.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            worksheet = writer.sheets[sheet_name[:31]]
            _format_sheet(worksheet, dataframe)

    output.seek(0)
    return output.getvalue()


def _document_rows(documents):
    rows = []
    for doc in documents:
        rows.append(
            {
                "document_id": doc.get("document_id", ""),
                "file_name": doc.get("file_name", ""),
                "type": doc.get("document_type", ""),
                "pages": doc.get("pages", ""),
                "language": doc.get("language", ""),
                "quality": doc.get("quality", ""),
                "confidence": doc.get("confidence", ""),
                "notes": "; ".join(doc.get("extraction_notes", []) or []),
            }
        )
    return rows


def _local_extraction_rows(local_extractions):
    return [
        {
            "file_name": item.get("file_name", ""),
            "status": item.get("status", ""),
            "error": item.get("error", ""),
            "text_preview": (item.get("text", "") or "")[:1000],
        }
        for item in local_extractions
    ]


def _format_sheet(worksheet, dataframe):
    worksheet.freeze_panes = "A2"
    for column_cells in worksheet.columns:
        header = column_cells[0].value or ""
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        width = min(max(max_length + 2, len(str(header)) + 2), 60)
        worksheet.column_dimensions[column_cells[0].column_letter].width = width
