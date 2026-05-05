import streamlit as st
    2 import pandas as pd
    3 from processor import DocProcessor
    4 import json
    5 import re
    6
    7 st.set_page_config(page_title="AI Document Coordinator", page_icon="📋", layout="wide")
    8
    9 st.title("📋 Помощник координатора: Сверка документов")
   10 st.markdown("ИИ анализирует любые файлы (PDF, Скэн, JPG, Excel, Word) и сверяет их с PO.")
   11
   12 with st.sidebar:
   13     st.header("Настройки")
   14     api_key = st.text_input("Введите Gemini API Key", type="password")
   15     st.info("Версия 0.4: Поддержка частичных отгрузок и всех форматов.")
   16
   17 uploaded_files = st.file_uploader(
   18     "Загрузите пакет документов (PO + Инвойс + др.)",
   19     type=["pdf", "jpg", "jpeg", "png", "xlsx", "docx"],
   20     accept_multiple_files=True
   21 )
   22
   23 if st.button("🚀 Начать проверку", use_container_width=True):
   24     if not uploaded_files:
   25         st.error("Загрузите файлы.")
   26     elif not api_key:
   27         st.warning("Введите API ключ.")
   28     else:
   29         with st.spinner("ИИ проводит глубокий аудит документов..."):
   30             try:
   31                 processor = DocProcessor(api_key=api_key)
   32                 result_raw = processor.process_files(uploaded_files)
   33
   34                 # Очистка и парсинг
   35                 clean_res = re.sub(r'```json\s*|\s*
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
