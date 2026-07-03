# Baselines: AI vs simpler methods (same checker)

Backends actually used -> TF-IDF: `pure-python`, vector: `pure-python-hashing`.

| method | n | pass_rate | grounded_rate | transfer_ok_rate | wellformed_rate | wrong_fact_rate | mean_grounding | mean_transfer_sim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai-claude | 50 | 0.9 | 0.94 | 0.98 | 0.98 | 0.0 | 0.933 | 0.252 |
| baseline-tfidf | 18 | 0.0 | 0.778 | 0.167 | 0.944 | 0.0 | 0.806 | 0.833 |
| baseline-vector | 18 | 0.0 | 0.667 | 0.278 | 0.944 | 0.0 | 0.713 | 0.722 |

- AI beats `baseline-tfidf` on pass rate: **True**
- AI beats `baseline-vector` on pass rate: **True**
