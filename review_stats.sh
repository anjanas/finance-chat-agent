#!/bin/bash

# Script to review statistics from experiment_tracker.db
# Usage: ./review_stats.sh

DB_FILE="experiment_tracker.db"

if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file $DB_FILE not found!"
    exit 1
fi

echo "=========================================="
echo "Experiment Tracker Statistics"
echo "=========================================="
echo ""

# Total queries
echo "📊 TOTAL QUERIES"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT COUNT(*) as total_queries 
    FROM queries;
"
echo ""

# Queries by status
echo "📈 QUERIES BY STATUS"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COALESCE(status, 'pending') as status,
        COUNT(*) as count,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM queries), 2) as percentage
    FROM queries 
    GROUP BY status
    ORDER BY count DESC;
"
echo ""

# Model usage statistics
echo "🤖 MODEL USAGE"
echo "----------------------------------------"
echo "Main Models:"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        main_model,
        COUNT(*) as usage_count,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM queries WHERE main_model IS NOT NULL), 2) as percentage
    FROM queries 
    WHERE main_model IS NOT NULL
    GROUP BY main_model
    ORDER BY usage_count DESC;
"
echo ""

echo "Intent Classifier Models:"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        intent_classifier_model,
        COUNT(*) as usage_count
    FROM queries 
    WHERE intent_classifier_model IS NOT NULL
    GROUP BY intent_classifier_model
    ORDER BY usage_count DESC;
"
echo ""

echo "Judge Models:"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        judge_model,
        COUNT(*) as usage_count
    FROM queries 
    WHERE judge_model IS NOT NULL
    GROUP BY judge_model
    ORDER BY usage_count DESC;
"
echo ""

# Guardrail statistics
echo "🛡️ GUARDRAIL STATISTICS"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        check_type,
        SUM(passed) as passed_count,
        COUNT(*) as total_checks,
        ROUND(SUM(passed) * 100.0 / COUNT(*), 2) as pass_rate_percent
    FROM guardrail_checks
    GROUP BY check_type
    ORDER BY check_type;
"
echo ""

# Response time statistics
echo "⏱️ RESPONSE TIME STATISTICS"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COUNT(*) as queries_with_timing,
        ROUND(AVG(response_time_ms), 2) as avg_response_time_ms,
        ROUND(MIN(response_time_ms), 2) as min_response_time_ms,
        ROUND(MAX(response_time_ms), 2) as max_response_time_ms,
        ROUND(AVG(response_time_ms) / 1000, 2) as avg_response_time_seconds
    FROM queries
    WHERE response_time_ms IS NOT NULL;
"
echo ""

# Token usage statistics
echo "💰 TOKEN USAGE"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        model_name,
        SUM(prompt_tokens) as total_prompt_tokens,
        SUM(completion_tokens) as total_completion_tokens,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as usage_count,
        ROUND(AVG(total_tokens), 0) as avg_tokens_per_query
    FROM token_usage
    GROUP BY model_name
    ORDER BY total_tokens DESC;
"
echo ""

sqlite3 -header -column "$DB_FILE" "
    SELECT 
        'TOTAL' as summary,
        SUM(prompt_tokens) as total_prompt_tokens,
        SUM(completion_tokens) as total_completion_tokens,
        SUM(total_tokens) as total_tokens
    FROM token_usage;
"
echo ""

# Judge approval statistics
echo "⚖️ JUDGE STATISTICS"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COUNT(*) as total_judged,
        SUM(judge_approved) as approved_count,
        COUNT(*) - SUM(judge_approved) as rejected_count,
        ROUND(SUM(judge_approved) * 100.0 / COUNT(*), 2) as approval_rate_percent
    FROM queries
    WHERE judge_approved IS NOT NULL;
"
echo ""

# Tool usage statistics
echo "🔧 TOOL USAGE"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        tool_name,
        COUNT(*) as usage_count,
        COUNT(DISTINCT query_id) as unique_queries
    FROM tool_calls
    GROUP BY tool_name
    ORDER BY usage_count DESC;
"
echo ""

# Iteration statistics
echo "🔄 ITERATION STATISTICS"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COUNT(*) as queries_with_iterations,
        ROUND(AVG(iterations), 2) as avg_iterations,
        MIN(iterations) as min_iterations,
        MAX(iterations) as max_iterations
    FROM queries
    WHERE iterations IS NOT NULL;
"
echo ""

# Prompt mode distribution
echo "📝 PROMPT MODE DISTRIBUTION"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COALESCE(prompt_mode, 'unknown') as prompt_mode,
        COUNT(*) as count,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM queries), 2) as percentage
    FROM queries
    GROUP BY prompt_mode
    ORDER BY count DESC;
"
echo ""

# Recent queries (last 5)
echo "📋 RECENT QUERIES (Last 5)"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        id,
        timestamp,
        SUBSTR(user_query, 1, 50) as query_preview,
        prompt_mode,
        status,
        ROUND(response_time_ms / 1000, 2) as response_time_seconds
    FROM queries
    ORDER BY timestamp DESC
    LIMIT 5;
"
echo ""

# Intent classification results
echo "🎯 INTENT CLASSIFICATION"
echo "----------------------------------------"
sqlite3 -header -column "$DB_FILE" "
    SELECT 
        COALESCE(intent_classified, 'not_classified') as intent,
        COUNT(*) as count,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM queries), 2) as percentage
    FROM queries
    GROUP BY intent_classified
    ORDER BY count DESC;
"
echo ""

echo "=========================================="
echo "Statistics review complete!"
echo "=========================================="
