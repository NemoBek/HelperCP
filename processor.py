import google.generativeai as genai
    2 import os
    3 import time
    4 import json
    5
    6 class DocProcessor:
    7     def __init__(self, api_key=None):
    8         if api_key:
    9             genai.configure(api_key=api_key)
   10             self.model = genai.GenerativeModel(
   11                 model_name='gemini-flash-latest',
   12                 generation_config={"response_mime_type": "application/json"}
   13             )
   14         else:
   15             self.model = None
   16
   17     def process_files(self, uploaded_files):
   18         if not self.model:
   19             return '{"error": "API ключ не настроен"}'
   20
   21         gemini_files = []
   22         temp_paths = []
   23
   24         try:
   25             # Загружаем файлы в облако Gemini
   26             for uploaded_file in uploaded_files:
   27                 temp_path = f"temp_{uploaded_file.name}"
   28                 with open(temp_path, "wb") as f:
   29                     f.write(uploaded_file.getbuffer())
   30
   31                 g_file = genai.upload_file(path=temp_path, display_name=uploaded_file.name)
   32                 gemini_files.append(g_file)
   33                 temp_paths.append(temp_path)
   34
   35             # Ожидание обработки файлов
   36             for g_file in gemini_files:
   37                 while g_file.state.name == "PROCESSING":
   38                     time.sleep(1)
   39                     g_file = genai.get_file(g_file.name)
   40
   41             prompt = """
   42             Ты - КРИТИЧЕСКИ настроенный старший координатор. Твоя цель - найти малейшие ошибки.
   43             ПОМНИ: PO является ГЛАВНЫМ документом. Invoice и Packing List могут содержать только ЧАСТЬ товаров из
      PO.
   44
   45             ТВОЯ ЗАДАЧА:
   46             1. Проверь общие данные: Номер PO, Даты, Условия поставки (Incoterms), Реквизиты.
   47             2. Для каждой позиции в Invoice/Packing List найди строку в PO.
   48             3. ПРОВЕРЬ: Цена за ед. (Unit Price), Количество (не превышает ли PO), Описание, Веса и Маркировку.
   49
   50             ПРАВИЛА СТАТУСА:
   51             - ✅: Идеальное совпадение.
   52             - ⚠️: Любое расхождение (даже в одну букву в маркировке или адресе).
   53
   54             ВЕРНИ JSON:
   55             {
   56                 "summary_table": [
   57                     {"parameter": "Наименование товара", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   58                     {"parameter": "Номер PO", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
   59                     {"parameter": "Дата заказа", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
   60                     {"parameter": "Позиция (Line Item)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   61                     {"parameter": "Цена за ед. (Unit Price)", "po": "...", "invoice": "...", "packing_list":
      "N/A", "status": "✅/⚠️"},
   62                     {"parameter": "Условия поставки", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   63                     {"parameter": "Вес Нетто (N.W)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   64                     {"parameter": "Вес Брутто (G.W)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   65                     {"parameter": "Объем (CBM)", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
   66                     {"parameter": "Маркировка", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"}
   67                 ],
   68                 "discrepancies": ["Детальное описание каждой найденной ошибки"],
   69                 "recommendations": ["Совет по исправлению"]
   70             }
   71             """
   72
   73             response = self.model.generate_content([prompt] + gemini_files)
   74             return response.text
   75
   76         except Exception as e:
   77             return json.dumps({"error": f"Ошибка: {str(e)}"})
   78         finally:
   79             # Всегда удаляем временные файлы для экономии места
   80             for p in temp_paths:
   81                 if os.path.exists(p): os.remove(p)
