# V6 financial row ranking

V6 keeps V5's abstention, resolution, and comparison allocation. For resolved annual-report intents, it makes one stable partition of the existing BM25 candidate order. A chunk moves to the first group if it contains a rendered table row with a numeric cell and the row label occurs as a contiguous phrase in the question. The match uses case-folded words and ignores punctuation. Original BM25 order breaks ties within both groups. The rule examines eligible chunks across document types and leaves forecasts, earnings-call questions, and unresolved queries on the existing order. The annual-report intent limits the change to the table-heavy path.

## V5 failure diagnosis

The trace records the first eligible rank, source and chunk ordinal, printed value, evidence excerpt, and BM25 score for each evidence group. Every V5 miss had matching evidence in the eligible pool. Across missing groups, the best eligible rank ranged from 6 to 22. Each scored below the highest returned chunk by 1.93–11.37 BM25 points, with a median gap of 5.84. This made row structure a stronger first experiment than changing extraction or increasing the chunk limit. [Per-question baseline diagnosis](v5-misses.json)

| Diagnosis | Public questions | Interpretation |
|---|---:|---|
| Correct evidence below the top five | 21 | Every missing group had a contiguous eligible match. |
| Returned a different document type for the same company | 17 | At least one returned chunk had a type different from the parsed intent. Only q013 had no returned chunk of the intended type. Other document types can still contain valid evidence. |
| Returned chunks omitted the relevant row label | 14 | For these table-evidence misses, none of the returned rows had the label of the best eligible missing evidence. Some results discussed the metric or a neighboring metric in prose. |
| Related row with the wrong reporting period | 1 observed | q055 returned a same-label cash row covering 2024–2025 when the question asked for 2023. This is a row-level check, since an annual-report metadata year alone cannot identify a comparative column. |
| Incomplete comparison | 8 | All eight represented both companies, but one or both figures were outside the selected chunks. |
| Evidence lost or split during extraction | 0 | Each missing printed fact was present in at least one eligible original chunk. |
| Prose evidence | 2 | q015 auditor at rank 12 and q018 repurchase announcement at rank 8. |

The categories overlap. Nineteen misses had the missing evidence in rendered rows. In the five cases with a related row already returned, examples include the other company's figure (q004, q013, q037), a different period (q055), and a different point-in-time cash row (q023).

## Scorecard

| Lecturer task | V5 | V6 |
|---|---:|---:|
| 1.1 Table rendering | 8.00/8 | 8.00/8 |
| 1.2 Chunking | 7.00/7 | 7.00/7 |
| 2.1 Valid retrieval | 5.00/5 | 5.00/5 |
| 2.2 Query parsing | 10.00/10 | 10.00/10 |
| 2.3 Retrieval recall | 1.63/15 | 15.00/15 |
| 3 Abstention | 5.00/10 | 5.00/10 |
| 4 Answer accuracy | 13.33/20 | 18.67/20 |
| **Automatic total** | **49.96/75** | **68.67/75** |

| Public measurement | V5 | V6 |
|---|---:|---:|
| Complete evidence Recall@5 | 25/46 | 44/46 |
| Fact / table / comparison evidence hits | 10/12 · 11/22 · 4/12 | 10/12 · 22/22 · 12/12 |
| Both companies represented | 12/12 | 12/12 |
| Table score / documents passing | 100% / 40/40 | 100% / 40/40 |
| Query fields correct | 180/180 | 180/180 |
| Answerable kept / unanswerable rejected | 46/46 / 7/14 | 46/46 / 7/14 |
| End-to-end accuracy | 40/60 (66.7%) | 56/60 (93.3%) |
| Fact / table / comparison / unanswerable answers | 10/12 · 11/22 · 5/12 · 14/14 | 10/12 · 20/22 · 12/12 · 14/14 |
| Student model calls | 0 | 0 |
| Generator calls | 53 | 53 |
| Generator input / output tokens | 94,341 / 169 | 111,588 / 178 |
| Estimated cost | $0.0143 | $0.0168 |
| Runner time / process wall time | 6.2 s / 6.930 s | 6.2 s / 7.171 s |

**Evidence gains** were q004, q013, q016, q017, q020, q021, q022, q023, q024, q031, q037, q040, q043, q045, q046, q050, q054, q055, and q060. There were zero evidence or live correctness losses. For q017, the two total-assets figures moved from eligible ranks 6 and 7 to output ranks 1 and 2. The period for q055 was recovered at output rank 1. [V5/V6 per-question retrieval ranks](ranks.json)

The generator answered 16 additional questions correctly. q015 and q018 still lacked their required prose in the retrieved chunks. q024 recovered the correct region and year at rank 2, but the generator chose 349.0 from FY2024 instead of 316.2 from FY2023. q050 recovered the correct FY2023 row at rank 1, but the generator chose 158.1 from the Americas row instead of 493.5 from Europe, Middle East and Africa. Both correct and incorrect figures were present in the same source chunk for q050. These are answer selection errors after an evidence hit.

## Synthetic checks and limits

Four ranking tests cover unseen companies, the labels “unbilled-service receivables,” “deferred grants,” and “scrap recovery yield,” comparative years 2029–2031, a simple table and grouped headers, bracketed negative values, percentages, nonnumeric rows, same-label passages for the wrong company, comparison allocation, BM25 tie order, and the prose fallback. The first ranking test failed against V5 before implementation. All 35 tests passed with V6.

A literal label match can miss synonyms and reordered or split labels. Generic labels may promote several years or neighboring values together, and digits and punctuation are ignored when comparing labels. Rich layouts can still obscure a value. Public results and synthetic tests do not measure private performance.

Adopt V6 as the submission candidate on the available evidence. The public gain is 18.71 automatic points with no measured loss in the existing full-score tasks or abstention. The remaining misses concern prose ranking and selecting the right row or column once the evidence is retrieved.

## Reproduce

Use the locked B0 dependencies and run from the V6 checkout.

~~~sh
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v6.diagnose > /tmp/hw4-v5-misses.json
cmp /tmp/hw4-v5-misses.json evaluation/v6/v5-misses.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-v6.json --compare evaluation/v5/offline.json
cmp /tmp/hw4-v6.json evaluation/v6/offline.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v6.compare_rankings > /tmp/hw4-v6-ranks.json
cmp /tmp/hw4-v6-ranks.json evaluation/v6/ranks.json
~~~

The single live evaluation ran `python hw4.py --data-folder public_test --output evaluation/v6/results.csv` with a 1,800-second external deadline. [Manifest](manifest.json) · [Frozen live CSV](results.csv) · [Runner log](runner.txt)
