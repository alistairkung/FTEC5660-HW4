# V2 deterministic query parsing

V2 scored 180/180 fields and 60/60 exact three-field matches on the public questions. The lecturer awards equal weight to each field. Companies, fiscal year and document type each scored 60/60. There were zero public failures to classify. The public parse score rose from 0% in V1 to 100% in V2.

The parser works from the question alone, before indexing. It uses capitalization, possessives, grammatical roles and coordination to identify subjects, including companies absent from the corpus. It extracts the requested year, including dated comparisons and forecast periods. An explicit earnings call takes precedence over forecast wording. Research cues select a broker report. Other questions default to an annual report.

## Retrieval control

All 300 ordered chunk positions across 60 questions matched frozen V1. An independent offline replay from the V1 merge and the V2 code revision also produced byte-identical generator prompts for every question, including passage text, metadata headers and order. The manifest records the SHA-256 of this sorted question-ID-to-prompt mapping, serialized with Python JSON defaults, UTF-8 characters and a trailing newline.

Recall remained 18/46 (10/12 facts, 6/22 table questions, 2/12 comparisons). Zero evidence hits were gained or lost. Both variants kept 46/46 answerables and rejected 0/14 unanswerables. Both passed 40/40 documents and scored 100% on tables. V2 made zero student calls and zero generator calls. **33/60 (55.0%) is the inherited V1 answer-accuracy reference.** There is no new V2 answer CSV, accuracy measurement or generator spend.

## Residual risks

Two exploratory synthetic questions illustrate ambiguity outside the public set. The lowercase subject in “How much did copper vale systems earn in FY2030?” produced an empty company list. In “Which had more assets: Reed and Vale or Willow Group?”, the parser treated “and” as a comparison boundary and returned Reed and Vale as separate companies. Exact corpus metadata could help resolve known entities in a later stage. Unknown entities, unfamiliar reporting verbs and questions asking about multiple fiscal periods remain harder to resolve from wording alone.

## Reproduce

Use CPython 3.14 and the dependency lock in `evaluation/b0/requirements.lock`. Run from the repository root at the V2 artifact commit.

```sh
uv venv --python 3.14 .venv
uv pip sync --python .venv/bin/python evaluation/b0/requirements.lock
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m unittest discover -s test -v
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.offline --output /tmp/v2-offline.json --compare evaluation/v1/offline.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m evaluation.v2.score_fields > /tmp/v2-parsed.json
cmp /tmp/v2-offline.json evaluation/v2/offline.json
cmp /tmp/v2-parsed.json evaluation/v2/parsed.json
```

The [question-level parses and field scores](parsed.json) use the lecturer scorer. The [offline report](offline.json) retains ordered chunk locators. The [manifest](manifest.json) ties both to the measured source, fixture tree, environment and prior experiment.
