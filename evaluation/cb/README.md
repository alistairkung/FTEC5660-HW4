# C+B submission-candidate experiment record

**Recommended for merge after review.** The promoted source reproduces the measured retrieval, and one independent full verification run reproduced **60/60** and **70.00/75**. This record accompanies the implementation PR. The final Task 5 report and personal reflection are outside its scope.

## Revision and component changes

The branch was cut from reviewed GitHub `main` at V6 `fb737e470be65c2cba75b77465e61f2a8cef9b73`. The implementation and replay files were verified in a clean clone of `183c7579a8b22ce54784162d7e7e487e951bfb1a`. The subsequent evidence commit records that run and retains the same runtime and tests.

The measured source and tests from `research/combined-prose-cells` were copied byte for byte. The runtime SHA-256 is `6e65ab615bfece13e6717b4171148f188a6ae042bbf714e49d670f6dcafa0379`. The reference pins the promoted test files, the V6 protected suffix, the public fixture tree, the environment lock and the stand-alone captures. It retains the exact ordered source and chunk locators and the SHA-256 of each formatted generator input for all four conditions. [Runtime](../../hw4.py) · [Frozen reference](reference.json) · [Verification receipt](verification/execution.json)

1. V6 still renders tables and splits parents. Ingestion also emits eligible scoped cells with their source caption, row, column and value. The cell lookup retains the already-emitted objects by source and text. BM25 still indexes V6 parents only.
2. V6 resolves the company, applies abstention and reserves comparison coverage. Track C promotes one original prose passage for eligible single-company questions. Ordinary financial-row matches retain priority.
3. Track B can substitute one already-indexed cell in its parent's slot. Emission requires a recognized unit indicator. A request for constant currency keeps the parent when the child lacks that basis. Both safeguards are the exact measured behavior.
4. The lecturer's generator, prompt, runner and scorer are byte-identical to V6. Neither experimental artifact nor public grading data is read by the student runtime.

## Full public measurements

| Run | Accuracy | Complete Recall@5 | Automatic marks | Gained / lost correct answers vs V6 |
|---|---:|---:|---:|---|
| Frozen V6 | 56/60 | 44/46 | 68.67/75 | Reference |
| Stand-alone C | 58/60 | 46/46 | 69.33/75 | q015, q018 / none |
| Stand-alone B | 58/60 | 44/46 | 69.33/75 | q024, q050 / none |
| Measured C+B | 60/60 | 46/46 | 70.00/75 | q015, q018, q024, q050 / none |
| Fresh C+B verification | **60/60** | **46/46** | **70.00/75** | **q015, q018, q024, q050 / none** |

The fresh run scored 12/12 facts, 22/22 table questions, 12/12 comparisons and 14/14 unanswerables. The unchanged Task 3 gate retained 46/46 answerables and rejected 7/14 unanswerables. Its five points are the only automatic marks short of the maximum. [Frozen V6](../v6/README.md) · [Track C CSV](research/track-c.csv) · [Track B CSV](research/track-b.csv) · [Measured C+B CSV](research/combined.csv) · [Fresh CSV](verification/results.csv)

| Lecturer task | Fresh points |
|---|---:|
| 1.1 · Table rendering | 8/8 |
| 1.2 · Chunking | 7/7 |
| 2.1 · Valid retrieval | 5/5 |
| 2.2 · Query parsing | 10/10 |
| 2.3 · Evidence recall | 15/15 |
| 3 · Abstention | 5/10 |
| 4 · Answer accuracy | 20/20 |
| **Total** | **70.00/75** |

Compared with C, the verification gained **q024** and **q050**. Compared with B, it gained **q015** and **q018**. Neither comparison lost an answer. The verified values were Whitlock Byrne LLP for q015, 75 for q018, 316.2 for q024 and 493.5 for q050. The fresh and measured C+B answers were identical on all 60 inputs. Against B, q003 differed only by the accepted `Inc.` suffix on the same prompt. It is generator variation and has no effect on marks. [Question-level audit](verification/audit.json)

The verification was one native lecturer CLI run with a 120-second wall deadline. It used 53 completed fixed-generator calls, 109,473 input tokens, 177 output tokens and zero student-model calls. Estimated cost was **$0.01652715**. The lecturer logged **6.4 s**, with **7.886 s** process wall time. The fixed model was `deepseek-v4-flash`, temperature 0, thinking off and an output limit of 64 tokens. [Fresh runner log](verification/runner.txt)

## Independent reproduction

A fresh single-branch clone installed all 59 packages from the original B0 lock on CPython 3.14.0, Darwin arm64. The installed version listing exactly matched the lock and `uv pip check` passed. Direct versions include `langchain-core 1.8.5`, `langchain-community 0.4.2`, `langchain-text-splitters 1.2.0`, `langchain-deepseek 1.2.1`, `rank-bm25 0.2.2`, `beautifulsoup4 4.15.0`, `lxml 6.1.3` and `python-dotenv 1.2.4`. [Complete dependency lock](../b0/requirements.lock) · [Environment record](verification/environment.json)

All **38 tests passed**. The offline replay checked the exact input trace on all 60 questions, including **53 matching prompt hashes and seven empty inputs**. It also ran the lecturer's canonicalization with model calls disabled. An independent source check rebuilt the 330 V6 parents and verified each of the 320 emitted children against its own rendered table and metadata. Every returned object was in the ingestion output. All 40 documents and all 12 grading tables passed. The longest chunk was 1,499 characters and the five-chunk maximum held. [Test log](verification/tests.txt) · [Offline and live audit](verification/audit.json)

In a clean checkout with `uv` and Python 3.14.0, these commands verify the committed trace and captured responses without an API key.

```sh
uv venv --python 3.14.0 .venv
uv pip sync --python .venv/bin/python evaluation/b0/requirements.lock
uv pip check --python .venv/bin/python
export PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -m unittest discover -s test
.venv/bin/python -m evaluation.cb.verify --live-dir evaluation/cb/verification
```

To measure again, provide `DEEPSEEK_API_KEY` in the environment and run `.venv/bin/python hw4.py --data-folder public_test --output /tmp/hw4-cb-results.csv` under one 120-second process deadline. The offline verifier checks deterministic input bytes. The captured answers remain separate from the deterministic trace because provider responses can vary.

## Remaining risks and rationale

The lecturer's promised private set shares the document templates and category proportions, which makes the complete public run useful evidence. It is not a private result. The combination was selected because C supplies the two missed prose facts, while B disambiguates two already-retrieved financial facts. The eleven changed prompts matched those of the two independent tracks. The clean-clone result repeated all four gains without affecting previously correct answers.

The earlier synthetic replay found two inherited prose completeness losses where a legal suffix or wrong-source auditor mention outweighed correct source or year. Explicit source requests and unfamiliar appointment wording remain sensitive. The unit and constant-currency fallbacks cover the tested cases, while other reporting qualifiers or footnotes can still be lost in a cell. The private set's performance and the prevalence of those cases remain unmeasured. The PR introduces no further retrieval changes and retains B0–V6 evidence as recorded.
