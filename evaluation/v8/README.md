# V8 historical abstention experiment

**Recommend merge after coordinator review.** V8 scored **72.14/75** on one complete native lecturer run, up **2.14** from the measured C+B baseline. It retained **60/60** correct answers and **46/46** complete evidence hits.

## Integration and provenance

The branch starts at merged C+B, `6d008816f7efa605c7b2f1a4b0553628e4a51986` (PR #8). The integrated `hw4.py` SHA-256 is `9ca0116dbab2c96baa916e6c0e9cf0a01e276110b930704917a6fab98531001e`. The three frozen policy source hashes and previous research assemblies are recorded in the [research freeze](research-freeze.json). The [assembler](assemble.py) checks those source hashes and reproduces the integrated file byte for byte. It removes research cross-module imports, renames colliding symbols, and wires the approved helper calls into the student section. It adds no policy condition or dependency.

```text
chunk_document
  emit the C+B parent and cell chunks
  attach adjacent heading and paragraph context privately to the first parent
retrieve
  parse and resolve company as in C+B
  inspect heading context and historical evidence
  apply the original C+B decision for officer questions facing the new monetary gap
  return [] on abstention, otherwise run the C+B ranking and cell selection
```

The lecturer's protected suffix, generator, prompt and CLI match C+B byte for byte. Chunk payloads keep the original text and metadata. The heading view is private runtime context and never enters the generator prompt. B0–V6 and C+B experiment artifacts are preserved.

## Offline acceptance

- **45 tests passed.** Seven new tests cover earlier historical failures, heading dates and units, relative periods, financial synonyms, officer intent, monetary questions with officer wording, governance-only dates, comparatives and ambiguous evidence. The existing suite retains its assertions, with the expected public rejection count updated from 7 to 10. [Tests](verification/tests.txt)
- **Public.** All 12 tables and 40 documents passed, all parser fields matched, and original-chunk provenance and size limits held. The index emitted 330 parents and 320 cells. All 46 answerables and evidence hits remained. The new correct abstentions are **q005, q028 and q049**, with no losses or false abstentions. All **50 retained inputs** matched the archived ordered chunk locators and prompt hashes, including in the dry lecturer runner's canonicalization. [Offline trace](verification/offline.json)
- **Approved research panels.** All 22 sealed cases reproduced their approved ordered chunks, prompt hashes, evidence hits and policy routes. The candidate kept **15/15** answerables, with **14/15** complete hits, **3/7** correct abstentions and zero false abstentions. The one incomplete hit was the previously observed tenure stress case. All nine named historical regression outcomes matched the approved replay on the original research corpora. [Sealed fixtures](fresh-panel/AUTHOR.md) · [Approved trace](approved-panel.json) · [Regression replay](verification/research-regressions.json)

## Measured lecturer results

| Task | Archived C+B | Native V8 |
| --- | ---: | ---: |
| 1.1 · Table rendering | 8/8 | 8/8 |
| 1.2 · Chunking | 7/7 | 7/7 |
| 2.1 · Valid retrieval | 5/5 | 5/5 |
| 2.2 · Query parsing | 10/10 | 10/10 |
| 2.3 · Recall@5 | 15/15 | 15/15 |
| 3 · Abstention | 5/10 | 7.14/10 |
| 4 · Answer accuracy | 20/20 | 20/20 |
| **Total** | **70.00/75** | **72.14/75** |

Correct answers were 12/12 facts, 22/22 table questions, 12/12 comparisons and 14/14 unanswerables. There were no gained or lost correct answers or evidence hits against C+B. The three new empty lists still produced the correct `NOT_FOUND`. There were no answer text changes on the 50 identical prompts and no generator failures. [Native CSV](verification/native/results.csv) · [Question-level audit](verification/live-audit.json)

The sole V8 native run used a **120-second** process deadline and finished in **4.7 s** lecturer time and **5.56 s** process wall time. It used **50 fixed generator calls**, **102,861 input tokens**, **168 output tokens** and **zero student model calls**. The lecturer's rates give an estimated **USD 0.01552995**. The archived C+B run used 53 generator calls, 109,473 input tokens and 177 output tokens, for **USD 0.01652715** at the same rates. These timings come from separate native runs. [Runner log](verification/native/runner.txt) · [Execution receipt](verification/native/execution.json)

## Remaining private-set risks

The scope of heading-derived amounts and indirect periods still depends on the filing wording. The prior research found a stress case where flattened sections coupled a relative engineering headcount with unrelated financial prose. During integration, a generic “Directors at FY2022” heading plus an adjacent monetary amount also prompted conservative retention in both the frozen and promoted policy. The narrower explicit tenure heading passed its regression. These behaviors can reduce new correct abstentions on unfamiliar negatives.

The officer exemption deliberately falls back to C+B. In the approved synthetic panel that rescued one CFO answer and gave up one heading-only rejection of a missing CFO fact, with both decisions returning to C+B's outcome. C+B's visible-heading call-title limitation and retrieval misses outside the original top five remain inherited. The sealed set is a targeted safety check and the public run is the measured benchmark. Private scores remain unmeasured.

## Reproduction

Use the existing [dependency lock](../b0/requirements.lock). The run used Python 3.14.0 with all 59 installed packages matching the lock and passing `uv pip check`. [Environment](verification/environment.json)

From a clean clone, these steps are offline and use the saved native responses:

```sh
uv venv --python 3.14.0 .venv
uv pip sync --python .venv/bin/python evaluation/b0/requirements.lock
export PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -m unittest discover -s test -q
.venv/bin/python -m evaluation.v8.verify --audit-native evaluation/v8/verification/native
shasum -a 256 -c evaluation/v8/source.sha256
```

When the approved officer-intent research directory is available, pass its path to `evaluation.v8.assemble` and compare the output with `hw4.py`. Passing `--research` to `evaluation.v8.verify` additionally replays the nine named earlier failures on their archived corpora. A deliberate new paid measurement requires `--run-native` with a fresh output directory and an externally supplied key. The wrapper reruns the offline gate before invoking the original CLI once.

The milestone ends at the coordinator review gate.
