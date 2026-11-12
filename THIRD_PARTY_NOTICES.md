# Third-party works and demonstration media

EgoLens builds on published research and separately installed dependencies. A reference does not imply endorsement. No model checkpoint, upstream full repository or full dataset is redistributed here.

## EgoLife / EgoRAG

- Code and research: <https://github.com/EvolvingLMMs-Lab/EgoLife>.
- Upstream code license: **S-Lab License 1.0**, not MIT/Apache. The original text is available at <https://raw.githubusercontent.com/EvolvingLMMs-Lab/EgoLife/main/LICENSE>.
- The public runtime here uses the project's native Qwen adapter and its own retrieval/conversation integration; it does not bundle the original EgoGPT model or the old EgoRAG/Chroma source tree. Do not apply a blanket MIT statement to upstream source if adding it later.

## Demonstration media

Source dataset: <https://huggingface.co/datasets/lmms-lab/EgoLife>.
The official dataset card declares `license: mit`: <https://huggingface.co/datasets/lmms-lab/EgoLife/blob/main/README.md>. A separate root LICENSE file was not supplied by that dataset repository at the time of preparation. Retain this attribution and refer to the original dataset terms when reusing media.

| Included derived clip | Original source | Excerpt | Added by EgoLens |
|---|---|---|---|
| `site/assets/demos/tool.mp4` | `DAY4_A1_JAKE_12253000.mp4` | 0–12s | Tracking overlay, silent web transcode |
| `site/assets/demos/bowl.mp4` | `DAY2_A1_JAKE_17163000.mp4` | 2–12s | Tracking overlay, silent web transcode |
| `site/assets/demos/bottles.mp4` | `DAY3_A1_JAKE_12000000.mp4` | 0–13s | Two-target overlay, silent web transcode |
| `site/assets/demos/memory-bed.mp4` | `DAY5_A1_JAKE_11003100.mp4` | 10–20s | Silent source excerpt for a recorded dialogue |
| `site/assets/demos/memory-phone.mp4` | `DAY6_A1_JAKE_09493300.mp4` | 0–12s | Silent source excerpt for a recorded dialogue |
| `site/assets/demos/recall-screen.mp4` | `DAY2_A1_JAKE_17383000.mp4` | 0–8s | Silent excerpt of the actual feedback window |
| `site/assets/demos/speech-replay.mp4` | `DAY4_A1_JAKE_CONTINUOUS_12150000.mp4` | 649.834–659.310s | Source speech excerpt with AAC audio |

The matching JPGs are frames from these derived clips. The first three clips are recorded tracking-module outputs. The four additional excerpts accompany curated actual historical dialogue/feedback records in `site/assets/experience.json`; answer excerpts are explicitly labelled. Clicking a historical step does not run a model. None of this footage was captured by EgoLens. Short excerpts do not establish full-sequence tracking accuracy or physical identity across days. Dataset research should cite the EgoLife paper using its [official citation](https://github.com/EvolvingLMMs-Lab/EgoLife#-citation).

## Separately installed components

- SAM2: <https://github.com/facebookresearch/sam2> (Apache-2.0; model terms also remain applicable).
- Qwen2.5-VL: <https://github.com/QwenLM/Qwen2.5-VL>; use the license of the selected checkpoint.
- OpenCLIP: <https://github.com/mlfoundations/open_clip> (MIT).
- Whisper: <https://github.com/openai/whisper> (MIT).
- Silero VAD: <https://github.com/snakers4/silero-vad> (MIT).
- FastAPI, Uvicorn, PyTorch, Transformers, Decord, NumPy and Pillow retain their respective upstream licenses.

No unified project license is granted here on behalf of third parties. The license for original EgoLens code is to be selected by the project author.
