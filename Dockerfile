# Glama/MCP-directory verification image: install and expose the stdio server.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# MCP over stdio — pipe JSON-RPC lines into the container:
#   docker build -t loci-mcp . && docker run -i loci-mcp
ENTRYPOINT ["loci-mcp"]
