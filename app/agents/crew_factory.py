"""
Builds a small, deterministic, sequential crew for ONE symbol at a time.

Deliberate simplicity choices for Phase 1 (see the plan we agreed on):
- Process.sequential, not hierarchical. No agent decides "who goes next" --
  the code decides. This removes an entire class of non-determinism.
- One symbol per crew run. Comparison mode just runs this crew multiple
  times from the orchestration layer (app/pipeline.py) and aggregates the
  results. This keeps every task's output schema a single flat object
  instead of a variable-length list, which smaller/free-tier models are
  much more reliable at producing correctly.
- Each agent gets at most one tool. Fewer tools per agent -> far fewer
  "picked the wrong tool" or "invented a tool name" failures.
- Every task has `output_pydantic` set, so CrewAI validates the output
  against our schema and automatically retries the task (feeding the
  validation error back to the agent) if it doesn't conform. This is what
  replaces the old system's manual string parsing entirely.
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from app.agents.llm_config import get_reasoning_llm, get_tool_llm
from app.config import get_settings
from app.schemas import MarketData, NewsSentiment, StockRecommendation
from app.tools.yfinance_tools import MarketDataTool, NewsTool


def build_stock_crew(symbol: str, time_horizon: str = "short_term") -> Crew:
    settings = get_settings()
    tool_llm = get_tool_llm()
    reasoning_llm = get_reasoning_llm()
    verbose = settings.environment == "development"

    market_data_agent = Agent(
        role="Market Data Analyst",
        goal=(
            f"Fetch accurate current price and technical indicator data for {symbol} "
            "using the get_market_data tool, exactly once."
        ),
        backstory=(
            "You are a meticulous quantitative analyst. You never guess numbers -- "
            "you only report what the tool returns. If the tool reports an error, "
            "you report that error honestly instead of making up plausible-looking data. "
        ),
        tools=[MarketDataTool()],
        llm=tool_llm,
        max_rpm=settings.groq_max_requests_per_minute,
        max_iter=4,
        verbose=verbose,
        allow_delegation=False,
    )

    news_analyst_agent = Agent(
        role="News Sentiment Analyst",
        goal=(
            f"Fetch recent news headlines for {symbol} using the get_recent_news tool, "
            "exactly once, and classify the overall sentiment."
        ),
        backstory=(
            "You are an equity news analyst. "
            "You carefully read the headlines returned by your news tool and determine "
            "whether their likely near-term impact on the company's stock is positive, "
            "negative, neutral, or mixed. "
            "Never invent headlines or facts. "
            "If no headlines are available, use NEUTRAL and explain why."
        ),
        tools=[NewsTool()],
        llm=reasoning_llm,
        max_rpm=settings.groq_max_requests_per_minute,
        max_iter=4,
        verbose=verbose,
        allow_delegation=False,
    )

    recommendation_agent = Agent(
        role="Trading Recommendation Strategist",
        goal=(
            "Synthesize market data and news sentiment into one clear, actionable "
            "BUY/SELL/HOLD recommendation with specific price levels."
        ),
        backstory=(
            "You are a risk-aware trading strategist. You never recommend a trade "
            "without a stop-loss, and you always explain your reasoning in plain "
            "English by referencing the specific technical and news evidence you were "
            "given -- you do not have tools, so you work only from the data provided "
            "to you by the other analysts. "
        ),
        tools=[],
        llm=reasoning_llm,
        max_iter=3,
        verbose=verbose,
        allow_delegation=False,
    )

    market_data_task = Task(
        description=(
            f"Get current market data and technical indicators for stock symbol '{symbol}' "
            "using your tool. Report the values exactly as returned."
        ),
        expected_output="A MarketData object with price, volume, and technical indicators.",
        agent=market_data_agent,
        output_pydantic=MarketData,
        max_retries=settings.task_max_retries,
    )

    news_task = Task(
        description=(
            f"Get recent news headlines for stock symbol '{symbol}' using your tool. "
            "Analyze the returned headlines and classify the overall sentiment as "
            "POSITIVE, NEGATIVE, NEUTRAL, or MIXED."
        ),
        expected_output=(
            "A structured NewsSentiment result containing the symbol, sentiment, "
            "headline count, up to 5 headlines, and a concise summary."
        ),
        agent=news_analyst_agent,
        output_pydantic=NewsSentiment,
        max_retries=settings.task_max_retries,
    )

    recommendation_task = Task(
        description=(
            f"Using the market data and news sentiment gathered for '{symbol}', produce a "
            f"trading recommendation suited to a {time_horizon.replace('_', ' ')} time horizon. "
            "Set a target_price and stop_loss consistent with the current price and trend. "
            "If the underlying data indicates an error (e.g. symbol not found), set action to "
            "HOLD, confidence to LOW, and explain the data issue in the reasoning field instead "
            "of fabricating numbers. "
            "IMPORTANT: Do not attempt to invoke any functions or format your output as a tool call named 'json'."
        ),
        expected_output="A StockRecommendation object with action, confidence, price levels, and reasoning.",
        agent=recommendation_agent,
        context=[market_data_task, news_task],
        output_pydantic=StockRecommendation,
        max_retries=settings.task_max_retries,
    )

    return Crew(
        agents=[market_data_agent, news_analyst_agent, recommendation_agent],
        tasks=[market_data_task, news_task, recommendation_task],
        process=Process.sequential,
        verbose=verbose,
    )
