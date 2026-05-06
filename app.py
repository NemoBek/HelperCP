import pandas as pd
import streamlit as st

from checker import build_check_report
from processor import DocProcessor
from report_exporter import build_excel_report
from storage import POStore


st.set_page_config(page_title="AI Document Coordinator", page_icon="📋", layout="wide")

st.title("📋 Помощник таможенного координатора")
st.markdown("Загрузите комплект документов, а помощник извлечет данные, сверит их с PO и покажет остатки по частичным отгрузкам.")


def show_table(rows, empty_message):
    if rows:
        st.dataframe(display_frame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(empty_message)


def display_frame(rows):
    dataframe = pd.DataFrame(rows).fillna("N/A")
    return dataframe.replace("", "N/A")


with st.sidebar:
    st.header("Настройки")
    api_key = st.text_input("Gemini API Key", type="password")
    model_name = st.text_input("Модель", value="gemini-2.5-flash")
    st.caption("Документы отправляются во внешний Gemini API. Загружайте только те данные, которые можно обрабатывать таким способом.")

uploaded_files = st.file_uploader(
    "Загрузите документы: PDF, фото, Excel, Word",
    type=["pdf", "jpg", "jpeg", "png", "xlsx", "xls", "docx", "txt"],
    accept_multiple_files=True,
)

if "analysis" not in st.session_state:
    st.session_state.analysis = None

if st.button("🚀 Проверить документы", use_container_width=True):
    if not uploaded_files:
        st.error("Загрузите файлы.")
    elif not api_key:
        st.warning("Введите API ключ.")
    else:
        with st.spinner("Извлекаю данные и сверяю документы..."):
            processor = DocProcessor(api_key=api_key, model_name=model_name)
            extraction = processor.process_files(uploaded_files)

            if "error" in extraction:
                st.session_state.analysis = None
                st.error(extraction["error"])
            else:
                store = POStore()
                report = build_check_report(extraction, store)
                st.session_state.analysis = {"extraction": extraction, "report": report}
                st.success("Проверка завершена.")

analysis = st.session_state.analysis

if analysis:
    extraction = analysis["extraction"]
    report = analysis["report"]

    tab_check, tab_docs, tab_items, tab_balance, tab_history, tab_notes, tab_raw = st.tabs(
        [
            "✅ Проверка",
            "📄 Документы",
            "📦 Позиции",
            "📊 Остатки PO",
            "🗂️ История PO",
            "⚠️ Риски",
            "🧾 JSON",
        ]
    )

    with tab_check:
        show_table(report["check_rows"], "Проверочные строки не сформированы.")
        st.download_button(
            "Скачать отчет Excel",
            data=build_excel_report(report, extraction),
            file_name=f"helpercp_report_{report.get('po_number') or 'documents'}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if report["can_save_shipment"]:
            if st.button("Сохранить эту отгрузку в историю PO"):
                store = POStore()
                saved, message = store.save_shipment(
                    report["po_number"],
                    report["invoice_numbers"],
                    report["invoice_items"],
                )
                if saved:
                    st.success(message)
                else:
                    st.warning(message)

    with tab_docs:
        doc_rows = [
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
            for doc in report["documents"]
        ]
        show_table(doc_rows, "Документы не распознаны.")

    with tab_items:
        show_table(report["extracted_items"], "Позиции не извлечены.")

    with tab_balance:
        show_table(report["po_balance"], "Остатки PO пока не рассчитаны.")

    with tab_history:
        show_table(report["shipment_history"], "По этому PO еще нет сохраненных отгрузок.")

    with tab_notes:
        for recommendation in report["recommendations"]:
            st.warning(recommendation)
        if not report["recommendations"]:
            st.info("Отдельных рекомендаций нет.")

    with tab_raw:
        st.json({key: value for key, value in extraction.items() if key != "raw_response"})
        with st.expander("Сырой ответ Gemini"):
            st.code(extraction.get("raw_response", ""))
