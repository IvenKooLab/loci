from second_brain.store import Store


def make_chunks(n):
    return [{"text": f"chunk {i} text", "section": f"S{i}"} for i in range(n)]


def make_vectors(n, dim=8):
    return [[float(i)] * dim for i in range(n)]


def test_upsert_and_count(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks(make_chunks(3), make_vectors(3), "/f.md", "h1")
    assert store.count() == 3


def test_reupsert_replaces_old_chunks(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks(make_chunks(3), make_vectors(3), "/f.md", "h1")
    store.upsert_chunks(make_chunks(2), make_vectors(2), "/f.md", "h2")
    assert store.count() == 2
    assert store.indexed_hash("/f.md") == "h2"


def test_indexed_hash_missing_file(tmp_path):
    store = Store(str(tmp_path / "db"))
    assert store.indexed_hash("/never.md") is None


def test_query_returns_breadcrumbs_and_tags(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks([{"text": "findme alpha", "section": "A > B"}],
                        make_vectors(1), "/f.md", "h", tags="rag,notes")
    hit = store.query(make_vectors(1)[0], 5)[0]
    assert hit["section"] == "A > B"
    assert hit["tags"] == "rag,notes"
    assert hit["source"] == "/f.md"


def test_all_chunks_and_get_many(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks(make_chunks(2), make_vectors(2), "/f.md", "h")
    ids, docs = store.all_chunks()
    assert len(ids) == len(docs) == 2
    got = store.get_many(ids[:1])
    assert got[0]["id"] == ids[0]
    assert got[0]["section"].startswith("S")


def test_delete_file(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks(make_chunks(2), make_vectors(2), "/f.md", "h")
    store.delete_file("/f.md")
    assert store.count() == 0


def test_prune_removes_only_gone_files(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks(make_chunks(2), make_vectors(2), "/keep.md", "h")
    store.upsert_chunks(make_chunks(2), make_vectors(2), "/gone.md", "h")
    removed = store.prune(keep={"/keep.md"})
    assert removed == ["/gone.md"]
    assert store.count() == 2
    assert store.list_sources() == {"/keep.md"}
