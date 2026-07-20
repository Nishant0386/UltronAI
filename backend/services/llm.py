import os
from groq import AsyncGroq

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

async def stream_chat(messages, system_prompt="You are ULTRON, a highly advanced AI assistant."):
    """
    Streams a response from Groq using Llama 3.
    """
    formatted_messages = [{"role": "system", "content": system_prompt}] + messages
    
    stream = await client.chat.completions.create(
        messages=formatted_messages,
        model="llama3-8b-8192", # Fast and capable
        stream=True,
    )
    
    async for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
