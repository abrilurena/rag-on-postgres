import json

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionToolParam,
)


def build_search_function() -> list[ChatCompletionToolParam]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_database",
                "description": "Search PostgreSQL database for relevant products based on the user query",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_query": {
                            "type": "string",
                            "description": "Query string to use for full text search, e.g. 'red shoes'",
                        },
                        "price_filter": {
                            "type": "object",
                            "description": "Filter search results based on price of the product",
                            "properties": {
                                "comparison_operator": {
                                    "type": "string",
                                    "description": "Operator to compare the column value, either '>', '<', '>=', '<=', '=='",
                                },
                                "value": {
                                    "type": "number",
                                    "description": "Value to compare against, e.g. 30",
                                },
                            },
                        },
                        "brand_filter": {
                            "type": "object",
                            "description": "Filter search results based on brand of the product",
                            "properties": {
                                "comparison_operator": {
                                    "type": "string",
                                    "description": "Operator to compare the column value, either '==' or '!='",
                                },
                                "value": {
                                    "type": "string",
                                    "description": "Value to compare against, e.g. AirStrider",
                                },
                            },
                        },
                    },
                    "required": ["search_query"],
                },
            },
        }
    ]


def extract_search_arguments(chat_completion: ChatCompletion):
    response_message = chat_completion.choices[0].message
    search_query = None
    filters = []
    if response_message.tool_calls:
        for tool in response_message.tool_calls:
            if tool.type != "function":
                continue
            function = tool.function
            if function.name == "search_database":
                arg = json.loads(function.arguments)
                search_query = arg.get("search_query")
                if "price_filter" in arg:
                    price_filter = arg["price_filter"]
                    filters.append(
                        {
                            "column": "price",
                            "comparison_operator": price_filter["comparison_operator"],
                            "value": price_filter["value"],
                        }
                    )
                if "brand_filter" in arg:
                    brand_filter = arg["brand_filter"]
                    filters.append(
                        {
                            "column": "brand",
                            "comparison_operator": brand_filter["comparison_operator"],
                            "value": brand_filter["value"],
                        }
                    )
    elif query_text := response_message.content:
        search_query = query_text.strip()
    return search_query, filters
