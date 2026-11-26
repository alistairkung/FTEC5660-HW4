# B0 experiment

B0 flattens HTML with BeautifulSoup, adds report metadata and splits at 1,500 characters with 200 characters of overlap. BM25 searches the whole corpus using lowercase whitespace tokens and returns the top five original chunks even for an unknown query. Query parsing returns an empty dictionary. The fixed generator produced 28 correct answers on the 60 public questions in one run. The retriever supplied all required evidence for 13 of 46 answerable questions.

## Reproduce the offline reference

Run from the repository root. The lock captures the 59 distributions installed from the lecturer's requirements on CPython 3.14.0, macOS arm64. For a self-contained B0 checkout, use the M1 artifact commit, which includes the measured code and the saved reference report.

```sh
uv venv --python 3.14 .venv
uv pip sync --python .venv/bin/python evaluation/b0/requirements.lock
uv pip check --python .venv/bin/python
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/hw4-offline.json --compare evaluation/b0/offline.json
cmp evaluation/b0/offline.json /tmp/hw4-offline.json
```

For a new deterministic variant, run the same evaluator against its checkout and pass the saved B0 report to `--compare`. It prints both sets of metrics and the question IDs with gained or lost evidence hits. The comparison requires matching fixture bytes. Ranked entries identify each chunk by source filename and zero-based ordinal within its document. The evaluator fails on retrieval contract violations and blocks outbound DNS and socket connections during scoring.

## Measurement evidence

- [Manifest](manifest.json) records the measured code revision, pre-existing candidate, fixture hashes, configuration, and scores. The final artifact commit follows the measured code commit.
- [Offline report](offline.json) records the ranked chunks and hit for every question. All three fresh processes, including one from a clean clone, produced identical bytes.
- [Lecturer CSV](results.csv) and [runner output](runner.txt) record the single live run. The command was `python hw4.py --data-folder public_test --output evaluation/b0/results.csv` with a 1,800-second subprocess timeout. The last two log lines are wall time and exit status from that wrapper. Cost is the lecturer's token-price estimate. Live answers and timings can vary.
- The fixed generator correctly answered 13/14 unanswerables despite B0 returning chunks for every question. One comparison answer scored correctly even though retrieval supplied zero complete comparison evidence sets. Use the retrieval and answer scores separately when evaluating V1.
