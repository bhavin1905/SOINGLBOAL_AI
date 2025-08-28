# NOTE: This script requires the 'langgraph' and 'langchain' libraries.
# If you see unresolved import errors, install them with:
# pip install langgraph langchain langchain-core

from typing import Annotated, TypedDict
from langgraph.graph import add_messages, StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from soinglobal_smartai.tools.telegram_dex_query_tool import TelegramDexQueryTool

load_dotenv()
memory = MemorySaver()

tool = TelegramDexQueryTool()


class BasicChatState(TypedDict):
    messages: Annotated[list, add_messages]


def chatbot(state: BasicChatState):
    # Get the latest user message
    user_message = state["messages"][-1]
    if isinstance(user_message, HumanMessage):
        user_query = user_message.content
        # Use the tool to answer the query
        response = tool._run(query=user_query, top_n=3, hours_after_call=24)
        return {"messages": state["messages"] + [AIMessage(content=response)]}
    else:
        return {"messages": state["messages"]}


graph = StateGraph(BasicChatState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
graph.add_edge("chatbot", END)

app = graph.compile(checkpointer=memory)

config = {"configurable": {"thread_id": 1}}

print("Welcome to the Telegram Promoter Chatbot! Type 'exit' or 'end' to quit.")
while True:
    user_input = input("User: ")
    if user_input.lower() in ["exit", "end"]:
        print("Thank you for using the Telegram Promoter Chatbot!")
        break
    else:
        result = app.invoke({
            "messages": [HumanMessage(content=user_input)]
        }, config=config)
        print("AI Response:", result["messages"][-1].content) 
