from __future__ import annotations

import asyncio

from orchestrator.handler import OrchestratorHandler


async def main():
    print("\n=== Multi-Agent Orchestrator CLI ===")
    print("Type your query and press Enter")
    print("Type 'exit' to quit\n")

    handler = OrchestratorHandler()

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in {"exit", "quit", "q"}:
                print("\nExiting...")
                break

            if not user_input:
                continue

            print("\nProcessing...\n")

            # Call handler
            result = await handler.handle(user_input)

            # Print response
            print("Bot:\n")
            print(result.get("result", "No response"))
            print("\n" + "=" * 60 + "\n")

        except KeyboardInterrupt:
            print("\nInterrupted. Exiting...")
            break

        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())