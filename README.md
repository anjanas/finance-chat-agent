# Finance Purple Agent

Purple agent to be used as baseline for the finance benchmark. It uses NEBIUS by default to instantiate the selected LLM.

## Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd finance-purple-agent
   ```

2. Install dependencies using `uv`:
   ```bash
   uv sync
   ```

   This will:
   - Create a virtual environment at `.venv`
   - Install all required dependencies from `pyproject.toml`
   - Install development dependencies (pytest, ruff)

## Configuration

The server requires environment variables for configuration. Create a `.env` file in the project root:

```bash
# Required: NEBIUS API Key
NEBIUS_API_KEY=your_nebius_api_key_here

# Model Configuration
MODEL_PROVIDER=nebius
MODEL_NAME=moonshotai/Kimi-K2-Instruct              # Main model for answering questions
INTENT_CLASSIFIER_MODEL=openai/gpt-4o-mini           # Model for guardrails and intent classification
JUDGE_MODEL_NAME=openai/gpt-4o-mini                  # Model for answer verification (if judge enabled)

# Prompt Mode: "json", "detailed", or "auto" (auto uses intent classifier)
PROMPT_MODE=json

# Judge Model (optional)
JUDGE_MODEL_ENABLED=false                            # Enable judge model for answer verification

# Training Date Cutoff
MODEL_TRAINING_CUTOFF=2024-04-01                     # Reject queries about dates beyond this

# MCP Server Configuration
MCP_ENABLED=false
MCP_SERVER=http://127.0.0.1:9020

# Logging
LOG_LEVEL=INFO
```

## Running the Server

Start the server using `uv run`:

```bash
uv run python src/server.py
```

The server will start on `http://127.0.0.1:9019` by default.

### Server Options

You can customize the server host, port, and card URL:

```bash
uv run python src/server.py --host 0.0.0.0 --port 8080 --card-url http://example.com
```

Options:
- `--host`: Host to bind (default: `127.0.0.1`)
- `--port`: Port to bind (default: `9019`)
- `--card-url`: External URL for agent card (default: `http://{host}:{port}/`)

## Running with Docker

The project includes a Dockerfile for containerized deployment.

### Prerequisites

