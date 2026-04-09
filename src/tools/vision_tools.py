"""
Vision tools for ADK agents
Gemini Vision API for image classification and structured extraction
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any

import cairosvg
import google.generativeai as genai
import structlog
from PIL import Image, UnidentifiedImageError

from src.core.config import settings
from src.tools.tool_decorator import tool

log = structlog.get_logger()

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Image type definitions
IMAGE_TYPES = [
    "whiteboard",
    "handwritten",
    "document",
    "screenshot",
    "business_card",
    "slide",
    "receipt",
    "photo",
]


def _decode_image_input(image_b64: str) -> tuple[bytes, str]:
    """
    Decode base64 image input.

    Supports plain base64 and data URLs (e.g. data:image/svg+xml;base64,...).
    Returns (bytes, mime_type).
    """
    mime_type = ""
    payload = image_b64.strip()

    if payload.startswith("data:") and "," in payload:
        header, payload = payload.split(",", 1)
        mime_type = header[5:].split(";", 1)[0].lower()

    image_bytes = base64.b64decode(payload)
    return image_bytes, mime_type


def is_svg(file_bytes: bytes, mime_type: str = "", filename: str = "") -> bool:
    """
    Detect SVG by MIME type, filename extension, or content signature.
    """
    if mime_type.lower() == "image/svg+xml":
        return True

    if filename.lower().endswith(".svg"):
        return True

    header = file_bytes[:300].decode(errors="ignore").lower().lstrip()
    return "<svg" in header or header.startswith("<?xml") and "<svg" in header


def load_image(file_bytes: bytes, mime_type: str = "", filename: str = "") -> Image.Image:
    """
    Load raster images directly, convert SVG to PNG in-memory before PIL handling.
    """
    try:
        if is_svg(file_bytes, mime_type=mime_type, filename=filename):
            png_bytes = cairosvg.svg2png(bytestring=file_bytes)
            return Image.open(io.BytesIO(png_bytes)).convert("RGB")
        return Image.open(io.BytesIO(file_bytes)).convert("RGB")
    except UnidentifiedImageError as exc:
        log.error(
            "image_load_unidentified",
            mime_type=mime_type,
            filename=filename,
            error=str(exc),
        )
        raise ValueError(
            "Unsupported or corrupted image. Supported formats: PNG, JPG, JPEG, SVG."
        ) from exc
    except Exception as exc:
        log.error(
            "image_load_failed",
            mime_type=mime_type,
            filename=filename,
            error=str(exc),
            exc_info=True,
        )
        raise ValueError("Failed to process uploaded image.") from exc


def _parse_json_response(text: str) -> dict[str, Any]:
    result_text = text.strip()
    if result_text.startswith("```"):
        result_text = result_text.split("\n", 1)[1].rsplit("\n", 1)[0]
        if result_text.startswith("json"):
            result_text = result_text[4:].strip()
    return json.loads(result_text)


@tool
async def classify_image(image_b64: str) -> dict:
    """
    Classify the type of image to determine processing strategy.

    Uses Gemini Vision to identify:
    - whiteboard: Whiteboard photos with diagrams/notes
    - handwritten: Handwritten notes or to-do lists
    - document: Printed documents, PDFs, reports
    - screenshot: Computer screenshots (UI, code, errors)
    - business_card: Business cards with contact info
    - slide: Presentation slides with bullet points
    - receipt: Receipts or invoices
    - photo: General photos

    Args:
        image_b64: Base64-encoded image

    Returns:
        Dictionary with image_type, confidence, and description
    """
    try:
        model = genai.GenerativeModel(settings.VISION_MODEL)

        image_bytes, mime_type = _decode_image_input(image_b64)
        image = load_image(image_bytes, mime_type=mime_type)

        prompt = f"""Classify this image into exactly one of these types: {', '.join(IMAGE_TYPES)}

