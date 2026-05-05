import google.generativeai as genai
import os
import time
import json

class DocProcessor:
     def __init__(self, api_key=None):
         if api_key:
             genai.configure(api_key=api_key)
             self.model = genai.GenerativeModel(
                 model_name='gemini-flash-latest',
                 generation_config={"response_mime_type": "application/json"}
             )
         else:
             self.model = None

     def process_files(self, uploaded_files):
         if not self.model:
             return '{"error": "API ключ не настроен"}'

         gemini_files = []
         temp_paths = []

         try:
             # Загружаем файлы в облако Gemini
             for uploaded_file in uploaded_files:
                 temp_path = f"temp_{uploaded_file.name}"
                 with open(temp_path, "wb") as f:
                     f.write(uploaded_file.getbuffer())

                 g_file = genai.upload_file(path=temp_path, display_name=uploaded_file.name)
                 gemini_files.append(g_file)
                 temp_paths.append(temp_path)

             # Ожидание обработки файлов
             for g_file in gemini_files:
                 while g_file.state.name == "PROCESSING":
                     time.sleep(1)
                     g_file = genai.get_file(g_file.name)

             prompt = """
             Ты - КРИТИЧЕСКИ настроенный старший координатор. Твоя цель - найти малейшие ошибки.
             ПОМНИ: PO является ГЛАВНЫМ документом. Invoice и Packing List могут содержать только ЧАСТЬ товаров из
      PO.

             ТВОЯ ЗАДАЧА:
             1. Проверь общие данные: Номер PO, Даты, Условия поставки (Incoterms), Реквизиты.
             2. Для каждой позиции в Invoice/Packing List найди строку в PO.
             3. ПРОВЕРЬ: Цена за ед. (Unit Price), Количество (не превышает ли PO), Описание, Веса и Маркировку.

             ПРАВИЛА СТАТУСА:
             - ✅: Идеальное совпадение.
             - ⚠️: Любое расхождение (даже в одну букву в маркировке или адресе).

             ВЕРНИ JSON:
             {
                 "summary_table": [
                     {"parameter": "Наименование товара", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
                     {"parameter": "Номер PO", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
                     {"parameter": "Дата заказа", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
                     {"parameter": "Позиция (Line Item)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
                     {"parameter": "Цена за ед. (Unit Price)", "po": "...", "invoice": "...", "packing_list":
      "N/A", "status": "✅/⚠️"},
                     {"parameter": "Условия поставки", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
                     {"parameter": "Вес Нетто (N.W)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
                     {"parameter": "Вес Брутто (G.W)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
                     {"parameter": "Объем (CBM)", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
                     {"parameter": "Маркировка", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"}
                 ],
                 "discrepancies": ["Детальное описание каждой найденной ошибки"],
                 "recommendations": ["Совет по исправлению"]
             }
             """

             response = self.model.generate_content([prompt] + gemini_files)
             return response.text

         except Exception as e:
               return json.dumps({"error": f"Ошибка: {str(e)}"})
         finally:
             # Всегда удаляем временные файлы для экономии места
             for p in temp_paths:
                 if os.path.exists(p): os.remove(p)
