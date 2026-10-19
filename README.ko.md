<p align="center">
  <img src="docs/assets/loci-banner.svg" alt="loci — shared memory for your AI tools" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/IvenKooLab/loci/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/IvenKooLab/loci/ci.yml?branch=main&amp;label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/loci-rag/"><img src="https://img.shields.io/pypi/v/loci-rag?color=367d65" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-367d65" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-367d65" alt="MIT license"></a>
</p>

**흩어진 노트, 프로젝트 문서, Agent의 기억을 검색하고 질문하며 출처까지 확인할 수 있는 지식 베이스로 만드세요. 터미널, 브라우저, MCP 클라이언트에서 사용할 수 있습니다.**

loci는 벡터 검색과 BM25를 결합하고 답변에 `파일 > 섹션` 인용을 붙입니다. 파일과 인덱스는 로컬에 저장됩니다. 임베딩과 채팅 요청은 설정한 서비스로 전송되며, 로컬 모델로 전체 과정을 오프라인에서 실행할 수도 있습니다.

[빠른 시작](#빠른-시작) · [Web 콘솔](#web-콘솔) · [AI 도구 연결](#ai-도구-연결) · [상세 가이드 · 영어](docs/guide.en.md)

![loci 콘솔과 기억 파일 미리보기](docs/assets/console-demo-light.png)

*실제 UI에 가상의 데모 데이터를 넣어 촬영했습니다. 개인 지식 베이스, 계정, API 키에는 연결하지 않았으며 통계는 예시 값입니다.*

<details>
<summary>어두운 테마 미리보기</summary>

![loci console — dark theme, fictional demo data](docs/assets/console-demo-dark.png)

</details>

## 무엇을 할 수 있나요?

| 필요한 작업 | loci의 기능 |
|---|---|
| 예전에 내린 결정 찾기 | 디렉터리를 가로지르는 하이브리드 검색과 태그·경로·날짜 필터 |
| 답변의 근거 확인하기 | 섹션별 출처 인용과 선택적인 주장별 검증 |
| AI 도구를 바꿔도 맥락 유지하기 | MCP로 같은 인스턴스를 공유하고 장기 기억을 Markdown으로 저장 |
| 각 Agent의 기억 살펴보기 | harness 자동 탐색, 파일 보기, 통계와 요약 |
| 화면에서 지식 베이스 관리하기 | 검색, 질문, 기억 편집, 인덱스 갱신과 감사 로그 |

Markdown, 텍스트, HTML, org-mode, 채팅 내보내기를 기본 지원합니다. PDF, Word, OCR은 선택 확장으로 제공됩니다. 기존 편집기나 Obsidian 저장소를 그대로 사용할 수 있습니다.

## 빠른 시작

**Python 3.11+**가 필요합니다. 설정 예제가 포함된 소스로 시작하려면:

```bash
git clone https://github.com/IvenKooLab/loci.git
cd loci
python -m pip install -e .
cp config.example.toml config.toml
```

`config.toml`의 `[llm]`, `[embed]`를 설정하고 `[[sources]].path`를 노트 디렉터리로 바꾸세요. 임베딩 서비스는 `/embeddings`를 지원해야 합니다. 채팅과 임베딩에 서로 다른 공급자를 사용할 수 있습니다.

```bash
loci ingest
loci search "배포 결정"
loci ask "배포 방식을 어떻게 결정했으며 이유는 무엇인가요?"
```

설정이 이미 있다면 `python -m pip install loci-rag`로 설치하고 `LOCI_HOME`에 인스턴스 디렉터리를 지정하세요. PDF·Word 지원: `python -m pip install 'loci-rag[pdf,docx]'`.

> 키는 `BRAIN_LLM_API_KEY`, `BRAIN_EMBED_API_KEY`로도 전달할 수 있습니다. 임베딩 모델을 바꾼 뒤에는 `loci ingest --force`로 인덱스를 다시 만드세요.

## Web 콘솔

```bash
loci serve-http
```

**[127.0.0.1:8765/ui](http://127.0.0.1:8765/ui)**를 여세요. UI는 영어·중국어 간체 및 밝은·어두운 테마 전환을 지원하며 별도의 프런트엔드 빌드가 필요하지 않습니다.

기본적으로 루프백 주소의 익명 연결에는 관리자 권한이 부여됩니다. 리버스 프록시나 SSH 터널을 사용한다면 `[http] local_admin = false`와 역할별 토큰을 설정하세요. [접근 제어 · 영어](docs/guide.en.md#web-console).

DeepSeek Harness에서는 [loci-dsh](https://github.com/IvenKooLab/loci-dsh)를 통해 같은 HTTP 백엔드의 검색, 질문, 기억 저장 기능을 워크벤치에서 사용할 수 있습니다.

## AI 도구 연결

MCP 클라이언트들이 **같은 `LOCI_HOME`**을 가리키면 설정, 인덱스, 기억을 공유합니다.

```json
{
  "mcpServers": {
    "loci": {
      "command": "loci-mcp",
      "env": { "LOCI_HOME": "/absolute/path/to/your/loci-instance" }
    }
  }
}
```

인스턴스 디렉터리에 `config.toml`이 있어야 합니다. 클라이언트가 `loci-mcp`를 찾지 못하면 실행 파일의 절대 경로를 지정하세요.

| MCP 도구 | 용도 |
|---|---|
| `brain_search` · `brain_ask` | 검색과 출처가 있는 답변 |
| `brain_remember` · `brain_forget` | 장기 기억 저장 및 철회 |
| `brain_links` · `brain_graph` | 노트 링크와 지식 관계 탐색 |
| `brain_wiki` · `brain_harness` | 지식 정리와 Agent 기억 관리 |
| `brain_stats` · `brain_ingest` | 인덱스 확인과 갱신 |

## 일상적인 사용 흐름

```bash
loci watch
loci remember "데모에는 스테이징 환경 사용" --title "데모 환경 결정"
loci search "데모 환경" --tag memory
loci ask "데모를 준비할 때 무엇을 확인해야 하나요?" --verify
loci harness
```

변경된 파일을 증분 색인하며 기억은 읽기 쉬운 Markdown으로 유지됩니다. 여러 기기에서는 원본 파일과 기억을 동기화하고 인덱스는 각 기기에서 다시 만드세요. 키는 저장소에 넣지 마세요.

## 문서

[사용 가이드 · 영어](docs/guide.en.md) · [설정 예제](config.example.toml) · [아키텍처](docs/ARCHITECTURE.md) · [변경 기록](CHANGELOG.md) · [로드맵](docs/roadmap.md) · [기여 안내](CONTRIBUTING.md)

런타임에는 OpenAI 호환 SDK와 ChromaDB를 사용하며 LangChain이나 LlamaIndex에 의존하지 않습니다. 테스트는 API 키 없이 오프라인으로 실행할 수 있습니다.

```bash
python -m pip install -e '.[dev,pdf]'
pytest
```

[GitHub](https://github.com/IvenKooLab/loci) · [Gitee](https://gitee.com/IvenKooLab/loci) · [MIT](LICENSE)
