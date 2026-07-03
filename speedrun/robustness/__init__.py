"""Adversarial-robustness checks (spec section 10 "we will try to break it").

Three re-runnable, stdlib-only checks, each with a synthetic self-test so it
produces a real report with or without an Anki collection:

* ``contradictions``  -- two cards that state opposite facts.
* ``rushed_reviews``  -- a student who taps "Good" without reading.
* ``sync_robustness`` -- a phone that goes offline mid-sync, or whose clock is
  set wrong.

Run all three:  ``python -m speedrun.robustness.run all``
"""
