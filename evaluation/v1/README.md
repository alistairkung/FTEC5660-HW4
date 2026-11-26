# V1 table-aware extraction

V1 changes the text substituted for each HTML table before the B0 splitter runs. Each table carries its caption, header text and section labels. Each data row carries its own label and the column header for each printed value. Wide rows continue on a new line with the same row label. Narrative extraction, metadata, splitting, BM25, query handling and generator settings use the B0 implementation.

## Public results

| Measure | B0 | V1 |
|---|---:|---:|
| Mean table score | 0% | 100% |
| Passing documents | 40/40 | 40/40 |
| Chunks / maximum characters | 278 / 1,499 | 330 / 1,499 |
| Answerable kept / unanswerable rejected | 46/46 / 0/14 | 46/46 / 0/14 |
| Recall@5 | 13/46 | 18/46 |
| Fact / table / comparison evidence hits | 10/12 / 3/22 / 0/12 | 10/12 / 6/22 / 2/12 |
| Accuracy | 28/60 | 33/60 |
| Correct fact / table / comparison / unanswerable answers | 10/12 / 4/22 / 1/12 / 13/14 | 10/12 / 6/22 / 3/12 / 14/14 |
| Generator calls / student calls | 60 / 0 | 60 / 0 |
| Generator input / output tokens | 110,953 / 180 | 114,192 / 187 |
| Estimated cost / runner time | $0.0168 / 6.9 s | $0.0172 / 7.0 s |

V1 scored 31.00/75 automatic public points. All 330 chunks were LangChain Documents found verbatim within the rendered text of their recorded source. All 395 probes survived across 40 documents. Two fresh offline processes produced identical reports, with zero provenance or retrieval contract violations. All 60 live CSV rows agreed with the offline hit flags and source sets.

| Table fixture | Cells kept / graded | Score |
|---|---:|---:|
| Income statement | 26/26 | 100% |
| Balance sheet | 38/38 | 100% |
| Cash flow | 31/31 | 100% |
| Segments | 8/8 | 100% |
| Regions | 8/8 | 100% |
| Receivables | 6/6 | 100% |
| Borrowings | 6/6 | 100% |
| Employees | 10/10 | 100% |
| Board | 14/14 | 100% |
| Executives | 10/10 | 100% |
| Research financial summary | 28/28 | 100% |
| Peer valuation | 8/8 | 100% |

## Where retrieval changed

Gained hits were q003 and q053 (two-company employee comparisons), q012 and q026 (borrowings), and q047 and q052 (assets). The lost hit was q038 (net income). To distinguish extraction from selection, we inspected actual chunk text and ranked all original chunks using each variant's existing BM25 scores. Ranks below are one-based. The generator saw only ranks 1–5. Source ordinals are zero-based, as in the offline reports.

| Question and source | B0 chunk excerpt | V1 chunk excerpt | What reached the generator |
|---|---|---|---|
| q012, Northgate Robotics FY2024 long-term borrowings, doc_028 | #7 `Long-term borrowings838.4883.2` | #12 `Long-term borrowings \| 2024: 838.4 \| 2023: 883.2` | No B0 chunk from an eligible source contained 838.4 as a whole number. V1 ranked the labeled row fourth and answered 838.4. |
| q016, Corvane Pharma FY2024 gross profit, doc_031 | #7 `Gross profit2,083.51,805.4` | #7 `Gross profit \| 2025: 2,083.5 \| 2024: 1,805.4` | V1 restored the requested prior-year amount. The best eligible chunk ranked 160th. Both answers were NOT_FOUND. |
| q020, Brightwater Energy FY2025 Midstream revenue, doc_032 | #8 `Midstream716.6659.1` | #11 `Midstream \| 2025: 716.6 \| 2024: 659.1` | V1 ranked the correct row 20th. Other passages from the right company ranked higher, including its broker review at rank one. Both answers were NOT_FOUND. |
| q038, Halcyon Freight FY2024 net income, doc_008 | #4 `Net income was USD 173.9 million` | #4 `Net income was USD 173.9 million` | The same printed evidence moved from third to sixth when the indexed corpus changed. B0 answered 173.9. V1 answered NOT_FOUND. |
| q051, Northgate Robotics FY2025 net receivables, doc_038 | #7 `Accounts receivable, net492.1477.3` | #11 `Accounts receivable, net \| 2025: 492.1 \| 2024: 477.3` | The first eligible V1 chunk ranked 17th. All five returned chunks came from other source files. Both answers were NOT_FOUND. |

For q016, q020 and q051, the renderer separated the required figure from its neighbour. Global BM25 still placed the evidence below the cutoff. For q038 even a narrative passage could lose rank because BM25 scores depend on the whole indexed corpus and compete with the newly split chunks.

All 18 complete V1 retrieval hits yielded correct answers. For q056 the generator named the winning company despite incomplete cash-comparison evidence. It also correctly returned NOT_FOUND on 14/14 unanswerables even though retrieval returned five chunks each time. Live accuracy reflects a single generator run per variant. The public fixtures cover 12 table kinds; an individual label, header and value whose combined length exceeds 400 characters cannot all fit on one scored line.

## Reproduction

Use the B0 dependency lock and separate checkouts. B0 was reverified from merged main at `bf5c90c4d4421c9328cab2b1434bc303654afb01`. The measured V1 source revision is `8367e729c04431c67b40e82321424cdc67056307`. The subsequent artifact commit includes the same code plus these results.

```sh
uv venv --python 3.14 .venv
uv pip sync --python .venv/bin/python evaluation/b0/requirements.lock
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-check.json --compare evaluation/b0/offline.json
cmp evaluation/v1/offline.json /tmp/hw4-check.json
```

In the B0 checkout, compare the generated file to `evaluation/b0/offline.json`. The authorized V1 live run used the unchanged `python hw4.py --data-folder public_test --output evaluation/v1/results.csv` with a 1,800-second external timeout. The process took 7.640 seconds including startup.

The [manifest](manifest.json) records dependency versions, fixture and artifact hashes, per-table scores, code revision and usage. The [offline report](offline.json) records ordered chunk locations, the [lecturer CSV](results.csv) records answers and the [run log](runner.txt) records timings and counters.
