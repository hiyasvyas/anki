# Checker report (pre-ship gate + 7f gold-set counts)

Artifact source: **SAMPLE cached** (50 items).

## Declared cutoffs (before results)

- min grounding score: `0.6`
- max transfer similarity (copy threshold): `0.55`
- choices required: `4`
- gold-set min pass rate: `0.8`

## Three counts (7f)

| Count | Meaning | N |
| --- | --- | ---: |
| 1. correct + useful | ships to students | 45 |
| 2. wrong (a wrong fact) | BLOCKED (worse than no card) | 0 |
| 3. correct-but-bad-teaching | BLOCKED (vague/trivial/dup/ungrounded) | 5 |
| total generated | | 50 |

Pass rate (correct+useful / total): **90.0%** (cutoff 80%) -> **MEETS CUTOFF**

Blocked (not shown to students): **5**

## Blocked items

- `gen-bio-cellresp-0` (bio-cellresp) [correct_bad_teaching]: grounding 0.54 < 0.60
- `gen-bio-cellresp-1` (bio-cellresp) [correct_bad_teaching]: grounding 0.43 < 0.60
- `gen-bio-cellresp-2` (bio-cellresp) [correct_bad_teaching]: near-copy: stem overlap 0.95 >= 0.55
- `gen-bio-membrane-3` (bio-membrane) [correct_bad_teaching]: duplicate choices
- `gen-bio-enzyme-3` (bio-enzyme) [correct_bad_teaching]: grounding 0.00 < 0.60
