#!/bin/bash

# Script to read questions from questions.csv and execute each query
# Usage: ./run_questions.sh [OPTIONS]
# Options:
#   --csv-file PATH    Path to CSV file (default: src/questions.csv)
#   --num-runs N       Number of times to run each question (default: 1)
#   --delay SECONDS    Delay between questions in seconds (default: 1)
#   --start N          Start from question number N (default: 1)
#   --end N            End at question number N (default: all)
#   --difficulty LEVEL Filter by difficulty (Easy, Medium, Hard)

set -e

# Default values
CSV_FILE="${CSV_FILE:-src/questions.csv}"
NUM_RUNS=1
DELAY=1
START_QUESTION=1
END_QUESTION=999999
DIFFICULTY_FILTER=""
SERVER_URL="${SERVER_URL:-http://127.0.0.1:9019}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --csv-file)
            CSV_FILE="$2"
            shift 2
            ;;
        --num-runs|-n)
            NUM_RUNS="$2"
            shift 2
            ;;
        --delay)
            DELAY="$2"
            shift 2
            ;;
        --start)
            START_QUESTION="$2"
            shift 2
            ;;
        --end)
            END_QUESTION="$2"
            shift 2
            ;;
        --difficulty)
            DIFFICULTY_FILTER="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --csv-file PATH    Path to CSV file (default: src/questions.csv)"
            echo "  -n, --num-runs N   Number of times to run each question (default: 1)"
            echo "  --delay SECONDS    Delay between questions in seconds (default: 1)"
            echo "  --start N          Start from question number N (default: 1)"
            echo "  --end N            End at question number N (default: all)"
            echo "  --difficulty LEVEL Filter by difficulty: Easy, Medium, or Hard"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run all questions"
            echo "  $0 --start 5 --end 10                 # Run questions 5-10"
            echo "  $0 --difficulty Easy                  # Run only Easy questions"
            echo "  $0 --num-runs 3 --delay 2             # Run each question 3 times with 2s delay"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if CSV file exists
if [ ! -f "$CSV_FILE" ]; then
    echo "Error: CSV file not found: $CSV_FILE"
    exit 1
fi

# Export variables for Python script
export CSV_FILE
export NUM_RUNS
export DELAY
export START_QUESTION
export END_QUESTION
export DIFFICULTY_FILTER
export SERVER_URL

# Read CSV and process questions using Python for proper CSV parsing
echo "Reading questions from: $CSV_FILE"
echo "Server URL: $SERVER_URL"
echo "Number of runs per question: $NUM_RUNS"
echo "Delay between questions: ${DELAY}s"
if [ -n "$DIFFICULTY_FILTER" ]; then
    echo "Difficulty filter: $DIFFICULTY_FILTER"
fi
echo "Question range: $START_QUESTION to $END_QUESTION"
echo ""

# Process questions using Python to parse CSV properly
python3 << 'PYTHON_SCRIPT'
import csv
import json
import urllib.request
import time
import sys
import os

csv_file = os.environ.get('CSV_FILE', 'src/questions.csv')
num_runs = int(os.environ.get('NUM_RUNS', '1'))
delay = float(os.environ.get('DELAY', '1'))
start_q = int(os.environ.get('START_QUESTION', '1'))
end_q = int(os.environ.get('END_QUESTION', '999999'))
difficulty_filter = os.environ.get('DIFFICULTY_FILTER', '')
server_url = os.environ.get('SERVER_URL', 'http://127.0.0.1:9019')

if not difficulty_filter:
    difficulty_filter = None

def send_query(qnum, question, difficulty, run_num):
    message_id = f"question-{qnum}-run-{run_num}-{int(time.time())}"
    
    print("")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Question #{qnum} [{difficulty}] - Run {run_num}/{num_runs}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Query: {question}")
    print("")
    
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "user",
                "parts": [{"kind": "text", "text": question}]
            }
        },
        "id": qnum
    }
    
    try:
        req = urllib.request.Request(
            server_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if 'error' in result:
                print("❌ Error occurred:")
                print(json.dumps(result['error'], indent=2))
                return False
            
            print("=== Agent Response ===")
            if 'result' in result and 'artifacts' in result['result']:
                for artifact in result['result']['artifacts']:
                    for part in artifact.get('parts', []):
                        if part.get('kind') == 'data' and 'response' in part.get('data', {}):
                            print(part['data']['response'])
                            print()
                        elif part.get('kind') == 'text' and part.get('text') != 'complete':
                            print(part['text'])
            print("")
            return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

# Count total questions first
total_questions = 0
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        qnum = int(row['question_number'])
        difficulty = row['difficulty']
        if qnum < start_q or qnum > end_q:
            continue
        if difficulty_filter and difficulty != difficulty_filter:
            continue
        total_questions += 1

print(f"Total questions to process: {total_questions}")
print("Starting execution...")
print("")

processed = 0
failed = 0

try:
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            qnum = int(row['question_number'])
            question = row['question']
            difficulty = row['difficulty']
            
            # Apply filters
            if qnum < start_q or qnum > end_q:
                continue
            if difficulty_filter and difficulty != difficulty_filter:
                continue
            
            # Run the question multiple times if specified
            for run in range(1, num_runs + 1):
                if send_query(qnum, question, difficulty, run):
                    processed += 1
                else:
                    failed += 1
                
                # Delay between runs
                if run < num_runs:
                    time.sleep(0.5)
            
            # Delay between questions
            time.sleep(delay)
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ Execution Complete")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Total questions processed: {processed}")
    if failed > 0:
        print(f"Failed queries: {failed}")
    print("")
    
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
