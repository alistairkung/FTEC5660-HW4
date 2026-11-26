# V5 evidence-aware abstention

V5 applies two corpus checks before the V4 ranking runs.

1. **Absent company.** A single unresolved parsed company must appear in a possessive or explicit `did <company> …` role in the question. Every indexed chunk must have company metadata. A known company name in the question or an exact mention of the unresolved name in indexed text keeps the V4 result. This preserves fallback on incomplete parses, ambiguous resolutions, and unresolved comparisons.
2. **Unsupported historical period.** For an annual-report question with one distinct recognized year and fully resolved subjects, abstain if any subject has annual-report metadata and its oldest annual report is more than one year newer than the requested period. A matching metadata year or a mention of the period anywhere in that subject's indexed chunks keeps the question eligible for that subject. The text check accepts the four-digit year and two-digit FY notation. The oldest report's immediately preceding year remains eligible for comparative columns.

The checks use question text and in-memory chunks. Future forecast and guidance periods stay eligible. All retained questions use V4's original ranked chunks. Metric wording, synonyms, and BM25 scores provide insufficient evidence for reliably rejecting a disclosure request in this experiment.

## Public results

| Metric | V4 | V5 |
|---|---:|---:|
| Answerable kept | 46/46 | 46/46 |
| Unanswerable rejected | 0/14 | 7/14 |
| Task 3 points | 0.00/10 | 5.00/10 |
| Recall@5 | 25/46 | 25/46 |
| Fact / table / comparison hits | 10/12 · 11/22 · 4/12 | 10/12 · 11/22 · 4/12 |
| Query fields correct | 180/180 | 180/180 |
| Answer accuracy | 40/60 | 40/60 |
| Estimated automatic points | 44.96/75 | 49.96/75 |

Task 3 uses `10 × max(0, kept_rate + rejected_rate − 1)`. V5 gets `10 × (46/46 + 7/14 − 1) = 5.00`. In the positive-score range, rejecting one public answerable costs about 0.217 Task 3 points and can also lose retrieval or answer credit. Each newly rejected unanswerable is worth about 0.714 Task 3 points. V5 had zero false abstentions and zero gained or lost evidence hits. The ordered chunk lists for all 53 retained questions were identical to V4.

| Public unanswerable class | Rejected | Nearby answerable controls |
|---|---:|---|
| Absent company | 5/5 | q030 asks the same cash question as q041 about a real company in the corpus. q036 is an operating-income question about a real company with a similar name to another indexed company. |
| Unsupported historical period | 2/5 | q024 and q026 ask for FY2023 comparative figures. q008 and q029 ask for guidance or a forecast beyond the report year. |
| Undisclosed metric | 0/4 | q020 asks for a disclosed segment's revenue. Similar wording alone would also miss q033's undisclosed single-customer revenue. q038 asks for a disclosed metric for the same company as q039. |

**Successful abstentions.** q001, q011, q034, q041, and q044 named companies with no exact indexed identity or literal occurrence, and each passed the subject-role and complete-metadata checks. q006 and q032 asked for a period outside the company's annual coverage and comparative allowance, with no matching year in that company's indexed text or metadata.

**Retained unanswerables.** The period rule preserved q005, q028, and q049 because the requested year appeared in governance text. The year occurred as a director's start year for q005 and an executive's start year for q028 and q049. These mentions may be unrelated, but they block historical abstention under the conservative policy. The other retained cases ask for lobbying expense (q019), offset spending (q025), single-customer revenue (q033), and churn (q039). The fixed generator returned NOT_FOUND for all seven.

The single V5 live run scored **40/60** with 10/12 facts, 11/22 tables, 5/12 comparisons, and 14/14 unanswerables. Per-question correctness matched the V4 live run. V5 made **53 generator calls** (V4 made 60), using **94,341 input and 169 output tokens** for an estimated **$0.0143** (V4 $0.0164). The runner reported **6.2 seconds**, with **6.930 seconds** wall time including startup. Student usage was zero.

## Generalization and next decision

Textual aliases and company metadata can disagree. The literal-name veto protects aliases that appear in the chunks, but alternate spellings and parser errors can still produce false absence. An older period may also appear implicitly in a multi-year table without a recognized year label. Incidental dates can make the period rule keep irrelevant evidence. The synthetic tests cover nearby companies, aliases, missing metadata, comparisons, historical values and forward guidance. The public score does not estimate private-set false abstentions.

Keep V5 as the conservative submission candidate and prioritize final report and packaging checks. Any later metric-level rejection experiment should use independent paraphrase and synonym controls, with retained answerables as a primary measure.

## Reproduce

Run from the V5 checkout with the B0 dependency lock.

```sh
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-v5.json --compare evaluation/v4/offline.json
cmp /tmp/hw4-v5.json evaluation/v5/offline.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v5.trace_abstention > /tmp/hw4-v5-abstentions.json
cmp /tmp/hw4-v5-abstentions.json evaluation/v5/abstentions.json
```

The single live run used `python hw4.py --data-folder public_test --output evaluation/v5/results.csv` with a 1,800-second external deadline. [Manifest](manifest.json) · [Question-level decisions](abstentions.json) · [Live CSV](results.csv) · [Runner log](runner.txt)
