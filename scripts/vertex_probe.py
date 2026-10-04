"""One opt-in Gemini request through the configured Vertex adapter; no servers."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


async def probe(project: str, credentials: Path, schema_file: Path | None = None,
                prompt_schema: bool = False) -> int:
    # Bind this invocation to the supplied project and file, never ambient ADC.
    info = json.loads(credentials.read_text())
    if info.get("type") == "service_account":
        account = info.get("client_email", "")
        matches = info.get("project_id") == project
    elif info.get("type") == "impersonated_service_account":
        account = info.get("service_account_impersonation_url", "").split("/serviceAccounts/")[-1].split(":")[0]
        matches = account.endswith(f"@{project}.iam.gserviceaccount.com")
    else:
        matches = False
    if not matches:
        raise ValueError("The credential must use a service account from --project")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials.resolve())
    os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = project
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_TELEMETRY"] = "False"

    import yaml

    import litellm

    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "litellm/config.yaml").read_text())
    route = next(item for item in config["model_list"] if item["model_name"] == "gemini-3.8-flash")
    router = litellm.Router(model_list=[{**route, "litellm_params": {
        **route["litellm_params"], "vertex_project": project, "vertex_location": "global",
    }}], num_retries=0, timeout=60)
    litellm.drop_params = False
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    messages = [{"role": "user", "content": 'Return {"ok":true}.'}]
    if schema_file is not None:
        schema = json.loads(schema_file.read_text())
        messages = [{"role": "user", "content": (
            "Extract story facts as JSON under the provided schema from this synthetic story: "
            "Mara enters a quiet room and closes the door. Use empty arrays where no fact is supported."
        )}]
    response_format = {"type": "json_schema", "json_schema": {
        "name": "vertex_probe", "strict": True, "schema": schema,
    }}
    if prompt_schema:
        messages.insert(0, {"role": "system", "content": (
            "Return one JSON object conforming to this complete schema. Resolve local $ref entries "
            "from $defs. Include source_review; use empty arrays only when no correction is needed. "
            "Return JSON only.\n" + json.dumps(schema, separators=(",", ":"))
        )})
        response_format = {"type": "json_object"}
    stream = await router.acompletion(
        model=route["model_name"], messages=messages, reasoning_effort="low",
        max_completion_tokens=2048, stream=True, stream_options={"include_usage": True},
        response_format=response_format,
    )
    chunks = [chunk async for chunk in stream]
    response = litellm.stream_chunk_builder(chunks, messages=messages)
    answer = json.loads(response.choices[0].message.content)
    report = {
        "project": project, "service_account": account,
        "provider": "vertex_ai", "model": response.model, "response": answer,
        "usage": response.usage.model_dump(exclude_none=True),
        "estimated_provider_cost_usd": litellm.completion_cost(completion_response=response),
        "cost_note": "Token estimate before Cloud trial credit; not a billing receipt.",
    }
    print(json.dumps(report, indent=2))
    return 0 if schema_file is not None or answer == {"ok": True} else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call", action="store_true", help="Make one billable request, with no retries")
    parser.add_argument("--project", help="Explicit credited Google Cloud project ID")
    parser.add_argument("--credentials", type=Path, help="New service-account key or impersonated ADC JSON")
    parser.add_argument("--schema-file", type=Path, help="Check a JSON schema using a short synthetic story")
    parser.add_argument("--prompt-schema", action="store_true", help="Send the schema as JSON mode instructions")
    args = parser.parse_args()
    if not args.call:
        parser.print_help()
        return 0
    if not args.project or not args.credentials:
        parser.error("--call requires --project and --credentials")
    try:
        return asyncio.run(probe(args.project, args.credentials.expanduser(), args.schema_file, args.prompt_schema))
    except Exception as exc:  # noqa: BLE001 -- sanitize all provider/auth failures
        # Do not dump auth objects or request headers into a shell transcript.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "http_status": getattr(exc, "status_code", None)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
