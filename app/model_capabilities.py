"""Conservative candidates for image -> primitive-scene JSON, not native 3D APIs.

Cloud catalogues without capability fields use a versioned, documented registry.
Unknown IDs are omitted rather than inferred from arbitrary substrings.
"""
import re

# References and update policy are documented in README's model catalogue section.
OPENAI_VISION = (
    'gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
    'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-5.1', 'gpt-5.2',
    'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-6.1-terra',
    'gpt-6.2-astra', 'gpt-6.2-sol',
)
GEMINI_VISION = (
    'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.5-flash',
    'gemini-2.5-flash-lite', 'gemini-2.5-pro', 'gemini-3-pro-preview',
    'gemini-3-flash-preview', 'gemini-4-carbon', 'gemini-4-neon', 'gemini-4-hydrogen',
)


def image_scene_candidate(provider, model_id, item):
    """Require image input + language generation; explicit negatives win."""
    caps = item.get('capabilities')
    if provider == 'ollama':
        return isinstance(caps, list) and {'vision', 'completion'}.issubset(caps)
    if isinstance(caps, dict):
        image = caps.get('image_input')
        if isinstance(image, dict) and isinstance(image.get('supported'), bool):
            if not image['supported']: return False
            if provider == 'anthropic': return True
    if provider == 'local_openai':
        # LM Studio's documented model type; no inference from a model's name.
        return item.get('type') == 'vlm'
    if provider == 'openai':
        return any(re.fullmatch(re.escape(base) + r'(?:-\d{4}-\d{2}-\d{2})?', model_id)
                   for base in OPENAI_VISION)
    if provider == 'gemini':
        if 'generateContent' not in (item.get('supportedGenerationMethods') or []):
            return False
        return any(re.fullmatch(re.escape(base) + r'(?:-\d{3})?', model_id)
                   for base in GEMINI_VISION)
    if provider == 'anthropic':
        return bool(re.fullmatch(r'claude-(?:3-(?:haiku|sonnet|opus)|3-5-(?:haiku|sonnet)|3-7-sonnet|(?:sonnet|opus|haiku)-4(?:-[0-9])?)(?:-\d{8}|-latest)?', model_id))
    return False
