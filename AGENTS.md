# AGENTS.md

## Project
This is a professional Wealth Portfolio Rebalancer for a Germany-based Scalable Capital investor.

## Core rules
- Never build auto-trading.
- Never connect directly to broker accounts.
- All holdings and prices must be manually entered by the user.
- Treat this as a decision-support tool, not financial advice.
- Prefer clear, explainable logic over complex black-box optimization.
- Respect Scalable Capital constraints:
  - Whole quantities for stocks, ETFs, ETCs, ETPs.
  - Crypto can be fractional.
  - Avoid direct orders below €250 unless strongly justified.
  - Use fee warnings for trades below €250.
  - Prefer EIX/gettex.
  - Avoid Xetra unless user explicitly asks.

## Required output tables
Every rebalance output should include:
1. Immediate buy/sell table
2. Execution order
3. Savings-plan adjustment table
4. Allocation table
5. Short market reasoning notes

## Coding standards
- Keep code beginner-readable.
- Use pandas for tables.
- Use tests for calculation logic.
- Do not hardcode logic only in Streamlit UI; keep calculations in rebalancer.py.