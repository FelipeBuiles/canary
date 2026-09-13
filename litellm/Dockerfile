FROM docker.litellm.ai/berriai/litellm:main-v1.83.14-stable

# The upstream LiteLLM image currently carries google-genai 1.37, which lacks
# GenerateContentConfig.image_config / ImageConfig. Canary requires those
# controls to preserve non-square panel and asset geometry (for example the
# 4:5 style proofs), so keep the local gateway aligned with production.
RUN /app/.venv/bin/python -m ensurepip \
    && /app/.venv/bin/python -m pip install --no-cache-dir "google-genai==1.75.0"

COPY litellm/patch_http_errors.py /app/patch_http_errors.py
RUN /app/.venv/bin/python /app/patch_http_errors.py

COPY litellm/patch_anthropic_refusals.py /app/patch_anthropic_refusals.py
RUN /app/.venv/bin/python /app/patch_anthropic_refusals.py