Respond ONLY with valid JSON (no markdown):
{{
  "type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "description": "<one sentence describing the image>"
}}"""

        response = await asyncio.to_thread(model.generate_content, [prompt, image])
        result = _parse_json_response(response.text)

        log.info(
            "image_classified", image_type=result["type"], confidence=result["confidence"]
        )
        return result

    except ValueError as exc:
        log.warning("image_classification_validation_failed", error=str(exc))
        return {
            "type": "photo",
            "confidence": 0.0,
            "description": "Image format not supported or file is corrupted.",
            "error": str(exc),
        }
    except Exception as exc:
        log.error("image_classification_failed", error=str(exc), exc_info=True)
        return {
            "type": "photo",
            "confidence": 0.5,
            "description": "Classification failed, defaulting to photo",
            "error": str(exc),
        }


@tool
async def analyze_image(image_b64: str, image_type: str) -> dict:
    """
    Deep analysis of image based on its classified type.

    Extracts structured data:
    - whiteboard: Text, action items, dates, diagrams
    - handwritten: Text, tasks with priority inference
    - document: Title, content, tables, deadlines
    - screenshot: Text, UI elements, error messages
    - business_card: Name, title, company, email, phone
    - slide: Title, bullet points, key data
    - receipt: Vendor, date, total, line items

    Args:
        image_b64: Base64-encoded image
        image_type: Type from classify_image

    Returns:
        Structured extraction as dictionary
    """
    try:
        model = genai.GenerativeModel(settings.VISION_MODEL)

        image_bytes, mime_type = _decode_image_input(image_b64)
        image = load_image(image_bytes, mime_type=mime_type)

        prompts = {
            "whiteboard": """Extract from this whiteboard image:
1. All visible text (preserve structure and layout)
2. Action items (lines with checkboxes, arrows, or action verbs like "Review", "Send", "Complete")
3. Dates or deadlines mentioned (any format)
4. Names of people mentioned
5. Any diagrams or visual elements described

Respond as valid JSON:
{
  "text": "<all text content>",
  "action_items": [{"task": "<description>", "assignee": "<person if mentioned>", "due_date": "<date if mentioned>"}],
  "dates": ["<list of dates found>"],
  "people": ["<list of names>"],
  "diagrams": "<description of any diagrams/visuals>"
}""",
            "handwritten": """Extract from this handwritten content:
1. All handwritten text (interpret handwriting accurately)
2. To-do items (checkboxes, dashes, bullets, numbers)
3. Priority indicators (!, *, underlining, highlighting = high priority)
4. Dates and deadlines
5. Any crossed-out or completed items

Respond as valid JSON:
{
  "text": "<full transcription>",
  "tasks": [{"title": "<task>", "priority": "P1|P2|P3", "due_date": "<if mentioned>", "completed": false}],
  "notes": ["<any non-task notes>"],
  "dates": ["<dates found>"]
}""",
            "document": """Extract from this document:
1. Document title and any headings
2. Full text content (preserve paragraph structure)
3. Any tables (as structured data)
4. Deadlines, action items, or decision points
5. Key people or stakeholders mentioned

Respond as valid JSON:
{
  "title": "<document title>",
  "content": "<full text>",
  "headings": ["<list of section headings>"],
  "tables": [{"headers": [], "rows": []}],
  "action_items": [{"item": "<description>", "deadline": "<if mentioned>"}],
  "deadlines": ["<list of dates>"],
  "keywords": ["<5-10 key topics>"]
}""",
            "screenshot": """Extract from this screenshot:
1. All visible text
2. UI elements and their labels
3. Any error messages or warnings
4. Code snippets if present
5. Application or window title

Respond as valid JSON:
{
  "text": "<all visible text>",
  "ui_elements": ["<buttons, menus, labels>"],
  "errors": ["<error messages>"],
  "code": "<code snippets if any>",
  "application": "<app/window title>"
}""",
            "business_card": """Extract contact information from this business card:

