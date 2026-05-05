import streamlit as st
import pandas as pd
from processor import DocProcessor
import json

st.set_page_config(page_title="AI Document Coordinator", page_icon="📋", layout="wide")

st.title("📋 Помощник координатора: Визуальная сверка документов")
st.markdown("ИИ анализирует оригинальные PDF-файлы (включая сканы и чертежи) для поиска расхождений.")

with st.sidebar:
    st.header("Настройки")
    api_key = st.text_input("Введите Gemini API Key", type="password")

uploaded_files = st.file_uploader(
    "Загрузите файлы (PDF, JPG, PNG, Excel, Word)", 
    type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx"], 
    accept_multiple_files=True
)

if st.button("🚀 Начать визуальную проверку", use_container_width=True):
    if not uploaded_files:
        st.error("Загрузите файлы.")
    elif not api_key:
        st.warning("Введите API ключ.")
    else:
        with st.spinner("ИИ изучает документы... (Это может занять 15-30 секунд)"):
            try:
                processor = DocProcessor(api_key=api_key)
                result_raw = processor.process_files(uploaded_files)
                
                res = json.loads(result_raw)
                
                if "error" in res:
                    st.error(res["error"])
                else:
                    st.success("Анализ завершен успешно!")
                    tab1, tab2 = st.tabs(["📊 Чек-лист", "🚩 Ошибки и рекомендации"])
                    
                    with tab1:
                        st.table(pd.DataFrame(res.get("summary_table", [])))
                    with tab2:
                        st.subheader("🚩 Найденные расхождения")
                        for d in res.get("discrepancies", []):
                            st.warning(d)
                        st.subheader("💡 Рекомендации")
                        for r in res.get("recommendations", []):
                            st.info(r)
            except Exception as e:
                st.error(f"Ошибка парсинга: {str(e)}")
                st.subheader("Сырой ответ ИИ для отладки:")
                st.code(result_raw)
