import json
import tempfile
import time
from pathlib import Path

from local_extractors import extract_local_text
from schemas import sanitize_extraction

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - depends on local environment
    genai = None
    types = None


DOCUMENT_EXTRACTION_PROMPT = """
Ты - внимательный помощник таможенного координатора.

Твоя задача на этом этапе НЕ проверять документы окончательно, а извлечь из них
структурированные данные максимально точно. Документы могут быть на русском,
английском или смешанном языке. Файлы могут быть плохого качества: сканы, фото,
повернутые страницы, размытые PDF. Если значение плохо читается, укажи низкую
уверенность и не выдумывай.

Важно:
- В одной загрузке может быть любое количество файлов.
- В одном PDF может быть несколько разных документов.
- Определи тип каждого документа или диапазона страниц.
- PO является главным документом, но invoice может содержать только часть PO.
- Пока не делай финальный вывод о несоответствиях. Только извлеки факты.
- Сохраняй числовые значения так, как они видны в документе. Если похоже, что
  OCR мог перепутать символы (например I00 вместо 100, O вместо 0), укажи это
  в evidence или extraction_notes и снизь confidence.
- Если ниже передан локально извлеченный текст/таблицы, используй их как более
  точный источник для обычных PDF/Excel/Word, но сверяй с визуальным файлом,
  особенно если документ плохого качества или это скан.

Верни только валидный JSON без Markdown:
{
  "documents": [
    {
      "document_id": "D1",
      "file_name": "исходное имя файла",
      "document_type": "PO | INVOICE | PACKING_LIST | CERTIFICATE | DRAWING | SPECIFICATION | TRANSPORT | OTHER",
      "pages": "1-2 или unknown",
      "language": "ru/en/mixed/unknown",
      "quality": "good | medium | poor",
      "confidence": 0.0,
      "key_fields": {
        "po_number": null,
        "po_date": null,
        "order_date": null,
        "invoice_number": null,
        "invoice_date": null,
        "packing_list_number": null,
        "packing_list_date": null,
        "contract_number": null,
        "proforma_invoice_number": null,
        "supplier": null,
        "buyer": null,
        "consignee": null,
        "notify_party": null,
        "ship_to": null,
        "bill_to": null,
        "currency": null,
        "incoterms": null,
        "payment_terms": null,
        "shipment_date": null,
        "delivery_date": null,
        "total_amount": null,
        "gross_weight": null,
        "net_weight": null,
        "packages": null,
        "country_of_origin": null,
        "hs_code": null,
        "marking": null,
        "container_number": null,
        "seal_number": null,
        "bl_awb_number": null,
        "vessel_flight": null
      },
      "line_items": [
        {
          "line_no": null,
          "material_code": null,
          "description": null,
          "quantity": null,
          "unit": null,
          "unit_price": null,
          "total_amount": null,
          "currency": null,
          "gross_weight": null,
          "net_weight": null,
          "packages": null,
          "country_of_origin": null,
          "hs_code": null,
          "evidence": "страница/строка/фрагмент, откуда взято значение",
          "confidence": 0.0
        }
      ],
      "extraction_notes": [
        "что было плохо видно, какие поля требуют ручной проверки"
      ]
    }
  ],
  "overall_notes": [
    "общие наблюдения по качеству документов"
  ]
}
"""


class DocProcessor:
    def __init__(self, api_key=None, model_name="gemini-2.5-flash", timeout_seconds=180):
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.client = None

        if api_key and genai is not None:
            self.client = genai.Client(api_key=api_key)

    def process_files(self, uploaded_files):
        if not self.api_key:
            return {"error": "API ключ не настроен"}

        if genai is None:
            return {
                "error": (
                    "Не установлен новый Gemini SDK. Установите зависимости: "
                    "pip install -r requirements.txt"
                )
            }

        if not uploaded_files:
            return {"error": "Файлы не загружены"}

        try:
            with tempfile.TemporaryDirectory(prefix="helpercp_") as temp_dir:
                gemini_files, local_extractions = self._upload_files(uploaded_files, Path(temp_dir))
                ready_files = self._wait_for_files(gemini_files)
                raw_text = self._generate_extraction(ready_files, local_extractions)
                parsed = self._parse_json(raw_text)
                parsed["raw_response"] = raw_text
                parsed["local_extractions"] = local_extractions
                return parsed
        except Exception as exc:
            return {"error": f"Ошибка обработки: {exc}"}

    def _upload_files(self, uploaded_files, temp_dir):
        gemini_files = []
        local_extractions = []

        for index, uploaded_file in enumerate(uploaded_files, start=1):
            original_name = getattr(uploaded_file, "name", f"document_{index}")
            suffix = Path(original_name).suffix or ".bin"
            temp_path = temp_dir / f"document_{index}{suffix}"

            with temp_path.open("wb") as file_handle:
                file_handle.write(uploaded_file.getbuffer())

            uploaded = self.client.files.upload(
                file=str(temp_path),
                config={"display_name": original_name},
            )
            gemini_files.append(uploaded)
            local_extractions.append(extract_local_text(temp_path, original_name))

        return gemini_files, local_extractions

    def _wait_for_files(self, gemini_files):
        ready_files = []
        deadline = time.time() + self.timeout_seconds

        for file_obj in gemini_files:
            current = file_obj

            while self._state_name(current) == "PROCESSING":
                if time.time() > deadline:
                    raise TimeoutError("Gemini слишком долго обрабатывает файл")
                time.sleep(1)
                current = self.client.files.get(name=current.name)

            if self._state_name(current) == "FAILED":
                raise RuntimeError(f"Gemini не смог обработать файл: {current.name}")

            ready_files.append(current)

        return ready_files

    def _generate_extraction(self, gemini_files, local_extractions):
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )
        local_context = self._local_context(local_extractions)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[DOCUMENT_EXTRACTION_PROMPT, local_context, *gemini_files],
            config=config,
        )
        return response.text or ""

    @staticmethod
    def _local_context(local_extractions):
        parts = ["Локально извлеченный текст/таблицы из файлов:"]
        for extraction in local_extractions:
            parts.append(f"\n--- {extraction['file_name']} ({extraction['status']}) ---")
            if extraction.get("error"):
                parts.append(f"Local extraction error: {extraction['error']}")
            if extraction.get("text"):
                parts.append(extraction["text"])
        return "\n".join(parts)

    @staticmethod
    def _state_name(file_obj):
        state = getattr(file_obj, "state", None)
        if state is None:
            return "ACTIVE"
        return getattr(state, "name", str(state)).upper()

    @staticmethod
    def _parse_json(raw_text):
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Gemini вернул JSON не в формате объекта")

        return sanitize_extraction(data)
