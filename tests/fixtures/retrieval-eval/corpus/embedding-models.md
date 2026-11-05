# Embedding and retrieval notes

## Hybrid fusion

We fuse vector hits with BM25 lexical hits using reciprocal rank fusion
(rrf_k = 60). Ranks only — scores from different channels are not
comparable, which is exactly why fusing raw scores is wrong.

## Tokenizers

The default tokenizer keeps latin words whole and splits CJK into single
characters; the cjk_bigram tokenizer improves recall on Chinese text at the
cost of some precision.

## Why not only vectors

Pure vector search misses exact identifiers like topic names and error
codes; the lexical channel catches those.
