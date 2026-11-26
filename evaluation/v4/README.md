# V4 comparison allocation

For two to five confidently resolved company identities, reserve the highest globally ranked chunk from each company. Fill the remaining slots with the highest-ranked unselected objects and return the selected objects in their original BM25 order. Repeated references to the same document object share one slot. When there are more than five identities, a reservation for every subject is impossible. The full company union stays eligible and the global ranking determines the five unique objects. Synthetic tests cover three, five, and six subjects.

| Public metric | B0 | V1 | V2 | V3 | V4 |
|---|---:|---:|---:|---:|---:|
| Table score | 0% | 100% | 100% | 100% | 100% |
| Documents passing | 40/40 | 40/40 | 40/40 | 40/40 | 40/40 |
| Correct query fields | 0/180 | 0/180 | 180/180 | 180/180 | 180/180 |
| Recall@5 | 13/46 | 18/46 | 18/46 | 25/46 | 25/46 |
| Fact hits | 10/12 | 10/12 | 10/12 | 10/12 | 10/12 |
| Table hits | 3/22 | 6/22 | 6/22 | 11/22 | 11/22 |
| Complete comparison hits | 0/12 | 2/12 | 2/12 | 4/12 | 4/12 |
| Both companies represented | — | — | — | 7/12 | 12/12 |
| Answerable kept | 46/46 | 46/46 | 46/46 | 46/46 | 46/46 |
| Unanswerable rejected | 0/14 | 0/14 | 0/14 | 0/14 | 0/14 |
| Answer accuracy | 28/60 | 33/60 | 33/60 (V1 reference) | 40/60 | 40/60 |

All 48 single-company ordered retrieval lists and all five global fallbacks matched V3. All 60 parse scores matched. Both offline runs returned identical reports with zero student model calls. There were zero gained or lost complete evidence hits.

## Comparison diagnosis

All twelve comparisons resolved both subjects. Every remaining failure returned both companies and missed one or more required facts. Each missing group had a matching value in an eligible original chunk, so neither unresolved names nor split evidence explained these misses. A dash indicates evidence absent from the returned list. The two ranks follow the ground-truth fact order.

| Comparison | Evidence at V3 candidate ranks | Evidence in V4 top five | Outcome |
|---|---:|---:|---|
| q003 employee count | 1, 5 | 1, 5 | Complete |
| q004 net income | 3, 9 | 3, — | Second company represented, figure missing |
| q013 net income | 1, 6 | 1, — | Second figure missing |
| q017 total assets | 6, 7 | —, — | Both figures missing |
| q021 cash | 10, 12 | —, — | Both figures missing |
| q022 total assets | 7, 9 | —, — | Both figures missing |
| q023 cash | 12, 14 | —, 5 | Sablewood gained its figure, Lumen figure missing |
| q031 net income | 12, 21 | —, — | Both figures missing |
| q037 operating income | 3, 22 | 3, — | Second figure missing |
| q053 employee count | 1, 3 | 1, 3 | Complete |
| q056 cash | 3, 4 | 3, 4 | Complete |
| q058 total assets | 3, 2 | 3, 2 | Complete |

For q004, the new Halcyon Freight chunk came from the earnings call. The required FY2024 net income figure was available at candidate rank nine. For q023, reserving a slot promoted Sablewood Retail's cash figure from candidate rank 14 to output rank five. Its counterpart remained outside the output. For q056, the original top five already included both cash figures, and V4 retained their positions.

The generator answered 40/60 correctly in one run. Category accuracy was 10/12 facts, 11/22 tables, 5/12 comparisons, and 14/14 unanswerables. All four complete comparisons were answered correctly. The generator also answered q023 correctly with incomplete scored evidence. The single-company table question q055 changed from a correct answer to NOT_FOUND with an identical retrieval list. The two live runs cannot attribute that answer change to allocation.

V4 made 60 generator calls with 108,622 input tokens and 188 output tokens, estimated at $0.0164. The runner reported 7.1 seconds, with 7.812 seconds elapsed including startup. Student calls were zero. All 60 live CSV rows matched the offline hit flags and source sets.

## Reproduce

Use the locked B0 dependencies and run these commands from the V4 artifact checkout.

```sh
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-v4.json --compare evaluation/v3/offline.json
cmp /tmp/hw4-v4.json evaluation/v4/offline.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v4.trace_comparisons > /tmp/hw4-v4-comparisons.json
cmp /tmp/hw4-v4-comparisons.json evaluation/v4/comparisons.json
```

The authorized live run used `python hw4.py --data-folder public_test --output evaluation/v4/results.csv` under a 1,800-second external deadline. [Manifest](manifest.json) · [Comparison trace](comparisons.json) · [Live CSV](results.csv) · [Runner log](runner.txt)
