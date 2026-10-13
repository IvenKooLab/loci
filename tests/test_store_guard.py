"""The vector-space guard (v0.6.x): one embedding model per collection.

Switching [embed] model/provider without --force used to crash chroma mid-ingest
(or, with matching dimensions, silently mix two vector spaces). ensure_embed()
must refuse with actionable guidance and rebuild cleanly under --force."""
import pytest

from loci.store import Store


def _seed(store, dim=4, fingerprint=False):
    store.collection.add(ids=["a"], documents=["x"], embeddings=[[0.1] * dim],
                         metadatas=[{"source": "f"}])
    if fingerprint:
        store._stamp({"embed_model": "model-A", "embed_dim": dim})


def test_legacy_collection_same_dim_gets_stamped(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4)                       # no fingerprint: pre-guard index
    store.ensure_embed("model-A", 4)
    assert store.collection.metadata.get("embed_model") == "model-A"
    assert store.collection.count() == 1      # untouched


def test_legacy_collection_dim_mismatch_is_caught(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4)
    with pytest.raises(SystemExit, match="--force"):
        store.ensure_embed("model-B", 3)


def test_fingerprinted_change_without_force_refuses(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4, fingerprint=True)
    with pytest.raises(SystemExit, match="--force"):
        store.ensure_embed("model-B", 3)      # different model AND dimension


def test_same_dim_different_model_is_caught_too(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4, fingerprint=True)
    with pytest.raises(SystemExit, match="--force"):
        store.ensure_embed("model-C", 4)      # would silently poison retrieval


def test_force_rebuilds_collection(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4, fingerprint=True)
    store.ensure_embed("model-B", 3, rebuild=True)
    assert store.collection.count() == 0      # old vectors dropped
    meta = store.collection.metadata
    assert meta["embed_model"] == "model-B" and meta["embed_dim"] == 3


def test_matching_model_passes(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    _seed(store, dim=4, fingerprint=True)
    store.ensure_embed("model-A", 4)
    assert store.collection.count() == 1
