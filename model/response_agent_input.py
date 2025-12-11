from pydantic import BaseModel, Field

class ResponseAgentInput(BaseModel):
    """
    A structured input model for the Notion_Response_Agent.
    It encapsulates the result from a specialist agent to be formatted into a user-friendly response.
    """

    action_type: str = Field(
        ...,
        description=(
            "The name of the agent that performed the action, e.g., "
            "'Notion_Task_Creation_Agent' or 'Notion_Task_Content_Generator_Agent'. "
            "This is used by the response agent to select the correct formatting template."
        )
    )

    language: str = Field(
        ...,
        description="The language code for the final response, e.g., 'en', 'ru', 'az'."
    )

    original_query: str = Field(
        ...,
        description=(
            "The full, original query from the user. This is crucial for detecting "
            "multi-query scenarios to determine the appropriate follow-up question."
        )
    )

    # Changed from 'Any' to 'str' since all specialist tools return a JSON string
    tool_output: str = Field(
        ...,
        description=(
            "The raw JSON string returned by the specialist agent's tool. This can be a "
            "dictionary or list serialized into a string, and it may contain the result "
            "of the operation or an error."
        )
    )
