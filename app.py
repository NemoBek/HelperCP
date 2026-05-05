import streamlit as st
import pandas as pd
from processor import DocProcessor
import json
import re

st.set_page_config(page_title="AI Document Coordinator", page_icon="📋", layout="wide")

st.title("📋 Помощник координатора: Сверка документов")
st.markdown("ИИ анализирует любые файлы (PDF, Скэн, JPG, Excel, Word) и сверяет их с PO.")

with st.sidebar:
     st.header("Настройки")
     api_key = st.text_input("Введите Gemini API Key", type="password")
     st.info("Версия 0.4: Поддержка частичных отгрузок и всех форматов.")

uploaded_files = st.file_uploader(
     "Загрузите пакет документов (PO + Инвойс + др.)",
     type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx"],
     accept_multiple_files=True
 )

if st.button("🚀 Начать проверку", use_container_width=True):
     if not uploaded_files:
         st.error("Загрузите файлы.")
     elif not api_key:
            st.warning("Введите API ключ.")
        else:
            with st.spinner("ИИ проводит глубокий аудит документов..."):
                try:
                    processor = DocProcessor(api_key=api_key)
                    result_raw = processor.process_files(uploaded_files)
   
                    # Очистка и парсинг
                    clean_res = re.sub(r'```json\s*|\s*
  `', '', result_raw).strip()
                  res = json.loads(clean_res, strict=False)

                  if "error" in res:
                      st.error(res["error"])
                  else:
                      st.success("Анализ завершен!")
                      tab1, tab2 = st.tabs(["📊 Чек-лист сверки", "🚩 Расхождения"])

                      with tab1:
                          if res.get("summary_table"):
                              st.table(pd.DataFrame(res["summary_table"]))

                      with tab2:
                          st.subheader("🚩 Детали ошибок")
                          for d in res.get("discrepancies", []):
                              st.warning(d)
                          st.subheader("💡 Рекомендации")
                          for r in res.get("recommendations", []):
                              st.info(r)
              except Exception as e:
                  st.error(f"Произошла ошибка: {str(e)}")
                  if 'result_raw' in locals():
                      with st.expander("Посмотреть технический ответ"):
                          st.code(result_raw)
