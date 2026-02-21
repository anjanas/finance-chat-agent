import json
import os
import argparse

import uvicorn
from starlette.responses import Response
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from agent import create_agent_card
from executor import PurpleAgentExecutor
from config import logger, settings


def main():
    parser = argparse.ArgumentParser(description="Run the Finance Agent Baseline.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=9019, help="Port to bind")
    parser.add_argument("--card-url", type=str, help="External URL for agent card")
    args = parser.parse_args()

    agent_url = args.card_url or f"http://{args.host}:{args.port}/"

    agent_card = create_agent_card(agent_url)

    request_handler = DefaultRequestHandler(
        agent_executor=PurpleAgentExecutor(model=settings.MODEL_NAME),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # Build the Starlette app
    app = server.build()

    # Add custom route for agent card endpoint
    async def agent_card_endpoint(request):
        """Endpoint to return the agent card as pretty-printed JSON."""
        body = json.dumps(agent_card.model_dump(), indent=2, ensure_ascii=False)
        return Response(content=body, media_type="application/json")

    # Add the route to the app
    app.routes.append(Route("/card", endpoint=agent_card_endpoint, methods=["GET"]))

    logger.info(f"Starting Finance Purple Agent on {args.host}:{args.port}")
    logger.info(f"PROMPT_MODE: {settings.PROMPT_MODE}")
    logger.info(f"MODEL_NAME (for answering): {settings.MODEL_NAME}")
    logger.info(f"INTENT_CLASSIFIER_MODEL: {settings.INTENT_CLASSIFIER_MODEL}")
    logger.info(f"MODEL_TRAINING_CUTOFF: {settings.MODEL_TRAINING_CUTOFF}")
    logger.info(f"JUDGE_MODEL_ENABLED: {settings.JUDGE_MODEL_ENABLED}")
    if settings.JUDGE_MODEL_ENABLED:
        logger.info(f"JUDGE_MODEL_NAME: {settings.JUDGE_MODEL_NAME}")
    logger.info(f"Agent card available at: http://{args.host}:{args.port}/card")

    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
