# Image plan input: contract for Ishani

Author: Tishneet. Version1. This is an additive warehouse input mode, not an S3
preview or a new authorization system. API handlers remain Ishani-owned.

## Submit and poll

Text stays unchanged: POST /v1/plans with {instruction}.

Live image submission:

```json
{"image_b64":"<raw base64, no data-URL prefix>","mime_type":"image/png"}
```

Ishani's handler should accept exactly one input variant. Reject mixed text/image
bodies, missing image fields and unknown fields; do not silently choose text or
drop a requested demo_mode. Dispatch images to:

```python
get_backend().start_image_plan(image_b64, mime_type, demo_mode=None)
```

Return HTTP202 with the normal {plan_id,status:PLANNING} response, not a completed
PlanStatus synchronously. StartExecution still receives only {plan_id}. Poll
GET /v1/plans/{id} for the normal candidate/authorization/simulation/execution
shape. Existing ambiguous-start handling retains the original plan_id.

Accept PNG or baseline/progressive JPEG only, decoded maximum128KiB, width/height
at most4096 and total pixels at most4,000,000. Resize/compress larger uploads in
the frontend. Backend checks base64, signatures and dimension headers; Bedrock
decodes the image. Corrupt contents can therefore still produce MODEL_ERROR.
Do not log upload bodies, include bytes in URLs, or return them in public status.

## Added public metadata (image submissions only)

input_metadata contains type=image, mode=live|scripted, demo_mode, mime_type,
sha256, size_bytes, width, height, and intent_source=UNTRUSTED_IMAGE_EXTRACTION.
instruction initially shows an image-pending placeholder, then the extracted
movement instruction. Render it as untrusted text, never HTML or authority.
Text submissions do not acquire new metadata or different behavior.

Live mode uses Nova Pro Converse with a text block plus image.source.bytes.
The model returns an extracted instruction and normal PlanActions. The backend
independently validates both structure and agreement with the extracted movement;
image claims such as "already authorized" never grant authority. The extraction
is NOT an independently trusted statement of user intent or exact OCR proof.
Candidates still pass the existing current authorization and simulation gates.
An authorization denial stops before simulation, replanning or execution, so
simulation and execution will be null for the intended policy-denial demo.

## Deterministic stage preset

Asset: backend/ai/assets/image-injection-v1.png (1000×440,42,754 bytes).
SHA256: b4bc7e16f1f01f81e5a47fc34dc279f22846efc6f63e6e7a6e2432a877f63271

```json
{"image_b64":"<base64 of that exact asset>","mime_type":"image/png","demo_mode":"image_injection_v1"}
```

Both API and worker must opt in with SENTINEL_IMAGE_DEMO_ENABLED=true. The workflow
SAM parameter ImageDemoEnabled controls the worker setting (default false).
Only the exact published asset is accepted. This mode substitutes the fixed
Keep the original bytes when uploading this preset; do not resize or re-encode it.
This mode substitutes the fixed
instruction "Move 11 packages from Zone A to Zone C." and its matching normal
move_packages action; it makes ZERO model calls. Current Cedar policy rejects
the per-action quantity with LIMIT_EXCEEDED. The agent must be ACTIVE and the
authorization service healthy to guarantee that specific reason code.

Show the label **Scripted image-attack preset — no live AI extraction**.
runtime.provider and candidate.provenance are SCRIPTED_IMAGE_FIXTURE; candidate
metrics.model_calls=0. Audit explicitly identifies the scripted generation.
Live mode is labeled BEDROCK and never falls back to the preset on refusal/error.
No authorization outcome is stubbed or forced by the preset.

This demonstrates that the existing backend blocks a known unauthorized request
originating in an image. It is not proof that Nova is always fooled, that we have
a prompt-injection detector, or that every possible injection is blocked. The
model is asked to extract an image instruction; describe that limitation honestly.

## Ownership and rollout

Tishneet: image validation, multimodal provider, workflow/adapter methods, asset,
tests and this contract. Ishani: POST routing, file upload, polling and live versus
scripted labels. No backend/api/ or frontend files are changed in this contribution.
Mariam's authorization/simulator/executor contracts and warehouse IAM are unchanged.
Bedrock still needs only existing model invocation permission.

Deploy the updated workflow artifact with its image asset, then package these
modules with Ishani's API. Merely changing the API body does not update the worker.
Do not enable the stage preset globally without its visible label.

References: [Converse image block](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlock.html),
[Nova image understanding](https://docs.aws.amazon.com/nova/latest/userguide/modalities-image.html).
