"""
Image upload component for Streamlit
Upload and analyze images with Gemini Vision
"""
import streamlit as st
import requests
from typing import Optional


def render_image_upload(api_url: str, token: str) -> None:
    """
    Render image upload interface with analysis

    Args:
        api_url: API base URL
        token: JWT token
    """
    st.markdown("### 📸 Image Analysis")
    st.markdown("Upload images to extract tasks, notes, and structured data using Gemini Vision")

    # Supported types info
    with st.expander("ℹ️ Supported Image Types"):
        st.markdown("""
        - **Whiteboard**: Extract action items, diagrams, meeting notes
        - **Handwritten Notes**: Transcribe and identify tasks with priorities
        - **Documents**: Extract title, content, tables, deadlines
        - **Screenshots**: Extract text, UI elements, error messages
        - **Business Cards**: Extract contact information
        - **Presentation Slides**: Extract bullet points and data
        - **Receipts**: Extract vendor, amount, line items
        - **Photos**: General description and visible text
        """)

    # File uploader
    uploaded_files = st.file_uploader(
        "Choose image(s) to analyze",
        type=['jpg', 'jpeg', 'png', 'webp'],
        accept_multiple_files=True,
        help="Max 20MB per image, up to 5 images at once",
        key="image_uploader"
    )

    # Options
    col1, col2 = st.columns(2)
    with col1:
        auto_create_tasks = st.checkbox(
            "Auto-create tasks",
            value=True,
            help="Automatically create tasks from extracted action items"
        )
    with col2:
        auto_create_note = st.checkbox(
            "Create summary note",
            value=False,
            help="Create a note with extracted content"
        )

    # Analyze button
    if uploaded_files and st.button("🔍 Analyze Images", type="primary", use_container_width=True):
        results = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Analyzing {uploaded_file.name}...")

            try:
                # Display thumbnail
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.image(uploaded_file, width=100)

                with col2:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        # Upload to API
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}

                        response = requests.post(
                            f"{api_url}/vision/analyze",
                            files=files,
                            params={
                                "auto_create_tasks": auto_create_tasks,
                                "auto_create_note": auto_create_note
                            },
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=30
                        )

                        if response.status_code == 200:
                            result = response.json()
                            results.append((uploaded_file.name, result))

                            # Display result
                            st.success(f"✅ **{result['image_type'].title()}** (Confidence: {result['confidence']:.0%})")
                            st.write(result['description'])

                            # Show extracted data
                            with st.expander("📋 Extracted Data"):
                                st.json(result['extracted_data'])

                            # Show created items
                            if result['tasks_created'] > 0:
                                st.info(f"✨ Created {result['tasks_created']} task(s)")
                            if result['notes_created'] > 0:
                                st.info(f"📝 Created {result['notes_created']} note(s)")

                            st.markdown(f"*{result['message']}*")

                        else:
                            st.error(f"❌ Analysis failed: {response.text}")

                st.divider()

            except requests.exceptions.Timeout:
                st.error(f"⏱️ Timeout analyzing {uploaded_file.name}")
            except Exception as e:
                st.error(f"❌ Error processing {uploaded_file.name}: {str(e)}")

            # Update progress
            progress_bar.progress((idx + 1) / len(uploaded_files))

        status_text.success(f"✅ Analyzed {len(results)} of {len(uploaded_files)} images")

        # Summary
        if results:
            st.markdown("---")
            st.markdown("### 📊 Analysis Summary")

            total_tasks = sum(r[1]['tasks_created'] for r in results)
            total_notes = sum(r[1]['notes_created'] for r in results)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Images Analyzed", len(results))
            with col2:
                st.metric("Tasks Created", total_tasks)
            with col3:
                st.metric("Notes Created", total_notes)


def show_image_examples():
    """Show example images users can try"""
    st.markdown("### 💡 Example Use Cases")

    examples = [
        ("📋 Whiteboard", "Photo meeting whiteboard → Auto-create action items"),
        ("✍️ Handwritten", "Scan to-do list → Convert to digital tasks"),
        ("📄 Document", "Upload contract → Extract deadlines and terms"),
        ("💻 Screenshot", "Error message → Save for troubleshooting"),
        ("🎫 Business Card", "Scan card → Save contact info"),
        ("📊 Presentation", "Photo of slide → Extract key points"),
        ("🧾 Receipt", "Scan receipt → Track expenses"),
    ]

    cols = st.columns(3)
    for idx, (icon_title, description) in enumerate(examples):
        with cols[idx % 3]:
            st.info(f"**{icon_title}**\n\n{description}")
