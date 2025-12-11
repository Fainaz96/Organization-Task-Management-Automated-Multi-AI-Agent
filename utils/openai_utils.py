import openai

def get_openai_response(conversation_history: list) -> str:
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=conversation_history,
            max_tokens=1000,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {str(e)}")