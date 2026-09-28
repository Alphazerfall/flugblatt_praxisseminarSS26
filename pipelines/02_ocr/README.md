# 02 OCR - PDF to JSON

Six scripts send a PDF to a hosted OCR/document API and save the result (plus any extracted images) next to the PDF, following the `data/<pdf_stem>/<format><Engine>/<pdf_stem>.<ext>` layout:

- `datalab_convert.py` - [Datalab Convert API](https://documentation.datalab.to/docs/welcome/api) (raw REST calls)
- `flugblatt_convert.py` - same Datalab convert endpoint, via the [Datalab Python SDK](https://documentation.datalab.to/docs/welcome/sdk/conversion) instead of raw REST, with our house settings (Accurate mode, paginate, keep headers/footers, merge cross-page content, new block types) baked in as defaults - no saved Datalab Pipeline needed. Also supports rotating across multiple API keys (e.g. teammates' free-credit accounts), automatically switching to the next one whenever the current one runs out of credits mid-run.
- `mistral_convert.py` - [Mistral OCR API](https://docs.mistral.ai/capabilities/OCR/basic_ocr/)
- `gemini_convert.py` - [Gemini API](https://ai.google.dev/gemini-api/docs/document-processing) (general-purpose VLM prompted for markdown, not a dedicated OCR product)
- `openrouter_convert.py` - [OpenRouter](https://openrouter.ai/) (routes to any vision-capable model available there, default `anthropic/claude-sonnet-4.5`; note none of the specialized OCR-leaderboard models - dots.ocr, chandra, MinerU, LightOnOCR, GLM-OCR, Falcon-OCR, Qianfan-OCR - are actually listed on OpenRouter as of writing, so this is for comparing frontier general-purpose VLMs, not the specialist models. Renders pages to images locally and sends them directly rather than using OpenRouter's PDF-preprocessing plugins, so the comparison reflects the chosen model's own vision capability)
- `glm_convert.py` - [GLM-OCR](https://github.com/zai-org/GLM-OCR), self-hosted, via the official `glmocr` SDK's pipeline mode. Unlike `pipelines/02_ocr/GLM-OCR/ocr_test.py` (which prompts the raw model directly over its OpenAI-compatible endpoint and only gets back plain per-page text), this drives the SDK's full two-stage pipeline - local PP-DocLayout-V3 layout detection, then parallel region recognition against the same self-hosted model server - for real positioned layout blocks with boxes, comparable to Datalab/Gemini `--blocks`.

## Setup

```bash
pip install -e .
```

Add your keys to a `.env` file in the repository root:

```env
DATALAB_API_KEY=your_key_here
DATALAB_API_KEYS=key_one,key_two,key_three
MISTRAL_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
```

`DATALAB_API_KEYS` (comma-separated, or pass `--api-keys` per run) is only used by `flugblatt_convert.py`, to rotate across several Datalab accounts - e.g. teammates' free-credit signups - moving to the next key automatically whenever the current one runs out of credits mid-run. Falls back to `DATALAB_API_KEY` if unset. Datalab has no API to check remaining balance ahead of time, so this is reactive (try, get a 402/403, rotate) rather than a pre-flight check - each batch is checkpointed to disk first, so switching keys mid-run never re-pays for a batch that already completed.

`glm_convert.py` needs the heavier optional `glmocr` extra instead (pulls in torch/transformers to run PP-DocLayout-V3 locally):

```bash
pip install -e ".[glmocr]"
```

It also needs a running self-hosted GLM-OCR model server (vLLM/SGLang/Ollama) - no API key. See [Notes](#notes) below.

## Usage

```bash
python pipelines/02_ocr/datalab_convert.py PDF [options]
python pipelines/02_ocr/flugblatt_convert.py PDF [options]
python pipelines/02_ocr/mistral_convert.py PDF [options]
python pipelines/02_ocr/gemini_convert.py PDF [options]
python pipelines/02_ocr/openrouter_convert.py PDF [options]
python pipelines/02_ocr/glm_convert.py PDF [options]
```

Run any script with `-h` to see all options.

## Examples

Convert a whole PDF:

```bash
python pipelines/02_ocr/datalab_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf"
python pipelines/02_ocr/mistral_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf"
python pipelines/02_ocr/gemini_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf"
python pipelines/02_ocr/openrouter_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf"
```

Convert pages 0-5 in balanced mode (Datalab):

```bash
python pipelines/02_ocr/datalab_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf" --page-range=0-5 -m=balanced
```

Convert with the house Flugblatt settings, batching the upload into 50-page chunks, rotating across several teammates' keys as credits run out:

```bash
python pipelines/02_ocr/flugblatt_convert.py "data/raw/Nr. 005 (1971)/0118_0005.pdf" --batch-size=50
```

Force a clean re-run instead of resuming from a previous interrupted run's checkpoints:

```bash
python pipelines/02_ocr/flugblatt_convert.py "data/raw/Nr. 005 (1971)/0118_0005.pdf" --batch-size=50 --fresh
```

Convert pages 0-5 only (Mistral, Gemini, OpenRouter):

```bash
python pipelines/02_ocr/mistral_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf" --page-range=0-5
python pipelines/02_ocr/gemini_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf" --page-range=0-5
python pipelines/02_ocr/openrouter_convert.py "data/raw/Nr. 001 (1967)/0118_0001.pdf" --page-range=0-5
```

Use a different model on OpenRouter, e.g. GPT-5:

```bash
python pipelines/02_ocr/openrouter_convert.py "data/test_set/test_set.pdf" -m openai/gpt-5
```

Get positioned layout blocks (bounding boxes) from Gemini instead of plain markdown:

```bash
python pipelines/02_ocr/gemini_convert.py "data/test_set/test_set.pdf" --blocks
```

Get positioned layout blocks from a self-hosted GLM-OCR server on the default `localhost:8080` (vLLM/SGLang):

```bash
python pipelines/02_ocr/glm_convert.py "data/test_set/test_set.pdf"
```

Same, but against a local Ollama install instead (see [Notes](#notes) for the one-time `ollama pull` setup - this is the right choice on a machine with no CUDA GPU):

```bash
python pipelines/02_ocr/glm_convert.py "data/test_set/test_set.pdf" --ollama
```

Force the local PP-DocLayout-V3 layout model onto CPU (e.g. to keep a single GPU free for the OCR model itself - not needed with `--ollama` on a GPU-less machine, it already auto-selects CPU):

```bash
python pipelines/02_ocr/glm_convert.py "data/test_set/test_set.pdf" --layout-device cpu
```

Quote paths that contain spaces, but not the option values.

## Notes

- `flugblatt_convert.py`: batch results are checkpointed to `<output_dir>/.checkpoints_<fingerprint>/batch_<pages>.json` as they complete and cleaned up once the full merge succeeds. The fingerprint hashes every setting that affects the result (format, mode, extras, etc.), so switching `--format` or other flags can't accidentally reuse a checkpoint written under different settings - but rerunning the exact same command after an interruption (e.g. all API keys ran out) resumes for free, only paying for the batches that hadn't completed yet.
- `gemini_convert.py` uses the new Gemini **Interactions API** (`client.interactions.create`), current as of mid-2026. If the `google-genai` SDK has moved on again by the time you run this, check [the docs](https://ai.google.dev/gemini-api/docs) for the current method name.
- Gemini has no dedicated OCR/table-extraction endpoint - it's prompted (via `--prompt`) to emit markdown with tables, so output quality depends on the model actually following that instruction. Use `--paginate` to ask it to mark original page breaks.
- `gemini_convert.py --blocks` gets positioned output (comparable to Mistral's `blocks`): renders pages to images locally and asks Gemini for a JSON array per page of `{type, box_2d, content}`, where `box_2d` is `[ymin, xmin, ymax, xmax]` normalized to 0-1000 (not absolute pixels like Mistral - rescale using each page's saved `dimensions`). Always saves as JSON regardless of `--format`.
- Mistral OCR returns per-page markdown/tables/images natively; `--format json` (default) keeps the full structured response, `--format markdown` concatenates just the page markdown.
- `openrouter_convert.py`'s `--format json` (default) is just `{"model": ..., "pages": [{"page": N, "text": ...}]}` - unlike Mistral, OpenRouter models don't return positioned blocks/bounding boxes, so this is markdown text wrapped in JSON, not structured layout data.
- `glm_convert.py` requires a self-hosted GLM-OCR model server first (the same one `pipelines/02_ocr/GLM-OCR/ocr_test.py` already talks to, default `localhost:8080`), e.g. `vllm serve zai-org/GLM-OCR --port 8080 --served-model-name glm-ocr` or the equivalent SGLang command - see the [glmocr README](https://github.com/zai-org/GLM-OCR#option-2-self-host-with-vllm--sglang). Both need a CUDA GPU. The script then additionally runs PP-DocLayout-V3 **locally** (via the `glmocr` SDK, not on that server) to detect layout regions before sending each one to the OCR server for recognition - a small (1-31M-param) object detector, not an LLM, so CPU is fine (`--layout-device cpu`) even without a GPU. First run downloads the PP-DocLayout-V3 weights from Hugging Face.
- No CUDA GPU (e.g. a laptop with only integrated graphics)? Use **Ollama** instead of vLLM/SGLang - GLM-OCR is officially published there and runs CPU-only:
  1. Install Ollama for Windows: https://ollama.com/download/windows (installs as a background service listening on `localhost:11434` - no separate `ollama serve` needed afterwards).
  2. `ollama pull glm-ocr` (~2.2GB; `ollama pull glm-ocr:q8_0` is a smaller/faster ~1.6GB quantization, a reasonable default with no GPU).
  3. Run with `--ollama`: `python pipelines/02_ocr/glm_convert.py PDF --ollama` - this alone switches the port to `11434`, the model to `glm-ocr:latest`, and the API mode to Ollama's native `/api/generate` (its OpenAI-compatible endpoint is known to fail on vision requests, per the glmocr SDK's own config comments). PP-DocLayout-V3 still runs locally via the `glmocr` SDK either way, on CPU (no GPU to auto-select).
  4. If output comes back truncated or garbled: Ollama's default context window is too small for image input plus a full-page OCR response. `pipelines/02_ocr/GLM-OCR/Modelfile` creates a custom tag with a wider context (`ollama create glm-ocr-flugblatt -f Modelfile` from that directory, then pass `-m glm-ocr-flugblatt:latest --ollama`).
- `glm_convert.py` overrides GLM-OCR's stock `label_task_mapping` config: by default the pipeline discards headers, footers, footnotes, page numbers and references entirely (no block at all), which would make it silently less complete than every other engine here. The override routes them through the "text" OCR task instead, same as everything else in this pipeline.
- `glm_convert.py`'s block `type` is GLM/PP-DocLayout-V3's own label vocabulary (`doc_title`, `paragraph_title`, `footer`, `table`, ...), and `bbox_2d` is `[x1, y1, x2, y2]` normalized 0-1000 per axis - a different key name *and* axis order from Gemini's `--blocks` `box_2d` (`[ymin, xmin, ymax, xmax]`), so `ocr_viewer`'s adapters distinguish the two by the `bbox_2d` vs. `box_2d` key rather than by shape alone.
