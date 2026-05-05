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
        """
        Загружает файлы в Gemini и запускает анализ.
        """
        if not self.model:
            return '{"error": "API ключ не настроен"}'

        gemini_files = []
        temp_paths = []

        try:
            # 1. Сохраняем файлы временно и загружаем в Gemini
            for uploaded_file in uploaded_files:
                temp_path = f"temp_{uploaded_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Загружаем файл в облако Gemini для анализа
                g_file = genai.upload_file(path=temp_path, display_name=uploaded_file.name)
                gemini_files.append(g_file)
                temp_paths.append(temp_path)

            # 2. Ждем обработки файлов (обычно мгновенно)
            for g_file in gemini_files:
                while g_file.state.name == "PROCESSING":
                    time.sleep(1)
                    g_file = genai.get_file(g_file.name)

            # 3. Формируем запрос
            prompt = """
            Ты - КРИТИЧЕСКИ настроенный старший координатор. Твоя цель - найти малейшие ошибки.
            Проведи детальную перекрестную сверку между всеми документами.
            
            ПРАВИЛА СТАТУСА:
            - Ставь ✅ только если данные ИДЕАЛЬНО совпадают или означают одно и то же (напр. 1.00 и 1).
            - Ставь ⚠️ если есть ЛЮБОЕ текстовое различие, отсутствие данных или несовпадение (напр. в Маркировке, Адресах или Датах).
            
            ОСОБОЕ ВНИМАНИЕ МАРКИРОВКЕ (Shipping Marks):
            В PO часто указано ТРЕБОВАНИЕ к маркировке (напр. "STOCK Onshore..."). Если в Invoice/PL указана другая маркировка (напр. номер инвойса поставщика), это КРИТИЧЕСКОЕ РАСХОЖДЕНИЕ. Ставь ⚠️.

            ВЕРНИ JSON со следующим списком параметров:
            {
                "summary_table": [
                    {"parameter": "Наименование товара", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Номер PO", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Дата документа", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Артикул (Material Code)", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Количество", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Единица измерения", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Общая сумма", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Условия поставки (Incoterms)", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Вес Нетто (N.W)", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Вес Брутто (G.W)", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Объем (CBM)", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"},
                    {"parameter": "Маркировка", "po": "...", "invoice": "...", "packing_list": "...", "status": "✅/⚠️"}
                ],
                "discrepancies": ["Детальное описание ошибки"],
                "recommendations": ["Совет"]
            }
            """

            # 4. Запускаем анализ
            response = self.model.generate_content([prompt] + gemini_files)
            
            # 5. Удаляем временные файлы
            for p in temp_paths:
                if os.path.exists(p): os.remove(p)
            
            return response.text

        except Exception as e:
            return json.dumps({"error": f"Ошибка обработки: {str(e)}"})