Respond as valid JSON:
{
  "name": "<full name>",
  "title": "<job title>",
  "company": "<company name>",
  "email": "<email address>",
  "phone": "<phone number>",
  "website": "<website URL>",
  "address": "<physical address if shown>"
}""",
            "slide": """Extract from this presentation slide:
1. Slide title
2. All bullet points and sub-points
3. Any data, numbers, or statistics
4. Charts or graphs described
5. Footer information (page number, date, etc.)

Respond as valid JSON:
{
  "title": "<slide title>",
  "bullet_points": ["<level 1>", "  - <level 2>"],
  "data_points": [{"metric": "<name>", "value": "<number>"}],
  "charts": "<description of any charts>",
  "footer": "<footer text>"
}""",
            "receipt": """Extract from this receipt/invoice:

Respond as valid JSON:
{
  "vendor": "<store/business name>",
  "date": "<transaction date>",
  "time": "<transaction time>",
  "total": "<total amount with currency>",
  "tax": "<tax amount>",
  "payment_method": "<cash/card/etc>",
  "line_items": [{"item": "<name>", "quantity": 1, "price": "<amount>"}]
}""",
            "photo": """Describe this photo in detail:
1. Main subjects or objects
2. Setting or location
3. Any text visible
4. Notable features or details

Respond as valid JSON:
{
  "description": "<detailed description>",
  "subjects": ["<list of main subjects>"],
  "text": "<any visible text>",
  "location": "<setting if identifiable>"
}""",
        }

        prompt = prompts.get(image_type, prompts["photo"])
        response = await asyncio.to_thread(model.generate_content, [prompt, image])
        result = _parse_json_response(response.text)

        log.info("image_analyzed", image_type=image_type, fields=list(result.keys()))
        return result

    except ValueError as exc:
        log.warning("image_analysis_validation_failed", error=str(exc))
        return {
            "error": str(exc),
            "text": "Analysis failed",
            "message": "Unsupported or corrupted image. Supported formats: PNG, JPG, JPEG, SVG.",
        }
    except Exception as exc:
        log.error("image_analysis_failed", error=str(exc), exc_info=True)
        return {
            "error": str(exc),
            "text": "Analysis failed",
            "message": "Could not extract structured data from image",
        }

@tool
async def extract_tasks_from_image(image_b64: str) -> dict:
    """
    Extract actionable tasks from any image (whiteboard, handwritten notes, document, slide).

    Combines classification + targeted extraction in a single call optimised
    for task creation. Returns a list of tasks ready to be inserted via TaskMaster.

    Args:
        image_b64: Base64-encoded image

    Returns:
        Dictionary with 'tasks' list and 'raw_text' transcription
    """
    try:
        model = genai.GenerativeModel(settings.VISION_MODEL)

        image_bytes, mime_type = _decode_image_input(image_b64)
        image = load_image(image_bytes, mime_type=mime_type)

        prompt = """Extract ALL actionable tasks from this image.
Look for: checkboxes, bullet points, numbered lists, action verbs (Review, Send, Fix, Complete, Schedule), deadlines, and any to-do items.

Respond ONLY with valid JSON (no markdown):
{
  "tasks": [
    {
      "title": "<short task title>",
      "description": "<additional context if any>",
      "priority": "P1|P2|P3",
      "due_date": "<YYYY-MM-DD or null>",
      "assignee": "<person name or null>"
    }
  ],
  "raw_text": "<full transcription of all visible text>"
}"""

        response = await asyncio.to_thread(model.generate_content, [prompt, image])
        result = _parse_json_response(response.text)

        log.info("tasks_extracted_from_image", task_count=len(result.get("tasks", [])))
        return result

    except ValueError as exc:
        log.warning("extract_tasks_validation_failed", error=str(exc))
        return {"tasks": [], "raw_text": "", "error": str(exc)}
    except Exception as exc:
        log.error("extract_tasks_from_image_failed", error=str(exc), exc_info=True)
        return {"tasks": [], "raw_text": "", "error": str(exc)}