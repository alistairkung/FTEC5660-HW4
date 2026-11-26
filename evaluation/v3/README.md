# V3 company metadata filtering

V3 builds a company-to-chunk lookup from indexed metadata. It casefolds and collapses whitespace, applies Unicode NFKC, and removes terminal periods and one trailing legal suffix for lookup. When two distinct full names share a key, the key is ambiguous. If every parsed subject resolves, V3 takes the union of their chunk positions and selects the first five from the existing whole-corpus BM25 order. The original BM25 scores and tie order apply to both filtered and global retrieval.

| Public metric | B0 | V1 | V2 | V3 |
|---|---:|---:|---:|---:|
| Table score | 0% | 100% | 100% | 100% |
| Documents passing | 40/40 | 40/40 | 40/40 | 40/40 |
| Parse fields | 0/180 | 0/180 | 180/180 | 180/180 |
| Recall@5 | 13/46 | 18/46 | 18/46 | 25/46 |
| Facts | 10/12 | 10/12 | 10/12 | 10/12 |
| Tables | 3/22 | 6/22 | 6/22 | 11/22 |
| Comparisons | 0/12 | 2/12 | 2/12 | 4/12 |
| Answerable kept | 46/46 | 46/46 | 46/46 | 46/46 |
| Unanswerable rejected | 0/14 | 0/14 | 0/14 | 0/14 |
| Answer accuracy | 28/60 | 33/60 | 33/60 (V1 reference) | 40/60 |

The single V3 live run answered 10/12 fact, 12/22 table, 4/12 comparison and 14/14 unanswerable questions correctly. All 25 questions with a complete evidence hit were correct. The generator also answered q055 correctly without a scored evidence hit. It completed 60 calls using 108,035 input tokens and 187 output tokens. The cost estimate was $0.0163. The runner reported 10.7 seconds, with 11.787 seconds elapsed including startup. Student usage was zero.

## Resolution and retrieval changes

55/60 questions resolved completely. The five fallbacks were q001, q011, q034, q041 and q044, all asking about companies absent from indexed metadata. No public question triggered an ambiguous key or empty parse. Global fallback keeps evidence available when resolution fails, and still returns chunks for absent-company queries. In synthetic tests, the V2 parser missed lowercase names and split a name containing “and.” Off-corpus fragments trigger fallback. A misparse in which every fragment happens to match a real company can still narrow the candidate pool incorrectly. The resolver accepts a lowercase or conjunction-bearing name when the parser supplies it intact.

Single-company hits rose from 16/34 to 21/34, and multi-company hits from 2/12 to 4/12. The seven gains were q030, q036, q038, q051, q056, q057 and q058. No previous hit was lost.

| Question | Best evidence ranks in V2 | Best evidence ranks in V3 |
|---|---:|---:|
| q030 cash and cash equivalents | 15 | 2 |
| q036 operating income | 18 | 4 |
| q038 net income | 6 | 5 |
| q051 net receivables | 17 | 1 |
| q056 cash comparison | 5, 7 | 3, 4 |
| q057 net cash from operating activities | 13 | 1 |
| q058 asset comparison | 9, 7 | 3, 2 |
| q004 net income comparison | 3, 11 | 3, 9 |

Both companies resolved on all 12 comparison questions. Five returned chunks from only one company. For q004, both evidence groups remained eligible, but the second ranked ninth. V4 can test seeding the top five with the highest-scoring chunk for each resolved comparison subject, then filling open slots in global rank order. Measure complete evidence coverage and lost hits, since some misses already contain chunks from both companies.

## Reproduce

Use the B0 environment lock at `evaluation/b0/requirements.lock`. Run from the V3 artifact checkout.

```sh
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-v3.json --compare evaluation/v2/offline.json
cmp /tmp/hw4-v3.json evaluation/v3/offline.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v3.trace_ranks > /tmp/hw4-v3-ranks.json
cmp /tmp/hw4-v3-ranks.json evaluation/v3/ranks.json
```

Two offline processes produced identical reports. The rank trace reconstructs the global order and checks it against all 60 frozen V2 retrieval lists. It also verifies the exact V2 parse output for every question and checks the selected top five against the V3 offline report. All 60 live CSV rows matched offline evidence flags and retrieved source sets. The single live run used `python hw4.py --data-folder public_test --output evaluation/v3/results.csv` with an external 1,800-second deadline. [Configuration and hashes](manifest.json) · [Evidence ranks and resolutions](ranks.json) · [Live answers](results.csv) · [Runner log](runner.txt)