- [Docker](https://www.docker.com/) installed and running

### Building the Docker Image

Build the Docker image from the project root:

```bash
docker build -t finance-purple-agent .
```

This will:
- Use the official `uv` Python image as the base
- Install all dependencies using `uv sync --locked`
- Configure the container to run the server on port 9019

### Running the Container

Run the container with port mapping:

```bash
docker run -d -p 9019:9019 --name finance-purple-agent finance-purple-agent
```

### Environment Variables

To pass environment variables (like `NEBIUS_API_KEY`) to the container:

```bash
docker run -d -p 9019:9019 \
  -e NEBIUS_API_KEY=your_api_key_here \
  -e MODEL_NAME=moonshotai/Kimi-K2-Instruct \
  --name finance-purple-agent \
  finance-purple-agent
```

### Using Environment File

You can also use a `.env` file:

```bash
docker run -d -p 9019:9019 \
  --env-file .env \
  --name finance-purple-agent \
  finance-purple-agent
```


## Testing the Server

Once the server is running, you can test it by accessing the agent card endpoint:

### Using curl

```bash
curl http://127.0.0.1:9019/card
```



### Example Response

The endpoint returns a JSON object containing the agent's metadata, including:
- `name`: "Finance Purple Agent"
- `version`: "0.1.0"
- `description`: Agent description
- `capabilities`: Agent capabilities (e.g., streaming)
- `skills`: List of agent skills with examples
- `url`: Agent service URL
- `signatures`: List of available JSON-RPC methods

## Features

### Prompt Modes

The agent supports three prompt modes:

- **`json`** (default): Returns concise JSON responses with `{"answer": value, "type": "eps/revenue/etc"}`
- **`detailed`**: Returns detailed, comprehensive financial explanations
- **`auto`**: Uses an intent classifier to automatically choose between JSON and detailed based on the query

Set the mode via `PROMPT_MODE` environment variable.

### Guardrails

The agent includes multiple guardrails to ensure quality and safety:

1. **Financial Question Check**: Validates that queries are related to finance before processing
2. **Training Date Cutoff**: Rejects queries about dates beyond the model's training cutoff to prevent hallucinations
3. **Intent Classification**: Automatically determines the appropriate response format (JSON vs detailed)

### Answer Verification

When `JUDGE_MODEL_ENABLED=true`, a separate judge model verifies each answer for:
- Correctness and factual accuracy
- Completeness
- Relevance
- Format compliance
- Absence of hallucinations

### Output Formatting

Numbers in responses are automatically formatted with:
- Commas for readability (e.g., `1,000,000`)
- M/B suffixes for millions/billions (e.g., `1M`, `2.5B`)

### Experiment Tracking

All agent interactions are automatically logged to a SQLite database (`experiment_tracker.db`) including:
- Queries and responses
- Model usage (main, intent classifier, judge)
- Token usage
- Tool calls
- Guardrail check results
- Response times
- Judge verification results

## Sending Queries to the Agent

The agent supports the A2A protocol and exposes JSON-RPC 2.0 methods for sending queries. The main method for sending queries is `message/send`.

### Using the Shell Script

The easiest way to send queries is using the provided `send_query.sh` script:

```bash
# Single query
./send_query.sh "What was Apple's revenue in Q4 2024?"

# Multiple runs (useful for testing/benchmarking)
./send_query.sh "What was Apple's revenue in Q4 2024?" --num-runs 5
./send_query.sh "What was Apple's revenue in Q4 2024?" -n 10

# Interactive mode (prompts for input)
./send_query.sh

# Show help
./send_query.sh --help
```

The script will:
- Send the query to the server (optionally multiple times)
- Display the agent's response for each run
- Show task status information (Task ID, Context ID, Status, Timestamp)
- Handle errors gracefully
- Display run progress and completion summary

### Reviewing Statistics

Use the `review_stats.sh` script to view comprehensive statistics from the experiment tracker database:

```bash
./review_stats.sh
```

This displays:
- Total queries and status breakdown
- Model usage statistics
- Guardrail pass rates
- Response time statistics
- Token usage by model
- Judge approval rates
- Tool usage statistics
- Recent queries
- And more...

### Direct Database Access

You can also query the database directly using sqlite3:

```bash
# View all queries
sqlite3 -header -column experiment_tracker.db "SELECT * FROM queries;"

# View token usage
sqlite3 -header -column experiment_tracker.db "SELECT * FROM token_usage;"

# View guardrail checks
sqlite3 -header -column experiment_tracker.db "SELECT * FROM guardrail_checks;"
```

## Architecture

### Model Usage

The agent uses three separate models for different purposes:

1. **Main Model** (`MODEL_NAME`): Used for answering user questions and tool calling
2. **Intent Classifier Model** (`INTENT_CLASSIFIER_MODEL`): Used for:
   - Financial question validation
   - Training date cutoff checks
   - Intent classification (JSON vs detailed)
3. **Judge Model** (`JUDGE_MODEL_NAME`): Used for answer verification (optional, enabled via `JUDGE_MODEL_ENABLED`)

This separation allows using optimized models for each task - a smaller/faster model for classification tasks and a more capable model for answering questions.

### Request Flow

1. **Input Guardrails**: Query is checked for financial relevance and date validity
2. **Intent Classification** (if `PROMPT_MODE=auto`): Determines response format
3. **Question Answering**: Main model processes the query, optionally using tools
4. **Answer Verification** (if judge enabled): Judge model validates the answer
5. **Output Formatting**: Numbers are formatted for readability
6. **Database Logging**: All interactions are logged to the experiment tracker

## Troubleshooting

### Database Errors

If you encounter database errors (e.g., duplicate columns), you can reset the database:

```bash
rm experiment_tracker.db
# The database will be recreated on next server start
```

### Model Configuration

Ensure all model names are correctly configured in your `.env` file. The models must be available through your NEBIUS API endpoint.

### Guardrail Rejections

If queries are being rejected:
- Check that queries are financial-related
- Verify the date in the query is not beyond `MODEL_TRAINING_CUTOFF`
- Review logs for specific rejection reasons

## Development

### Project Structure

```
finance-chat-agent/
├── src/
│   ├── agent.py          # Main agent implementation
│   ├── config.py         # Configuration and settings
│   ├── database.py       # Experiment tracker database
│   ├── executor.py       # A2A protocol executor
│   ├── server.py         # HTTP server
│   └── tools.py          # MCP tools integration
├── send_query.sh         # Script to send queries
├── review_stats.sh       # Script to view statistics
├── experiment_tracker.db # SQLite database (auto-created)
└── README.md
```

### Logs

Logs are stored in the `logs/` directory:
- `finance-purple-agent.log`: Main application log
- `agent-failures.log`: Failed agent requests
- `agent-successes.log`: Successful agent requests

