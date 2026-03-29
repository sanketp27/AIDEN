"""
Vision tools for ADK agents
Gemini Vision API for image classification and structured extraction
"""
from src.tools.tool_decorator import tool
import google.generativeai as genai
from src.core.config import settings
from PIL import Image
import asyncio
import base64
import io
import json
import structlog

log = structlog.get_logger()

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Image type definitions
IMAGE_TYPES = [
    'whiteboard',
    'handwritten',
    'document',
    'screenshot',
    'business_card',
    'slide',
    'receipt',
    'photo'
]


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

        # Decode image
        image_bytes = base64.b64decode(image_b64)
        image = Image.open(io.BytesIO(image_bytes))

        prompt = f"""Classify this image into exactly one of these types: {', '.join(IMAGE_TYPES)}

Respond ONLY with valid JSON (no markdown):
{{
  "type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "description": "<one sentence describing the image>"
}}"""

        # Fix Bug #3: generate_content is synchronous — run in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(model.generate_content, [prompt, image])

        # Parse JSON response
        result_text = response.text.strip()
        # Remove markdown code blocks if present
        if result_text.startswith('```'):
            result_text = result_text.split('\n', 1)[1].rsplit('\n', 1)[0]
            if result_text.startswith('json'):
                result_text = result_text[4:].strip()

        result = json.loads(result_text)

        log.info("image_classified",
                image_type=result['type'],
                confidence=result['confidence'])

        return result

    except Exception as e:
        log.error("image_classification_failed", error=str(e))
        return {
            "type": "photo",
            "confidence": 0.5,
            "description": "Classification failed, defaulting to photo",
            "error": str(e)
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

        # Decode image
        image_bytes = base64.b64decode(image_b64)
        image = Image.open(io.BytesIO(image_bytes))

        # Type-specific prompts
        prompts = {
            'whiteboard': """Extract from this whiteboard image:
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

            'handwritten': """Extract from this handwritten content:
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

            'document': """Extract from this document:
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

            'screenshot': """Extract from this screenshot:
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

            'business_card': """Extract contact information from this business card:

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

            'slide': """Extract from this presentation slide:
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

            'receipt': """Extract from this receipt/invoice:

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

            'photo': """Describe this photo in detail:
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
}"""
        }

        prompt = prompts.get(image_type, prompts['photo'])

        # Fix Bug #3: generate_content is synchronous — run in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(model.generate_content, [prompt, image])

        # Parse JSON response
        result_text = response.text.strip()
        # Remove markdown code blocks
        if result_text.startswith('```'):
            result_text = result_text.split('\n', 1)[1].rsplit('\n', 1)[0]
            if result_text.startswith('json'):
                result_text = result_text[4:].strip()

        result = json.loads(result_text)

        log.info("image_analyzed",
                image_type=image_type,
                fields=list(result.keys()))

        return result

    except Exception as e:
        log.error("image_analysis_failed", error=str(e))
        return {
            "error": str(e),
            "text": "Analysis failed",
            "message": "Could not extract structured data from image"
        }


@tool
async def extract_tasks_from_image(image_b64: str) -> dict:
    """
    Extract action items and tasks from any image type.

    This is a specialized tool that focuses on finding tasks/to-dos
    regardless of image type.

    Args:
        image_b64: Base64-encoded image

    Returns:
        List of tasks ready for TaskMaster
    """
    try:
        # First classify
        classification = await classify_image(image_b64)
        image_type = classification['type']

        # Then analyze
        analysis = await analyze_image(image_b64, image_type)

        # Extract tasks based on type
        tasks = []

        # Get action items (different field names by type)
        action_items = analysis.get('action_items', [])
        task_items = analysis.get('tasks', [])

        for item in action_items:
            tasks.append({
                'title': item.get('task') or item.get('item', 'Untitled task'),
                'priority': 'P2',  # Default medium priority
                'due_date': item.get('due_date') or item.get('deadline'),
                'description': f'Extracted from {image_type} image',
                'tags': [image_type, 'from-image']
            })

        for item in task_items:
            tasks.append({
                'title': item.get('title', 'Untitled task'),
                'priority': item.get('priority', 'P2'),
                'due_date': item.get('due_date'),
                'description': f'Extracted from {image_type} image',
                'tags': [image_type, 'from-image']
            })

        log.info("tasks_extracted_from_image",
                image_type=image_type,
                task_count=len(tasks))

        return {
            'image_type': image_type,
            'tasks': tasks,
            'count': len(tasks),
            'message': f'Extracted {len(tasks)} task(s) from {image_type} image'
        }

    except Exception as e:
        log.error("task_extraction_failed", error=str(e))
        return {
            'tasks': [],
            'count': 0,
            'error': str(e),
            'message': 'Failed to extract tasks from image'
        }
