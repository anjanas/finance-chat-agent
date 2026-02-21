import json
import re
import time
from datetime import datetime

from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentCardSignature,
    AgentSkill,
    Part,
    TaskState,
    TextPart,
)

from tools import Tools
from config import logger, log_agent_failure, settings
from openai import OpenAI
from database import get_tracker

# States
TERMINAL_STATES = {
    TaskState.completed,
    TaskState.canceled,
    TaskState.failed,
    TaskState.rejected
}


class PurpleAgent:
    """Basic agent responding finance related questions"""

    def __init__(self, model: str = "moonshotai/Kimi-K2-Instruct", temperature: int = 0, context_id: str = "default", prompt_mode: str = None):
        self.model = model
        self.temperature = temperature
        self.context_id = context_id
        self.prompt_mode = prompt_mode if prompt_mode is not None else settings.PROMPT_MODE  # "detailed", "json", or "auto"
        self.use_intent_classifier = self.prompt_mode == "auto"  # Use classifier if mode is "auto"
        logger.info(f"PurpleAgent initialized with prompt_mode: {self.prompt_mode}, use_intent_classifier: {self.use_intent_classifier}")
        self.conversation_history: list[dict] = []
        self._tools = None
        if settings.MCP_ENABLED:
            self._tools = Tools(settings.MCP_SERVER, context_id=context_id)
        self.client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=settings.NEBIUS_API_KEY
        )
        # Intent classifier client (uses different model for guardrails and intent classification)
        self.intent_classifier_client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=settings.NEBIUS_API_KEY
        )
        logger.info(f"Intent classifier model: {settings.INTENT_CLASSIFIER_MODEL}")
        
        # Judge client for answer verification (uses different model)
        self.judge_enabled = settings.JUDGE_MODEL_ENABLED
        self.judge_client = None
        if self.judge_enabled:
            self.judge_client = OpenAI(
                base_url="https://api.tokenfactory.nebius.com/v1/",
                api_key=settings.NEBIUS_API_KEY
            )
            logger.info(f"Judge model enabled: {settings.JUDGE_MODEL_NAME}")


    async def process_message(
        self,
        message: str,
        reset_conversation: bool = False,
        updater: 'TaskUpdater | None' = None
    ) -> tuple[str, dict]:
        """
        Process a message by looping internally with LLM and MCP tools.

        Args:
            message: User message to process
            reset_conversation: Start from scratch
            updater: Optional TaskUpdater for sending A2A progress updates

        Returns:
            tuple: (Status, Response)
        """

        if reset_conversation:
            self.conversation_history = []

        # Initialize database tracker
        tracker = get_tracker()
        start_time = time.time()
        query_id = None

        # Input guardrail: Check if the query is financial-related
        is_financial = await self._is_financial_question(message)
        if not is_financial:
            rejection_message = "I'm a financial assistant specialized in answering questions about finance, companies, stocks, earnings, revenue, and related financial topics. I'm unable to help with non-financial questions. Please ask me about financial matters instead."
            logger.info(f"Request rejected - not a financial question: {message[:100]}")
            
            # Log to database
            query_id = tracker.log_query(
                user_query=message,
                context_id=self.context_id,
                prompt_mode=self.prompt_mode,
                main_model=self.model,
                intent_classifier_model=settings.INTENT_CLASSIFIER_MODEL,
                judge_model=settings.JUDGE_MODEL_NAME if settings.JUDGE_MODEL_ENABLED else None,
                is_financial=False,
                status="rejected",
                response=rejection_message,
                response_time_ms=(time.time() - start_time) * 1000
            )
            tracker.log_guardrail_check(query_id, "financial_question", False)
            
            return "Rejected", {"status": "rejected", "response": rejection_message}

        # Input guardrail: Check if query asks about dates beyond training cutoff
        date_check = await self._check_training_date_cutoff(message)
        if not date_check["valid"]:
            rejection_message = f"I'm unable to answer questions about dates beyond my training cutoff date ({settings.MODEL_TRAINING_CUTOFF}). {date_check.get('message', 'Please ask about dates within my knowledge cutoff.')}"
            logger.info(f"Request rejected - date beyond training cutoff: {message[:100]}")
            
            # Log to database
            query_id = tracker.log_query(
                user_query=message,
                context_id=self.context_id,
                prompt_mode=self.prompt_mode,
                main_model=self.model,
                intent_classifier_model=settings.INTENT_CLASSIFIER_MODEL,
                judge_model=settings.JUDGE_MODEL_NAME if settings.JUDGE_MODEL_ENABLED else None,
                is_financial=True,
                date_check_passed=False,
                status="rejected",
                response=rejection_message,
                response_time_ms=(time.time() - start_time) * 1000
            )
            tracker.log_guardrail_check(query_id, "financial_question", True)
            tracker.log_guardrail_check(query_id, "date_cutoff", False, date_check.get('message'))
            
            return "Rejected", {"status": "rejected", "response": rejection_message}

        # Classify intent to determine prompt mode if using intent classifier
        current_prompt_mode = self.prompt_mode
        intent_classified = None
        if self.use_intent_classifier:
            current_prompt_mode = await self._classify_intent(message)
            intent_classified = current_prompt_mode
            logger.info(f"Intent classified: prompt_mode={current_prompt_mode} for query: {message[:100]}")

        # Log query to database (after guardrails pass)
        query_id = tracker.log_query(
            user_query=message,
            context_id=self.context_id,
            prompt_mode=current_prompt_mode,
            main_model=self.model,
            intent_classifier_model=settings.INTENT_CLASSIFIER_MODEL,
            judge_model=settings.JUDGE_MODEL_NAME if settings.JUDGE_MODEL_ENABLED else None,
            is_financial=True,
            date_check_passed=True,
            intent_classified=intent_classified
        )
        tracker.log_guardrail_check(query_id, "financial_question", True)
        tracker.log_guardrail_check(query_id, "date_cutoff", True)

        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        # Get available tools (each time)
        tool_list = await self._tools.get_tools() if self._tools else None

        # Track judge retry attempts
        judge_retry_count = 0
        MAX_JUDGE_RETRIES = 2  # Maximum number of retries after judge rejection

        # Loop until final answer is obtained (just for errors)
        for iteration in range(settings.MAX_ITERATIONS):
            try:
                # Prepare messages for LLM call
                messages = self._get_system_messages(prompt_mode=current_prompt_mode) + self.conversation_history

                # Log LLM request
                logger.info(f"LLM Request [iteration {iteration + 1}]: model={self.model}, temperature={self.temperature}, context_id={self.context_id}")
                logger.info(f"LLM Request [iteration {iteration + 1}]: {len(messages)} messages in conversation")
                
                # Log full request text/messages
                logger.info(f"LLM Request Messages [iteration {iteration + 1}]:")
                for idx, msg in enumerate(messages):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if role == "system":
                        logger.info(f"  Message {idx + 1} [{role}]: {content[:500]}{'...' if len(content) > 500 else ''}")
                    elif role == "user":
                        logger.info(f"  Message {idx + 1} [{role}]: {content}")
                    elif role == "assistant":
                        logger.info(f"  Message {idx + 1} [{role}]: {content[:500]}{'...' if len(content) > 500 else ''}")
                    elif role == "tool":
                        tool_name = msg.get("name", "unknown")
                        tool_content = msg.get("content", "")
                        logger.info(f"  Message {idx + 1} [{role}:{tool_name}]: {tool_content[:500]}{'...' if len(tool_content) > 500 else ''}")
                    else:
                        logger.info(f"  Message {idx + 1} [{role}]: {str(msg)[:500]}")
                
                logger.debug(f"LLM Request full messages JSON: {json.dumps(messages, indent=2, ensure_ascii=False)}")
                
                # Log tools being passed to LLM
                if self._tools:
                    logger.info(f"LLM Request Tools [iteration {iteration + 1}]: {len(tool_list)} tool(s) available")
                    logger.info(f"LLM Request Tool Names: {[t['function']['name'] for t in tool_list]}")
                else:
                    logger.info(f"LLM Request Tools [iteration {iteration + 1}]: no tools available")
                
                logger.debug(f"LLM Request messages: {len(messages)} messages, last user message: {self.conversation_history[-1]['content'][:200] if self.conversation_history else 'N/A'}")

                # Get LLM response with function calling
                start_time = time.time()
                if self._tools:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        temperature=self.temperature,
                        messages=messages,
                        tools=tool_list if tool_list else None,
                        tool_choice="auto",  # Enable automatic tool calling
                        #parallel_tool_calls=False,  # Process one tool at a time
                    )
                else:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        temperature=self.temperature,
                        messages=messages
                    )
                elapsed_time = time.time() - start_time

                assistant_message = response.choices[0].message
                
                # Log LLM response
                response_content = assistant_message.content or ""
                response_length = len(response_content) if response_content else 0
                logger.info(f"LLM Response [iteration {iteration + 1}]: elapsed_time={elapsed_time:.2f}s, response_length={response_length} chars")
                
                # Log full response text
                if response_content:
                    logger.info(f"LLM Response Text [iteration {iteration + 1}]:")
                    logger.info(f"  {response_content}")
                else:
                    logger.info(f"LLM Response Text [iteration {iteration + 1}]: (no content)")
                
                # Log tool calls if present
                tool_calls = assistant_message.tool_calls
                if tool_calls:
                    logger.info(f"LLM Response Tool Calls [iteration {iteration + 1}]: {len(tool_calls)} tool call(s)")
                    for idx, tool_call in enumerate(tool_calls):
                        tool_name = tool_call.function.name
                        tool_args = tool_call.function.arguments
                        logger.info(f"  Tool Call {idx + 1}: {tool_name}")
                        logger.info(f"    Arguments: {tool_args}")
                else:
                    logger.info(f"LLM Response Tool Calls [iteration {iteration + 1}]: none")

                # Log token usage if available
                if hasattr(response, 'usage') and response.usage:
                    usage = response.usage
                    prompt_tokens = getattr(usage, 'prompt_tokens', None)
                    completion_tokens = getattr(usage, 'completion_tokens', None)
                    total_tokens = getattr(usage, 'total_tokens', None)
                    logger.info(f"LLM Token Usage [iteration {iteration + 1}]: prompt_tokens={prompt_tokens or 'N/A'}, completion_tokens={completion_tokens or 'N/A'}, total_tokens={total_tokens or 'N/A'}")
                    
                    # Log token usage to database
                    if query_id and prompt_tokens:
                        tracker.log_token_usage(
                            query_id=query_id,
                            model_name=self.model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens
                        )
                
                # Log full response object at DEBUG level
                logger.debug(f"LLM Response full object: {json.dumps({'content': response_content, 'tool_calls': [{'name': tc.function.name, 'arguments': tc.function.arguments} for tc in (tool_calls or [])]}, indent=2, ensure_ascii=False)}")

                # Add response to history
                message_dict = {
                    "role": "assistant",
                    "content": assistant_message.content
                }

                self.conversation_history.append(message_dict)

                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    if "context_id" in tool_args:
                        del tool_args["context_id"] # Causes issues
                    logger.info(f"Calling tool {tool_name} with args {tool_args}")

                    try:
                        result = await self._tools.call_tool(tool_name, tool_args)
                        logger.info(f"Tool {tool_name} result {result}")
                        
                        # Log tool call to database
                        if query_id:
                            tracker.log_tool_call(
                                query_id=query_id,
                                iteration=iteration + 1,
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_result=result
                            )

                        self.conversation_history.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": json.dumps(result)
                        })
                    except Exception as e:
                        logger.error(f"Tool {tool_name} failed: {e}")
                        result = {"success": False, "error": str(e)}
                        
                        # Log failed tool call to database
                        if query_id:
                            tracker.log_tool_call(
                                query_id=query_id,
                                iteration=iteration + 1,
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_result=result
                            )

                logger.debug(f"Iteration {iteration + 1}: content={response_content[:1000] if response_content else '(no content)'}")

                # If there are no tool calls, the LLM gave a final answer - verify with judge and format
                if not tool_calls:
                    # Log the LLM answer before sending to judge
                    logger.info(f"LLM Answer (before judge): {assistant_message.content}")
                    
                    response_time_ms = (time.time() - start_time) * 1000
                    judge_approved = None
                    judge_reason = None
                    
                    # Verify answer with judge model if enabled
                    if self.judge_enabled and self.judge_client:
                        judge_result = await self._judge_answer(message, assistant_message.content, current_prompt_mode)
                        judge_approved = judge_result["valid"]
                        judge_reason = judge_result.get("reason")
                        
                        if not judge_result["valid"]:
                            logger.warning(f"Judge rejected answer (retry {judge_retry_count}/{MAX_JUDGE_RETRIES}): {judge_reason or 'Unknown reason'}")
                            
                            # If we haven't exceeded max retries, send feedback back to model for retry
                            if judge_retry_count < MAX_JUDGE_RETRIES:
                                judge_retry_count += 1
                                
                                # Add judge feedback to conversation for retry
                                feedback_message = f"The previous answer was rejected. Feedback: {judge_reason or 'The answer did not meet quality standards. Please provide a corrected answer.'}"
                                
                                logger.info(f"Sending judge feedback back to model for retry {judge_retry_count}")
                                
                                # Add the feedback as a user message to continue the conversation
                                self.conversation_history.append({
                                    "role": "user",
                                    "content": feedback_message
                                })
                                
                                # Continue the loop to let the model retry
                                continue
                            else:
                                # Max retries exceeded, return error
                                logger.error(f"Judge rejected answer after {MAX_JUDGE_RETRIES} retries")
                                error_message = f"I was unable to provide a reliable answer after {MAX_JUDGE_RETRIES} attempts. {judge_reason or 'The answer did not meet quality standards.'}"
                                
                                # Update query in database
                                if query_id:
                                    tracker.update_query(
                                        query_id=query_id,
                                        status="judge_rejected",
                                        response=error_message,
                                        response_time_ms=response_time_ms,
                                        iterations=iteration + 1,
                                        judge_approved=False,
                                        judge_reason=judge_reason
                                    )
                                
                                return "Judge rejected", {"status": "failed", "response": error_message}
                        else:
                            logger.info(f"Judge approved answer")
                    
                    formatted_response = self._format_response(assistant_message.content, current_prompt_mode)
                    
                    # Update query in database with final response
                    if query_id:
                        tracker.update_query(
                            query_id=query_id,
                            status="complete",
                            response=formatted_response,
                            response_time_ms=response_time_ms,
                            iterations=iteration + 1,
                            judge_approved=judge_approved,
                            judge_reason=judge_reason
                        )
                    
                    return "Final answer", {"status" : "complete", "response" : formatted_response}
                
                # If there are tool calls, continue to next iteration so LLM can use the tool results
                # The loop will continue and call LLM again with the tool results in conversation_history

            except Exception as e:
                logger.error(f"Error in iteration {iteration + 1}: {e}")
                log_agent_failure(
                    "iteration error",
                    user_message=message,
                    context_id=self.context_id,
                    detail=str(e),
                )

        # Max iterations reached without submit_answer
        logger.warning(f"Max iterations ({settings.MAX_ITERATIONS}) reached without submitting answer")
        log_agent_failure(
            "max iterations reached without final answer",
            user_message=message,
            context_id=self.context_id,
            detail=f"MAX_ITERATIONS={settings.MAX_ITERATIONS}",
        )

    async def _check_training_date_cutoff(self, message: str) -> dict:
        """Check if the query asks about dates beyond the model's training cutoff."""
        try:
            training_cutoff = datetime.strptime(settings.MODEL_TRAINING_CUTOFF, "%Y-%m-%d")
            
            # Use LLM to extract dates from the query
            date_extraction_prompt = f"""Extract any dates, years, quarters, or time periods mentioned in the following query. 
If the query asks about future dates, specific dates, quarters, or years, identify them.

Examples:
- "What was Apple's revenue in Q4 2024?" -> 2024-10-01 (Q4 2024 starts)
- "What is Microsoft's EPS in 2025?" -> 2025-01-01
- "Who is the CEO of Tesla?" -> no specific date
- "What was Amazon's revenue last year?" -> check if it's beyond cutoff
- "What will be Apple's revenue in 2026?" -> 2026-01-01

User query: {message}

Respond with:
- If there are specific dates/years/quarters mentioned that are clearly in the future or beyond {settings.MODEL_TRAINING_CUTOFF}, respond with: "DATE:YYYY-MM-DD" (use the earliest date mentioned)
- If the query asks about "future", "upcoming", "next", "will be", respond with: "FUTURE"
- If no specific future dates are mentioned, respond with: "VALID"
- If the query asks about relative dates like "last year", "recent", "current", respond with: "VALID"

Only respond with one of: DATE:YYYY-MM-DD, FUTURE, or VALID"""

            response = self.intent_classifier_client.chat.completions.create(
                model=settings.INTENT_CLASSIFIER_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": "You are a date extraction system. Extract dates from queries and check if they're beyond the training cutoff."},
                    {"role": "user", "content": date_extraction_prompt}
                ]
            )
            
            result = response.choices[0].message.content.strip().upper()
            
            if result == "FUTURE":
                return {
                    "valid": False,
                    "message": "I cannot answer questions about future events or dates beyond my training cutoff."
                }
            elif result.startswith("DATE:"):
                try:
                    extracted_date_str = result.replace("DATE:", "").strip()
                    extracted_date = datetime.strptime(extracted_date_str, "%Y-%m-%d")
                    
                    if extracted_date > training_cutoff:
                        return {
                            "valid": False,
                            "message": f"The query asks about dates ({extracted_date_str}) beyond my training cutoff ({settings.MODEL_TRAINING_CUTOFF})."
                        }
                    else:
                        return {"valid": True}
                except ValueError:
                    # If date parsing fails, be conservative and allow it
                    logger.warning(f"Could not parse extracted date: {result}, allowing query")
                    return {"valid": True}
            else:
                # VALID or any other response - allow the query
                return {"valid": True}
                
        except Exception as e:
            logger.error(f"Error in training date cutoff check: {e}, defaulting to allow")
            # Default to allowing if there's an error to avoid blocking legitimate requests
            return {"valid": True}

    async def _judge_answer(self, user_query: str, answer: str, prompt_mode: str) -> dict:
        """Use a judge model to verify the quality and correctness of the answer."""
        if not self.judge_client:
            return {"valid": True}  # If judge is not enabled, always pass
        
        judge_prompt = f"""You are a quality judge for a financial assistant. Evaluate the answer provided to the user's question.

User's question: {user_query}

Answer provided: {answer}

Evaluate the answer based on:
1. **Correctness**: Is the answer factually correct and accurate?
2. **Completeness**: Does it fully address the user's question?
3. **Relevance**: Is the answer relevant to the financial question asked?
4. **Format**: If the question expects JSON, is the answer valid JSON? If it expects detailed explanation, is it comprehensive?
5. **Hallucination**: Does the answer contain any made-up information, unsupported claims, or data that seems fabricated?

For JSON responses, check:
- Is it valid JSON format?
- Does it contain the required fields (answer and type)?
- Is the answer field a reasonable value?

For detailed responses, check:
- Is it comprehensive and informative?
- Does it explain the financial concepts clearly?
- Is it free from obvious errors or contradictions?

Respond with ONLY one word:
- "APPROVE" if the answer is correct, complete, relevant, and of good quality
- "REJECT" if the answer has issues, is incorrect, incomplete, irrelevant, or contains hallucinations

Only respond with "APPROVE" or "REJECT"."""

        try:
            response = self.judge_client.chat.completions.create(
                model=settings.JUDGE_MODEL_NAME,
                temperature=0,
                messages=[
                    {"role": "system", "content": "You are a quality judge. Evaluate answers and respond with only 'APPROVE' or 'REJECT'."},
                    {"role": "user", "content": judge_prompt}
                ]
            )
            
            result = response.choices[0].message.content.strip().upper()
            
            if result == "APPROVE":
                return {"valid": True}
            elif result == "REJECT":
                # Try to get a reason from the judge
                reason_prompt = f"""The answer was rejected. Provide a brief reason (1-2 sentences) why the answer was rejected.

User's question: {user_query}
Answer: {answer}

Reason for rejection:"""
                
                try:
                    reason_response = self.judge_client.chat.completions.create(
                        model=settings.JUDGE_MODEL_NAME,
                        temperature=0,
                        messages=[
                            {"role": "system", "content": "Provide a brief reason for rejection."},
                            {"role": "user", "content": reason_prompt}
                        ]
                    )
                    reason = reason_response.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"Error getting rejection reason: {e}")
                    reason = "The answer did not meet quality standards."
                
                return {
                    "valid": False,
                    "reason": reason
                }
            else:
                # If judge returns unexpected response, log warning but approve
                logger.warning(f"Judge returned unexpected response: {result}, defaulting to approve")
                return {"valid": True}
                
        except Exception as e:
            logger.error(f"Error in judge verification: {e}, defaulting to approve")
            # Default to approving if judge fails to avoid blocking legitimate answers
            return {"valid": True}

    async def _is_financial_question(self, message: str) -> bool:
        """Check if the user's query is related to finance."""
        guardrail_prompt = f"""You are a guardrail system for a financial assistant. Determine if the user's query is related to finance, business, companies, stocks, earnings, revenue, financial metrics, or any financial topic.

Examples of FINANCIAL questions:
- "What is Apple's revenue?"
- "Who is the CFO of Microsoft?"
- "Explain EPS"
- "Compare Tesla and Ford stock prices"
- "What was Amazon's profit last quarter?"

Examples of NON-FINANCIAL questions:
- "What is the weather today?"
- "Tell me a joke"
- "How do I cook pasta?"
- "What is the capital of France?"
- "Explain quantum physics"

User query: {message}

Respond with only one word: "yes" if it's a financial question, "no" if it's not."""

        try:
            response = self.intent_classifier_client.chat.completions.create(
                model=settings.INTENT_CLASSIFIER_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": "You are a guardrail system. Respond with only one word: 'yes' if the query is financial, 'no' if it's not."},
                    {"role": "user", "content": guardrail_prompt}
                ]
            )
            result = response.choices[0].message.content.strip().lower()
            is_financial = result in ["yes", "y"]
            logger.info(f"Financial question check: {is_financial} for query: {message[:100]}")
            return is_financial
        except Exception as e:
            logger.error(f"Error in financial question check: {e}, defaulting to allow")
            # Default to allowing if there's an error to avoid blocking legitimate requests
            return True

    async def _classify_intent(self, message: str) -> str:
        """Classify user intent to determine if response should be JSON or detailed."""
        classification_prompt = f"""You are an intent classifier for a financial assistant. Based on the user's query, determine whether the response should be:
- "json": If the query asks for a specific numerical value or fact that can be answered concisely with a number (e.g., "What is Apple's EPS?", "What was Microsoft's revenue in Q4?")
- "detailed": If the query asks for explanations, analysis, comparisons, or requires context and reasoning (e.g., "Explain how EPS is calculated", "Compare Apple and Microsoft's financial performance", "What factors affect revenue?")

User query: {message}

Respond with only one word: either "json" or "detailed"."""

        try:
            response = self.intent_classifier_client.chat.completions.create(
                model=settings.INTENT_CLASSIFIER_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": "You are an intent classifier. Respond with only one word: 'json' or 'detailed'."},
                    {"role": "user", "content": classification_prompt}
                ]
            )
            result = response.choices[0].message.content.strip().lower()
            if result in ["json", "detailed"]:
                return result
            else:
                logger.warning(f"Intent classifier returned unexpected value: {result}, defaulting to 'json'")
                return "json"
        except Exception as e:
            logger.error(f"Error in intent classification: {e}, defaulting to 'json'")
            return "json"

    def _format_number(self, num: float) -> str:
        """Format a number with commas and M/B suffixes for readability."""
        if num is None:
            return ""
        
        # Handle negative numbers
        is_negative = num < 0
        abs_num = abs(num)
        
        # Format with M/B suffixes
        if abs_num >= 1_000_000_000:
            formatted = f"{abs_num / 1_000_000_000:.2f}".rstrip('0').rstrip('.')
            suffix = "B"
        elif abs_num >= 1_000_000:
            formatted = f"{abs_num / 1_000_000:.2f}".rstrip('0').rstrip('.')
            suffix = "M"
        else:
            # For numbers less than 1M, just add commas
            formatted = f"{abs_num:,.2f}".rstrip('0').rstrip('.')
            suffix = ""
        
        # Add commas to the formatted number before the decimal point
        if '.' in formatted:
            int_part, dec_part = formatted.split('.')
            int_part = f"{int(int_part):,}"
            formatted = f"{int_part}.{dec_part}" if dec_part else int_part
        else:
            formatted = f"{int(formatted):,}"
        
        result = f"{formatted}{suffix}"
        return f"-{result}" if is_negative else result

    def _format_response(self, response: str, prompt_mode: str) -> str:
        """Format the response by adding commas and M/B suffixes to numbers."""
        if not response:
            return response
        
        # Try to parse as JSON first (for json mode)
        if prompt_mode != "detailed":
            try:
                # Try to extract JSON from the response
                response_clean = response.strip()
                # Remove markdown code blocks if present
                if response_clean.startswith("```"):
                    lines = response_clean.split("\n")
                    response_clean = "\n".join(lines[1:-1]) if len(lines) > 2 else response_clean
                
                data = json.loads(response_clean)
                if isinstance(data, dict) and "answer" in data:
                    # Format the answer field if it's a number
                    if isinstance(data["answer"], (int, float)):
                        # Store both original and formatted for flexibility
                        original_answer = data["answer"]
                        data["answer"] = self._format_number(data["answer"])
                        # Optionally keep original as a separate field
                        # data["answer_original"] = original_answer
                    elif isinstance(data["answer"], str):
                        # Try to parse string as number and format it
                        try:
                            num = float(data["answer"].replace(',', ''))
                            data["answer"] = self._format_number(num)
                        except ValueError:
                            # If not a number, leave as is
                            pass
                    # Reconstruct JSON
                    return json.dumps(data, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                # If not valid JSON, fall through to text formatting
                pass
        
        # For detailed responses or if JSON parsing failed, format numbers in text
        def format_match(match):
            """Format a matched number."""
            num_str = match.group(0)
            try:
                # Remove existing commas and parse
                num = float(num_str.replace(',', ''))
                # Only format large numbers (>= 1000) to avoid formatting small decimals or percentages
                if abs(num) >= 1000:
                    return self._format_number(num)
                else:
                    # For small numbers, just add commas if >= 1000, otherwise leave as is
                    if abs(num) >= 1000:
                        return f"{num:,.2f}".rstrip('0').rstrip('.')
                    return num_str
            except ValueError:
                return num_str
        
        # Pattern to match numbers (integers and decimals, but not already formatted with M/B)
        # Avoid matching numbers that already have M or B suffix
        pattern = r'\b(?<![\d,.])\d{1,3}(?:,\d{3})*(?:\.\d+)?(?!\s*[MB])\b'
        formatted_response = re.sub(pattern, format_match, response)
        
        return formatted_response

    def _get_system_messages(self, prompt_mode: str = None) -> list[dict]:
        """Get system messages for the agent."""
        mode = prompt_mode if prompt_mode is not None else self.prompt_mode
        
        if mode == "detailed":
            default_message = """
                You are a financial assistant providing faithful information regarding the questions posed by the user. 
                Provide detailed, comprehensive answers that explain the financial concepts, data, and context relevant to the user's question.
            """
        else:  # json mode (default)
            default_message = """
                You are a financial assistant. You must only reply with a JSON object containing two fields: "answer" (the numerical value) and "type" (a string indicating the type of answer, such as "eps", "revenue", "price", etc.). Format your response as valid JSON, for example: {"answer": 123.45, "type": "eps"} or {"answer": 1000000, "type": "revenue"}. Do not include any text, explanations, or additional content outside the JSON structure.
            """
        
        if self._tools:
            default_message += "Use tools to complete your knowledge."

        return [{
            "role": "system",
            "content": default_message
        }]

def create_agent_card(url: str) -> AgentCard:
    """Create the agent card for the finance agent."""
    skill = AgentSkill(
        id="expertise",
        name="Financial expertise",
        description="Responds to financial questions",
        tags=["finance", "purple"],
        examples=[
            "What was Apple's revenue in Q4 2024?",
            "Who is the CFO of Microsoft?",
        ],
    )
    
    # Standard A2A protocol JSON-RPC method signatures
    # The A2A SDK's DefaultRequestHandler automatically exposes these standard methods:
    # - message/send: Send a message and wait for completion
    # - message/stream: Send a message and receive streaming updates
    # - tasks/get: Get task status by ID
    # - tasks/cancel: Cancel a task
    signatures = [
        AgentCardSignature(
            protected="false",
            signature="message/send"
        ),
        AgentCardSignature(
            protected="false",
            signature="message/stream"
        ),
        AgentCardSignature(
            protected="false",
            signature="tasks/get"
        ),
        AgentCardSignature(
            protected="false",
            signature="tasks/cancel"
        )
    ]
    
    return AgentCard(
        name="Finance Purple Agent",
        description="Purple agent for the finance agentic benchmark",
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
        signatures=signatures,
    )
