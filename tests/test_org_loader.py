from loci.loaders import _read_org, scan_sources


ORG_DOC = """#+TITLE: Garden Log
#+FILETAGS: :farming:journal:
#+AUTHOR: Iven
* Spring
Planting went well this year.
** Radishes
First crop, 21 days.
- water daily
+ thin the seedlings
See [[https://example.com/radish][the radish guide]] and [[*Radishes][this section]].
* Summer
#+BEGIN_SRC python
print("hot")
#+END_SRC
"""


def test_org_title_becomes_h1_and_headings_map():
    out = _read_org(ORG_DOC)
    assert out.startswith("---\ntags: [farming, journal]\n---")
    assert "# Garden Log" in out           # TITLE → h1
    assert "## Spring" in out              # * shifts one level under the title
    assert "### Radishes" in out           # ** → ###
    assert "## Summer" in out
    assert "#+AUTHOR" not in out           # other #+KEYWORDS dropped


def test_org_lists_normalized_and_links_converted():
    out = _read_org(ORG_DOC)
    assert "- water daily" in out
    assert "- thin the seedlings" in out   # "+ " bullet → "- "
    assert "[the radish guide](https://example.com/radish)" in out
    assert "this section" in out           # internal link keeps text only, no broken md link


def test_org_src_block_survives_as_plain_text():
    out = _read_org(ORG_DOC)
    assert "#+BEGIN_SRC" in out and 'print("hot")' in out  # passes through verbatim


def test_scan_sources_picks_up_org_with_tags(tmp_path):
    (tmp_path / "log.org").write_text(ORG_DOC, encoding="utf-8")
    docs = scan_sources([{"path": str(tmp_path)}])
    assert len(docs) == 1
    doc = docs[0]
    assert doc["tags"] == "farming,journal"       # FILETAGS → frontmatter → tags field
    assert "### Radishes" in doc["content"]
