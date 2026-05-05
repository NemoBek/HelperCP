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
   25             for uploaded_file in uploaded_files:
   26                 temp_path = f"temp_{uploaded_file.name}"
   27                 with open(temp_path, "wb") as f:
   28                     f.write(uploaded_file.getbuffer())
   29
   30                 g_file = genai.upload_file(path=temp_path, display_name=uploaded_file.name)
   31                 gemini_files.append(g_file)
   32                 temp_paths.append(temp_path)
   33
   34             for g_file in gemini_files:
   35                 while g_file.state.name == "PROCESSING":
   36                     time.sleep(1)
   37                     g_file = genai.get_file(g_file.name)
   38
   39             prompt = """
   40             Ты - КРИТИЧЕСКИ настроенный старший координатор. Твоя цель - найти малейшие ошибки.
   41             ПОМНИ: PO является ГЛАВНЫМ документом. Invoice и Packing List могут содержать только ЧАСТЬ товаров из
      PO (частичная отгрузка).
   42
   43             ТВОЯ ЗАДАЧА:
   44             1. Для каждой позиции в Invoice/Packing List найди соответствующую строку (Line Item) в PO по Material
      Code или Наименованию.
   45             2. ПРОВЕРЬ:
   46                - Совпадает ли цена за единицу товара (Unit Price) для этой позиции.
   47                - Не превышает ли количество в инвойсе количество в PO.
   48                - Совпадают ли технические характеристики.
   49             3. Если в инвойсе только часть товаров из PO - это НОРМАЛЬНО, но укажи это в отчете.
   50
   51             ПРАВИЛА СТАТУСА:
   52             - Ставь ✅ если позиция из инвойса полностью соответствует своей строке в PO.
   53             - Ставь ⚠️ если есть расхождение в цене, количестве или если позиция не найдена.
   54
   55             ВЕРНИ JSON со следующим списком параметров:
   56             {
   57                 "summary_table": [
   58                     {"parameter": "Наименование товара", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   59                     {"parameter": "Номер PO", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
   60                     {"parameter": "Дата заказа", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"},
   61                     {"parameter": "Позиция (Line Item) из инвойса", "po": "значение в PO", "invoice": "значение в
      инвойсе", "packing_list": "...", "status": "✅/⚠️"},
   62                     {"parameter": "Цена за ед. (Unit Price)", "po": "...", "invoice": "...", "packing_list":
      "N/A", "status": "✅/⚠️"},
   63                     {"parameter": "Общая сумма (Total)", "po": "...", "invoice": "...", "packing_list": "N/A",
      "status": "✅/⚠️"},
   64                     {"parameter": "Вес Брутто (G.W)", "po": "...", "invoice": "...", "packing_list": "...",
      "status": "✅/⚠️"},
   65                     {"parameter": "Маркировка", "po": "...", "invoice": "...", "packing_list": "...", "status":
      "✅/⚠️"}
   66                 ],
   67                 "discrepancies": ["Детальное описание ошибки"],
   68                 "recommendations": ["Совет"]
   69             }
   70             """
   71
   72             response = self.model.generate_content([prompt] + gemini_files)
   73
   74             for p in temp_paths:
   75                 if os.path.exists(p): os.remove(p)
   76
   77             return response.text
   78
   79         except Exception as e:
   80             return json.dumps({"error": f"Ошибка обработки: {str(e)}"})
