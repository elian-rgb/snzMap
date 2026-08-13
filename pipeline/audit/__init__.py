"""Precision audit: are the events the extractor produced actually true?

Deliberately separate from `pipeline.spans.evaluate`, which measures recall against gold
rows Kiki writes from outside the system. The two answer different questions and must not
be reported as one number.
"""
