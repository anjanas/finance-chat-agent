#!/bin/bash

# Script to send queries to the Finance Purple Agent via message/send endpoint
# Usage: ./send_query.sh "Your question here" [--num-runs N]
#        ./send_query.sh "Your question here" [-n N]
#        ./send_query.sh                    # Will prompt for input

set -e

# Default values
SERVER_URL="${SERVER_URL:-http://127.0.0.1:9019}"
NUM_RUNS=1
QUERY=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--num-runs)
            NUM_RUNS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS] \"Your question here\""
            echo ""
            echo "Options:"
            echo "  -n, --num-runs N    Number of times to send the request (default: 1)"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 \"What is Apple's revenue?\""
            echo "  $0 \"What is Apple's revenue?\" --num-runs 5"
            echo "  $0 \"What is Apple's revenue?\" -n 10"
            exit 0
            ;;
        *)
            if [ -z "$QUERY" ]; then
                QUERY="$1"
            else
                QUERY="$QUERY $1"
            fi
            shift
            ;;
    esac
done

# Get query from prompt if not provided
if [ -z "$QUERY" ]; then
    echo "Enter your query:"
    read -r QUERY
fi

if [ -z "$QUERY" ]; then
    echo "Error: Query cannot be empty"
    exit 1
fi

# Validate num_runs
if ! [[ "$NUM_RUNS" =~ ^[0-9]+$ ]] || [ "$NUM_RUNS" -lt 1 ]; then
    echo "Error: num_runs must be a positive integer"
    exit 1
fi

echo "Sending query to $SERVER_URL..."
echo "Query: $QUERY"
echo "Number of runs: $NUM_RUNS"
echo ""

# Function to send a single request
send_request() {
    local run_number=$1
    local message_id="query-$(date +%s)-$run_number"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Run $run_number of $NUM_RUNS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Send the request
    RESPONSE=$(curl -s -X POST "$SERVER_URL" \
      -H "Content-Type: application/json" \
      -d "{
        \"jsonrpc\": \"2.0\",
        \"method\": \"message/send\",
        \"params\": {
          \"message\": {
            \"messageId\": \"$message_id\",
            \"role\": \"user\",
            \"parts\": [
              {
                \"kind\": \"text\",
                \"text\": \"$QUERY\"
              }
            ]
          }
        },
        \"id\": $run_number
      }")

    # Check if response contains an error
    if echo "$RESPONSE" | grep -q '"error"'; then
        echo "❌ Error occurred:"
        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        echo ""
        return 1
    fi

    # Extract and display the response
    echo "=== Agent Response ==="
    echo "$RESPONSE" | python3 -c "
import sys
import json

try:
    data = json.load(sys.stdin)
    if 'result' in data and 'artifacts' in data['result']:
        for artifact in data['result']['artifacts']:
            for part in artifact.get('parts', []):
                if part.get('kind') == 'data' and 'response' in part.get('data', {}):
                    print(part['data']['response'])
                    print()
                elif part.get('kind') == 'text' and part.get('text') != 'complete':
                    print(part['text'])
    else:
        print(json.dumps(data, indent=2))
except Exception as e:
    print('Error parsing response:', e)
    sys.stdin.seek(0)
    print(sys.stdin.read())
" 2>/dev/null || echo "$RESPONSE" | python3 -m json.tool

    # Display task status if available
    echo ""
    echo "=== Task Status ==="
    echo "$RESPONSE" | python3 -c "
import sys
import json

try:
    data = json.load(sys.stdin)
    if 'result' in data:
        result = data['result']
        print(f\"Task ID: {result.get('id', 'N/A')}\")
        print(f\"Context ID: {result.get('contextId', 'N/A')}\")
        if 'status' in result:
            status = result['status']
            print(f\"Status: {status.get('state', 'N/A')}\")
            print(f\"Timestamp: {status.get('timestamp', 'N/A')}\")
except:
    pass
" 2>/dev/null
    
    echo ""
}

# Send requests in a loop
for ((i=1; i<=NUM_RUNS; i++)); do
    send_request $i
    
    # Add a small delay between runs (except for the last one)
    if [ $i -lt $NUM_RUNS ]; then
        sleep 0.5
    fi
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Completed $NUM_RUNS run(s)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"