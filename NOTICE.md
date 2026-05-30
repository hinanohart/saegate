# NOTICE

`saegate` source code is licensed under the MIT License (see `LICENSE`).

## Third-party model artifacts

`saegate` does not redistribute model weights. Users opt into downloading
artifacts at runtime via the `inference` extras. Each artifact retains its
upstream license.

### Default inspector LM and SAE

- `meta-llama/Llama-3.1-8B-Instruct` — governed by the
  **LLAMA 3.1 COMMUNITY LICENSE** (Meta). License source:
  <https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct/blob/main/LICENSE>
  (verified 2026-05-23).
- `Goodfire/Llama-3.1-8B-Instruct-SAE-l19` — derives from Llama 3.1 and
  inherits the same license. Hub page:
  <https://huggingface.co/Goodfire/Llama-3.1-8B-Instruct-SAE-l19>
  (verified 2026-05-23).

By installing `saegate[inference]` and loading these artifacts you accept
the LLAMA 3.1 COMMUNITY LICENSE at the Hugging Face Hub download step.

### Alternate SAEs

`saegate` is artifact-agnostic. Any SAE loadable via `sae_lens.SAE.from_pretrained`
can be substituted by overriding `ProbeConfig.sae_model_id` and
`sae_layer`. Users are responsible for honoring the license attached to
whatever artifact they load.

## Trademarks

"Llama" is a trademark of Meta Platforms, Inc. "Claude" is a trademark of
Anthropic, PBC. `saegate` is not affiliated with, endorsed by, or sponsored
by either.
