from agent.agent_class import LLMService

llm_service = LLMService(
        service="openrouter",
        model_name="qwen/qwen3-235b-a22b",
        api_key='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',
        temperature=0,
        max_tokens=0,
    )

a = llm_service.generate("2+2")
print(a)