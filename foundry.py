"""Dependency-free Microsoft Foundry Responses adapter."""
import json
import os
import urllib.request
import urllib.error
from urllib.parse import urlparse

def configuration():
    endpoint = os.getenv('FOUNDRY_ENDPOINT', '').strip().rstrip('/')
    url = urlparse(endpoint)
    if (url.scheme != 'https' or not url.hostname or
        not url.hostname.endswith(('.openai.azure.com', '.services.ai.azure.com')) or
        url.username or url.password or url.port not in (None, 443) or
        url.query or url.fragment or url.path != '/openai/v1'):
        raise ValueError('Set FOUNDRY_ENDPOINT to your Azure resource https://…/openai/v1 endpoint.')
    key = os.getenv('FOUNDRY_API_KEY', '').strip()
    model = os.getenv('FOUNDRY_DEPLOYMENT', '').strip()
    if not key or not model:
        raise ValueError('Set FOUNDRY_API_KEY and FOUNDRY_DEPLOYMENT on the server.')
    return endpoint, key, model

def complete(instructions, data):
    endpoint, key, deployment = configuration()
    payload = {'model': deployment, 'instructions': instructions,
               'input': json.dumps(data, ensure_ascii=False),
               'max_output_tokens': 6000, 'store': False}
    request = urllib.request.Request(endpoint + '/responses', data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'api-key': key}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        messages = {401: 'Azure authentication failed.', 403: 'Azure access denied.',
                    404: 'Check your Azure endpoint and deployment.', 429: 'Azure quota or rate limit reached.'}
        raise RuntimeError(messages.get(error.code, 'Azure request failed. Check model compatibility.')) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Azure is unreachable or timed out.') from None
    if result.get('status') != 'completed':
        raise RuntimeError('Model response did not complete. No partial analysis was accepted.')
    text = '\n'.join(c['text'] for item in result.get('output', []) for c in item.get('content', [])
                     if c.get('type') == 'output_text' and isinstance(c.get('text'), str))
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError('Model did not return valid JSON. Nothing was accepted; you can retry manually.') from None
    return parsed, {'deployment': deployment, 'usage': result.get('usage', {})}
